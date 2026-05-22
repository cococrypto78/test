"""
Task: Classification Haiku d'une réponse entrante.
"""
import asyncio
import uuid
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


@app.task(bind=True, max_retries=3, default_retry_delay=30)
def classify_incoming_reply(self, tenant_id: str, message_id: str, reply_content: str):
    """Classifie une réponse avec Haiku et crée un enregistrement Reply."""
    async def _run():
        from crm.database import session_context
        from crm.models import Reply, Message, MessageStatus
        from ai.drafting import classify_reply
        from sqlalchemy import select
        from datetime import datetime

        async with session_context() as session:
            msg_result = await session.execute(
                select(Message).where(
                    Message.id == message_id,
                    Message.tenant_id == tenant_id,
                )
            )
            msg = msg_result.scalar_one_or_none()
            if not msg:
                logger.warning(f"[ClassifyReply] Message {message_id} not found")
                return

            intent, confidence = await classify_reply(tenant_id, reply_content, session)

            reply = Reply(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                message_id=message_id,
                content=reply_content,
                classified_intent=intent,
                confidence=confidence,
                received_at=datetime.utcnow(),
            )
            session.add(reply)

            msg.status = MessageStatus.replied
            msg.reply_received_at = datetime.utcnow()

            await session.commit()
            logger.info(f"[ClassifyReply] message={message_id} intent={intent} confidence={confidence:.2f}")

    try:
        run_async(_run())
    except Exception as exc:
        self.retry(exc=exc)
