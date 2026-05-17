import json
from .base_agent import BaseAgent
from utils.logger import logger

CONVERSION_SYSTEM_PROMPT = """You are a senior sales manager with 20+ years of experience reading deal readiness.
You analyze the entire conversation history with a prospect and determine if they are ready for a human sales rep.

Buying signals to detect:
- Asking specific questions about pricing, timeline, implementation
- Mentioning a budget or approval process
- Requesting a demo, call, or more detailed information
- Expressing urgency or deadline
- Comparing with alternatives (they're shopping)
- Positive engagement: multiple replies, long messages, sharing internal context
- Mentioning pain points in detail

Disqualification signals:
- Explicit "not interested" or "remove me"
- Wrong company fit confirmed
- No budget/authority
- Wrong timing (more than 12 months out)

Return JSON:
{
  "ready_for_human": <true|false>,
  "confidence": <float 0.0-1.0>,
  "urgency": "<low|medium|high|critical>",
  "signals_detected": ["<signal1>", "<signal2>", ...],
  "objections_present": ["<objection1>", ...],
  "recommended_action": "<string — what the human rep should do>",
  "talking_points": ["<point1>", "<point2>", ...],
  "risk_of_loss": "<low|medium|high — risk of losing this prospect if not contacted now>",
  "summary": "<2-3 sentence summary for the human rep>"
}
"""


class ConversionDetector(BaseAgent):
    def __init__(self):
        super().__init__("ConversionDetector")

    async def assess_readiness(
        self,
        prospect: dict,
        all_interactions: list[dict],
    ) -> dict:
        interactions_text = "\n\n".join(
            f"[{i.get('direction', '?')} | {i.get('channel', '?')} | {i.get('timestamp', '?')}]\n{i.get('content', '')}"
            for i in all_interactions
        )

        user_message = f"""
## Prospect Profile
{json.dumps(prospect, indent=2)}

## Complete Interaction History
{interactions_text}

Assess whether this prospect is ready to be handed off to a human sales representative.
"""
        result = await self.think(
            system_prompt=CONVERSION_SYSTEM_PROMPT,
            user_message=user_message,
            temperature=0.2,
        )

        try:
            text = result["text"].strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            assessment = json.loads(text)
            logger.info(
                f"[ConversionDetector] Prospect '{prospect.get('full_name')}': "
                f"ready={assessment.get('ready_for_human')}, "
                f"confidence={assessment.get('confidence')}, "
                f"urgency={assessment.get('urgency')}"
            )
            return assessment
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error(f"[ConversionDetector] Failed to parse assessment: {e}")
            return {
                "ready_for_human": False,
                "confidence": 0.0,
                "urgency": "low",
                "signals_detected": [],
                "objections_present": [],
                "recommended_action": "Continue automated nurturing",
                "talking_points": [],
                "risk_of_loss": "low",
                "summary": "Assessment failed — manual review required.",
            }

    async def batch_assess(
        self,
        prospects_with_interactions: list[dict],
    ) -> list[dict]:
        results = []
        for item in prospects_with_interactions:
            assessment = await self.assess_readiness(
                item["prospect"],
                item["interactions"],
            )
            results.append({
                "prospect_id": item["prospect"].get("id"),
                "assessment": assessment,
            })
        return results
