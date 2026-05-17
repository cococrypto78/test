import asyncio
import random
from typing import Optional
from playwright.async_api import async_playwright, Browser, Page
from channels.base_channel import BaseChannel
from config.settings import settings
from utils.logger import logger


class TikTokHandler(BaseChannel):
    channel_name = "tiktok"

    def __init__(self):
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        self._logged_in = False

    async def _get_page(self) -> Page:
        if self._page and not self._page.is_closed():
            return self._page
        playwright = await async_playwright().start()
        self._browser = await playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await self._browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
            viewport={"width": 390, "height": 844},
            is_mobile=True,
        )
        self._page = await context.new_page()
        await self._page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return self._page

    async def _human_delay(self, min_ms: int = 800, max_ms: int = 2500) -> None:
        await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))

    async def _login(self) -> bool:
        if self._logged_in:
            return True
        page = await self._get_page()
        try:
            await page.goto("https://www.tiktok.com/login/phone-or-email/email", wait_until="networkidle")
            await self._human_delay(2000, 4000)
            email_input = await page.query_selector('input[name="username"]')
            if email_input:
                await email_input.type(settings.tiktok_username, delay=random.randint(60, 140))
                await self._human_delay()
                pwd_input = await page.query_selector('input[type="password"]')
                if pwd_input:
                    await pwd_input.type(settings.tiktok_password, delay=random.randint(60, 140))
                    await self._human_delay()
                    login_btn = await page.query_selector('[data-e2e="login-button"]')
                    if login_btn:
                        await login_btn.click()
                        await asyncio.sleep(5)
                        if "login" not in page.url:
                            self._logged_in = True
                            logger.info("[TikTok] Logged in successfully")
                            return True
            logger.warning("[TikTok] Login may require CAPTCHA — check manually")
            return False
        except Exception as e:
            logger.error(f"[TikTok] Login failed: {e}")
            return False

    async def search_prospects(self, keywords: list[str], limit: int = 30) -> list[dict]:
        if not await self.rate_limit_check():
            return []
        if not await self._login():
            return []

        page = await self._get_page()
        prospects = []

        for keyword in keywords[:2]:
            try:
                await page.goto(f"https://www.tiktok.com/search/user?q={keyword}", wait_until="networkidle")
                await self._human_delay(2000, 4000)

                user_cards = await page.query_selector_all('[data-e2e="search-user-info-container"]')
                for card in user_cards[: limit // len(keywords[:2])]:
                    try:
                        name_el = await card.query_selector('[data-e2e="search-user-unique-id"]')
                        display_el = await card.query_selector('[data-e2e="search-user-nickname"]')
                        bio_el = await card.query_selector('[data-e2e="search-user-desc"]')

                        username = await name_el.inner_text() if name_el else ""
                        display_name = await display_el.inner_text() if display_el else username
                        bio = await bio_el.inner_text() if bio_el else ""

                        if username:
                            prospects.append({
                                "full_name": display_name.strip(),
                                "tiktok_handle": username.strip().lstrip("@"),
                                "notes": bio.strip(),
                                "source_channel": "tiktok",
                            })
                    except Exception as e:
                        logger.debug(f"[TikTok] Error parsing card: {e}")
                    await self._human_delay(300, 800)
            except Exception as e:
                logger.error(f"[TikTok] Search failed for '{keyword}': {e}")

        logger.info(f"[TikTok] Found {len(prospects)} prospects")
        return prospects

    async def send_message(self, username: str, message: str) -> bool:
        if not await self.rate_limit_check():
            return False
        if not await self._login():
            return False

        page = await self._get_page()
        try:
            await page.goto(f"https://www.tiktok.com/@{username}", wait_until="networkidle")
            await self._human_delay(2000, 4000)

            msg_btn = await page.query_selector('[data-e2e="message-button"]')
            if not msg_btn:
                logger.warning(f"[TikTok] Cannot DM @{username} — follow first or account restricted")
                return False

            await msg_btn.click()
            await self._human_delay(1500, 3000)

            input_el = await page.query_selector('[data-e2e="dm-message-input"]')
            if input_el:
                await input_el.type(message, delay=random.randint(50, 120))
                await self._human_delay(500, 1200)
                send_btn = await page.query_selector('[data-e2e="dm-message-send"]')
                if send_btn:
                    await send_btn.click()
                    logger.info(f"[TikTok] DM sent to @{username}")
                    return True
        except Exception as e:
            logger.error(f"[TikTok] Failed to send DM to @{username}: {e}")
        return False

    async def get_messages(self) -> list[dict]:
        if not await self._login():
            return []

        page = await self._get_page()
        messages = []
        try:
            await page.goto("https://www.tiktok.com/message/", wait_until="networkidle")
            await self._human_delay(2000, 4000)

            threads = await page.query_selector_all('[data-e2e="conversation-list-item"]')
            for thread in threads[:10]:
                try:
                    await thread.click()
                    await self._human_delay(1000, 2000)
                    msg_els = await page.query_selector_all('[data-e2e="message-item-others"] .message-bubble-text')
                    sender_el = await page.query_selector('[data-e2e="conversation-header-nickname"]')
                    sender = await sender_el.inner_text() if sender_el else "unknown"
                    for msg_el in msg_els[-3:]:
                        content = await msg_el.inner_text()
                        messages.append({
                            "channel": "tiktok",
                            "sender": sender.strip(),
                            "content": content.strip(),
                            "direction": "in",
                        })
                except Exception as e:
                    logger.debug(f"[TikTok] Error reading thread: {e}")
        except Exception as e:
            logger.error(f"[TikTok] Failed to fetch messages: {e}")
        return messages

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
