"""
Instagram channel — Meta Graph API (Messenger Platform) OU paste mode.

Mode API : requiert un compte Business Instagram + Facebook App approuvé
avec la permission instagram_manage_messages. Utilise l'endpoint
POST /me/messages via le token de page Facebook.

Si le tenant n'a pas configuré Meta Graph API, bascule automatiquement
en paste mode.
"""
import httpx
from channels.base import ChannelAdapter, SendResult, PastePayload
from config.settings import settings
from utils.logger import logger

META_GRAPH_BASE = "https://graph.facebook.com/v19.0"


class InstagramAdapter(ChannelAdapter):

    def _get_token(self, tenant) -> str | None:
        cfg = getattr(tenant, "channel_config_instagram", None) or {}
        return cfg.get("meta_graph_access_token") or settings.meta_graph_access_token or None

    def _get_page_id(self, tenant) -> str | None:
        cfg = getattr(tenant, "channel_config_instagram", None) or {}
        return cfg.get("meta_page_id") or settings.meta_page_id or None

    def supports_server_send(self) -> bool:
        return bool(settings.meta_graph_access_token and settings.meta_page_id)

    def send(self, tenant, prospect, message_text: str) -> SendResult:
        token = self._get_token(tenant)
        page_id = self._get_page_id(tenant)

        if not token or not page_id:
            logger.info("[Instagram] Pas de Meta Graph API configuré — passage en paste mode")
            return SendResult(
                success=False,
                error="Meta Graph API non configuré. Utilisez prepare_paste().",
            )

        ig_id = getattr(prospect, "instagram_handle", None)
        if not ig_id:
            return SendResult(success=False, error="Pas d'instagram_handle pour ce prospect")

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    f"{META_GRAPH_BASE}/{page_id}/messages",
                    params={"access_token": token},
                    json={
                        "recipient": {"id": ig_id},
                        "message": {"text": message_text},
                        "messaging_type": "MESSAGE_TAG",
                        "tag": "CONFIRMED_EVENT_UPDATE",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                msg_id = data.get("message_id", "")
                logger.info(f"[Instagram] Message envoyé via Graph API, id={msg_id}")
                return SendResult(success=True, external_id=msg_id)

        except httpx.HTTPStatusError as e:
            error_body = e.response.text
            logger.error(f"[Instagram] Graph API error {e.response.status_code}: {error_body}")
            return SendResult(success=False, error=f"Meta API {e.response.status_code}: {error_body}")
        except Exception as e:
            logger.error(f"[Instagram] Erreur: {e}")
            return SendResult(success=False, error=str(e))

    def prepare_paste(self, tenant, prospect, message_text: str) -> PastePayload:
        handle = getattr(prospect, "instagram_handle", "").lstrip("@")
        return PastePayload(
            copy_text=message_text,
            profile_url=f"https://www.instagram.com/{handle}/" if handle else None,
            extra={"channel": "instagram", "prospect_id": getattr(prospect, "id", None)},
        )
