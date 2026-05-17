from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy import select, and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Prospect, Campaign, Interaction, AgentLog, HumanHandoff, ProspectStatus, InteractionDirection
from utils.logger import logger


class ProspectRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: dict, campaign_id: Optional[int] = None) -> Prospect:
        prospect = Prospect(**data)
        self.session.add(prospect)
        await self.session.commit()
        await self.session.refresh(prospect)
        logger.info(f"Created prospect: {prospect.full_name} (id={prospect.id})")
        return prospect

    async def get_by_id(self, prospect_id: int) -> Optional[Prospect]:
        result = await self.session.execute(
            select(Prospect)
            .where(Prospect.id == prospect_id)
            .options(selectinload(Prospect.interactions))
        )
        return result.scalar_one_or_none()

    async def get_by_channel_handle(self, channel: str, handle: str) -> Optional[Prospect]:
        channel_map = {
            "linkedin": Prospect.linkedin_url,
            "twitter": Prospect.twitter_handle,
            "instagram": Prospect.instagram_handle,
            "tiktok": Prospect.tiktok_handle,
            "email": Prospect.email,
        }
        field = channel_map.get(channel)
        if not field:
            return None
        result = await self.session.execute(select(Prospect).where(field == handle))
        return result.scalar_one_or_none()

    async def update_status(self, prospect_id: int, status: ProspectStatus) -> Optional[Prospect]:
        await self.session.execute(
            update(Prospect)
            .where(Prospect.id == prospect_id)
            .values(status=status, updated_at=datetime.utcnow())
        )
        await self.session.commit()
        return await self.get_by_id(prospect_id)

    async def update_score(self, prospect_id: int, score: float, qualification_data: Optional[dict] = None) -> Optional[Prospect]:
        values: dict = {"score": score, "updated_at": datetime.utcnow()}
        if qualification_data:
            values["qualification_data"] = qualification_data
        await self.session.execute(
            update(Prospect).where(Prospect.id == prospect_id).values(**values)
        )
        await self.session.commit()
        return await self.get_by_id(prospect_id)

    async def update_sentiment(self, prospect_id: int, sentiment: str) -> None:
        await self.session.execute(
            update(Prospect).where(Prospect.id == prospect_id).values(sentiment=sentiment, updated_at=datetime.utcnow())
        )
        await self.session.commit()

    async def get_interactions(self, prospect_id: int) -> List[Interaction]:
        result = await self.session.execute(
            select(Interaction)
            .where(Interaction.prospect_id == prospect_id)
            .order_by(Interaction.timestamp.asc())
        )
        return list(result.scalars().all())

    async def add_interaction(
        self,
        prospect_id: int,
        channel: str,
        direction: str,
        content: str,
        campaign_id: Optional[int] = None,
        sentiment_score: Optional[float] = None,
    ) -> Interaction:
        interaction = Interaction(
            prospect_id=prospect_id,
            campaign_id=campaign_id,
            channel=channel,
            direction=direction,
            content=content,
            sentiment_score=sentiment_score,
        )
        self.session.add(interaction)
        await self.session.execute(
            update(Prospect)
            .where(Prospect.id == prospect_id)
            .values(last_interaction=datetime.utcnow(), updated_at=datetime.utcnow())
        )
        await self.session.commit()
        return interaction

    async def add_log(
        self,
        agent_name: str,
        action: str,
        prospect_id: Optional[int] = None,
        details: Optional[dict] = None,
    ) -> AgentLog:
        log = AgentLog(
            agent_name=agent_name,
            action=action,
            prospect_id=prospect_id,
            details=details or {},
        )
        self.session.add(log)
        await self.session.commit()
        return log

    async def get_prospects_needing_followup(self, days_since_contact: int = 3) -> List[Prospect]:
        cutoff = datetime.utcnow() - timedelta(days=days_since_contact)
        result = await self.session.execute(
            select(Prospect)
            .where(
                and_(
                    Prospect.status.in_([ProspectStatus.CONTACTED, ProspectStatus.RESPONDING]),
                    or_(
                        Prospect.last_interaction <= cutoff,
                        Prospect.last_interaction.is_(None),
                    ),
                )
            )
            .options(selectinload(Prospect.interactions))
        )
        return list(result.scalars().all())

    async def get_prospects_by_status(self, status: ProspectStatus, limit: int = 50) -> List[Prospect]:
        result = await self.session.execute(
            select(Prospect)
            .where(Prospect.status == status)
            .order_by(Prospect.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_handoff_queue(self, include_resolved: bool = False) -> List[HumanHandoff]:
        query = select(HumanHandoff).options(selectinload(HumanHandoff.prospect))
        if not include_resolved:
            query = query.where(HumanHandoff.resolved_at.is_(None))
        query = query.order_by(HumanHandoff.notified_at.asc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_handoff(self, handoff_id: int) -> Optional[HumanHandoff]:
        result = await self.session.execute(
            select(HumanHandoff)
            .where(HumanHandoff.id == handoff_id)
            .options(selectinload(HumanHandoff.prospect))
        )
        return result.scalar_one_or_none()

    async def create_handoff(
        self,
        prospect_id: int,
        reason: str,
        urgency: str = "medium",
        notes: Optional[str] = None,
    ) -> HumanHandoff:
        handoff = HumanHandoff(
            prospect_id=prospect_id,
            reason=reason,
            urgency=urgency,
            notes=notes,
        )
        self.session.add(handoff)
        await self.session.commit()
        await self.session.refresh(handoff)
        return handoff

    async def resolve_handoff(self, handoff_id: int, notes: Optional[str] = None) -> Optional[HumanHandoff]:
        result = await self.session.execute(
            select(HumanHandoff).where(HumanHandoff.id == handoff_id)
        )
        handoff = result.scalar_one_or_none()
        if handoff:
            handoff.resolved_at = datetime.utcnow()
            if notes:
                handoff.notes = notes
            await self.session.commit()
        return handoff

    async def search_prospects(
        self,
        status: Optional[ProspectStatus] = None,
        channel: Optional[str] = None,
        min_score: Optional[float] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Prospect]:
        query = select(Prospect)
        conditions = []
        if status:
            conditions.append(Prospect.status == status)
        if channel:
            conditions.append(Prospect.source_channel == channel)
        if min_score is not None:
            conditions.append(Prospect.score >= min_score)
        if conditions:
            query = query.where(and_(*conditions))
        query = query.order_by(Prospect.score.desc()).limit(limit).offset(offset)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_discovered_prospects(self, limit: int = 50) -> List[Prospect]:
        result = await self.session.execute(
            select(Prospect)
            .where(Prospect.status == ProspectStatus.DISCOVERED)
            .order_by(Prospect.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_qualified_uncontacted(self, min_score: float = 60.0, limit: int = 20) -> List[Prospect]:
        result = await self.session.execute(
            select(Prospect)
            .where(
                and_(
                    Prospect.status == ProspectStatus.QUALIFIED,
                    Prospect.score >= min_score,
                )
            )
            .order_by(Prospect.score.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_recent_logs(self, limit: int = 100) -> List[AgentLog]:
        result = await self.session.execute(
            select(AgentLog).order_by(AgentLog.timestamp.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def count_by_status(self) -> dict:
        from sqlalchemy import func
        result = await self.session.execute(
            select(Prospect.status, func.count(Prospect.id))
            .group_by(Prospect.status)
        )
        return {row[0]: row[1] for row in result.all()}

    async def get_active_campaigns(self) -> list:
        result = await self.session.execute(
            select(Campaign).where(Campaign.is_active == True).order_by(Campaign.created_at.desc())
        )
        campaigns = result.scalars().all()
        return [
            {
                "id": c.id,
                "name": c.name,
                "target_icp": c.target_icp or {},
                "channels": c.channels or [],
                "daily_limit": c.daily_limit,
                "min_qualification_score": c.min_qualification_score,
                "product_description": c.product_description or "",
                "value_proposition": c.value_proposition or "",
                "target_outcome": c.target_outcome or "Book a discovery call",
                "is_active": c.is_active,
            }
            for c in campaigns
        ]

    async def get_campaign(self, campaign_id: int) -> Optional[Campaign]:
        result = await self.session.execute(
            select(Campaign).where(Campaign.id == campaign_id)
        )
        return result.scalar_one_or_none()

    async def create_campaign(self, data: dict) -> Campaign:
        campaign = Campaign(**data)
        self.session.add(campaign)
        await self.session.commit()
        await self.session.refresh(campaign)
        return campaign

    async def update_campaign(self, campaign_id: int, values: dict) -> None:
        await self.session.execute(
            update(Campaign).where(Campaign.id == campaign_id).values(**values)
        )
        await self.session.commit()

    async def get_daily_stats(self) -> dict:
        from sqlalchemy import func
        counts = await self.count_by_status()
        total_contacted = counts.get(ProspectStatus.CONTACTED, 0)
        total_responding = counts.get(ProspectStatus.RESPONDING, 0)
        response_rate = (total_responding / total_contacted * 100) if total_contacted > 0 else 0.0

        avg_result = await self.session.execute(
            select(func.avg(Prospect.score)).where(Prospect.score > 0)
        )
        avg_score = avg_result.scalar() or 0.0

        return {
            "discovered": counts.get(ProspectStatus.DISCOVERED, 0),
            "qualified": counts.get(ProspectStatus.QUALIFIED, 0),
            "contacted": total_contacted,
            "responding": total_responding,
            "handoff": counts.get(ProspectStatus.HANDOFF, 0),
            "rejected": counts.get(ProspectStatus.REJECTED, 0),
            "converted": counts.get(ProspectStatus.CONVERTED, 0),
            "response_rate": round(response_rate, 1),
            "avg_score": round(float(avg_score), 1),
        }
