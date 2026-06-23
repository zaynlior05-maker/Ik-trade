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
            taken = candles[i].high > s.price if bias == Bias.BEARISH else candles[i].low < s.price
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

    # POI must be FRESH (unmitigated) and entered on the FIRST return only.
    pois = poi_mod.find_order_blocks(candles, bias) + poi_mod.find_breaker_blocks(candles, bias)
    # Rule 1: the POI must be the CAUSE of this move -- i.e. it originated within the
    # MSS -> BOS displacement leg, not some unrelated older block.
    pois = [p for p in pois if _idx_of_ts(candles, p.ts) >= ev.mss_idx - 5]
    pois.sort(key=lambda pz: abs(((pz.top + pz.bottom) / 2) - candles[-1].close))
    last = len(candles) - 1
    for poi in pois:
        ft = poi_mod.first_touch_index(candles, poi)
        if ft is None:                 # not yet returned -> fresh, pending candidate
            ev.poi, ev.poi_tap_idx = poi, None
            break
        if ft == last:                 # first return is happening now -> fresh first-touch entry
            ev.poi, ev.poi_tap_idx = poi, ft
            break
        # else: an earlier pullback already mitigated this block -> not fresh -> skip it
    return ev


def classify(ev: Events) -> Optional[str]:
    # EVERY valid setup needs all four: structure shift (MSS), liquidity taken
    # (IDM), a break of structure (BOS), and a POI tap. No shortcuts.
    if ev.mss_idx is None or ev.idm_after is None:
        return None
    if ev.bos_idx is None or ev.poi_tap_idx is None:
        return None
    if ev.idm_before is not None:
        # IDM before the MSS -> Type B (still needs BOS before the POI)
        return "B" if ev.poi_tap_idx > ev.bos_idx else None
    if ev.poi_tap_idx < ev.bos_idx:
        return "C"        # POI tapped before BOS
    if ev.bos_idx < ev.poi_tap_idx:
        return "A"        # BOS before POI
    return None


def typed_signal(symbol: str, candles: List[Candle], bias: Bias, timeframe: str) -> Optional[Signal]:
    ev = detect_events(candles, bias)
    if ev.poi is None or ev.mss_idx is None:
        return None
    price = candles[-1].close

    # MARKET: full structure AND price has tapped the POI -> enter now
    label = classify(ev)
    if label and ev.poi_tap_idx is not None:
        entry = price
        if bias == Bias.BEARISH:
            stop, target = ev.poi.top, min(c.low for c in candles[ev.mss_idx:])
        else:
            stop, target = ev.poi.bottom, max(c.high for c in candles[ev.mss_idx:])
        return Signal(
            pair=symbol, setup_type=f"Type {label} ({ev.poi.kind}) \u2014 MARKET enter now",
            bias=bias, entry=entry, stop=stop, target=target,
            timeframe=timeframe, event=StructEvent.MSS,
        )

    # PENDING: full confluence (MSS + IDM + BOS + POI) formed, price not at POI yet -> set a limit
    if ev.idm_after is not None and ev.bos_idx is not None and ev.poi_tap_idx is None:
        lab = "B" if ev.idm_before is not None else "A"
        if bias == Bias.BULLISH and ev.poi.top <= price:
            entry, stop = ev.poi.top, ev.poi.bottom
            target = max(c.high for c in candles[ev.mss_idx:])
        elif bias == Bias.BEARISH and ev.poi.bottom >= price:
            entry, stop = ev.poi.bottom, ev.poi.top
            target = min(c.low for c in candles[ev.mss_idx:])
        else:
            return None
        return Signal(
            pair=symbol, setup_type=f"Type {lab} ({ev.poi.kind}) \u2014 PENDING set limit",
            bias=bias, entry=entry, stop=stop, target=target,
            timeframe=timeframe, event=StructEvent.MSS,
        )

    return None
                  timeframe=timeframe, event=StructEvent.MSS)
