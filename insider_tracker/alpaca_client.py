"""Thin wrapper around alpaca-py used for the four things the tracker needs:
reading account equity, verifying a symbol is tradable, and submitting a
notional (fractional-dollar) market buy. Market DAY orders submitted outside
RTH are queued by Alpaca to the next open, so we don't gate on market hours.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest


@dataclass(frozen=True)
class OrderResult:
    ok: bool
    order_id: str | None
    status: str
    message: str


class AlpacaClient:
    def __init__(self, allow_live: bool = False) -> None:
        key = os.environ.get("ALPACA_API_KEY", "").strip()
        secret = os.environ.get("ALPACA_API_SECRET", "").strip()
        if not key or not secret:
            raise RuntimeError(
                "ALPACA_API_KEY and ALPACA_API_SECRET must be set in the environment "
                "(or .env file). Get them from your Alpaca dashboard."
            )
        # Paper unless live is asked for twice: ALPACA_PAPER=false and --live.
        # A typo or a blank value therefore stays on paper.
        wants_live = os.environ.get("ALPACA_PAPER", "true").strip().lower() in ("0", "false", "no")
        paper = not (wants_live and allow_live)
        self.client = TradingClient(key, secret, paper=paper)
        self.paper = paper

    def account_equity(self) -> float:
        acct = self.client.get_account()
        return float(acct.equity)

    def asset_tradable(self, symbol: str) -> bool:
        try:
            asset = self.client.get_asset(symbol)
        except Exception:
            return False
        return bool(getattr(asset, "tradable", False))

    def submit_notional_buy(self, symbol: str, notional: float) -> OrderResult:
        req = MarketOrderRequest(
            symbol=symbol,
            notional=notional,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        try:
            order = self.client.submit_order(req)
            return OrderResult(
                ok=True,
                order_id=str(order.id),
                status=str(order.status),
                message="submitted",
            )
        except Exception as e:
            return OrderResult(ok=False, order_id=None, status="rejected", message=str(e))
