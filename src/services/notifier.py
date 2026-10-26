"""Mobile Push Notification Service.

Supports:
1. ntfy.sh (Recommended, 100% free, zero registration, works on iOS & Android via app or web push)
2. Bark (iOS popular lightweight push client)
3. Telegram Bot (Custom Bot API)
4. Local macOS push notifications
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_NTFY_TOPIC = "academic_chief_alerts"


class MobileNotifier:
    """Unified push notification client for mobile devices."""

    def __init__(
        self,
        default_topic: str = DEFAULT_NTFY_TOPIC,
        bark_key: str = "",
        telegram_token: str = "",
        telegram_chat_id: str = "",
    ):
        self.default_topic = default_topic
        self.bark_key = bark_key
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id

    async def send(
        self,
        title: str,
        message: str,
        priority: int = 3,  # 1 (min) to 5 (urgent)
        tags: Optional[list[str]] = None,
        topic: Optional[str] = None,
        click_url: Optional[str] = None,
        notify_mac: bool = True,
    ) -> dict[str, Any]:
        """Dispatch push notification to configured mobile channels."""
        target_topic = topic or self.default_topic
        results: dict[str, Any] = {"success": True, "channels": {}}

        # 1. ntfy.sh push (Works on iOS, Android, and Web)
        try:
            ntfy_payload = {
                "topic": target_topic,
                "title": title,
                "message": message,
                "priority": max(1, min(5, priority)),
                "tags": tags or ["mortar_board", "alarm_clock"],
            }
            if click_url:
                ntfy_payload["click"] = click_url

            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.post("https://ntfy.sh", json=ntfy_payload)
                if res.status_code == 200:
                    results["channels"]["ntfy"] = {"status": "sent", "topic": target_topic}
                else:
                    results["channels"]["ntfy"] = {"status": "error", "code": res.status_code}
        except Exception as e:
            logger.warning(f"ntfy push error: {e}")
            results["channels"]["ntfy"] = {"status": "error", "error": str(e)}

        # 2. Bark push (iOS)
        if self.bark_key:
            try:
                bark_url = f"https://api.day.app/{self.bark_key}/"
                bark_payload = {
                    "title": title,
                    "body": message,
                    "group": "AcademicChief",
                    "level": "timeSensitive" if priority >= 4 else "active",
                }
                async with httpx.AsyncClient(timeout=8.0) as client:
                    b_res = await client.post(bark_url, json=bark_payload)
                    results["channels"]["bark"] = {"status": "sent" if b_res.status_code == 200 else "error"}
            except Exception as e:
                logger.warning(f"Bark push error: {e}")
                results["channels"]["bark"] = {"status": "error", "error": str(e)}

        # 3. Telegram Bot push
        if self.telegram_token and self.telegram_chat_id:
            try:
                tg_url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
                tg_payload = {
                    "chat_id": self.telegram_chat_id,
                    "text": f"*{title}*\n\n{message}",
                    "parse_mode": "Markdown",
                }
                async with httpx.AsyncClient(timeout=8.0) as client:
                    t_res = await client.post(tg_url, json=tg_payload)
                    results["channels"]["telegram"] = {"status": "sent" if t_res.status_code == 200 else "error"}
            except Exception as e:
                logger.warning(f"Telegram push error: {e}")
                results["channels"]["telegram"] = {"status": "error", "error": str(e)}

        # 4. macOS local desktop notification
        if notify_mac:
            try:
                clean_title = title.replace('"', '\\"')
                clean_msg = message.replace('"', '\\"').replace("\n", " ")
                sound = "Glass" if priority <= 3 else "Ping"
                cmd = f'osascript -e \'display notification "{clean_msg}" with title "{clean_title}" sound name "{sound}"\''
                os.system(cmd)
                results["channels"]["macos"] = {"status": "sent"}
            except Exception as e:
                results["channels"]["macos"] = {"status": "error", "error": str(e)}

        return results
