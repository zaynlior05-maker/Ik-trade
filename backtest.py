"""
Backtest harness.

Replays historical candles through the SAME AlignmentEngine the live bot uses,
then checks each signal forward to see whether TP or SL was hit first. Prints
win rate and expectancy (in R) per symbol and setup, so you can tune the
constants (MIN_RR, consolidation_mult, SWING_LOOKBACK, ...) on evidence.

Two ways to run:
  python backtest.py            # uses your live OANDA/ccxt keys to pull history
  python backtest.py --demo     # runs on synthetic data, no keys needed (sanity)

How it works: BacktestFeed serves only the candles that had CLOSED as of a moving
cursor, so evaluate() sees exactly what it would have seen live at that moment.
The cursor walks the 15M timeline; each new signal is simulated forward on 15M.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Tuple

from models import Candle, Signal, Bias
from data.feeds import TF_SECONDS
from analysis.pipeline import AlignmentEngine

TFS = ("4H", "3H", "1H", "30M", "15M")
WARMUP = 200          # bars of 15M history before we start evaluating
MAX_FORWARD = 200     # 15M bars to wait for TP/SL before calling a trade "open"


class BacktestFeed:
    """Serves candles up to `cursor` (epoch secs). Mimics the live DataFeed API."""

    def __init__(self, history: Dict[Tuple[str, str], List[Candle]]):
        self._data = history
        self.cursor = 0

    def get_candles(self, symbol: str, timeframe: str, count: int = 300) -> List[Candle]:
        full = self._data.get((symbol, timeframe), [])
        closed = [c for c in full if c.ts + TF_SECONDS[timeframe] <= self.cursor]
        return closed[-count:]


def simulate(signal: Signal, fwd: List[Candle]) -> float | None:
    """
    Return realized R: +rr on TP, -1.0 on SL, None if neither within MAX_FORWARD.
    If a single candle straddles both, assume SL first (conservative).
    """
    rr = signal.rr()
    if rr is None:
        return None
    for c in fwd[:MAX_FORWARD]:
        if signal.bias == Bias.BULLISH:
            if c.low <= signal.stop:
                return -1.0
            if c.high >= signal.target:
                return rr
        else:
            if c.high >= signal.stop:
                return -1.0
            if c.low <= signal.target:
                return rr
    return None


def run_symbol(symbol: str, history: Dict[Tuple[str, str], List[Candle]]) -> None:
    feed = BacktestFeed(history)
    engine = AlignmentEngine(feed, symbol)
    base = history[(symbol, "15M")]
    seen: set[str] = set()
    results: Dict[str, List[float]] = {}

    for i in range(WARMUP, len(base) - 1):
        feed.cursor = base[i].ts + TF_SECONDS["15M"]      # close of this 15M bar
        for sig in engine.evaluate():
            key = f"{sig.setup_type}|{sig.bias.value}|{round(sig.entry, 1)}"
            if key in seen:
                continue
            seen.add(key)
            r = simulate(sig, base[i + 1:])
            if r is None:
                continue
            results.setdefault(sig.setup_type, []).append(r)

    _print_report(symbol, results)


def _print_report(symbol: str, results: Dict[str, List[float]]) -> None:
    print(f"\n===== {symbol} =====")
    if not results:
        print("  no resolved signals in this window")
        return
    for setup, rs in results.items():
        wins = sum(1 for r in rs if r > 0)
        n = len(rs)
        expectancy = sum(rs) / n
        print(f"  {setup}")
        print(f"    trades {n} | win% {100*wins/n:.0f} | "
              f"expectancy {expectancy:+.2f}R | total {sum(rs):+.1f}R")


# --- data loading -------------------------------------------------------------

def load_from_live(symbols: List[str], count: int = 1500) -> Dict[Tuple[str, str], List[Candle]]:
    from data.feeds import OandaFeed, CcxtFeed
    forex = {"XAUUSD", "GBPCAD", "USDJPY"}
    oanda = OandaFeed(os.environ["OANDA_TOKEN"], os.getenv("OANDA_ENV", "practice")) \
        if any(s in forex for s in symbols) else None
    ccxt_feed = CcxtFeed(os.getenv("CCXT_EXCHANGE", "kraken"))
    hist: Dict[Tuple[str, str], List[Candle]] = {}
    for s in symbols:
        feed = oanda if s in forex else ccxt_feed
        for tf in TFS:
            hist[(s, tf)] = feed.get_candles(s, tf, count)
            print(f"loaded {s} {tf}: {len(hist[(s, tf)])} candles")
    return hist


def _demo_history() -> Dict[Tuple[str, str], List[Candle]]:
    import random
    random.seed(7)
    hist: Dict[Tuple[str, str], List[Candle]] = {}
    for tf in TFS:
        step = TF_SECONDS[tf]
        n = 600
        candles, p, t = [], 100.0, 0
        for _ in range(n):
            o = p
            p += random.uniform(-1, 1.05)          # slight upward drift
            h = max(o, p) + random.uniform(0, 0.6)
            l = min(o, p) - random.uniform(0, 0.6)
            candles.append(Candle(ts=t, open=o, high=h, low=l, close=round(p, 2)))
            t += step
        hist[("DEMO", tf)] = candles
    return hist


def main() -> None:
    if "--demo" in sys.argv:
        run_symbol("DEMO", _demo_history())
        return
    symbols = ["XAUUSD", "GBPCAD", "USDJPY", "BTCUSD"]
    hist = load_from_live(symbols)
    for s in symbols:
        run_symbol(s, hist)


if __name__ == "__main__":
    main()
