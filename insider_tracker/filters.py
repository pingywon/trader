"""Conviction filters applied to each parsed Form 4 transaction.

Each Transaction yields an accept/reject Decision. The reason string is persisted
so you can later audit why a filing was skipped without re-fetching.
"""
from __future__ import annotations

from dataclasses import dataclass

from .edgar import Transaction


@dataclass(frozen=True)
class FilterConfig:
    open_market_only: bool
    exclude_10b5_1: bool
    roles_allowed: tuple[str, ...]
    min_insider_dollars: float


@dataclass(frozen=True)
class Decision:
    accept: bool
    reason: str


def evaluate(tx: Transaction, cfg: FilterConfig) -> Decision:
    if cfg.open_market_only and tx.tx_code != "P":
        return Decision(False, f"tx_code={tx.tx_code!r} (not open-market purchase)")
    if tx.acquired_disposed and tx.acquired_disposed != "A":
        return Decision(False, f"disposal not acquisition (ad={tx.acquired_disposed!r})")
    if cfg.exclude_10b5_1 and tx.is_10b5_1:
        return Decision(False, "10b5-1 pre-scheduled plan trade")
    if not _role_allowed(tx, cfg.roles_allowed):
        return Decision(
            False,
            f"role not allowed (director={tx.is_director} officer={tx.is_officer} "
            f"title={tx.officer_title!r})",
        )
    if tx.dollars < cfg.min_insider_dollars:
        return Decision(
            False,
            f"${tx.dollars:,.0f} below min_insider_dollars ${cfg.min_insider_dollars:,.0f}",
        )
    if not tx.symbol:
        return Decision(False, "no trading symbol on issuer")
    if tx.shares <= 0 or tx.price_per_share <= 0:
        return Decision(False, "zero shares or price")
    role = _role_str(tx)
    return Decision(True, f"{tx.tx_code} ${tx.dollars:,.0f} {tx.symbol} by {role}")


def _role_allowed(tx: Transaction, roles: tuple[str, ...]) -> bool:
    title_lc = (tx.officer_title or "").lower()
    for r in roles:
        r = r.lower().strip()
        if r == "director" and tx.is_director:
            return True
        if r == "ceo" and ("chief executive" in title_lc or "ceo" in title_lc):
            return True
        if r == "cfo" and ("chief financial" in title_lc or "cfo" in title_lc):
            return True
        if r == "chief" and tx.is_officer and "chief" in title_lc:
            return True
        if r == "president" and "president" in title_lc:
            return True
    return False


def _role_str(tx: Transaction) -> str:
    parts = []
    if tx.is_director:
        parts.append("Director")
    if tx.officer_title:
        parts.append(tx.officer_title)
    if tx.is_ten_percent:
        parts.append("10%Owner")
    return ", ".join(parts) or "Insider"
