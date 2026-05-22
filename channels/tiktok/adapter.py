"""
TikTok channel — PASTE MODE ONLY.

L'API DM publique TikTok n'est pas disponible pour les apps non-enterprise.
Toute automation server-side (Playwright, scraping) viole les CGU TikTok
et entraîne le ban du compte.
"""
from channels.base import ChannelAdapter, SendResult, PastePayload
from utils.logger import logger


class TikTokAdapter(ChannelAdapter):

    def supports_server_send(self) -> bool:
        return False

    def send(self, tenant, prospect, message_text: str) -> SendResult:
        logger.warning("[TikTok] server-side send refusé — paste mode uniquement")
        return SendResult(
            success=False,
            error="TikTok ne supporte pas l'envoi server-side. Utilisez prepare_paste().",
        )

    def prepare_paste(self, tenant, prospect, message_text: str) -> PastePayload:
        handle = getattr(prospect, "tiktok_handle", "").lstrip("@")
        return PastePayload(
            copy_text=message_text,
            profile_url=f"https://www.tiktok.com/@{handle}" if handle else None,
            extra={"channel": "tiktok", "prospect_id": getattr(prospect, "id", None)},
        )
