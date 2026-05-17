import redis.asyncio as aioredis
from datetime import datetime
from typing import Optional
from config.settings import settings
from utils.logger import logger


_channel_limit_map = {
    "linkedin": ("connection", lambda: settings.max_daily_connections_linkedin),
    "twitter": ("dm", lambda: settings.max_daily_dms_twitter),
    "instagram": ("dm", lambda: settings.max_daily_dms_instagram),
    "tiktok": ("dm", lambda: settings.max_daily_dms_tiktok),
    "email": ("send", lambda: settings.max_daily_emails),
}


class RateLimiter:
    def __init__(self, channel: Optional[str] = None):
        self._redis: Optional[aioredis.Redis] = None
        self._channel = channel

    async def _get_redis(self) -> aioredis.Redis:
        if not self._redis:
            self._redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    def _daily_key(self, channel: str, action: str) -> str:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        return f"rate_limit:{channel}:{action}:{date_str}"

    async def check_and_increment(self, channel: str, action: str, limit: int) -> bool:
        """Returns True if action is allowed, False if limit exceeded."""
        redis = await self._get_redis()
        key = self._daily_key(channel, action)

        pipe = redis.pipeline()
        await pipe.incr(key)
        await pipe.expire(key, 86400)
        results = await pipe.execute()

        current_count = results[0]
        if current_count > limit:
            logger.warning(f"Rate limit exceeded: {channel}/{action} ({current_count}/{limit})")
            return False
        logger.debug(f"Rate limit ok: {channel}/{action} ({current_count}/{limit})")
        return True

    async def get_current_count(self, channel: str, action: str) -> int:
        redis = await self._get_redis()
        key = self._daily_key(channel, action)
        val = await redis.get(key)
        return int(val) if val else 0

    async def reset(self, channel: str, action: str) -> None:
        redis = await self._get_redis()
        key = self._daily_key(channel, action)
        await redis.delete(key)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()

    async def is_allowed(self) -> bool:
        if not self._channel or self._channel not in _channel_limit_map:
            return True
        action, limit_fn = _channel_limit_map[self._channel]
        return await self.check_and_increment(self._channel, action, limit_fn())

    async def can_send_linkedin_connection(self) -> bool:
        return await self.check_and_increment(
            "linkedin", "connection", settings.max_daily_connections_linkedin
        )

    async def can_send_instagram_dm(self) -> bool:
        return await self.check_and_increment(
            "instagram", "dm", settings.max_daily_dms_instagram
        )

    async def can_send_twitter_dm(self) -> bool:
        return await self.check_and_increment(
            "twitter", "dm", settings.max_daily_dms_twitter
        )

    async def can_send_email(self) -> bool:
        return await self.check_and_increment(
            "email", "send", settings.max_daily_emails
        )

    async def can_send_tiktok_dm(self) -> bool:
        return await self.check_and_increment(
            "tiktok", "dm", settings.max_daily_dms_tiktok
        )


rate_limiter = RateLimiter()
