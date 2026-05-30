"""
Task: Drafte tous les messages d'une campagne pour les prospects en attente.
"""
import asyncio
import uuid
from celery.utils.log import get_task_logger
from tasks.celery_app import app

logger = get_task_logger(__name__)


def run_async(coro):
    return asyncio.run(coro)


def _make_session_factory():
    """Crée un moteur asyncpg frais pour le loop Celery — évite le conflit d'event loop."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from crm.database import _async_url
    from config.settings import settings
    engine = create_async_engine(_async_url(settings.database_url), poolclass=NullPool)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def draft_campaign_messages(self, tenant_id: str, campaign_id: str):
    """Drafte les messages pour tous les prospects d'une campagne."""
    async def _run():
        from crm.models import Campaign, Prospect, Message, MessageStatus, ChannelEnum
        from ai.drafting import draft_message
        from sqlalchemy import select, exists, not_, func

        AsyncSession = _make_session_factory()
        async with AsyncSession() as session:
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

            # Exclure les prospects qui ont déjà un message pour cette campagne
            has_message = exists().where(
                Message.tenant_id == tenant_id,
                Message.prospect_id == Prospect.id,
                Message.campaign_id == campaign_id,
            )
            prospects_result = await session.execute(
                select(Prospect).where(
                    Prospect.tenant_id == tenant_id,
                    Prospect.status == "discovered",
                    not_(has_message),
                ).limit(50)
            )
            prospects = prospects_result.scalars().all()

            sequence = campaign.sequence or []
            drafted = 0

            for prospect in prospects:
                # Compter les messages existants pour ce prospect+campagne afin de savoir
                # à quelle étape de la séquence on en est
                existing_count_result = await session.execute(
                    select(func.count(Message.id)).where(
                        Message.tenant_id == tenant_id,
                        Message.prospect_id == prospect.id,
                        Message.campaign_id == campaign_id,
                    )
                )
                already_drafted = existing_count_result.scalar() or 0

                for step_index, step in enumerate(sequence):
                    if step_index < already_drafted:
                        # Cette étape a déjà été draftée
                        continue

                    channel = step.get("channel", "email")
                    context = step.get("context", campaign.name)

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
                        await session.flush()
                        drafted += 1
                    except Exception as e:
                        logger.error(f"Draft failed for prospect {prospect.id} step {step_index}: {e}")

            await session.commit()
            logger.info(f"[DraftCampaign] tenant={tenant_id} campaign={campaign_id} drafted={drafted}")

    try:
        run_async(_run())
    except Exception as exc:
        self.retry(exc=exc)
