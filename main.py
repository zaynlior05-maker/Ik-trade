"""
Entry point. Routes each pair to the right feed, evaluates on a fixed cadence,
and de-dupes so the same setup isn't re-sent on every scan.

Run:  python main.py
Config comes from environment variables (see .env.example).
"""
from __future__ import annotations

import os
import time
from typing import Dict

from data.feeds import OandaFeed, CcxtFeed
from analysis.pipeline import AlignmentEngine
from alerts.telegram import send_signal_with_chart

FOREX = {"XAUUSD", "GBPCAD", "USDJPY"}
CRYPTO = {"BTCUSD"}
SCAN_SECONDS = int(os.getenv("SCAN_SECONDS", "60"))  # how often to poll


def build_engines() -> Dict[str, AlignmentEngine]:
    engines: Dict[str, AlignmentEngine] = {}
    if FOREX:
        oanda = OandaFeed(
            token=os.environ["OANDA_TOKEN"],
            environment=os.getenv("OANDA_ENV", "practice"),
        )
        for s in FOREX:
            engines[s] = AlignmentEngine(oanda, s)
    if CRYPTO:
        ccxt_feed = CcxtFeed(exchange_id=os.getenv("CCXT_EXCHANGE", "binance"))
        for s in CRYPTO:
            engines[s] = AlignmentEngine(ccxt_feed, s)
    return engines


def signal_key(sig) -> str:
    # one alert per (pair, setup, bias, rounded stop) — stops duplicate spam
    return f"{sig.pair}|{sig.setup_type}|{sig.bias.value}|{round(sig.stop, 1)}"


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    engines = build_engines()
    seen: set[str] = set()

    print(f"Bot live. Watching {list(engines)} every {SCAN_SECONDS}s.")
    while True:
        for symbol, engine in engines.items():
            for sig in engine.evaluate():
                key = signal_key(sig)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    candles = engine.feed.get_candles(symbol, sig.timeframe)
                    send_signal_with_chart(token, chat_id, sig, candles)
                    print(f"SENT {key}  (R:R {sig.rr()})")
                except Exception as e:
                    seen.discard(key)  # allow retry next loop
                    print(f"send failed for {key}: {e}")
        time.sleep(SCAN_SECONDS)


if __name__ == "__main__":
    main()
