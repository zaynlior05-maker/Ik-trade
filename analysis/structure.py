"""
Market structure engine.

Definitions locked to spec:
  - Swing point  : 3-BAR FRACTAL (one bar each side -> lookback = 1).
  - Displacement : a break is a valid MSS ONLY IF the breaking candle closes its
                   BODY past the swing point AND leaves behind a valid FVG.
                   A body-close past the swing WITHOUT an FVG is the weaker CHoCH.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from models import Candle, Swing, Bias, StructEvent

SWING_LOOKBACK = 1   # 3-bar fractal: extreme vs 1 bar each side


def find_swings(candles: List[Candle], lookback: int = SWING_LOOKBACK) -> List[Swing]:
    swings: List[Swing] = []
    n = lookback
    for i in range(n, len(candles) - n):
        window = candles[i - n:i + n + 1]
        c = candles[i]
        if c.high == max(w.high for w in window) and c.high > max(
            candles[i - 1].high, candles[i + 1].high
        ) - 1e-12:
            swings.append(Swing(ts=c.ts, price=c.high, kind="high"))
        if c.low == min(w.low for w in window) and c.low < min(
            candles[i - 1].low, candles[i + 1].low
        ) + 1e-12:
            swings.append(Swing(ts=c.ts, price=c.low, kind="low"))
    return swings


def last_swing(swings: List[Swing], kind: str) -> Optional[Swing]:
    for s in reversed(swings):
        if s.kind == kind:
            return s
    return None


def fvg_at(candles: List[Candle], i: int, direction: Bias) -> Optional[Tuple[float, float]]:
    """
    FVG left behind by an impulse whose final candle is index i.
    Uses the 3-candle imbalance (i-2, i-1, i): the body of i-1 fails to fill the
    gap between candle i-2 and candle i.
      bullish FVG zone = (top=low[i], bottom=high[i-2])  valid if low[i] > high[i-2]
      bearish FVG zone = (top=low[i-2], bottom=high[i])  valid if high[i] < low[i-2]
    Returns (top, bottom) or None.
    """
    if i < 2 or i >= len(candles):
        return None
    a, c = candles[i - 2], candles[i]
    if direction == Bias.BULLISH and c.low > a.high:
        return (c.low, a.high)
    if direction == Bias.BEARISH and c.high < a.low:
        return (a.low, c.high)
    return None


def bias_from_structure(candles: List[Candle], lookback: int = 2) -> Bias:
    swings = find_swings(candles, lookback)
    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]
    if len(highs) < 3 or len(lows) < 3:
        return Bias.NEUTRAL
    # compare the latest swing to the 3rd-from-last: robust to a single pullback
    hh = highs[-1].price > highs[-3].price
    hl = lows[-1].price > lows[-3].price
    lh = highs[-1].price < highs[-3].price
    ll = lows[-1].price < lows[-3].price
    if hh and hl:
        return Bias.BULLISH
    if lh and ll:
        return Bias.BEARISH
    return Bias.NEUTRAL


def detect_structure_event(candles: List[Candle], prevailing: Bias) -> Optional[StructEvent]:
    """
    Classify a structural break on the most recently CLOSED candle, in the
    direction OPPOSING `prevailing` (the reversal we want after a POI tap).
      body-close past swing + FVG  -> MSS
      body-close past swing, no FVG -> CHoCH
    """
    if len(candles) < 4:
        return None
    swings = find_swings(candles)
    sh = last_swing(swings, "high")
    sl = last_swing(swings, "low")
    last = candles[-1]
    i = len(candles) - 1
    body_low, body_high = min(last.open, last.close), max(last.open, last.close)

    if prevailing == Bias.BEARISH and sh:           # want bullish reversal
        if body_high > sh.price:                    # body closed past swing high
            return StructEvent.MSS if fvg_at(candles, i, Bias.BULLISH) else StructEvent.CHOCH
    if prevailing == Bias.BULLISH and sl:           # want bearish reversal
        if body_low < sl.price:
            return StructEvent.MSS if fvg_at(candles, i, Bias.BEARISH) else StructEvent.CHOCH
    return None


def fvg_centered(candles: List[Candle], i: int, direction: Bias) -> Optional[Tuple[float, float]]:
    """
    Canonical 3-candle FVG with displacement candle `i` as the MIDDLE candle,
    i.e. the imbalance sitting right beside an order block (needs i-1 and i+1).
      bullish valid if low[i+1] > high[i-1]  -> zone (low[i+1], high[i-1])
      bearish valid if high[i+1] < low[i-1]  -> zone (low[i-1], high[i+1])
    """
    if i < 1 or i + 1 >= len(candles):
        return None
    a, c = candles[i - 1], candles[i + 1]
    if direction == Bias.BULLISH and c.low > a.high:
        return (c.low, a.high)
    if direction == Bias.BEARISH and c.high < a.low:
        return (a.low, c.high)
    return None


def structural_stop(candles: List[Candle], direction: Bias) -> float:
    swings = find_swings(candles)
    if direction == Bias.BULLISH:
        s = last_swing(swings, "low")
        return s.price if s else min(c.low for c in candles[-10:])
    s = last_swing(swings, "high")
    return s.price if s else max(c.high for c in candles[-10:])
