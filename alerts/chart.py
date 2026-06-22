"""
Render a signal as a candlestick PNG (in-memory) to attach to the Telegram alert.
Headless 'Agg' backend so it works on a server with no display.
"""
from __future__ import annotations

import io
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

UP = "#1f9d8f"
DOWN = "#e05a5a"
ENTRY_C = "#1f9d8f"
SL_C = "#e05a5a"
TP_C = "#2b6cb0"
ZONE_C = "#b9842b"


def render_signal_png(sig, candles: List, lookback: int = 60) -> Optional[bytes]:
    cs = candles[-lookback:]
    if len(cs) < 3:
        return None

    tick = max(abs(cs[-1].close) * 1e-5, 1e-6)   # min body height so dojis show
    fig, ax = plt.subplots(figsize=(8, 4.6))

    for i, c in enumerate(cs):
        up = c.close >= c.open
        col = UP if up else DOWN
        ax.plot([i, i], [c.low, c.high], color=col, lw=0.8, zorder=2)
        lo, hi = (c.open, c.close) if up else (c.close, c.open)
        ax.add_patch(Rectangle((i - 0.3, lo), 0.6, max(hi - lo, tick),
                               facecolor=col, edgecolor=col, zorder=3))

    # shaded zone: CRT range, else the POI bracket (entry..stop)
    if sig.range_high is not None and sig.range_low is not None:
        ax.axhspan(sig.range_low, sig.range_high, color=ZONE_C, alpha=0.12, zorder=1)
    else:
        z1, z2 = sorted([sig.entry, sig.stop])
        ax.axhspan(z1, z2, color=ZONE_C, alpha=0.12, zorder=1)

    n = len(cs)
    for y, col, lab in [(sig.entry, ENTRY_C, "Entry"),
                        (sig.stop, SL_C, "SL"),
                        (sig.target, TP_C, "TP")]:
        ax.axhline(y, color=col, lw=1.3, zorder=4)
        ax.text(n - 0.5, y, f"  {lab} {y:.3f}", color=col, fontsize=8,
                va="center", fontweight="bold")

    ax.set_title(f"{sig.pair}  {sig.timeframe}  \u2014  {sig.setup_type}",
                 fontsize=10, fontweight="bold")
    ax.set_xlim(-1, n + 9)
    ax.set_xticks([])
    for s in ("top", "right", "bottom"):
        ax.spines[s].set_visible(False)

    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", dpi=130, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
