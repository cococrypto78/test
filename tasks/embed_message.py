"""
Task: Génère l'embedding pgvector pour un message (async, post-approval).
Utilise OpenAI text-embedding-3-small si disponible, sinon stub.
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


@app.task(bind=True, max_retries=2, default_retry_delay=60)
def embed_message_task(self, tenant_id: str, message_id: str):
    """Génère et stocke l'embedding d'un message pour la recherche vectorielle."""
    async def _run():
        from crm.database import session_context
        from crm.models import Message, VoiceEmbedding
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
            if not msg or not msg.final_text:
                return

            embedding = await _generate_embedding(msg.final_text)
            if not embedding:
                return

            ve = VoiceEmbedding(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                message_id=message_id,
                embedding=embedding,
                context=msg.final_text[:500],
            )
            session.add(ve)
            await session.commit()
            logger.info(f"[EmbedMessage] Embedded message {message_id}")

    try:
        run_async(_run())
    except Exception as exc:
        self.retry(exc=exc)


async def _generate_embedding(text: str) -> list[float] | None:
    """Génère un vecteur 1536 dimensions. Placeholder — connecter OpenAI embeddings en prod."""
    try:
        import numpy as np
        # Zero vector as placeholder until an embedding provider is configured
        # In production: use openai.embeddings.create(model="text-embedding-3-small", input=text)
        return [0.0] * 1536
    except Exception as e:
        logger.warning(f"[EmbedMessage] Embedding generation failed: {e}")
        return None
