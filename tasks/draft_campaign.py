"""
Task: Drafte tous les messages d'une campagne pour les prospects en attente.
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


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def draft_campaign_messages(self, tenant_id: str, campaign_id: str):
    """Drafte les messages pour tous les prospects d'une campagne."""
    async def _run():
        from crm.database import session_context
        from crm.models import Campaign, Prospect, Message, MessageStatus, ChannelEnum
        from ai.drafting import draft_message
        from sqlalchemy import select

        async with session_context() as session:
            result = await session.execute(
                select(Campaign).where(
                    Campaign.id == campaign_id,
                    Campaign.tenant_id == tenant_id,
                )
            )
            campaign = result.scalar_one_or_none()
            if not campaign:
                logger.error(f"Campaign {campaign_id} not found for tenant {tenant_id}")
                return

            prospects_result = await session.execute(
                select(Prospect).where(
                    Prospect.tenant_id == tenant_id,
                    Prospect.status == "discovered",
                ).limit(50)
            )
            prospects = prospects_result.scalars().all()

            sequence = campaign.sequence or []
            drafted = 0

            for prospect in prospects:
                for step in sequence:
                    channel = step.get("channel", "email")
                    context = step.get("context", campaign.name)

                    existing = await session.execute(
                        select(Message).where(
                            Message.tenant_id == tenant_id,
                            Message.prospect_id == prospect.id,
                            Message.campaign_id == campaign_id,
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue

                    try:
                        draft_text = await draft_message(
                            tenant_id=str(tenant_id),
                            prospect=prospect,
                            channel=channel,
                            campaign_context=context,
                            session=session,
                        )
                        msg = Message(
                            id=uuid.uuid4(),
                            tenant_id=tenant_id,
                            prospect_id=prospect.id,
                            campaign_id=campaign_id,
                            channel=ChannelEnum(channel),
                            status=MessageStatus.drafted,
                            draft_text=draft_text,
                            final_text=draft_text,
                            edit_count=0,
                        )
                        session.add(msg)
                        drafted += 1
                    except Exception as e:
                        logger.error(f"Draft failed for prospect {prospect.id}: {e}")

            await session.commit()
            logger.info(f"[DraftCampaign] tenant={tenant_id} campaign={campaign_id} drafted={drafted}")

    try:
        run_async(_run())
    except Exception as exc:
        self.retry(exc=exc)
