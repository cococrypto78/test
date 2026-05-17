from abc import ABC, abstractmethod
from typing import Optional
from utils.logger import logger


class BaseChannel(ABC):
    channel_name: str = "base"

    @abstractmethod
    async def search_prospects(self, keywords: list[str], limit: int = 50) -> list[dict]:
        pass

    @abstractmethod
    async def send_message(self, handle: str, message: str) -> bool:
        pass

    @abstractmethod
    async def get_messages(self) -> list[dict]:
        pass

    async def rate_limit_check(self) -> bool:
        from utils.rate_limiter import RateLimiter
        limiter = RateLimiter(self.channel_name)
        return await limiter.is_allowed()

    def _log(self, action: str, details: str = "") -> None:
        logger.info(f"[{self.channel_name}] {action} {details}")
