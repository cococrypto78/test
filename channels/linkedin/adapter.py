"""
LinkedIn channel — PASTE MODE ONLY.

LinkedIn interdit toute automation server-side (scraping, login automatisé,
envoi de messages via script). Toute violation entraîne le ban du compte.
Ce module génère uniquement un payload pour que l'utilisateur colle
lui-même le message dans son navigateur.
"""
from channels.base import ChannelAdapter, SendResult, PastePayload
from utils.logger import logger


class LinkedInAdapter(ChannelAdapter):

    def supports_server_send(self) -> bool:
        return False

    def send(self, tenant, prospect, message_text: str) -> SendResult:
        logger.warning("[LinkedIn] server-side send refused — paste mode only")
        return SendResult(
            success=False,
            error="LinkedIn ne supporte pas l'envoi server-side. Utilisez prepare_paste().",
        )

    def prepare_paste(self, tenant, prospect, message_text: str) -> PastePayload:
        return PastePayload(
            copy_text=message_text,
            profile_url=getattr(prospect, "linkedin_url", None),
            mark_sent_endpoint=f"/api/messages/mark-sent",
            extra={"channel": "linkedin", "prospect_id": getattr(prospect, "id", None)},
        )
