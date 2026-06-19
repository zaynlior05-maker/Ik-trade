"""
Telegram output. Formats a Signal into the exact layout requested and posts it
to a channel via the Bot API (no heavy deps -- just `requests`).

Setup:
  1. Create a bot with @BotFather -> get TELEGRAM_BOT_TOKEN.
  2. Add the bot to your channel as an admin.
  3. TELEGRAM_CHAT_ID = "@yourchannel" or the numeric -100... id.
"""
from __future__ import annotations

import requests

from models import Signal

_API = "https://api.telegram.org/bot{token}/sendMessage"


def format_signal(sig: Signal) -> str:
    arrow = "🟢" if sig.bias.value == "Bullish" else "🔴"
    direction = "Long" if sig.bias.value == "Bullish" else "Short"

    # CRT setups use the dedicated range-based layout
    if sig.range_high is not None and sig.range_low is not None:
        return (
            f"{arrow} *{sig.pair}*\n"
            f"*Setup Type:* {sig.setup_type}\n"
            f"*Direction:* {direction}\n"
            f"*CRT Range High:* `{sig.range_high:.3f}`\n"
            f"*CRT Range Low:* `{sig.range_low:.3f}`\n"
            f"*Target (TP):* `{sig.target:.3f}`  (opposing range expansion)"
        )

    rr = sig.rr()
    rr_line = f"\n*R:R:* {rr}" if rr else ""
    return (
        f"{arrow} *{sig.pair}* — Signal\n"
        f"*Setup Type:* {sig.setup_type}\n"
        f"*Aligned Bias:* {sig.bias.value}\n"
        f"*Confirmation:* {sig.event.value} on {sig.timeframe}\n"
        f"*Entry:* `{sig.entry:.3f}`\n"
        f"*Invalidation (SL):* `{sig.stop:.3f}`\n"
        f"*Target (TP):* `{sig.target:.3f}`"
        f"{rr_line}"
    )


def send(token: str, chat_id: str, text: str) -> None:
    resp = requests.post(
        _API.format(token=token),
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        timeout=15,
    )
    resp.raise_for_status()


def send_signal(token: str, chat_id: str, sig: Signal) -> None:
    send(token, chat_id, format_signal(sig))
