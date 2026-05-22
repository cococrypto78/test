"""
Twitter/X channel — API officielle v2 (OAuth 1.0a User Context).
Envoie des DMs via POST /2/dm_conversations/with/:participant_id/messages.
Requiert X API Basic tier ($100/mois, 10k tweets/mois).
"""
import tweepy
from channels.base import ChannelAdapter, SendResult, PastePayload
from config.settings import settings
from utils.logger import logger


def _build_client(tenant_config: dict | None = None) -> tweepy.Client:
    cfg = tenant_config or {}
    return tweepy.Client(
        bearer_token=cfg.get("x_api_bearer_token") or settings.x_api_bearer_token,
        consumer_key=cfg.get("x_api_key") or settings.x_api_key,
        consumer_secret=cfg.get("x_api_secret") or settings.x_api_secret,
        access_token=cfg.get("x_access_token") or settings.x_access_token,
        access_token_secret=cfg.get("x_access_token_secret") or settings.x_access_token_secret,
        wait_on_rate_limit=True,
    )


class TwitterAdapter(ChannelAdapter):

    def supports_server_send(self) -> bool:
        return bool(settings.x_api_key and settings.x_access_token)

    def send(self, tenant, prospect, message_text: str) -> SendResult:
        handle = getattr(prospect, "twitter_handle", None)
        if not handle:
            return SendResult(success=False, error="Pas de twitter_handle pour ce prospect")

        tenant_config = getattr(tenant, "channel_config_twitter", None) or {}
        client = _build_client(tenant_config)
        handle = handle.lstrip("@")

        try:
            user_resp = client.get_user(username=handle)
            if not user_resp.data:
                return SendResult(success=False, error=f"Utilisateur @{handle} introuvable")

            participant_id = user_resp.data.id
            resp = client.create_direct_message(participant_id=participant_id, text=message_text)
            dm_id = str(resp.data.get("dm_conversation_id", "")) if resp.data else ""
            logger.info(f"[Twitter] DM envoyé à @{handle}")
            return SendResult(success=True, external_id=dm_id)

        except tweepy.errors.Forbidden as e:
            return SendResult(success=False, error=f"Envoi DM refusé par Twitter: {e}")
        except Exception as e:
            logger.error(f"[Twitter] Erreur envoi DM à @{handle}: {e}")
            return SendResult(success=False, error=str(e))

    def prepare_paste(self, tenant, prospect, message_text: str) -> PastePayload:
        handle = getattr(prospect, "twitter_handle", "").lstrip("@")
        return PastePayload(
            copy_text=message_text,
            profile_url=f"https://x.com/{handle}" if handle else None,
            extra={"channel": "twitter", "prospect_id": getattr(prospect, "id", None)},
        )
