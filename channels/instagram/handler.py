import json
import os
from pathlib import Path
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, TwoFactorRequired
from channels.base_channel import BaseChannel
from config.settings import settings
from utils.logger import logger

SESSION_FILE = Path("/tmp/instagram_session.json")


class InstagramHandler(BaseChannel):
    channel_name = "instagram"

    def __init__(self):
        self._cl = Client()
        self._logged_in = False

    async def _login(self) -> bool:
        if self._logged_in:
            return True
        try:
            if SESSION_FILE.exists():
                self._cl.load_settings(SESSION_FILE)
                self._cl.login(settings.instagram_username, settings.instagram_password)
                self._cl.dump_settings(SESSION_FILE)
            else:
                self._cl.login(settings.instagram_username, settings.instagram_password)
                self._cl.dump_settings(SESSION_FILE)
            self._logged_in = True
            logger.info("[Instagram] Logged in successfully")
            return True
        except TwoFactorRequired:
            logger.error("[Instagram] 2FA required — configure app password")
            return False
        except LoginRequired as e:
            logger.error(f"[Instagram] Login failed: {e}")
            SESSION_FILE.unlink(missing_ok=True)
            return False
        except Exception as e:
            logger.error(f"[Instagram] Login error: {e}")
            return False

    async def search_prospects(self, keywords: list[str], limit: int = 30) -> list[dict]:
        if not await self.rate_limit_check():
            return []
        if not await self._login():
            return []

        prospects = []
        try:
            for keyword in keywords[:3]:
                users = self._cl.search_users(keyword, count=limit // len(keywords[:3]))
                for user in users:
                    info = self._cl.user_info(user.pk)
                    prospects.append({
                        "full_name": info.full_name or info.username,
                        "instagram_handle": info.username,
                        "notes": info.biography or "",
                        "source_channel": "instagram",
                        "instagram_id": str(info.pk),
                        "followers": info.follower_count,
                        "is_business": info.is_business,
                    })
        except Exception as e:
            logger.error(f"[Instagram] Search failed: {e}")
        logger.info(f"[Instagram] Found {len(prospects)} prospects")
        return prospects

    async def send_message(self, username: str, message: str) -> bool:
        if not await self.rate_limit_check():
            return False
        if not await self._login():
            return False

        try:
            user_id = self._cl.user_id_from_username(username)
            self._cl.direct_send(message, user_ids=[user_id])
            logger.info(f"[Instagram] DM sent to @{username}")
            return True
        except Exception as e:
            logger.error(f"[Instagram] Failed to send DM to @{username}: {e}")
            return False

    async def get_messages(self) -> list[dict]:
        if not await self._login():
            return []

        messages = []
        try:
            threads = self._cl.direct_threads(amount=20)
            for thread in threads:
                if not thread.messages:
                    continue
                for msg in thread.messages[:5]:
                    if msg.item_type != "text":
                        continue
                    is_outbound = str(msg.user_id) == str(self._cl.user_id)
                    if not is_outbound:
                        sender = thread.users[0].username if thread.users else "unknown"
                        messages.append({
                            "channel": "instagram",
                            "sender": sender,
                            "content": msg.text or "",
                            "direction": "in",
                            "timestamp": str(msg.timestamp),
                        })
        except Exception as e:
            logger.error(f"[Instagram] Failed to fetch messages: {e}")
        return messages
