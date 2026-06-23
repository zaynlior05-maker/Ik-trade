"""
Render a signal as a candlestick PNG (in-memory) to attach to the Telegram alert.
Headless 'Agg' backend so it works on a server with no display.

For Type A/B/C signals it re-derives and MARKS the structure on the chart:
POI zone, MSS, IDM (liquidity), BOS -- so the reason for the entry is visible.
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
MARK_C = "#22324f"


def _mark(ax, x, y, text, color):
    ax.annotate(text, (x, y), fontsize=7.5, fontweight="bold", color=color,
                ha="center", va="bottom",
                xytext=(0, 6), textcoords="offset points")
    ax.plot([x], [y], marker="o", markersize=3, color=color, zorder=6)


def _annotate_structure(ax, sig, candles, offset):
    """Mark POI / MSS / IDM / BOS for typed setups. Best-effort; never raises."""
    try:
        from analysis.setups import detect_events
        ev = detect_events(candles, sig.bias)
        if ev.poi is not None:
            ax.axhspan(ev.poi.bottom, ev.poi.top, color=ZONE_C, alpha=0.16, zorder=1)
            ax.text(0.5, (ev.poi.top + ev.poi.bottom) / 2,
                    f" POI ({ev.poi.kind})", fontsize=7.5, color=ZONE_C,
                    va="center", fontweight="bold")
        marks = []
        if ev.mss_idx is not None:
            marks.append((ev.mss_idx, candles[ev.mss_idx].low, "MSS", MARK_C))
        idm = ev.idm_after if ev.idm_after is not None else ev.idm_before
        if idm is not None:
            marks.append((idm, candles[idm].high, "IDM", DOWN))
        if ev.bos_idx is not None:
            marks.append((ev.bos_idx, candles[ev.bos_idx].low, "BOS", MARK_C))
        for idx, y, text, color in marks:
            x = idx - offset
            if x >= 0:
                _mark(ax, x, y, text, color)
    except Exception as e:
        print(f"structure annotate skipped: {e}")


def render_signal_png(sig, candles: List, lookback: int = 70) -> Optional[bytes]:
    cs = candles[-lookback:]
    if len(cs) < 3:
        return None
    offset = len(candles) - len(cs)

    tick = max(abs(cs[-1].close) * 1e-5, 1e-6)
    fig, ax = plt.subplots(figsize=(8, 4.6))

    for i, c in enumerate(cs):
        up = c.close >= c.open
        col = UP if up else DOWN
        ax.plot([i, i], [c.low, c.high], color=col, lw=0.8, zorder=2)
        lo, hi = (c.open, c.close) if up else (c.close, c.open)
        ax.add_patch(Rectangle((i - 0.3, lo), 0.6, max(hi - lo, tick),
                               facecolor=col, edgecolor=col, zorder=3))

    if sig.range_high is not None and sig.range_low is not None:
        # CRT: shade the range
        ax.axhspan(sig.range_low, sig.range_high, color=ZONE_C, alpha=0.12, zorder=1)
    else:
        # Typed setup: mark POI / MSS / IDM / BOS
        _annotate_structure(ax, sig, candles, offset)

    n = len(cs)
    for y, col, lab in [(sig.entry, ENTRY_C, "Entry"),
                        (sig.stop, SL_C, "SL"),
                        (sig.target, TP_C, "TP")]:
        ax.axhline(y, color=col, lw=1.3, zorder=4)
        ax.text(n - 0.5, y, f"  {lab} {y:.3f}", color=col, fontsize=8,
                va="center", fontweight="bold")

    ax.set_title(f"{sig.pair}  {sig.timeframe}  -  {sig.setup_type}",
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
