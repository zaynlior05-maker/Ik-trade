"""
Points of Interest.

ORDER BLOCK (to spec):
  - Zone = highest wick to lowest wick of the LAST CONSECUTIVE OPPOSING candle(s)
    immediately before a displacement leg (a leg whose final candle leaves an FVG).
  - The OB is invalidated immediately if its corresponding FVG is COMPLETELY
    FILLED before price returns to the OB zone.

FVG POIs are also exposed (raw imbalances), used by the HTF POI-tap logic.
"""
from __future__ import annotations

from typing import List, Optional

from models import Candle, POI, Bias
from analysis.structure import fvg_at, fvg_centered, find_swings


def _opp_color(c: Candle, direction: Bias) -> bool:
    # opposing candle = against the displacement direction
    return (not c.bullish) if direction == Bias.BULLISH else c.bullish


def _swept_liquidity(prior: List[Candle], run: List[Candle], direction: Bias) -> bool:
    """
    Valid OB requires a liquidity TAKE-OUT: the OB run must have swept a prior
    swing extreme before the displacement (the 'Take Out' rule).
      bullish OB -> run low must dip below a prior swing low
      bearish OB -> run high must push above a prior swing high
    """
    swings = find_swings(prior)
    if direction == Bias.BULLISH:
        run_low = min(c.low for c in run)
        return any(run_low < s.price for s in swings if s.kind == "low")
    run_high = max(c.high for c in run)
    return any(run_high > s.price for s in swings if s.kind == "high")


def find_order_blocks(candles: List[Candle], direction: Bias) -> List[POI]:
    out: List[POI] = []
    for i in range(2, len(candles) - 1):   # need i+1 for the adjacent FVG
        disp = candles[i]
        # displacement candle must move in `direction` and leave an adjacent FVG (the GAP)
        if direction == Bias.BULLISH and not disp.bullish:
            continue
        if direction == Bias.BEARISH and disp.bullish:
            continue
        fvg = fvg_centered(candles, i, direction)
        if not fvg:
            continue

        # walk back over the consecutive opposing candles forming the OB
        j = i - 1
        run: List[Candle] = []
        while j >= 0 and _opp_color(candles[j], direction):
            run.append(candles[j])
            j -= 1
        if not run:
            continue

        # TAKE-OUT rule: the run must have swept prior liquidity
        if not _swept_liquidity(candles[:j + 1], run, direction):
            continue

        top = max(c.high for c in run)        # highest wick
        bottom = min(c.low for c in run)      # lowest wick
        ob_ts = run[-1].ts

        if _fvg_filled_before_return(candles, i, fvg, direction, top, bottom):
            continue                          # invalidated: FVG filled first

        out.append(POI("OB", direction, top=top, bottom=bottom, ts=ob_ts))

    price = candles[-1].close
    out.sort(key=lambda p: abs(((p.top + p.bottom) / 2) - price))
    return out


def _fvg_filled_before_return(candles, i, fvg, direction, ob_top, ob_bottom) -> bool:
    """True if the displacement FVG is fully filled before price re-enters the OB."""
    fvg_top, fvg_bottom = fvg
    for c in candles[i + 1:]:
        returned = c.low <= ob_top and c.high >= ob_bottom
        if direction == Bias.BULLISH:
            fvg_full = c.low <= fvg_bottom    # traded through entire bullish gap
        else:
            fvg_full = c.high >= fvg_top      # traded through entire bearish gap
        if fvg_full and not returned:
            return True
        if returned:
            return False                      # price got back to OB first -> valid
    return False


def find_fvgs(candles: List[Candle], direction: Bias) -> List[POI]:
    out: List[POI] = []
    for i in range(2, len(candles)):
        z = fvg_at(candles, i, direction)
        if z:
            out.append(POI("FVG", direction, top=z[0], bottom=z[1], ts=candles[i].ts))
    return out


def _mitigated_before_last(poi: POI, candles: List[Candle]) -> bool:
    """OB counts as spent if price re-entered it AFTER creation but BEFORE the last bar."""
    for c in candles[:-1]:
        if c.ts <= poi.ts:
            continue
        if c.low <= poi.top and c.high >= poi.bottom:
            return True
    return False


def active_pois(candles: List[Candle], direction: Bias) -> List[POI]:
    if direction == Bias.NEUTRAL:
        return []
    pois = find_order_blocks(candles, direction) + find_fvgs(candles, direction)
    fresh = [p for p in pois if not _mitigated_before_last(p, candles)]
    price = candles[-1].close
    fresh.sort(key=lambda p: abs(((p.top + p.bottom) / 2) - price))
    return fresh


def price_tapped_poi(price: float, pois: List[POI]) -> Optional[POI]:
    for p in pois:
        if p.contains(price):
            return p
    return None
