"""
Type A / B / C setup classifier.

Sequences (bearish-primary, bullish mirrored):
    Type A : MSS -> IDM -> BOS -> POI
    Type B : IDM -> MSS -> IDM -> BOS -> POI
    Type C : MSS -> IDM -> POI -> BOS

POI rule (fresh / first-touch): the order/breaker block must be the CAUSE of the
move (born in the MSS->BOS leg), still UNMITIGATED, and entered on the FIRST
return only. A block a prior pullback already tapped is treated as stale.
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
    idm_before: Optional[int] = None
    idm_after: Optional[int] = None
    bos_idx: Optional[int] = None
    poi_tap_idx: Optional[int] = None
    poi: Optional[object] = None


def _idx_of_ts(candles: List[Candle], ts: int) -> int:
    for i, c in enumerate(candles):
        if c.ts == ts:
            return i
    return -1


def _find_mss(candles: List[Candle], bias: Bias) -> Optional[int]:
    """Index of the candle delivering the CHoCH/MSS into bias."""
    swings = find_swings(candles)
    if bias == Bias.BEARISH:
        lows = [s for s in swings if s.kind == "low"]
        for k in range(1, len(lows)):
            # need a higher low (bullish micro-structure) to then break down
            if lows[k].price > lows[k - 1].price:
                start = _idx_of_ts(candles, lows[k].ts) + 1
                for i in range(start, len(candles)):
                    if candles[i].close < lows[k].price:
                        return i
    else:
        highs = [s for s in swings if s.kind == "high"]
        for k in range(1, len(highs)):
            # need a lower high (bearish micro-structure) to then break up
            if highs[k].price < highs[k - 1].price:
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
    for s in [x for x in swings if x.kind == kind]:
        start = _idx_of_ts(candles, s.ts) + 1
        for i in range(start, len(candles)):
            c = candles[i]
            if bias == Bias.BEARISH:
                taken = c.high > s.price
            else:
                taken = c.low < s.price
            if taken:
                out.append(i)
                break
    return sorted(out)


def _bos_after(candles: List[Candle], bias: Bias, mss_idx: int) -> Optional[int]:
    """Continuation break after the MSS leg."""
    leg = candles[mss_idx:mss_idx + 5] or candles[mss_idx:]
    if not leg:
        return None
    if bias == Bias.BEARISH:
        leg_low = min(c.low for c in leg)
        for i in range(mss_idx + 1, len(candles)):
            if candles[i].close < leg_low:
                return i
    else:
        leg_high = max(c.high for c in leg)
        for i in range(mss_idx + 1, len(candles)):
            if candles[i].close > leg_high:
                return i
    return None


def detect_events(candles: List[Candle], bias: Bias) -> Events:
    ev = Events()
    ev.mss_idx = _find_mss(candles, bias)
    if ev.mss_idx is None:
        return ev

    sweeps = _idm_sweeps(candles, bias)
    befores = [i for i in sweeps if i < ev.mss_idx]
    afters = [i for i in sweeps if i > ev.mss_idx]
    ev.idm_before = befores[-1] if befores else None
    ev.idm_after = afters[0] if afters else None
    ev.bos_idx = _bos_after(candles, bias, ev.mss_idx)

    obs = poi_mod.find_order_blocks(candles, bias)
    bbs = poi_mod.find_breaker_blocks(candles, bias)
    pois = obs + bbs

    # Rule 1: POI must be the CAUSE of this move (born in/after the MSS leg).
    lo = ev.mss_idx - 5
    pois = [p for p in pois if _idx_of_ts(candles, p.ts) >= lo]

    price = candles[-1].close
    pois.sort(key=lambda p: abs((p.top + p.bottom) / 2 - price))

    last = len(candles) - 1
    for poi in pois:
        ft = poi_mod.first_touch_index(candles, poi)
        if ft is None:
            # not yet returned -> fresh, pending candidate
            ev.poi = poi
            ev.poi_tap_idx = None
            break
        if ft == last:
            # first return is happening now -> fresh first-touch entry
            ev.poi = poi
            ev.poi_tap_idx = ft
            break
        # else: an earlier pullback already mitigated it -> stale -> skip
    return ev


def classify(ev: Events) -> Optional[str]:
    # Every valid setup needs all four: MSS, IDM, BOS, POI tap.
    if ev.mss_idx is None or ev.idm_after is None:
        return None
    if ev.bos_idx is None or ev.poi_tap_idx is None:
        return None
    if ev.idm_before is not None:
        if ev.poi_tap_idx > ev.bos_idx:
            return "B"
        return None
    if ev.poi_tap_idx < ev.bos_idx:
        return "C"
    if ev.bos_idx < ev.poi_tap_idx:
        return "A"
    return None


def typed_signal(
    symbol: str, candles: List[Candle], bias: Bias, timeframe: str
) -> Optional[Signal]:
    ev = detect_events(candles, bias)
    if ev.poi is None or ev.mss_idx is None:
        return None
    price = candles[-1].close

    # MARKET: full structure AND price has tapped the POI -> enter now
    label = classify(ev)
    if label and ev.poi_tap_idx is not None:
        entry = price
        if bias == Bias.BEARISH:
            stop = ev.poi.top
            target = min(c.low for c in candles[ev.mss_idx:])
        else:
            stop = ev.poi.bottom
            target = max(c.high for c in candles[ev.mss_idx:])
        stype = f"Type {label} ({ev.poi.kind}) - MARKET enter now"
        return Signal(
            pair=symbol,
            setup_type=stype,
            bias=bias,
            entry=entry,
            stop=stop,
            target=target,
            timeframe=timeframe,
            event=StructEvent.MSS,
        )

    # PENDING: full confluence formed, price not at POI yet -> set a limit
    pending = (
        ev.idm_after is not None
        and ev.bos_idx is not None
        and ev.poi_tap_idx is None
    )
    if pending:
        lab = "B" if ev.idm_before is not None else "A"
        if bias == Bias.BULLISH and ev.poi.top <= price:
            entry = ev.poi.top
            stop = ev.poi.bottom
            target = max(c.high for c in candles[ev.mss_idx:])
        elif bias == Bias.BEARISH and ev.poi.bottom >= price:
            entry = ev.poi.bottom
            stop = ev.poi.top
            target = min(c.low for c in candles[ev.mss_idx:])
        else:
            return None
        stype = f"Type {lab} ({ev.poi.kind}) - PENDING set limit"
        return Signal(
            pair=symbol,
            setup_type=stype,
            bias=bias,
            entry=entry,
            stop=stop,
            target=target,
            timeframe=timeframe,
            event=StructEvent.MSS,
        )

    return None