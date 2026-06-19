"""
Candle Range Theory (CRT) on 3H/4H.

RANGE ("the candle range"):
  CRH = high of the reference candle(s), CRL = low. By default the reference is
  the single prior completed candle (block_size=1). Increase block_size to define
  the range from the high/low of a block of candles.

MANIPULATION ("wicks don't count"): the current candle must WICK beyond a range
extreme but CLOSE its body back INSIDE the range. A close BEYOND the level is a
real breakout, not a sweep, and is rejected.
  - sweep CRL (wick below) + close back above CRL  -> Long  (expand toward CRH)
  - sweep CRH (wick above) + close back below CRH  -> Short (expand toward CRL)

This module flags the HTF CRT + the range to trade toward. LTF entry refinement
(MSS / breaker block) is handled by the pipeline's other setups.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from models import Bias


@dataclass
class CRTConfig:
    block_size: int = 1          # candles forming the reference range
    body_fully_inside: bool = True  # require the whole body inside the range


def detect_crt(candles, cfg: CRTConfig = CRTConfig()) -> Optional[Tuple[Bias, float, float]]:
    """Returns (bias, range_low, range_high) if the latest candle triggers CRT."""
    if len(candles) < cfg.block_size + 1:
        return None

    ref = candles[-(cfg.block_size + 1):-1]      # the range candle(s)
    crh = max(c.high for c in ref)
    crl = min(c.low for c in ref)
    m = candles[-1]                              # the manipulation candle
    body_low, body_high = min(m.open, m.close), max(m.open, m.close)
    body_inside = (crl <= body_low and body_high <= crh) if cfg.body_fully_inside else True

    # LONG: wick sweeps below CRL, body closes strictly back inside the range
    if m.low < crl and crl < m.close < crh and body_inside:
        return Bias.BULLISH, crl, crh

    # SHORT: wick sweeps above CRH, body closes strictly back inside the range
    if m.high > crh and crl < m.close < crh and body_inside:
        return Bias.BEARISH, crl, crh

    return None
