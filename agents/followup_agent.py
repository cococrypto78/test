import json
from datetime import datetime, timedelta
from .base_agent import BaseAgent
from utils.logger import logger

FOLLOWUP_SYSTEM_PROMPT = """You are an expert Sales Development Representative (SDR) with deep expertise in
multi-touch outreach sequences. You analyze prospect responses and craft contextually perfect follow-ups.

Your response analysis framework:
- Detect sentiment: positive/neutral/negative/interested/objecting/not_now
- Identify intent signals: curious, comparing options, budget concern, timing issue, wrong person, interested
- Recommend next action: reply, call, send_resource, wait, escalate_to_human, close_lost

For follow-up drafts:
- Acknowledge previous interaction naturally
- Add new value — never just "checking in"
- Reference their response if they replied
- If no response: try a completely different angle/hook
- Keep it shorter each follow-up

Always return JSON:
{
  "sentiment": "<positive|neutral|negative|interested|objecting|not_now>",
  "intent": "<string description>",
  "buying_signals": ["<signal1>", ...],
  "objections": ["<objection1>", ...],
  "suggested_reply": "<drafted reply message>",
  "escalate_to_human": <true|false>,
  "escalation_reason": "<reason or null>",
  "next_action": "<reply|call|send_resource|wait|escalate_to_human|close_lost>",
  "wait_days": <int — how many days before next touch>,
  "confidence": <float 0-1>
}
"""

SEQUENCE_INTERVALS = [3, 7, 14, 21]


class FollowUpAgent(BaseAgent):
    def __init__(self):
        super().__init__("FollowUpAgent")

    async def analyze_response(
        self,
        prospect: dict,
        response_text: str,
        interaction_history: list[dict],
    ) -> dict:
        history_summary = "\n".join(
            f"[{i.get('direction', 'out')} | {i.get('channel', '?')} | {i.get('timestamp', '?')}]: {i.get('content', '')[:200]}"
            for i in interaction_history[-10:]
        )

        user_message = f"""
## Prospect
{json.dumps(prospect, indent=2)}

## Conversation History (last 10)
{history_summary}

## Latest Response from Prospect
{response_text}

Analyze this response and provide follow-up recommendations.
"""
        result = await self.think(
            system_prompt=FOLLOWUP_SYSTEM_PROMPT,
            user_message=user_message,
            temperature=0.4,
        )

        try:
            text = result["text"].strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            analysis = json.loads(text)
            logger.info(
                f"[FollowUpAgent] Analyzed response for '{prospect.get('full_name')}': "
                f"sentiment={analysis.get('sentiment')}, escalate={analysis.get('escalate_to_human')}"
            )
            return analysis
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error(f"[FollowUpAgent] Failed to parse response analysis: {e}")
            return {
                "sentiment": "neutral",
                "intent": "unclear",
                "buying_signals": [],
                "objections": [],
                "suggested_reply": "",
                "escalate_to_human": False,
                "escalation_reason": None,
                "next_action": "wait",
                "wait_days": 7,
                "confidence": 0.0,
            }

    async def draft_followup(
        self,
        prospect: dict,
        interaction_history: list[dict],
        campaign: dict,
        touch_number: int,
    ) -> dict:
        days_since_first = SEQUENCE_INTERVALS[min(touch_number - 1, len(SEQUENCE_INTERVALS) - 1)]

        history_summary = "\n".join(
            f"[{i.get('direction', 'out')} | {i.get('channel', '?')}]: {i.get('content', '')[:300]}"
            for i in interaction_history[-5:]
        )

        user_message = f"""
## Touch #{touch_number} Follow-Up (Day {days_since_first} of sequence)

## Prospect
{json.dumps(prospect, indent=2)}

## Previous Interactions
{history_summary}

## Campaign Context
{json.dumps(campaign, indent=2)}

This is follow-up #{touch_number}. No response yet to previous messages.
Craft a follow-up that tries a completely different angle than previous attempts.
Return JSON with: subject (nullable), body, variant_b, hook, tone.
"""
        result = await self.think(
            system_prompt=FOLLOWUP_SYSTEM_PROMPT,
            user_message=user_message,
            temperature=0.8,
        )

        try:
            text = result["text"].strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error(f"[FollowUpAgent] Failed to parse followup draft: {e}")
            return {"subject": None, "body": result.get("text", ""), "variant_b": "", "hook": "", "tone": "neutral"}

    def get_next_followup_date(self, touch_number: int, from_date: datetime | None = None) -> datetime:
        base = from_date or datetime.utcnow()
        idx = min(touch_number, len(SEQUENCE_INTERVALS) - 1)
        return base + timedelta(days=SEQUENCE_INTERVALS[idx])
