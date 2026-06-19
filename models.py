"""Core data models shared across the bot."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Bias(str, Enum):
    BULLISH = "Bullish"
    BEARISH = "Bearish"
    NEUTRAL = "Neutral"  # no clean structure -> no trade


class StructEvent(str, Enum):
    BOS = "BOS"      # break of structure (continuation)
    CHOCH = "CHoCH"  # change of character (first counter-break)
    MSS = "MSS"      # CHoCH confirmed with displacement


@dataclass(frozen=True)
class Candle:
    ts: int          # epoch seconds of candle OPEN
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def rng(self) -> float:
        return self.high - self.low

    @property
    def bullish(self) -> bool:
        return self.close >= self.open


@dataclass(frozen=True)
class Swing:
    ts: int
    price: float
    kind: str  # "high" or "low"


@dataclass(frozen=True)
class POI:
    """An order block or FVG zone."""
    kind: str           # "OB" or "FVG"
    direction: Bias     # the direction it supports
    top: float
    bottom: float
    ts: int
    mitigated: bool = False

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top


@dataclass
class Signal:
    pair: str
    setup_type: str
    bias: Bias
    entry: float
    stop: float
    target: float
    timeframe: str          # the LTF that confirmed (e.g. "15M")
    event: StructEvent
    range_high: Optional[float] = None   # set for CRT signals
    range_low: Optional[float] = None

    def rr(self) -> Optional[float]:
        risk = abs(self.entry - self.stop)
        reward = abs(self.target - self.entry)
        return round(reward / risk, 2) if risk else None
