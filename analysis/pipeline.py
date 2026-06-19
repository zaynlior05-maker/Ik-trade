"""
The alignment engine. This is where your strict top-down rule lives:

    LTF entry NEVER fires unless 4H and 1H agree on bias AND price has tapped a
    valid HTF POI in that direction.

Flow per symbol on each evaluation:
    1. HTF bias = bias(4H) and bias(1H); must MATCH and be non-neutral.
    2. Build active POIs (OB/FVG) on 4H and 1H in the bias direction.
    3. If current price is inside a POI -> "armed".
    4. While armed, scan 30M then 15M for an MSS/CHoCH in the bias direction.
    5. On confirmation (candle close) -> emit a Signal.
    Also: independently scan 3H/4H CRT as a second setup type.
"""
from __future__ import annotations

from typing import List, Optional

from models import Signal, Bias, StructEvent
from analysis import structure as st
from analysis import poi as poi_mod
from analysis import crt as crt_mod
from analysis import setups as setups_mod

MIN_RR = 1.5  # suppress signals whose reward:risk is below this


class AlignmentEngine:
    def __init__(self, feed, symbol: str):
        self.feed = feed
        self.symbol = symbol

    # --- HTF -----------------------------------------------------------------
    def htf_bias(self) -> Bias:
        b4 = st.bias_from_structure(self.feed.get_candles(self.symbol, "4H"))
        b1 = st.bias_from_structure(self.feed.get_candles(self.symbol, "1H"))
        # 4H leads; 1H must agree OR be neutral. Only an actively conflicting 1H stands us down.
        if b4 == Bias.NEUTRAL or (b1 != Bias.NEUTRAL and b1 != b4):
            bias = Bias.NEUTRAL
        else:
            bias = b4
        print(f"[{self.symbol}] HTF bias  4H={b4.value}  1H={b1.value}  ->  {bias.value}")
        return bias

    # --- Setup 1: HTF POI tap + LTF MSS -------------------------------------
    def check_poi_alignment(self) -> Optional[Signal]:
        bias = self.htf_bias()
        if bias == Bias.NEUTRAL:
            return None

        htf = self.feed.get_candles(self.symbol, "4H") + self.feed.get_candles(self.symbol, "1H")
        pois = poi_mod.active_pois(htf, bias)
        price = self.feed.get_candles(self.symbol, "15M")[-1].close
        if not poi_mod.price_tapped_poi(price, pois):
            return None  # not at a POI -> stay flat

        # armed: look for confirmation on 30M then 15M
        for tf in ("30M", "15M"):
            ltf = self.feed.get_candles(self.symbol, tf)
            event = st.detect_structure_event(ltf, prevailing=_opposite(bias))
            if event in (StructEvent.MSS, StructEvent.CHOCH):
                entry = ltf[-1].close
                stop = st.structural_stop(ltf, bias)
                target = self._next_opposing_level(htf, bias, entry)
                return Signal(
                    pair=self.symbol,
                    setup_type="HTF POI Tap + LTF Alignment",
                    bias=bias, entry=entry, stop=stop, target=target,
                    timeframe=tf, event=event,
                )
        return None

    # --- Setup 2: 3H/4H CRT --------------------------------------------------
    def check_crt(self) -> Optional[Signal]:
        for tf in ("4H", "3H"):
            candles = self.feed.get_candles(self.symbol, tf)
            res = crt_mod.detect_crt(candles)
            if not res:
                continue
            bias, r_low, r_high = res
            entry = candles[-1].close
            stop = r_low if bias == Bias.BULLISH else r_high
            target = r_high if bias == Bias.BULLISH else r_low
            return Signal(
                pair=self.symbol, setup_type=f"{tf} Candle Range Theory (CRT)",
                bias=bias, entry=entry, stop=stop, target=target,
                timeframe=tf, event=StructEvent.MSS,
                range_high=r_high, range_low=r_low,
            )
        return None

    # --- Setup 3: Type A/B/C structured setups (LTF) ------------------------
    def check_typed_setups(self) -> Optional[Signal]:
        bias = self.htf_bias()
        if bias == Bias.NEUTRAL:
            return None
        for tf in ("30M", "15M"):
            ltf = self.feed.get_candles(self.symbol, tf)
            sig = setups_mod.typed_signal(self.symbol, ltf, bias, tf)
            if sig:
                return sig
        return None

    def evaluate(self) -> List[Signal]:
        signals = []
        for fn in (self.check_poi_alignment, self.check_crt, self.check_typed_setups):
            try:
                s = fn()
                if s and (s.rr() is None or s.rr() >= MIN_RR):
                    signals.append(s)
                elif s:
                    print(f"[{self.symbol}] skipped {s.setup_type}: R:R {s.rr()} < {MIN_RR}")
            except Exception as e:  # never let one symbol kill the loop
                print(f"[{self.symbol}] {fn.__name__} error: {e}")
        return signals

    # --- helpers -------------------------------------------------------------
    def _next_opposing_level(self, htf, bias: Bias, entry: float) -> float:
        swings = st.find_swings(htf)
        if bias == Bias.BULLISH:
            highs = [s.price for s in swings if s.kind == "high" and s.price > entry]
            return min(highs) if highs else entry * 1.01
        lows = [s.price for s in swings if s.kind == "low" and s.price < entry]
        return max(lows) if lows else entry * 0.99


def _opposite(b: Bias) -> Bias:
    return Bias.BEARISH if b == Bias.BULLISH else Bias.BULLISH
    return Bias.BEARISH if b == Bias.BULLISH else Bias.BULLISH
