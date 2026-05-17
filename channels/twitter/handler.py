import tweepy
from channels.base_channel import BaseChannel
from config.settings import settings
from utils.logger import logger


class TwitterHandler(BaseChannel):
    channel_name = "twitter"

    def __init__(self):
        self._client = tweepy.Client(
            bearer_token=settings.twitter_bearer_token,
            consumer_key=settings.twitter_api_key,
            consumer_secret=settings.twitter_api_secret,
            access_token=settings.twitter_access_token,
            access_token_secret=settings.twitter_access_secret,
            wait_on_rate_limit=True,
        )

    async def search_prospects(self, keywords: list[str], limit: int = 50) -> list[dict]:
        if not await self.rate_limit_check():
            return []

        prospects = []
        query = " OR ".join(f'"{kw}"' for kw in keywords) + " -is:retweet lang:fr lang:en"

        try:
            response = self._client.search_recent_tweets(
                query=query,
                max_results=min(limit, 100),
                expansions=["author_id"],
                user_fields=["name", "username", "description", "public_metrics", "location", "url"],
            )

            if not response.data:
                return []

            users_by_id = {}
            if response.includes and response.includes.get("users"):
                for user in response.includes["users"]:
                    users_by_id[user.id] = user

            seen_authors = set()
            for tweet in response.data:
                author_id = tweet.author_id
                if author_id in seen_authors:
                    continue
                seen_authors.add(author_id)
                user = users_by_id.get(author_id)
                if user:
                    prospects.append({
                        "full_name": user.name,
                        "twitter_handle": user.username,
                        "notes": user.description or "",
                        "source_channel": "twitter",
                        "twitter_id": str(user.id),
                        "followers": user.public_metrics.get("followers_count", 0) if user.public_metrics else 0,
                    })

            logger.info(f"[Twitter] Found {len(prospects)} prospects")
        except Exception as e:
            logger.error(f"[Twitter] Search failed: {e}")

        return prospects

    async def send_message(self, handle: str, message: str) -> bool:
        if not await self.rate_limit_check():
            return False

        try:
            user_response = self._client.get_user(username=handle)
            if not user_response.data:
                logger.warning(f"[Twitter] User not found: {handle}")
                return False

            user_id = user_response.data.id
            self._client.create_direct_message(participant_id=user_id, text=message)
            logger.info(f"[Twitter] DM sent to @{handle}")
            return True
        except tweepy.errors.Forbidden as e:
            logger.warning(f"[Twitter] Cannot DM @{handle}: {e}")
            return False
        except Exception as e:
            logger.error(f"[Twitter] Failed to send DM to @{handle}: {e}")
            return False

    async def get_messages(self) -> list[dict]:
        messages = []
        try:
            me = self._client.get_me()
            if not me.data:
                return []

            dm_events = self._client.get_direct_message_events(
                dm_event_fields=["text", "sender_id", "created_at"],
                expansions=["sender_id"],
                user_fields=["name", "username"],
                max_results=50,
            )

            if not dm_events.data:
                return []

            users_by_id = {}
            if dm_events.includes and dm_events.includes.get("users"):
                for user in dm_events.includes["users"]:
                    users_by_id[str(user.id)] = user

            my_id = str(me.data.id)
            for event in dm_events.data:
                sender_id = str(event.sender_id)
                if sender_id == my_id:
                    continue
                sender = users_by_id.get(sender_id)
                messages.append({
                    "channel": "twitter",
                    "sender": sender.username if sender else sender_id,
                    "content": event.text,
                    "direction": "in",
                    "timestamp": str(event.created_at) if event.created_at else "",
                })
        except Exception as e:
            logger.error(f"[Twitter] Failed to fetch DMs: {e}")
        return messages

    async def follow_user(self, username: str) -> bool:
        try:
            me = self._client.get_me()
            user = self._client.get_user(username=username)
            if me.data and user.data:
                self._client.follow_user(id=user.data.id)
                logger.info(f"[Twitter] Followed @{username}")
                return True
        except Exception as e:
            logger.error(f"[Twitter] Failed to follow @{username}: {e}")
        return False
