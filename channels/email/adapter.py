"""
Email channel — envoi server-side via Postmark.
Domaine d'envoi DÉDIÉ obligatoire (jamais le domaine principal du client).
SPF/DKIM/DMARC vérifiés à l'onboarding du tenant.
"""
import httpx
from channels.base import ChannelAdapter, SendResult, PastePayload
from config.settings import settings
from utils.logger import logger

POSTMARK_API_BASE = "https://api.postmarkapp.com"


def _build_html(body: str, unsubscribe_url: str = "#") -> str:
    paragraphs = "".join(
        f"<p style='margin:0 0 16px'>{line}</p>"
        for line in body.split("\n") if line.strip()
    )
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:Arial,sans-serif;font-size:15px;color:#222;max-width:600px;margin:0 auto;padding:24px">
{paragraphs}
<hr style="margin:32px 0;border:none;border-top:1px solid #eee">
<p style="font-size:12px;color:#999"><a href="{unsubscribe_url}" style="color:#999">Se désabonner</a></p>
</body>
</html>"""


class EmailAdapter(ChannelAdapter):

    def _get_token(self, tenant) -> str:
        cfg = getattr(tenant, "channel_config_email", None) or {}
        return cfg.get("postmark_server_token") or settings.postmark_server_token

    def _get_sending_domain(self, tenant) -> str:
        cfg = getattr(tenant, "channel_config_email", None) or {}
        return cfg.get("email_sending_domain") or settings.email_sending_domain

    def supports_server_send(self) -> bool:
        return bool(settings.postmark_server_token and settings.email_sending_domain)

    def send(self, tenant, prospect, message_text: str) -> SendResult:
        token = self._get_token(tenant)
        domain = self._get_sending_domain(tenant)

        if not token or not domain:
            return SendResult(success=False, error="Postmark non configuré (token ou domaine manquant)")

        to_email = getattr(prospect, "email", None)
        if not to_email:
            return SendResult(success=False, error="Pas d'email pour ce prospect")

        subject_line = message_text.split("\n")[0][:80] if message_text else "Message"
        if message_text.startswith("Subject:"):
            lines = message_text.split("\n", 1)
            subject_line = lines[0].replace("Subject:", "").strip()
            message_text = lines[1].strip() if len(lines) > 1 else message_text

        from_name = getattr(tenant, "founder_name", "Sales Team")
        from_email = f"hello@{domain}"

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    f"{POSTMARK_API_BASE}/email",
                    headers={
                        "X-Postmark-Server-Token": token,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json={
                        "From": f"{from_name} <{from_email}>",
                        "To": to_email,
                        "Subject": subject_line,
                        "TextBody": message_text,
                        "HtmlBody": _build_html(message_text),
                        "MessageStream": "outbound",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                msg_id = data.get("MessageID", "")
                logger.info(f"[Email] Envoyé via Postmark à {to_email}, MessageID={msg_id}")
                return SendResult(success=True, external_id=msg_id)

        except httpx.HTTPStatusError as e:
            error_body = e.response.text
            logger.error(f"[Email] Postmark error {e.response.status_code}: {error_body}")
            return SendResult(success=False, error=f"Postmark {e.response.status_code}: {error_body}")
        except Exception as e:
            logger.error(f"[Email] Erreur: {e}")
            return SendResult(success=False, error=str(e))

    def prepare_paste(self, tenant, prospect, message_text: str) -> PastePayload:
        return PastePayload(
            copy_text=message_text,
            extra={"channel": "email", "to": getattr(prospect, "email", "")},
        )
