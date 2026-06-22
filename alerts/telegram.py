"""
Telegram output. Formats a Signal and posts it (with a chart) to a channel.

Setup:
  1. Create a bot with @BotFather -> TELEGRAM_BOT_TOKEN.
  2. Add the bot to your channel as an admin.
  3. TELEGRAM_CHAT_ID = "@yourchannel" or the numeric -100... id.
"""
from __future__ import annotations

import requests

from models import Signal

_MSG = "https://api.telegram.org/bot{token}/sendMessage"
_PHOTO = "https://api.telegram.org/bot{token}/sendPhoto"


def format_signal(sig: Signal) -> str:
    arrow = "\U0001f7e2" if sig.bias.value == "Bullish" else "\U0001f534"
    direction = "Long" if sig.bias.value == "Bullish" else "Short"

    if sig.range_high is not None and sig.range_low is not None:
        return (
            f"{arrow} *{sig.pair}*\n"
            f"*Setup Type:* {sig.setup_type}\n"
            f"*Direction:* {direction}\n"
            f"*CRT Range High:* `{sig.range_high:.3f}`\n"
            f"*CRT Range Low:* `{sig.range_low:.3f}`\n"
            f"*Target (TP):* `{sig.target:.3f}`  (opposing range expansion)"
        )

    head = ""
    if "PENDING" in sig.setup_type:
        head = "\u23f3 *PENDING SETUP* \u2014 place a LIMIT order (price not there yet)\n"
    elif "MARKET" in sig.setup_type:
        head = "\U0001f6a8 *LIVE* \u2014 enter at MARKET now\n"

    rr = sig.rr()
    rr_line = f"\n*R:R:* {rr}" if rr else ""
    return (
        head +
        f"{arrow} *{sig.pair}* \u2014 Signal\n"
        f"*Setup Type:* {sig.setup_type}\n"
        f"*Aligned Bias:* {sig.bias.value}\n"
        f"*Entry:* `{sig.entry:.3f}`\n"
        f"*Invalidation (SL):* `{sig.stop:.3f}`\n"
        f"*Target (TP):* `{sig.target:.3f}`"
        f"{rr_line}"
    )


def send(token: str, chat_id: str, text: str) -> None:
    resp = requests.post(
        _MSG.format(token=token),
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        timeout=15,
    )
    resp.raise_for_status()


def send_photo(token: str, chat_id: str, png: bytes, caption: str) -> None:
    resp = requests.post(
        _PHOTO.format(token=token),
        data={"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"},
        files={"photo": ("signal.png", png, "image/png")},
        timeout=30,
    )
    resp.raise_for_status()


def send_signal(token: str, chat_id: str, sig: Signal) -> None:
    """Text-only alert (fallback)."""
    send(token, chat_id, format_signal(sig))


def send_signal_with_chart(token: str, chat_id: str, sig: Signal, candles) -> None:
    """Alert with a chart attached; falls back to text if rendering/sending the image fails."""
    caption = format_signal(sig)
    try:
        from alerts.chart import render_signal_png
        png = render_signal_png(sig, candles)
        if png:
            send_photo(token, chat_id, png, caption)
            return
    except Exception as e:
        print(f"chart render/send failed ({e}); sending text only")
    send(token, chat_id, caption)
