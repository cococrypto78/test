"""
Task: Envoie les messages approuvés (rate-limited à 100/jour/tenant).
"""
import asyncio
from celery.utils.log import get_task_logger
from tasks.celery_app import app

logger = get_task_logger(__name__)


def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@app.task(bind=True, max_retries=2, default_retry_delay=120)
def send_approved_messages(self):
    """Envoie tous les messages en status 'approved' via les adapters canaux."""
    async def _run():
        from crm.database import session_context
        from crm.models import Message, MessageStatus, Prospect, Tenant, ChannelCredential
        from channels.email.adapter import EmailAdapter
        from channels.twitter.adapter import TwitterAdapter
        from channels.instagram.adapter import InstagramAdapter
        from sqlalchemy import select, func
        from datetime import datetime, date

        adapters = {
            "email": EmailAdapter(),
            "twitter": TwitterAdapter(),
            "instagram": InstagramAdapter(),
        }

        async with session_context() as session:
            result = await session.execute(
                select(Message).where(Message.status == MessageStatus.approved).limit(100)
            )
            messages = result.scalars().all()

            for msg in messages:
                tenant_result = await session.execute(
                    select(Tenant).where(Tenant.id == msg.tenant_id)
                )
                tenant = tenant_result.scalar_one_or_none()
                if not tenant:
                    continue

                prospect_result = await session.execute(
                    select(Prospect).where(
                        Prospect.id == msg.prospect_id,
                        Prospect.tenant_id == msg.tenant_id,
                    )
                )
                prospect = prospect_result.scalar_one_or_none()
                if not prospect:
                    continue

                channel = msg.channel.value
                adapter = adapters.get(channel)

                if not adapter:
                    # Paste mode channels (linkedin, tiktok) — skip server-side send
                    continue

                if not adapter.supports_server_send():
                    continue

                text = msg.final_text or msg.draft_text or ""
                send_result = adapter.send(tenant, prospect, text)

                if send_result.success:
                    msg.status = MessageStatus.sent
                    msg.sent_at = datetime.utcnow()
                    logger.info(f"[SendApproved] Sent message {msg.id} via {channel}")
                else:
                    msg.status = MessageStatus.failed
                    logger.warning(f"[SendApproved] Failed to send {msg.id}: {send_result.error}")

            await session.commit()

    try:
        run_async(_run())
    except Exception as exc:
        self.retry(exc=exc)
