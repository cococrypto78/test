import asyncio
import sys
import uvicorn
from utils.logger import logger


def run_api():
    from config.settings import settings
    uvicorn.run(
        "api.app:app",
        host="0.0.0.0",
        port=settings.api_port,
        reload=settings.is_development,
        log_level=settings.log_level.lower(),
    )


async def run_cycle(cycle_name: str, campaign_id: int | None = None):
    from crm.database import session_context as get_session, init_db
    from crm.repository import ProspectRepository
    from agents.orchestrator import Orchestrator

    await init_db()
    async with get_session() as session:
        repo = ProspectRepository(session)
        campaigns = await repo.get_active_campaigns()
        campaign = next((c for c in campaigns if campaign_id is None or c["id"] == campaign_id), campaigns[0] if campaigns else {})

        orchestrator = Orchestrator(session)

        if cycle_name == "full":
            result = await orchestrator.run_full_cycle(campaign)
        elif cycle_name == "qualify":
            result = await orchestrator.run_qualification_cycle(campaign)
        elif cycle_name == "outreach":
            result = await orchestrator.run_outreach_cycle(campaign)
        elif cycle_name == "followup":
            result = await orchestrator.run_followup_cycle(campaign)
        elif cycle_name == "conversion":
            result = await orchestrator.run_conversion_check()
        else:
            logger.error(f"Unknown cycle: {cycle_name}")
            return

        logger.info(f"Cycle '{cycle_name}' result: {result}")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "api"

    if command == "api":
        run_api()
    elif command in ("full", "qualify", "outreach", "followup", "conversion"):
        campaign_id = int(sys.argv[2]) if len(sys.argv) > 2 else None
        asyncio.run(run_cycle(command, campaign_id))
    else:
        print(f"Usage: python main.py [api|full|qualify|outreach|followup|conversion] [campaign_id]")
        sys.exit(1)
