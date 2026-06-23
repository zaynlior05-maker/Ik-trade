"""
The alignment engine - disciplined SMC/ICT signals only.

Every LTF signal (continuation OR reversal) needs all four:
    Structure (MSS) + Liquidity (IDM) + BOS + POI (OB or BB)

CONTINUATION : trade WITH the 4H/1H bias (default).
REVERSAL     : trade AGAINST the bias, only when "armed" (price swept the
               trend's liquidity extreme AND rejected it). At an extreme we
               hunt reversal; otherwise continuation.

CRT: 4H only, and only when the sweep took out a real key level.

Overlapping LTF signals (e.g. a 15M and a 30M setup at the same level) are
de-duplicated -- the better R:R is kept.
"""
from __future__ import annotations

from typing import List

from models import Signal, Bias, StructEvent
from analysis import structure as st
from analysis import crt as crt_mod
from analysis import setups as setups_mod

MIN_RR = 1.3
CRT_TIMEFRAMES = ("4H",)
LTF_TIMEFRAMES = ("15M", "30M")


def _valid_geometry(s) -> bool:
    if s.bias == Bias.BULLISH:
        return s.stop < s.entry < s.target
    return s.stop > s.entry > s.target


def _overlap(a, b) -> bool:
    a_lo, a_hi = sorted([a.entry, a.stop])
    b_lo, b_hi = sorted([b.entry, b.stop])
    return a_lo <= b_hi and b_lo <= a_hi


def _dedupe(signals: List[Signal]) -> List[Signal]:
    kept: List[Signal] = []
    ordered = sorted(signals, key=lambda x: -(x.rr() or 0))
    for s in ordered:
        clash = False
        for k in kept:
            if s.pair == k.pair and s.bias == k.bias and _overlap(s, k):
                clash = True
                break
        if not clash:
            kept.append(s)
    return kept


def _htf_liquidity_swept(htf, bias: Bias, window: int = 3) -> bool:
    swings = st.find_swings(htf)
    if bias == Bias.BULLISH:
        highs = [s.price for s in swings if s.kind == "high"]
        if not highs:
            return False
        level = max(highs[-3:])
        swept = any(c.high > level for c in htf[-window:])
        rejected = htf[-1].close < level
        return swept and rejected
    lows = [s.price for s in swings if s.kind == "low"]
    if not lows:
        return False
    level = min(lows[-3:])
    swept = any(c.low < level for c in htf[-window:])
    rejected = htf[-1].close > level
    return swept and rejected


def _opposite(b: Bias) -> Bias:
    return Bias.BEARISH if b == Bias.BULLISH else Bias.BULLISH


class AlignmentEngine:
    def __init__(self, feed, symbol: str):
        self.feed = feed
        self.symbol = symbol

    def htf_bias(self) -> Bias:
        b4 = st.bias_from_structure(self.feed.get_candles(self.symbol, "4H"))
        b1 = st.bias_from_structure(self.feed.get_candles(self.symbol, "1H"))
        if b4 == Bias.NEUTRAL or (b1 != Bias.NEUTRAL and b1 != b4):
            bias = Bias.NEUTRAL
        else:
            bias = b4
        print(
            f"[{self.symbol}] bias 4H={b4.value} "
            f"1H={b1.value} -> {bias.value}"
        )
        return bias

    def check_typed_setups(self, bias: Bias) -> List[Signal]:
        out: List[Signal] = []
        for tf in LTF_TIMEFRAMES:
            ltf = self.feed.get_candles(self.symbol, tf)
            sig = setups_mod.typed_signal(self.symbol, ltf, bias, tf)
            if sig:
                out.append(sig)
        return out

    def check_reversal_setups(self, bias: Bias) -> List[Signal]:
        rev = _opposite(bias)
        out: List[Signal] = []
        for tf in LTF_TIMEFRAMES:
            ltf = self.feed.get_candles(self.symbol, tf)
            sig = setups_mod.typed_signal(self.symbol, ltf, rev, tf)
            if sig:
                sig.setup_type = "Reversal - " + sig.setup_type
                out.append(sig)
        return out

    def check_crt(self) -> List[Signal]:
        out: List[Signal] = []
        for tf in CRT_TIMEFRAMES:
            candles = self.feed.get_candles(self.symbol, tf)
            res = crt_mod.detect_crt(candles)
            if not res:
                continue
            bias, r_low, r_high = res
            if not crt_mod.swept_key_level(candles, bias, r_low, r_high):
                print(f"[{self.symbol}] CRT {tf} ignored: not a key level")
                continue
            entry = candles[-1].close
            stop = r_low if bias == Bias.BULLISH else r_high
            target = r_high if bias == Bias.BULLISH else r_low
            out.append(Signal(
                pair=self.symbol,
                setup_type=f"{tf} Candle Range Theory (CRT)",
                bias=bias, entry=entry, stop=stop, target=target,
                timeframe=tf, event=StructEvent.MSS,
                range_high=r_high, range_low=r_low))
        return out

    def _safe(self, fn, *args) -> List[Signal]:
        try:
            return fn(*args)
        except Exception as e:
            print(f"[{self.symbol}] {fn.__name__} error: {e}")
            return []

    def evaluate(self) -> List[Signal]:
        signals: List[Signal] = []
        bias = self.htf_bias()

        ltf: List[Signal] = []
        if bias != Bias.NEUTRAL:
            htf4 = self.feed.get_candles(self.symbol, "4H")
            if _htf_liquidity_swept(htf4, bias):
                print(f"[{self.symbol}] liquidity swept -> REVERSAL")
                ltf = self._safe(self.check_reversal_setups, bias)
            else:
                ltf = self._safe(self.check_typed_setups, bias)

        ltf = _dedupe(ltf)

        for s in ltf + self._safe(self.check_crt):
            if not _valid_geometry(s):
                print(f"[{self.symbol}] skipped {s.setup_type}: bad geometry "
                      f"e={s.entry} sl={s.stop} tp={s.target}")
                continue
            if s.rr() is None or s.rr() >= MIN_RR:
                signals.append(s)
            else:
                print(
                    f"[{self.symbol}] skip {s.setup_type}: "
                    f"R:R {s.rr()} < {MIN_RR}"
                )
        return signals
