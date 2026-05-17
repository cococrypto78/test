from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from .qualification_agent import QualificationAgent
from .outreach_agent import OutreachAgent
from .followup_agent import FollowUpAgent
from .conversion_detector import ConversionDetector
from crm.repository import ProspectRepository
from crm.models import ProspectStatus
from notifications.notifier import HumanNotifier
from utils.logger import logger


class Orchestrator:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ProspectRepository(session)
        self.qualifier = QualificationAgent()
        self.outreach = OutreachAgent()
        self.followup = FollowUpAgent()
        self.detector = ConversionDetector()
        self.notifier = HumanNotifier()

    async def run_qualification_cycle(self, campaign: dict) -> int:
        prospects = await self.repo.get_prospects_by_status(ProspectStatus.DISCOVERED, limit=50)
        qualified_count = 0

        for prospect in prospects:
            prospect_data = {
                "id": prospect.id,
                "full_name": prospect.full_name,
                "email": prospect.email,
                "company": prospect.company,
                "title": prospect.title,
                "source_channel": prospect.source_channel,
                "linkedin_url": prospect.linkedin_url,
                "twitter_handle": prospect.twitter_handle,
                "instagram_handle": prospect.instagram_handle,
                "tiktok_handle": prospect.tiktok_handle,
                "notes": prospect.notes,
            }

            assessment = await self.qualifier.qualify_prospect(
                prospect_data,
                campaign.get("target_icp", {}),
            )

            score = assessment.get("score", 0)
            await self.repo.update_score(prospect.id, score, assessment)

            if score >= campaign.get("min_qualification_score", 50):
                await self.repo.update_status(prospect.id, ProspectStatus.QUALIFIED)
                qualified_count += 1
                await self.repo.add_log(
                    agent_name="Orchestrator",
                    action="prospect_qualified",
                    prospect_id=prospect.id,
                    details={"score": score, "assessment": assessment},
                )
            else:
                await self.repo.update_status(prospect.id, ProspectStatus.REJECTED)
                await self.repo.add_log(
                    agent_name="Orchestrator",
                    action="prospect_rejected",
                    prospect_id=prospect.id,
                    details={"score": score, "reason": assessment.get("disqualification_reason")},
                )

        logger.info(f"[Orchestrator] Qualification cycle: {qualified_count}/{len(prospects)} qualified")
        return qualified_count

    async def run_outreach_cycle(self, campaign: dict) -> int:
        prospects = await self.repo.get_prospects_by_status(ProspectStatus.QUALIFIED, limit=20)
        sent_count = 0

        for prospect in prospects:
            recommended_channel = prospect.qualification_data.get("recommended_channel", prospect.source_channel) if prospect.qualification_data else prospect.source_channel

            channel_handler = await self._get_channel_handler(recommended_channel)
            if not channel_handler:
                logger.warning(f"[Orchestrator] No handler for channel {recommended_channel}")
                continue

            prospect_data = self._prospect_to_dict(prospect)
            draft = await self.outreach.draft_message(prospect_data, campaign, recommended_channel)

            handle = self._get_handle(prospect, recommended_channel)
            if not handle:
                logger.warning(f"[Orchestrator] No handle for prospect {prospect.id} on {recommended_channel}")
                continue

            success = await channel_handler.send_message(handle, draft["body"])

            if success:
                await self.repo.update_status(prospect.id, ProspectStatus.CONTACTED)
                await self.repo.add_interaction(
                    prospect_id=prospect.id,
                    campaign_id=campaign.get("id"),
                    channel=recommended_channel,
                    direction="out",
                    content=draft["body"],
                )
                sent_count += 1
                await self.repo.add_log(
                    agent_name="Orchestrator",
                    action="outreach_sent",
                    prospect_id=prospect.id,
                    details={"channel": recommended_channel, "hook": draft.get("hook")},
                )

        logger.info(f"[Orchestrator] Outreach cycle: {sent_count} messages sent")
        return sent_count

    async def run_followup_cycle(self, campaign: dict) -> int:
        prospects = await self.repo.get_prospects_needing_followup()
        followup_count = 0

        for prospect in prospects:
            interactions = await self.repo.get_interactions(prospect.id)
            prospect_data = self._prospect_to_dict(prospect)

            inbound = [i for i in interactions if i.direction == "in"]
            if inbound:
                latest_response = inbound[-1]
                analysis = await self.followup.analyze_response(
                    prospect_data,
                    latest_response.content,
                    [{"direction": i.direction, "channel": i.channel, "content": i.content, "timestamp": str(i.timestamp)} for i in interactions],
                )

                await self.repo.update_sentiment(prospect.id, analysis.get("sentiment"))

                if analysis.get("escalate_to_human"):
                    await self.repo.update_status(prospect.id, ProspectStatus.HANDOFF)
                    await self.notifier.notify_handoff(
                        prospect_data,
                        analysis.get("escalation_reason", "Prospect ready for human contact"),
                        "high",
                    )
                    continue

                if analysis.get("next_action") == "close_lost":
                    await self.repo.update_status(prospect.id, ProspectStatus.REJECTED)
                    continue

                reply = analysis.get("suggested_reply")
                if reply:
                    channel = latest_response.channel
                    channel_handler = await self._get_channel_handler(channel)
                    handle = self._get_handle(prospect, channel)
                    if channel_handler and handle:
                        await channel_handler.send_message(handle, reply)
                        await self.repo.add_interaction(
                            prospect_id=prospect.id,
                            campaign_id=campaign.get("id"),
                            channel=channel,
                            direction="out",
                            content=reply,
                        )
                        followup_count += 1
            else:
                touch_number = len([i for i in interactions if i.direction == "out"])
                if touch_number >= 4:
                    await self.repo.update_status(prospect.id, ProspectStatus.REJECTED)
                    continue

                draft = await self.followup.draft_followup(
                    prospect_data,
                    [{"direction": i.direction, "channel": i.channel, "content": i.content} for i in interactions],
                    campaign,
                    touch_number + 1,
                )

                channel = prospect.source_channel
                channel_handler = await self._get_channel_handler(channel)
                handle = self._get_handle(prospect, channel)
                if channel_handler and handle and draft.get("body"):
                    await channel_handler.send_message(handle, draft["body"])
                    await self.repo.add_interaction(
                        prospect_id=prospect.id,
                        campaign_id=campaign.get("id"),
                        channel=channel,
                        direction="out",
                        content=draft["body"],
                    )
                    followup_count += 1

        logger.info(f"[Orchestrator] Follow-up cycle: {followup_count} follow-ups sent")
        return followup_count

    async def run_conversion_check(self) -> int:
        prospects = await self.repo.get_prospects_by_status(ProspectStatus.RESPONDING, limit=100)
        handoff_count = 0

        for prospect in prospects:
            interactions = await self.repo.get_interactions(prospect.id)
            if len(interactions) < 2:
                continue

            prospect_data = self._prospect_to_dict(prospect)
            assessment = await self.detector.assess_readiness(
                prospect_data,
                [{"direction": i.direction, "channel": i.channel, "content": i.content, "timestamp": str(i.timestamp)} for i in interactions],
            )

            if assessment.get("ready_for_human") and assessment.get("confidence", 0) >= 0.7:
                await self.repo.update_status(prospect.id, ProspectStatus.HANDOFF)
                await self.repo.create_handoff(
                    prospect_id=prospect.id,
                    reason=assessment.get("summary", ""),
                    urgency=assessment.get("urgency", "medium"),
                )
                await self.notifier.notify_handoff(
                    prospect_data,
                    assessment.get("summary", "Prospect ready for conversion"),
                    assessment.get("urgency", "medium"),
                    context={
                        "signals": assessment.get("signals_detected", []),
                        "talking_points": assessment.get("talking_points", []),
                        "recommended_action": assessment.get("recommended_action"),
                        "risk_of_loss": assessment.get("risk_of_loss"),
                    },
                )
                handoff_count += 1

        logger.info(f"[Orchestrator] Conversion check: {handoff_count} handoffs triggered")
        return handoff_count

    async def run_full_cycle(self, campaign: dict) -> dict:
        logger.info(f"[Orchestrator] Starting full cycle for campaign '{campaign.get('name')}'")
        results = {
            "qualified": await self.run_qualification_cycle(campaign),
            "outreach_sent": await self.run_outreach_cycle(campaign),
            "followups_sent": await self.run_followup_cycle(campaign),
            "handoffs": await self.run_conversion_check(),
            "timestamp": datetime.utcnow().isoformat(),
        }
        logger.info(f"[Orchestrator] Full cycle complete: {results}")
        return results

    async def _get_channel_handler(self, channel: str):
        try:
            if channel == "linkedin":
                from channels.linkedin.scraper import LinkedInScraper
                return LinkedInScraper()
            elif channel == "twitter":
                from channels.twitter.handler import TwitterHandler
                return TwitterHandler()
            elif channel == "instagram":
                from channels.instagram.handler import InstagramHandler
                return InstagramHandler()
            elif channel == "tiktok":
                from channels.tiktok.handler import TikTokHandler
                return TikTokHandler()
            elif channel == "email":
                from channels.email.handler import EmailHandler
                return EmailHandler()
        except Exception as e:
            logger.error(f"[Orchestrator] Failed to load handler for {channel}: {e}")
        return None

    def _get_handle(self, prospect, channel: str) -> Optional[str]:
        mapping = {
            "linkedin": prospect.linkedin_url,
            "twitter": prospect.twitter_handle,
            "instagram": prospect.instagram_handle,
            "tiktok": prospect.tiktok_handle,
            "email": prospect.email,
        }
        return mapping.get(channel)

    def _prospect_to_dict(self, prospect) -> dict:
        return {
            "id": prospect.id,
            "full_name": prospect.full_name,
            "email": prospect.email,
            "company": prospect.company,
            "title": prospect.title,
            "source_channel": prospect.source_channel,
            "score": prospect.score,
            "linkedin_url": prospect.linkedin_url,
            "twitter_handle": prospect.twitter_handle,
            "instagram_handle": prospect.instagram_handle,
            "tiktok_handle": prospect.tiktok_handle,
            "notes": prospect.notes,
            "personalization_hints": prospect.qualification_data.get("personalization_hints", []) if prospect.qualification_data else [],
        }
