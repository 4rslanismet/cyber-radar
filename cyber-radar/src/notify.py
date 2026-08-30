"""Telegram bot bildirimi. E-posta yerine Telegram tercih edildi çünkü tek
HTTP isteğiyle çalışır, ekstra SMTP/kimlik doğrulama derdi yok."""
from __future__ import annotations

import httpx

from . import config

_TELEGRAM_MAX_LEN = 4096


def _chunk(text: str, size: int = _TELEGRAM_MAX_LEN) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [text]


def send_telegram(text: str) -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    ok = True
    for chunk in _chunk(text):
        try:
            resp = httpx.post(
                url,
                data={"chat_id": config.TELEGRAM_CHAT_ID, "text": chunk, "parse_mode": "Markdown"},
                timeout=15.0,
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            ok = False
    return ok
