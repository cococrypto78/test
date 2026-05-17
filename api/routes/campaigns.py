from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from crm.database import get_session
from crm.repository import ProspectRepository
from api.schemas import CampaignCreate, CampaignOut

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.get("/", response_model=list[CampaignOut])
async def list_campaigns(session: AsyncSession = Depends(get_session)):
    repo = ProspectRepository(session)
    return await repo.get_active_campaigns()


@router.post("/", response_model=CampaignOut, status_code=201)
async def create_campaign(data: CampaignCreate, session: AsyncSession = Depends(get_session)):
    repo = ProspectRepository(session)
    return await repo.create_campaign(data.model_dump())


@router.post("/{campaign_id}/activate")
async def activate_campaign(campaign_id: int, session: AsyncSession = Depends(get_session)):
    repo = ProspectRepository(session)
    campaign = await repo.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    await repo.update_campaign(campaign_id, {"is_active": True})
    return {"status": "activated"}


@router.post("/{campaign_id}/pause")
async def pause_campaign(campaign_id: int, session: AsyncSession = Depends(get_session)):
    repo = ProspectRepository(session)
    campaign = await repo.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    await repo.update_campaign(campaign_id, {"is_active": False})
    return {"status": "paused"}


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: int, session: AsyncSession = Depends(get_session)):
    repo = ProspectRepository(session)
    campaign = await repo.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    await session.delete(campaign)
    await session.commit()
