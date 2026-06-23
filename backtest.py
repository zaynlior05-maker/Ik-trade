"""
Backtest harness.

Replays history through the SAME AlignmentEngine the live bot uses, then checks
each signal forward (TP vs SL first) and prints win rate + expectancy in R, per
setup type. PENDING signals are only counted if price actually reaches the limit
(the fill) before anything else.

Run on Railway: set the Procfile worker to `python -u backtest.py`, deploy, read
the logs, then set it back to `python -u main.py`.

Local:
  python backtest.py            # uses your OANDA/ccxt keys to pull history
  python backtest.py --demo     # synthetic data, no keys (sanity only)
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Tuple

from models import Candle, Signal, Bias
from data.feeds import TF_SECONDS
from analysis.pipeline import AlignmentEngine

TFS = ("4H", "3H", "1H", "30M", "15M")
WARMUP = 200
MAX_FORWARD = 200


class BacktestFeed:
    """Serves candles up to `cursor` (epoch secs). Mimics the live feed API."""

    def __init__(self, history: Dict[Tuple[str, str], List[Candle]]):
        self._data = history
        self.cursor = 0

    def get_candles(self, symbol, timeframe, count=300):
        full = self._data.get((symbol, timeframe), [])
        closed = [c for c in full if c.ts + TF_SECONDS[timeframe] <= self.cursor]
        return closed[-count:]


def simulate(signal: Signal, fwd: List[Candle]):
    """Realized R: +rr on TP, -1.0 on SL, None if unresolved. Models limit fill."""
    rr = signal.rr()
    if rr is None:
        return None
    pending = "PENDING" in signal.setup_type
    filled = not pending
    for c in fwd[:MAX_FORWARD]:
        if not filled:
            # limit order fills only if price trades to the entry level
            if c.low <= signal.entry <= c.high:
                filled = True
            else:
                continue
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


def _core_type(setup_type: str) -> str:
    """Collapse 'Type A (OB) - MARKET ...' to a clean bucket for reporting."""
    s = setup_type
    rev = "Reversal " if s.startswith("Reversal") else ""
    if "Type A" in s:
        return rev + "Type A"
    if "Type B" in s:
        return rev + "Type B"
    if "Type C" in s:
        return rev + "Type C"
    if "CRT" in s:
        return "CRT"
    return s


def run_symbol(symbol, history, totals):
    feed = BacktestFeed(history)
    engine = AlignmentEngine(feed, symbol)
    base = history[(symbol, "15M")]
    seen: set[str] = set()
    results: Dict[str, List[float]] = {}

    for i in range(WARMUP, len(base) - 1):
        feed.cursor = base[i].ts + TF_SECONDS["15M"]
        for sig in engine.evaluate():
            key = f"{sig.setup_type}|{sig.bias.value}|{round(sig.stop, 1)}"
            if key in seen:
                continue
            seen.add(key)
            r = simulate(sig, base[i + 1:])
            if r is None:
                continue
            bucket = _core_type(sig.setup_type)
            results.setdefault(bucket, []).append(r)
            totals.setdefault(bucket, []).append(r)

    _print_report(symbol, results)


def _print_report(title, results):
    print(f"\n===== {title} =====")
    if not results:
        print("  no resolved signals in this window")
        return
    for setup, rs in sorted(results.items()):
        wins = sum(1 for r in rs if r > 0)
        n = len(rs)
        exp = sum(rs) / n
        print(
            f"  {setup:18} trades {n:3} | "
            f"win% {100*wins/n:3.0f} | "
            f"exp {exp:+.2f}R | total {sum(rs):+.1f}R"
        )


def load_from_live(symbols, count=1500):
    from data.feeds import OandaFeed, CcxtFeed
    forex = {"XAUUSD", "GBPCAD", "USDJPY"}
    oanda = None
    if any(s in forex for s in symbols):
        oanda = OandaFeed(os.environ["OANDA_TOKEN"],
                          os.getenv("OANDA_ENV", "practice"))
    ccxt_feed = CcxtFeed(os.getenv("CCXT_EXCHANGE", "kraken"))
    hist: Dict[Tuple[str, str], List[Candle]] = {}
    for s in symbols:
        feed = oanda if s in forex else ccxt_feed
        for tf in TFS:
            hist[(s, tf)] = feed.get_candles(s, tf, count)
            print(f"loaded {s} {tf}: {len(hist[(s, tf)])} candles")
    return hist


def _demo_history():
    import random
    random.seed(7)
    hist: Dict[Tuple[str, str], List[Candle]] = {}
    for tf in TFS:
        step = TF_SECONDS[tf]
        candles, p, t = [], 100.0, 0
        for _ in range(600):
            o = p
            p += random.uniform(-1, 1.05)
            h = max(o, p) + random.uniform(0, 0.6)
            l = min(o, p) - random.uniform(0, 0.6)
            candles.append(Candle(ts=t, open=o, high=h, low=l, close=round(p, 2)))
            t += step
        hist[("DEMO", tf)] = candles
    return hist


def main():
    totals: Dict[str, List[float]] = {}
    if "--demo" in sys.argv:
        run_symbol("DEMO", _demo_history(), totals)
    else:
        symbols = ["XAUUSD", "GBPCAD", "USDJPY", "BTCUSD"]
        hist = load_from_live(symbols)
        for s in symbols:
            run_symbol(s, hist)
    _print_report("ALL SYMBOLS (combined)", totals)
    print("\nDone. Set the Procfile worker back to: python -u main.py")


if __name__ == "__main__":
    main()
