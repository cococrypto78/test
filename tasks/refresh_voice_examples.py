"""
Task: Cron quotidien — rafraîchit les exemples de voix pour tous les tenants.
Sélectionne les top messages approved/sent des 30 derniers jours.
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


@app.task(bind=True, max_retries=2, default_retry_delay=300)
def refresh_all_tenants(self):
    """Rafraîchit les VoiceExamples pour tous les tenants actifs."""
    async def _run():
        from crm.database import session_context
        from crm.models import Tenant, TenantStatus, Message, MessageStatus, VoiceExample, ChannelEnum
        from sqlalchemy import select, delete
        from datetime import datetime, timedelta

        async with session_context() as session:
            tenants_result = await session.execute(
                select(Tenant).where(Tenant.status == TenantStatus.active)
            )
            tenants = tenants_result.scalars().all()

            for tenant in tenants:
                await _refresh_tenant(session, str(tenant.id))

            logger.info(f"[RefreshVoiceExamples] Refreshed {len(tenants)} tenants")

    try:
        run_async(_run())
    except Exception as exc:
        self.retry(exc=exc)


async def _refresh_tenant(session, tenant_id: str):
    from crm.models import Message, MessageStatus, VoiceExample, ChannelEnum
    from sqlalchemy import select, delete
    from datetime import datetime, timedelta
    import uuid

    cutoff = datetime.utcnow() - timedelta(days=30)

    # Delete old examples for this tenant
    await session.execute(
        delete(VoiceExample).where(VoiceExample.tenant_id == tenant_id)
    )

    # Fetch best messages (approved/sent, last 30 days)
    for channel in ChannelEnum:
        msgs_result = await session.execute(
            select(Message).where(
                Message.tenant_id == tenant_id,
                Message.channel == channel,
                Message.status.in_([MessageStatus.sent, MessageStatus.approved]),
                Message.created_at >= cutoff,
                Message.final_text.isnot(None),
            ).order_by(Message.created_at.desc()).limit(10)
        )
        msgs = msgs_result.scalars().all()

        for msg in msgs:
            example = VoiceExample(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                channel=channel,
                context_summary=None,
                final_text=msg.final_text,
                refreshed_at=datetime.utcnow(),
            )
            session.add(example)

    await session.commit()
