import asyncio
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from crm.database import get_session
from crm.repository import ProspectRepository
from api.schemas import AgentRunRequest, StatsOut

router = APIRouter(prefix="/agents", tags=["agents"])

_running_cycles: dict = {}


async def _run_cycle(cycle_name: str, campaign: dict | None, session_factory):
    from agents.orchestrator import Orchestrator
    async with session_factory() as session:
        orchestrator = Orchestrator(session)
        if campaign is None:
            repo = ProspectRepository(session)
            campaigns = await repo.get_active_campaigns()
            campaign = campaigns[0] if campaigns else {}

        if cycle_name == "qualification":
            return await orchestrator.run_qualification_cycle(campaign)
        elif cycle_name == "outreach":
            return await orchestrator.run_outreach_cycle(campaign)
        elif cycle_name == "followup":
            return await orchestrator.run_followup_cycle(campaign)
        elif cycle_name == "conversion":
            return await orchestrator.run_conversion_check()
        elif cycle_name == "full":
            return await orchestrator.run_full_cycle(campaign)
        else:
            raise ValueError(f"Unknown cycle: {cycle_name}")


@router.get("/status")
async def get_status():
    return {
        "running_cycles": list(_running_cycles.keys()),
        "agents": ["QualificationAgent", "OutreachAgent", "FollowUpAgent", "ConversionDetector", "Orchestrator"],
        "status": "operational",
    }


@router.post("/run/{cycle_name}")
async def run_cycle(
    cycle_name: str,
    request: AgentRunRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    valid_cycles = ["qualification", "outreach", "followup", "conversion", "full"]
    if cycle_name not in valid_cycles:
        raise HTTPException(status_code=400, detail=f"Invalid cycle. Choose from: {valid_cycles}")

    repo = ProspectRepository(session)
    campaign = None
    if request.campaign_id:
        campaign = await repo.get_campaign(request.campaign_id)
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        campaign = {
            "id": campaign.id,
            "name": campaign.name,
            "target_icp": campaign.target_icp,
            "channels": campaign.channels,
            "min_qualification_score": 50,
            "product_description": campaign.product_description if hasattr(campaign, "product_description") else "",
            "value_proposition": campaign.value_proposition if hasattr(campaign, "value_proposition") else "",
            "target_outcome": campaign.target_outcome if hasattr(campaign, "target_outcome") else "Book a call",
        }

    from crm.database import async_session_factory

    async def _bg():
        await _run_cycle(cycle_name, campaign, async_session_factory)

    background_tasks.add_task(_bg)
    return {"status": "started", "cycle": cycle_name}


@router.get("/logs")
async def get_logs(limit: int = 100, session: AsyncSession = Depends(get_session)):
    repo = ProspectRepository(session)
    return await repo.get_recent_logs(limit=limit)


@router.get("/stats", response_model=StatsOut)
async def get_stats(session: AsyncSession = Depends(get_session)):
    repo = ProspectRepository(session)
    return await repo.get_daily_stats()
