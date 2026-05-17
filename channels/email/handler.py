import aiosmtplib
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from channels.base_channel import BaseChannel
from config.settings import settings
from utils.logger import logger


class EmailHandler(BaseChannel):
    channel_name = "email"

    def _build_html(self, body: str, unsubscribe_link: str) -> str:
        paragraphs = "".join(f"<p style='margin:0 0 16px'>{line}</p>" for line in body.split("\n") if line.strip())
        return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:Arial,sans-serif;font-size:15px;color:#222;max-width:600px;margin:0 auto;padding:24px">
{paragraphs}
<hr style="margin:32px 0;border:none;border-top:1px solid #eee">
<p style="font-size:12px;color:#999">
  <a href="{unsubscribe_link}" style="color:#999">Se désabonner</a>
</p>
</body>
</html>"""

    async def send_message(self, to_address: str, message: str) -> bool:
        subject_line, body = message, message
        if message.startswith("Subject:"):
            lines = message.split("\n", 1)
            subject_line = lines[0].replace("Subject:", "").strip()
            body = lines[1].strip() if len(lines) > 1 else message

        return await self.send_email(to_address, subject_line, body)

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        html: str | None = None,
        from_name: str | None = None,
    ) -> bool:
        if not await self.rate_limit_check():
            return False

        tracking_id = str(uuid.uuid4())
        unsubscribe_link = f"https://{settings.smtp_from.split('@')[1]}/unsubscribe?id={tracking_id}"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formataddr((from_name or settings.smtp_from_name, settings.smtp_from))
        msg["To"] = to
        msg["Message-ID"] = f"<{tracking_id}@{settings.smtp_from.split('@')[1]}>"
        msg["List-Unsubscribe"] = f"<{unsubscribe_link}>"

        msg.attach(MIMEText(body, "plain", "utf-8"))
        msg.attach(MIMEText(html or self._build_html(body, unsubscribe_link), "html", "utf-8"))

        try:
            await aiosmtplib.send(
                msg,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_user,
                password=settings.smtp_password,
                use_tls=settings.smtp_port == 465,
                start_tls=settings.smtp_port == 587,
            )
            logger.info(f"[Email] Sent to {to}: '{subject}'")
            return True
        except Exception as e:
            logger.error(f"[Email] Failed to send to {to}: {e}")
            return False

    async def search_prospects(self, keywords: list[str], limit: int = 50) -> list[dict]:
        logger.warning("[Email] Direct prospect search not supported — use external lead lists")
        return []

    async def get_messages(self) -> list[dict]:
        logger.warning("[Email] Inbound email reading requires IMAP setup")
        return []

    @staticmethod
    def verify_email(address: str) -> bool:
        import re
        pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
        return bool(re.match(pattern, address))
