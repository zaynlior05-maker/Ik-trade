"""
Type A / B / C setup classifier.

Sequences (bearish-primary, bullish mirrored):
    Type A : MSS -> IDM -> BOS -> POI
    Type B : IDM -> MSS -> IDM -> BOS -> POI
    Type C : MSS -> IDM -> POI -> BOS   (only one where BOS is AFTER POI)

Classify by order of events on the LTF:
    - IDM before MSS exists            -> B
    - POI tapped before BOS            -> C
    - else (MSS, IDM, BOS, then POI)   -> A

POI rule (fresh / first-touch): the order/breaker block must be the CAUSE of the
move (born in the MSS->BOS leg), still UNMITIGATED, and entered on the FIRST
return only. A block a prior pullback already tapped is treated as stale.

NOTE: the event detectors (esp. IDM) are pragmatic v1 rules with tunable
constants -- the most subjective part of the strategy. Validate with
backtest.py before trusting live.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from models import Candle, Bias, Signal, StructEvent
from analysis.structure import find_swings
from analysis import poi as poi_mod


@dataclass
class Events:
    mss_idx: Optional[int] = None
    idm_before: Optional[int] = None   # IDM swept before MSS (Type B marker)
    idm_after: Optional[int] = None    # IDM swept after MSS
    bos_idx: Optional[int] = None
    poi_tap_idx: Optional[int] = None
    poi: Optional[object] = None


def _idx_of_ts(candles: List[Candle], ts: int) -> int:
    for i, c in enumerate(candles):
        if c.ts == ts:
            return i
    return -1


def _find_mss(candles: List[Candle], bias: Bias) -> Optional[int]:
    """Index of the candle delivering the CHoCH/MSS into `bias`."""
    swings = find_swings(candles)
    if bias == Bias.BEARISH:
        lows = [s for s in swings if s.kind == "low"]
        for k in range(1, len(lows)):
            if lows[k].price > lows[k - 1].price:           # higher low (bullish)
                start = _idx_of_ts(candles, lows[k].ts) + 1
                for i in range(start, len(candles)):
                    if candles[i].close < lows[k].price:    # broken down = MSS
                        return i
    else:
        highs = [s for s in swings if s.kind == "high"]
        for k in range(1, len(highs)):
            if highs[k].price < highs[k - 1].price:         # lower high (bearish)
                start = _idx_of_ts(candles, highs[k].ts) + 1
                for i in range(start, len(candles)):
                    if candles[i].close > highs[k].price:
                        return i
    return None


def _idm_sweeps(candles: List[Candle], bias: Bias) -> List[int]:
    """Indices where an inducement is taken (minor swing high/low swept)."""
    swings = find_swings(candles)
    out: List[int] = []
    kind = "high" if bias == Bias.BEARISH else "low"
    for s in [s for s in swings if s.kind == kind]:
        start = _idx_of_ts(candles, s.ts) + 1
        for i in range(start, len(candles)):
            taken = candles[i