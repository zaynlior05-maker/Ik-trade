"""
Candle Range Theory (CRT) on 3H/4H — to spec.

  1. Identify a structural CONSOLIDATION range (accumulation): a window of recent
     candles whose total span is tight relative to their average candle range.
     Range High = max high, Range Low = min low of that window.
  2. Valid setup = the latest candle makes a CLEAN WICK liquidity sweep OUTSIDE
     Range High/Low, with its BODY closing STRICTLY back INSIDE the range.
       - sweep below Range Low + body closes inside  -> Long (expansion up)
       - sweep above Range High + body closes inside  -> Short (expansion down)

All thresholds are tunable constants below.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Optional, Tuple

from models import Bias


@dataclass
class CRTConfig:
    window: int = 5               # candles forming the consolidation
    consolidation_mult: float = 4.0  # span must be <= mult * avg candle range
    min_wick_frac: float = 0.0    # optional: min sweep depth as frac of avg range


def _is_consolidation(window, cfg: CRTConfig) -> Optional[Tuple[float, float]]:
    if len(window) < cfg.window:
        return None
    rng_high = max(c.high for c in window)
    rng_low = min(c.low for c in window)
    span = rng_high - rng_low
    avg = mean(c.rng for c in window) or 1e-9
    if span <= cfg.consolidation_mult * avg:
        return rng_high, rng_low
    return None


def detect_crt(candles, cfg: CRTConfig = CRTConfig()) -> Optional[Tuple[Bias, float, float]]:
    """Returns (bias, range_low, range_high) if the latest candle triggers CRT."""
    if len(candles) < cfg.window + 1:
        return None
    window = candles[-(cfg.window + 1):-1]   # consolidation precedes the manipulation
    rng = _is_consolidation(window, cfg)
    if not rng:
        return None
    rng_high, rng_low = rng

    m = candles[-1]
    body_low, body_high = min(m.open, m.close), max(m.open, m.close)
    avg = mean(c.rng for c in window) or 1e-9

    # LONG: wick sweeps below range low, body strictly inside
    swept_low = m.low < rng_low and (rng_low - m.low) >= cfg.min_wick_frac * avg
    body_inside = rng_low < body_low and body_high < rng_high
    if swept_low and body_inside and rng_low < m.close < rng_high:
        return Bias.BULLISH, rng_low, rng_high

    # SHORT: wick sweeps above range high, body strictly inside
    swept_high = m.high > rng_high and (m.high - rng_high) >= cfg.min_wick_frac * avg
    if swept_high and body_inside and rng_low < m.close < rng_high:
        return Bias.BEARISH, rng_low, rng_high

    return None
