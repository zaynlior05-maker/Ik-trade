"""
Data feeds. One interface, two implementations:

  - OandaFeed : forex / metals (XAUUSD, GBPCAD, USDJPY). Free practice key.
  - CcxtFeed  : crypto (BTCUSD) via any ccxt-supported exchange.

Both return a list[Candle] of CLOSED candles, oldest -> newest.

Timeframe strings used throughout the bot: "15M","30M","1H","3H","4H".
OANDA supports H3 natively. Most crypto exchanges do NOT expose 3H, so we
resample it from 1H (see resample()).
"""
from __future__ import annotations

from typing import List, Dict
import time

from models import Candle

# --- timeframe helpers --------------------------------------------------------

TF_SECONDS: Dict[str, int] = {
    "15M": 15 * 60, "30M": 30 * 60,
    "1H": 3600, "3H": 3 * 3600, "4H": 4 * 3600,
}

_OANDA_GRAN = {"15M": "M15", "30M": "M30", "1H": "H1", "3H": "H3", "4H": "H4"}
_CCXT_TF = {"15M": "15m", "30M": "30m", "1H": "1h", "4H": "4h"}  # note: no 3h


def resample(candles: List[Candle], factor: int) -> List[Candle]:
    """Aggregate N base candles into one (e.g. 3x 1H -> 3H). Drops trailing partial."""
    out: List[Candle] = []
    for i in range(0, len(candles) - factor + 1, factor):
        chunk = candles[i:i + factor]
        out.append(Candle(
            ts=chunk[0].ts,
            open=chunk[0].open,
            high=max(c.high for c in chunk),
            low=min(c.low for c in chunk),
            close=chunk[-1].close,
            volume=sum(c.volume for c in chunk),
        ))
    return out


class DataFeed:
    def get_candles(self, symbol: str, timeframe: str, count: int = 300) -> List[Candle]:
        raise NotImplementedError


# --- OANDA (forex / metals) ---------------------------------------------------

class OandaFeed(DataFeed):
    """Requires: pip install oandapyV20 ; an OANDA practice/live token + account id."""

    # map your bot symbols -> OANDA instruments
    SYMBOLS = {"XAUUSD": "XAU_USD", "GBPCAD": "GBP_CAD", "USDJPY": "USD_JPY"}

    def __init__(self, token: str, environment: str = "practice"):
        from oandapyV20 import API
        self._api = API(access_token=token, environment=environment)

    def get_candles(self, symbol: str, timeframe: str, count: int = 300) -> List[Candle]:
        from oandapyV20.endpoints.instruments import InstrumentsCandles
        instrument = self.SYMBOLS[symbol]
        params = {"granularity": _OANDA_GRAN[timeframe], "count": count, "price": "M"}
        req = InstrumentsCandles(instrument=instrument, params=params)
        self._api.request(req)
        out: List[Candle] = []
        for c in req.response["candles"]:
            if not c["complete"]:          # skip the still-forming candle
                continue
            m = c["mid"]
            out.append(Candle(
                ts=int(_parse_rfc3339(c["time"])),
                open=float(m["o"]), high=float(m["h"]),
                low=float(m["l"]), close=float(m["c"]),
                volume=float(c.get("volume", 0)),
            ))
        return out


# --- Crypto (ccxt) ------------------------------------------------------------

class CcxtFeed(DataFeed):
    """Requires: pip install ccxt. Default exchange Binance; BTCUSD -> BTC/USDT."""

    SYMBOLS = {"BTCUSD": "BTC/USDT"}

    def __init__(self, exchange_id: str = "binance"):
        import ccxt
        self._ex = getattr(ccxt, exchange_id)({"enableRateLimit": True})

    def get_candles(self, symbol: str, timeframe: str, count: int = 300) -> List[Candle]:
        market = self.SYMBOLS[symbol]
        if timeframe == "3H":
            # exchange has no 3h: pull 3x 1H and aggregate
            base = self._fetch(market, "1h", count * 3)
            return resample(base, 3)
        return self._fetch(market, _CCXT_TF[timeframe], count)

    def _fetch(self, market: str, tf: str, count: int) -> List[Candle]:
        rows = self._ex.fetch_ohlcv(market, timeframe=tf, limit=count + 1)
        # last row may be the open candle; drop it to keep only closed candles
        now_ms = self._ex.milliseconds()
        tf_ms = self._ex.parse_timeframe(tf) * 1000
        rows = [r for r in rows if r[0] + tf_ms <= now_ms]
        return [Candle(ts=int(r[0] / 1000), open=r[1], high=r[2],
                       low=r[3], close=r[4], volume=r[5]) for r in rows]


def _parse_rfc3339(s: str) -> float:
    # OANDA returns e.g. "2026-06-18T16:00:00.000000000Z"
    s = s.split(".")[0].rstrip("Z")
    return time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%S"))
