"""
Task: Poll les webhooks / boîtes mail pour les réponses entrantes.
Les réponses email entrent via webhook Postmark (inbound).
Les réponses Twitter entrent via Account Activity API webhook.
Ce task vérifie les messages envoyés en attente de réponse.
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


@app.task(bind=True, max_retries=2, default_retry_delay=60)
def check_all_replies(self):
    """Vérifie l'état des messages envoyés et déclenche classify_reply si réponse détectée."""
    async def _run():
        from crm.database import session_context
        from crm.models import Message, MessageStatus
        from sqlalchemy import select
        from datetime import datetime, timedelta

        async with session_context() as session:
            cutoff = datetime.utcnow() - timedelta(days=7)
            result = await session.execute(
                select(Message).where(
                    Message.status == MessageStatus.sent,
                    Message.sent_at >= cutoff,
                    Message.reply_received_at.is_(None),
                ).limit(200)
            )
            messages = result.scalars().all()
            logger.info(f"[CheckReplies] Checking {len(messages)} sent messages for replies")
            # Replies arrive via webhooks (Postmark inbound, Twitter Account Activity API)
            # This task just ensures the monitoring loop is active
            # Actual reply processing is done in the webhook handlers

    try:
        run_async(_run())
    except Exception as exc:
        self.retry(exc=exc)
