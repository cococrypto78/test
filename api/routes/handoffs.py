from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from crm.database import get_session
from crm.repository import ProspectRepository
from api.schemas import HandoffOut, HandoffResolve

router = APIRouter(prefix="/handoffs", tags=["handoffs"])


@router.get("/", response_model=list[HandoffOut])
async def list_handoffs(
    resolved: bool = False,
    session: AsyncSession = Depends(get_session),
):
    repo = ProspectRepository(session)
    return await repo.get_handoff_queue(include_resolved=resolved)


@router.get("/{handoff_id}", response_model=HandoffOut)
async def get_handoff(handoff_id: int, session: AsyncSession = Depends(get_session)):
    repo = ProspectRepository(session)
    handoff = await repo.get_handoff(handoff_id)
    if not handoff:
        raise HTTPException(status_code=404, detail="Handoff not found")
    return handoff


@router.get("/{handoff_id}/context")
async def get_handoff_context(handoff_id: int, session: AsyncSession = Depends(get_session)):
    repo = ProspectRepository(session)
    handoff = await repo.get_handoff(handoff_id)
    if not handoff:
        raise HTTPException(status_code=404, detail="Handoff not found")

    interactions = await repo.get_interactions(handoff.prospect_id)
    prospect = await repo.get_by_id(handoff.prospect_id)

    return {
        "handoff": handoff,
        "prospect": prospect,
        "conversation_history": [
            {
                "channel": i.channel,
                "direction": i.direction,
                "content": i.content,
                "timestamp": i.timestamp,
                "sentiment_score": i.sentiment_score,
            }
            for i in interactions
        ],
    }


@router.post("/{handoff_id}/resolve")
async def resolve_handoff(
    handoff_id: int,
    body: HandoffResolve,
    session: AsyncSession = Depends(get_session),
):
    repo = ProspectRepository(session)
    handoff = await repo.get_handoff(handoff_id)
    if not handoff:
        raise HTTPException(status_code=404, detail="Handoff not found")
    await repo.resolve_handoff(handoff_id, body.notes)
    return {"status": "resolved"}
