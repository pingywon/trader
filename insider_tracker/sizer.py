"""Position sizing: map insider purchase $ size to an Alpaca notional order size.

The tiered approach is deliberately coarse — the goal is to weight conviction
without overfitting to the exact dollar amount an insider happened to spend.
Whatever tier is chosen, the result is further capped at `max_pct_of_equity`
of account equity as a safety rail.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tier:
    min: float
    max: float
    notional: float


@dataclass(frozen=True)
class SizingConfig:
    tiers: tuple[Tier, ...]
    max_pct_of_equity: float


def size_notional(insider_dollars: float, account_equity: float, cfg: SizingConfig) -> float:
    notional = 0.0
    for tier in cfg.tiers:
        if tier.min <= insider_dollars < tier.max:
            notional = tier.notional
            break
    cap = account_equity * cfg.max_pct_of_equity
    return round(min(notional, cap), 2)
