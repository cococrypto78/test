from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from crm.database import get_session
from crm.repository import ProspectRepository
from crm.models import ProspectStatus
from api.schemas import ProspectCreate, ProspectOut, InteractionOut
from typing import Optional

router = APIRouter(prefix="/prospects", tags=["prospects"])


@router.get("/", response_model=list[ProspectOut])
async def list_prospects(
    status: Optional[str] = None,
    channel: Optional[str] = None,
    min_score: Optional[int] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    repo = ProspectRepository(session)
    status_enum = ProspectStatus(status) if status else None
    return await repo.search_prospects(status=status_enum, channel=channel, min_score=min_score, limit=limit, offset=offset)


@router.get("/{prospect_id}", response_model=ProspectOut)
async def get_prospect(prospect_id: int, session: AsyncSession = Depends(get_session)):
    repo = ProspectRepository(session)
    prospect = await repo.get_by_id(prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")
    return prospect


@router.post("/", response_model=ProspectOut, status_code=201)
async def create_prospect(data: ProspectCreate, session: AsyncSession = Depends(get_session)):
    repo = ProspectRepository(session)
    return await repo.create(data.model_dump(), campaign_id=None)


@router.get("/{prospect_id}/interactions", response_model=list[InteractionOut])
async def get_interactions(prospect_id: int, session: AsyncSession = Depends(get_session)):
    repo = ProspectRepository(session)
    return await repo.get_interactions(prospect_id)


@router.delete("/{prospect_id}", status_code=204)
async def delete_prospect(prospect_id: int, session: AsyncSession = Depends(get_session)):
    repo = ProspectRepository(session)
    prospect = await repo.get_by_id(prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")
    await session.delete(prospect)
    await session.commit()
