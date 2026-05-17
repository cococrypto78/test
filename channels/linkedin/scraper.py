import asyncio
import random
from typing import Optional
from playwright.async_api import async_playwright, Browser, Page
from channels.base_channel import BaseChannel
from config.settings import settings
from utils.logger import logger


class LinkedInScraper(BaseChannel):
    channel_name = "linkedin"

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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
        )
        self._page = await context.new_page()
        await self._page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return self._page

    async def _human_delay(self, min_ms: int = 500, max_ms: int = 2000) -> None:
        await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))

    async def _login(self) -> bool:
        if self._logged_in:
            return True
        page = await self._get_page()
        try:
            await page.goto("https://www.linkedin.com/login", wait_until="networkidle")
            await self._human_delay()
            await page.fill("#username", settings.linkedin_email)
            await self._human_delay(300, 800)
            await page.fill("#password", settings.linkedin_password)
            await self._human_delay(500, 1200)
            await page.click('[type="submit"]')
            await page.wait_for_url("**/feed/**", timeout=15000)
            self._logged_in = True
            logger.info("[LinkedIn] Logged in successfully")
            return True
        except Exception as e:
            logger.error(f"[LinkedIn] Login failed: {e}")
            return False

    async def search_prospects(
        self,
        keywords: list[str],
        limit: int = 20,
        filters: Optional[dict] = None,
    ) -> list[dict]:
        if not await self.rate_limit_check():
            logger.warning("[LinkedIn] Rate limit reached")
            return []

        if not await self._login():
            return []

        page = await self._get_page()
        prospects = []
        query = " ".join(keywords)

        try:
            search_url = f"https://www.linkedin.com/search/results/people/?keywords={query}&origin=GLOBAL_SEARCH_HEADER"
            if filters and filters.get("location"):
                search_url += f"&geoUrn={filters['location']}"

            await page.goto(search_url, wait_until="networkidle")
            await self._human_delay(1000, 2500)

            results = await page.query_selector_all(".reusable-search__result-container")

            for result in results[:limit]:
                try:
                    name_el = await result.query_selector(".entity-result__title-text a")
                    title_el = await result.query_selector(".entity-result__primary-subtitle")
                    company_el = await result.query_selector(".entity-result__secondary-subtitle")
                    link_el = await result.query_selector(".entity-result__title-text a")

                    name = await name_el.inner_text() if name_el else ""
                    title = await title_el.inner_text() if title_el else ""
                    company = await company_el.inner_text() if company_el else ""
                    profile_url = await link_el.get_attribute("href") if link_el else ""

                    if name and profile_url:
                        prospects.append({
                            "full_name": name.strip(),
                            "title": title.strip(),
                            "company": company.strip(),
                            "linkedin_url": profile_url.split("?")[0],
                            "source_channel": "linkedin",
                        })
                        await self._human_delay(200, 600)
                except Exception as e:
                    logger.debug(f"[LinkedIn] Error parsing result: {e}")

        except Exception as e:
            logger.error(f"[LinkedIn] Search failed: {e}")

        logger.info(f"[LinkedIn] Found {len(prospects)} prospects")
        return prospects

    async def send_message(self, profile_url: str, message: str) -> bool:
        if not await self.rate_limit_check():
            return False
        if not await self._login():
            return False

        page = await self._get_page()
        try:
            await page.goto(profile_url, wait_until="networkidle")
            await self._human_delay(1500, 3000)

            msg_btn = await page.query_selector('[aria-label*="Message"]')
            if not msg_btn:
                connect_btn = await page.query_selector('[aria-label*="Connect"]')
                if connect_btn:
                    await connect_btn.click()
                    await self._human_delay(1000, 2000)
                    add_note_btn = await page.query_selector('[aria-label="Add a note"]')
                    if add_note_btn:
                        await add_note_btn.click()
                        await self._human_delay(500, 1000)
                        note_input = await page.query_selector("#custom-message")
                        if note_input:
                            await note_input.type(message[:300], delay=random.randint(50, 120))
                    send_btn = await page.query_selector('[aria-label="Send now"]')
                    if send_btn:
                        await send_btn.click()
                        logger.info(f"[LinkedIn] Connection request sent to {profile_url}")
                        return True
                return False

            await msg_btn.click()
            await self._human_delay(1000, 2000)
            msg_input = await page.query_selector(".msg-form__contenteditable")
            if msg_input:
                await msg_input.click()
                await msg_input.type(message, delay=random.randint(40, 100))
                await self._human_delay(500, 1200)
                send_btn = await page.query_selector('[class*="msg-form__send-button"]')
                if send_btn:
                    await send_btn.click()
                    logger.info(f"[LinkedIn] Message sent to {profile_url}")
                    return True
        except Exception as e:
            logger.error(f"[LinkedIn] Failed to send message to {profile_url}: {e}")
        return False

    async def get_messages(self) -> list[dict]:
        if not await self._login():
            return []

        page = await self._get_page()
        messages = []
        try:
            await page.goto("https://www.linkedin.com/messaging/", wait_until="networkidle")
            await self._human_delay(1500, 3000)

            threads = await page.query_selector_all(".msg-conversation-listitem__link")
            for thread in threads[:20]:
                try:
                    await thread.click()
                    await self._human_delay(800, 1500)
                    msgs = await page.query_selector_all(".msg-s-event-listitem--other .msg-s-event__content")
                    for msg in msgs[-3:]:
                        content = await msg.inner_text()
                        sender_el = await page.query_selector(".msg-entity-lockup__entity-title")
                        sender = await sender_el.inner_text() if sender_el else "Unknown"
                        messages.append({
                            "channel": "linkedin",
                            "sender": sender.strip(),
                            "content": content.strip(),
                            "direction": "in",
                        })
                except Exception as e:
                    logger.debug(f"[LinkedIn] Error reading thread: {e}")
        except Exception as e:
            logger.error(f"[LinkedIn] Failed to read messages: {e}")
        return messages

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
