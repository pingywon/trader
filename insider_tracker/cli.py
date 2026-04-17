"""Command-line entry point.

Subcommands:
  run              — poll EDGAR once, filter, submit orders. Suitable for cron.
  run --dry-run    — log what would be traded without touching Alpaca or state.
  status           — print recent processed filings and recent trades.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .alpaca_client import AlpacaClient
from .edgar import Transaction, fetch_feed, fetch_transactions
from .filters import FilterConfig, evaluate
from .sizer import SizingConfig, Tier, size_notional
from .state import State

log = logging.getLogger("insider_tracker")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="insider-tracker")
    parser.add_argument("--config", default=str(_default_config_path()))
    parser.add_argument("--db", default=str(_default_db_path()))
    parser.add_argument("--verbose", "-v", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="poll EDGAR once and trade")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="evaluate filings and log decisions but do not submit orders or persist state",
    )

    sub.add_parser("status", help="print recent processed filings and trades")

    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    cfg = _load_config(Path(args.config))
    state = State(Path(args.db))

    if args.cmd == "run":
        return _cmd_run(state, cfg, dry_run=args.dry_run)
    if args.cmd == "status":
        return _cmd_status(state)
    return 1


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    # httpx/httpcore log every request at INFO; that's noise for this tool.
    for name in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _default_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config.yaml"


def _default_db_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "state.db"


def _load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _filter_cfg(cfg: dict) -> FilterConfig:
    f = cfg["filters"]
    return FilterConfig(
        open_market_only=bool(f.get("open_market_only", True)),
        exclude_10b5_1=bool(f.get("exclude_10b5_1", True)),
        roles_allowed=tuple(
            f.get("roles_allowed", ["director", "ceo", "cfo", "chief", "president"])
        ),
        min_insider_dollars=float(f.get("min_insider_dollars", 0)),
    )


def _sizing_cfg(cfg: dict) -> SizingConfig:
    s = cfg["sizing"]
    tiers = tuple(
        Tier(min=float(t["min"]), max=float(t["max"]), notional=float(t["notional"]))
        for t in s["tiers"]
    )
    return SizingConfig(tiers=tiers, max_pct_of_equity=float(s.get("max_pct_of_equity", 0.05)))


def _cmd_run(state: State, cfg: dict, dry_run: bool) -> int:
    fcfg = _filter_cfg(cfg)
    scfg = _sizing_cfg(cfg)
    poll = cfg.get("polling", {})
    max_age = timedelta(hours=int(poll.get("max_age_hours", 48)))
    feed_count = int(poll.get("feed_count", 100))
    min_filed = datetime.now(tz=timezone.utc) - max_age

    log.info("Fetching Form 4 feed (count=%d, max_age=%s)", feed_count, max_age)
    refs = fetch_feed(count=feed_count)
    log.info("Feed returned %d filings", len(refs))

    alpaca: AlpacaClient | None = None
    if dry_run:
        # In dry-run we use a synthetic equity so the sizing cap still shows in logs.
        equity = float(os.environ.get("DRY_RUN_EQUITY", "100000"))
        log.info("[DRY RUN] simulated equity: $%.2f", equity)
    else:
        alpaca = AlpacaClient()
        equity = alpaca.account_equity()
        log.info(
            "Alpaca %s account equity: $%.2f",
            "paper" if alpaca.paper else "LIVE",
            equity,
        )

    traded = skipped = errored = 0

    for ref in refs:
        if ref.filed_at < min_filed:
            continue
        if not dry_run and state.is_processed(ref.accession):
            continue
        try:
            txs = fetch_transactions(ref)
        except Exception as e:
            log.error("Fetch failed %s: %s", ref.accession, e)
            if not dry_run:
                state.mark_processed(ref.accession, "", "", "error", f"fetch failed: {e}")
            errored += 1
            continue

        if not txs:
            if not dry_run:
                state.mark_processed(
                    ref.accession, "", "", "skipped", "no parseable nonDerivative transactions"
                )
            skipped += 1
            continue

        # Act on the first accepted row. Multi-row filings usually split a single
        # purchase across price points; one notional order covers the signal.
        chosen: Transaction | None = None
        reject_reason = ""
        for tx in txs:
            decision = evaluate(tx, fcfg)
            if decision.accept:
                chosen = tx
                break
            reject_reason = decision.reason

        if chosen is None:
            log.debug("Skip %s: %s", txs[0].symbol or ref.accession, reject_reason)
            if not dry_run:
                state.mark_processed(
                    ref.accession, txs[0].symbol, txs[0].tx_code, "skipped", reject_reason
                )
            skipped += 1
            continue

        notional = size_notional(chosen.dollars, equity, scfg)
        if notional <= 0:
            if not dry_run:
                state.mark_processed(
                    ref.accession, chosen.symbol, chosen.tx_code, "skipped", "sizer returned 0"
                )
            skipped += 1
            continue

        msg = (
            f"{chosen.symbol}: insider ${chosen.dollars:,.0f} by {chosen.owner_name} "
            f"({_role_short(chosen)}) -> notional ${notional:.2f}"
        )
        if dry_run:
            log.info("[DRY RUN] %s", msg)
            traded += 1
            continue

        assert alpaca is not None
        if not alpaca.asset_tradable(chosen.symbol):
            reason = f"{chosen.symbol} not tradable on Alpaca"
            log.warning(reason)
            state.mark_processed(ref.accession, chosen.symbol, chosen.tx_code, "skipped", reason)
            skipped += 1
            continue

        result = alpaca.submit_notional_buy(chosen.symbol, notional)
        if result.ok:
            log.info("SUBMITTED %s  status=%s  id=%s", msg, result.status, result.order_id)
            state.mark_processed(ref.accession, chosen.symbol, chosen.tx_code, "traded", msg)
            state.record_trade(
                accession=ref.accession,
                symbol=chosen.symbol,
                notional=notional,
                insider_dollars=chosen.dollars,
                insider_name=chosen.owner_name,
                insider_role=_role_short(chosen),
                alpaca_order_id=result.order_id,
                status=result.status,
            )
            traded += 1
        else:
            log.error("REJECTED %s: %s", chosen.symbol, result.message)
            state.mark_processed(
                ref.accession, chosen.symbol, chosen.tx_code, "error", result.message
            )
            errored += 1

    log.info("Done. traded=%d skipped=%d errored=%d", traded, skipped, errored)
    return 0


def _role_short(tx: Transaction) -> str:
    if tx.officer_title:
        return tx.officer_title
    if tx.is_director:
        return "Director"
    if tx.is_ten_percent:
        return "10% Owner"
    return "Insider"


def _cmd_status(state: State) -> int:
    print("== Recent filings processed ==")
    for row in state.recent_processed(25):
        print(
            f"{row['processed_at']}  {(row['symbol'] or ''):>6}  "
            f"{row['action']:>7}  {row['reason']}"
        )
    print("\n== Recent trades ==")
    for row in state.recent_trades(25):
        print(
            f"{row['submitted_at']}  {row['symbol']:>6}  ${row['notional']:>8.2f}  "
            f"{row['status']:>12}  {row['insider_name']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
