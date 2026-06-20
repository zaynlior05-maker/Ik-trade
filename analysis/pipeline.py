"""
The alignment engine.

Setups (POI + Type A/B/C respect the 4H/1H bias; CRT is range-based):
  1. POI setups (4H / 1H / 15M): a valid OB/FVG in the bias direction ->
       PENDING alert (set a limit) while price is away from it, then
       MARKET  alert (enter now) the moment price taps it.
  2. CRT        (4H / 3H): candle-range sweep + close back inside.
  3. Type A/B/C (30M / 15M): the MSS -> IDM -> BOS -> POI sequence.
"""
from __future__ import annotations

from typing import List, Optional

from models import Signal, Bias, StructEvent
from analysis import structure as st
from analysis import poi as poi_mod
from analysis import crt as crt_mod
from analysis import setups as setups_mod

MIN_RR = 1.3                       # suppress signals whose reward:risk is below this
POI_TIMEFRAMES = ("4H", "1H", "15M")
CRT_TIMEFRAMES = ("4H", "3H")


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

    # --- Setup 1: POI pending + market (4H / 1H / 15M) -----------------------
    def check_poi_setups(self) -> List[Signal]:
        bias = self.htf_bias()
        if bias == Bias.NEUTRAL:
            return []
        price = self.feed.get_candles(self.symbol, "15M")[-1].close
        htf = self.feed.get_candles(self.symbol, "4H") + self.feed.get_candles(self.symbol, "1H")
        out: List[Signal] = []
        for tf in POI_TIMEFRAMES:
            candles = self.feed.get_candles(self.symbol, tf)
            pois = poi_mod.active_pois(candles, bias)
            if bias == Bias.BULLISH:
                pois = [p for p in pois if p.bottom <= price]   # demand at/below price
            else:
                pois = [p for p in pois if p.top >= price]      # supply at/above price
            if pois:
                out.append(self._poi_signal(pois[0], bias, price, tf, htf))
        return out

    def _poi_signal(self, poi, bias, price, tf, htf) -> Signal:
        if bias == Bias.BULLISH:
            limit, stop, direction = poi.top, poi.bottom, "BUY"
        else:
            limit, stop, direction = poi.bottom, poi.top, "SELL"
        target = self._next_opposing_level(htf, bias, limit)
        if poi.contains(price):
            entry, state = price, f"MARKET \u2014 {direction} now"
        else:
            entry, state = limit, f"PENDING \u2014 set {direction} LIMIT"
        return Signal(
            pair=self.symbol, setup_type=f"{tf} POI {poi.kind} \u2014 {state}",
            bias=bias, entry=entry, stop=stop, target=target,
            timeframe=tf, event=StructEvent.MSS,
        )

    # --- Setup 2: CRT (4H / 3H only) ----------------------------------------
    def check_crt(self) -> List[Signal]:
        out: List[Signal] = []
        for tf in CRT_TIMEFRAMES:
            candles = self.feed.get_candles(self.symbol, tf)
            res = crt_mod.detect_crt(candles)
            if not res:
                continue
            bias, r_low, r_high = res
            entry = candles[-1].close
            stop = r_low if bias == Bias.BULLISH else r_high
            target = r_high if bias == Bias.BULLISH else r_low
            out.append(Signal(
                pair=self.symbol, setup_type=f"{tf} Candle Range Theory (CRT)",
                bias=bias, entry=entry, stop=stop, target=target,
                timeframe=tf, event=StructEvent.MSS, range_high=r_high, range_low=r_low))
        return out

    # --- Setup 3: Type A/B/C (30M / 15M) ------------------------------------
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

    # --- run all -------------------------------------------------------------
    def evaluate(self) -> List[Signal]:
        signals: List[Signal] = []
        for fn in (self.check_poi_setups, self.check_crt, self.check_typed_setups):
            try:
                res = fn()
                items = res if isinstance(res, list) else ([res] if res else [])
                for s in items:
                    if s.rr() is None or s.rr() >= MIN_RR:
                        signals.append(s)
                    else:
                        print(f"[{self.symbol}] skipped {s.setup_type}: R:R {s.rr()} < {MIN_RR}")
            except Exception as e:
                print(f"[{self.symbol}] {fn.__name__} error: {e}")
        return signals

    # --- helper --------------------------------------------------------------
    def _next_opposing_level(self, htf, bias: Bias, entry: float) -> float:
        swings = st.find_swings(htf)
        if bias == Bias.BULLISH:
            highs = [s.price for s in swings if s.kind == "high" and s.price > entry]
            return min(highs) if highs else entry * 1.01
        lows = [s.price for s in swings if s.kind == "low" and s.price < entry]
        return max(lows) if lows else entry * 0.99
    return Bias.BEARISH if b == Bias.BULLISH else Bias.BULLISH
