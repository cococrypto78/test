import asyncio
from celery.utils.log import get_task_logger
from tasks.celery_app import app
from crm.database import session_context as get_session
from crm.repository import ProspectRepository

logger = get_task_logger(__name__)


def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _get_active_campaigns(session) -> list[dict]:
    repo = ProspectRepository(session)
    return await repo.get_active_campaigns()


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def discovery_task(self):
    async def _run():
        from agents.orchestrator import Orchestrator
        from channels.linkedin.scraper import LinkedInScraper
        from channels.twitter.handler import TwitterHandler
        from channels.instagram.handler import InstagramHandler
        from channels.tiktok.handler import TikTokHandler

        async with get_session() as session:
            campaigns = await _get_active_campaigns(session)
            for campaign in campaigns:
                icp = campaign.get("target_icp", {})
                keywords = icp.get("keywords", [])

                handlers = [
                    ("linkedin", LinkedInScraper()),
                    ("twitter", TwitterHandler()),
                    ("instagram", InstagramHandler()),
                    ("tiktok", TikTokHandler()),
                ]

                repo = ProspectRepository(session)
                total_found = 0
                for channel, handler in handlers:
                    if channel not in campaign.get("channels", []):
                        continue
                    try:
                        prospects = await handler.search_prospects(keywords, limit=30)
                        for p in prospects:
                            existing = await repo.get_by_channel_handle(channel, p.get(f"{channel}_handle") or p.get("linkedin_url", ""))
                            if not existing:
                                await repo.create(p, campaign["id"])
                                total_found += 1
                    except Exception as e:
                        logger.error(f"Discovery failed for {channel}: {e}")

                logger.info(f"Discovery task: found {total_found} new prospects for campaign '{campaign['name']}'")

    try:
        run_async(_run())
    except Exception as exc:
        raise self.retry(exc=exc)


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def qualification_task(self):
    async def _run():
        from agents.orchestrator import Orchestrator
        async with get_session() as session:
            campaigns = await _get_active_campaigns(session)
            for campaign in campaigns:
                orchestrator = Orchestrator(session)
                count = await orchestrator.run_qualification_cycle(campaign)
                logger.info(f"Qualification task: {count} prospects qualified for '{campaign['name']}'")

    try:
        run_async(_run())
    except Exception as exc:
        raise self.retry(exc=exc)


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def outreach_task(self):
    async def _run():
        from agents.orchestrator import Orchestrator
        async with get_session() as session:
            campaigns = await _get_active_campaigns(session)
            for campaign in campaigns:
                orchestrator = Orchestrator(session)
                count = await orchestrator.run_outreach_cycle(campaign)
                logger.info(f"Outreach task: {count} messages sent for '{campaign['name']}'")

    try:
        run_async(_run())
    except Exception as exc:
        raise self.retry(exc=exc)


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def followup_task(self):
    async def _run():
        from agents.orchestrator import Orchestrator
        async with get_session() as session:
            campaigns = await _get_active_campaigns(session)
            for campaign in campaigns:
                orchestrator = Orchestrator(session)
                count = await orchestrator.run_followup_cycle(campaign)
                logger.info(f"Follow-up task: {count} follow-ups sent for '{campaign['name']}'")

    try:
        run_async(_run())
    except Exception as exc:
        raise self.retry(exc=exc)


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def conversion_check_task(self):
    async def _run():
        from agents.orchestrator import Orchestrator
        async with get_session() as session:
            orchestrator = Orchestrator(session)
            count = await orchestrator.run_conversion_check()
            logger.info(f"Conversion check: {count} handoffs triggered")

    try:
        run_async(_run())
    except Exception as exc:
        raise self.retry(exc=exc)


@app.task(bind=True, max_retries=2)
def daily_summary_task(self):
    async def _run():
        from notifications.notifier import HumanNotifier
        async with get_session() as session:
            repo = ProspectRepository(session)
            stats = await repo.get_daily_stats()
            notifier = HumanNotifier()
            await notifier.notify_daily_summary(stats)
            logger.info(f"Daily summary sent: {stats}")

    try:
        run_async(_run())
    except Exception as exc:
        raise self.retry(exc=exc)
