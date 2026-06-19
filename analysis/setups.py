"""Type A / B / C setup classifier (bearish-primary, bullish mirrored).
   A: MSS->IDM->BOS->POI   B: IDM->MSS->IDM->BOS->POI   C: MSS->IDM->POI->BOS
   v1 event rules (esp. IDM) are tunable — validate with backtest.py before live."""
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


def _idx_of_ts(candles, ts):
    for i, c in enumerate(candles):
        if c.ts == ts:
            return i
    return -1


def _find_mss(candles, bias):
    swings = find_swings(candles)
    if bias == Bias.BEARISH:
        lows = [s for s in swings if s.kind == "low"]
        for k in range(1, len(lows)):
            if lows[k].price > lows[k - 1].price:
                start = _idx_of_ts(candles, lows[k].ts) + 1
                for i in range(start, len(candles)):
                    if candles[i].close < lows[k].price:
                        return i
    else:
        highs = [s for s in swings if s.kind == "high"]
        for k in range(1, len(highs)):
            if highs[k].price < highs[k - 1].price:
                start = _idx_of_ts(candles, highs[k].ts) + 1
                for i in range(start, len(candles)):
                    if candles[i].close > highs[k].price:
                        return i
    return None


def _idm_sweeps(candles, bias):
    swings = find_swings(candles)
    out = []
    kind = "high" if bias == Bias.BEARISH else "low"
    for s in [s for s in swings if s.kind == kind]:
        start = _idx_of_ts(candles, s.ts) + 1
        for i in range(start, len(candles)):
            taken = candles[i].high > s.price if bias == Bias.BEARISH else candles[i].low < s.price
            if taken:
                out.append(i)
                break
    return sorted(out)


def _bos_after(candles, bias, mss_idx):
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


def detect_events(candles, bias):
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
    pois = poi_mod.find_order_blocks(candles, bias)
    if pois:
        ev.poi = pois[0]
        for i in range(ev.mss_idx, len(candles)):
            if candles[i].low <= ev.poi.top and candles[i].high >= ev.poi.bottom:
                ev.poi_tap_idx = i
                break
    return ev


def classify(ev):
    if ev.mss_idx is None or ev.idm_after is None:
        return None
    if ev.idm_before is not None:
        return "B"
    if ev.poi_tap_idx is not None and (ev.bos_idx is None or ev.poi_tap_idx < ev.bos_idx):
        return "C"
    if ev.bos_idx is not None and ev.poi_tap_idx is not None and ev.bos_idx < ev.poi_tap_idx:
        return "A"
    return None


def typed_signal(symbol, candles, bias, timeframe):
    ev = detect_events(candles, bias)
    label = classify(ev)
    if not label or ev.poi is None or ev.poi_tap_idx is None:
        return None
    entry = candles[-1].close
    if bias == Bias.BEARISH:
        stop = ev.poi.top
        target = min(c.low for c in candles[ev.mss_idx:])
    else:
        stop = ev.poi.bottom
        target = max(c.high for c in candles[ev.mss_idx:])
    return Signal(pair=symbol, setup_type=f"Type {label} ({ev.poi.kind})",
                  bias=bias, entry=entry, stop=stop, target=target,
                  timeframe=timeframe, event=StructEvent.MSS)
