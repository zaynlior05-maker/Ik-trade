"""
The alignment engine — disciplined SMC/ICT signals only.

Every LOWER-TIMEFRAME signal (continuation OR reversal) must show ALL FOUR:
    Structure (MSS)  +  Liquidity (IDM sweep)  +  BOS  +  POI (OB or BB)

CONTINUATION : trade WITH the 4H/1H bias (the default).
REVERSAL     : trade AGAINST the bias, but only when "armed" — i.e. price has
               swept the trend's own liquidity extreme (a prior swing high in an
               uptrend / swing low in a downtrend) AND rejected it (closed back
               inside). The counter-trend MSS is the CHoCH. At an extreme we hunt
               reversal; otherwise continuation.

CRT is the only range setup: 4H ONLY, and only when the sweep took out a real
key level.
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
    """Reject malformed signals: SL below & TP above entry for longs, opposite for shorts."""
    if s.bias == Bias.BULLISH:
        return s.stop < s.entry < s.target
    return s.stop > s.entry > s.target


def _htf_liquidity_swept(htf, bias: Bias, window: int = 3) -> bool:
    """
    Reversal arming: did price sweep the trend's liquidity extreme AND reject it?
      uptrend   -> a recent candle wicked ABOVE a prior swing high but the latest
                   candle CLOSED back below it (failed breakout = buy-side grab).
      downtrend -> wicked BELOW a prior swing low but CLOSED back above it.
    """
    swings = st.find_swings(htf)
    if bias == Bias.BULLISH:
        highs = [s.price for s in swings if s.kind == "high"]
        if not highs:
            return False
        level = max(highs[-3:])                     # a recent swing-high liquidity pool
        swept = any(c.high > level for c in htf[-window:])
        rejected = htf[-1].close < level            # closed back BELOW = failed breakout
        return swept and rejected
    lows = [s.price for s in swings if s.kind == "low"]
    if not lows:
        return False
    level = min(lows[-3:])
    swept = any(c.low < level for c in htf[-window:])
    rejected = htf[-1].close > level                # closed back ABOVE = failed breakdown
    return swept and rejected


def _opposite(b: Bias) -> Bias:
    return Bias.BEARISH if b == Bias.BULLISH else Bias.BULLISH


class AlignmentEngine:
    def __init__(self, feed, symbol: str):
        self.feed = feed
        self.symbol = symbol

    # --- HTF bias ------------------------------------------------------------
    def htf_bias(self) -> Bias:
        b4 = st.bias_from_structure(self.feed.get_candles(self.symbol, "4H"))
        b1 = st.bias_from_structure(self.feed.get_candles(self.symbol, "1H"))
        if b4 == Bias.NEUTRAL or (b1 != Bias.NEUTRAL and b1 != b4):
            bias = Bias.NEUTRAL
        else:
            bias = b4
        print(f"[{self.symbol}] HTF bias  4H={b4.value}  1H={b1.value}  ->  {bias.value}")
        return bias

    # --- LTF continuation: Type A/B/C WITH the bias -------------------------
    def check_typed_setups(self, bias: Bias) -> List[Signal]:
        out: List[Signal] = []
        for tf in LTF_TIMEFRAMES:
            ltf = self.feed.get_candles(self.symbol, tf)
            sig = setups_mod.typed_signal(self.symbol, ltf, bias, tf)
            if sig:
                out.append(sig)
        return out

    # --- LTF reversal: Type A/B/C AGAINST the bias (armed only) --------------
    def check_reversal_setups(self, bias: Bias) -> List[Signal]:
        rev = _opposite(bias)
        out: List[Signal] = []
        for tf in LTF_TIMEFRAMES:
            ltf = self.feed.get_candles(self.symbol, tf)
            sig = setups_mod.typed_signal(self.symbol, ltf, rev, tf)
            if sig:
                sig.setup_type = "Reversal \u2014 " + sig.setup_type
                out.append(sig)
        return out

    # --- CRT: 4H only, must sweep a key level -------------------------------
    def check_crt(self) -> List[Signal]:
        out: List[Signal] = []
        for tf in CRT_TIMEFRAMES:
            candles = self.feed.get_candles(self.symbol, tf)
            res = crt_mod.detect_crt(candles)
            if not res:
                continue
            bias, r_low, r_high = res
            if not crt_mod.swept_key_level(candles, bias, r_low, r_high):
                print(f"[{self.symbol}] CRT {tf} ignored: sweep not at a key level")
                continue
            entry = candles[-1].close
            stop = r_low if bias == Bias.BULLISH else r_high
            target = r_high if bias == Bias.BULLISH else r_low
            out.append(Signal(
                pair=self.symbol, setup_type=f"{tf} Candle Range Theory (CRT)",
                bias=bias, entry=entry, stop=stop, target=target,
                timeframe=tf, event=StructEvent.MSS, range_high=r_high, range_low=r_low))
        return out

    def _safe(self, fn, *args) -> List[Signal]:
        try:
            return fn(*args)
        except Exception as e:
            print(f"[{self.symbol}] {fn.__name__} error: {e}")
            return []

    # --- run all -------------------------------------------------------------
    def evaluate(self) -> List[Signal]:
        signals: List[Signal] = []
        bias = self.htf_bias()

        ltf: List[Signal] = []
        if bias != Bias.NEUTRAL:
            if _htf_liquidity_swept(self.feed.get_candles(self.symbol, "4H"), bias):
                print(f"[{self.symbol}] HTF liquidity swept -> hunting REVERSAL")
                ltf = self._safe(self.check_reversal_setups, bias)
            else:
                ltf = self._safe(self.check_typed_setups, bias)

        for s in ltf + self._safe(self.check_crt):
            if not _valid_geometry(s):
                print(f"[{self.symbol}] skipped {s.setup_type}: bad geometry "
                      f"entry={s.entry} sl={s.stop} tp={s.target}")
                continue
            if s.rr() is None or s.rr() >= MIN_RR:
                signals.append(s)
            else:
                print(f"[{self.symbol}] skipped {s.setup_type}: R:R {s.rr()} < {MIN_RR}")
        return signals
