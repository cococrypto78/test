import json
from typing import Optional
from .base_agent import BaseAgent
from utils.logger import logger

QUALIFICATION_SYSTEM_PROMPT = """You are an expert B2B sales qualification specialist with 15+ years of experience.
Your role is to evaluate prospects against an Ideal Customer Profile (ICP) and assign a qualification score.

Scoring criteria (0-100):
- Company fit (industry, size, stage): 30 points
- Role fit (decision maker, budget authority, influence): 25 points
- Problem fit (likely has the pain point our solution addresses): 25 points
- Engagement signals (activity, content interests, growth indicators): 20 points

Always return a JSON object with these exact fields:
{
  "score": <int 0-100>,
  "reasoning": "<detailed explanation>",
  "recommended_channel": "<linkedin|twitter|instagram|tiktok|email>",
  "personalization_hints": ["<hint1>", "<hint2>", ...],
  "disqualification_reason": "<string or null>",
  "recommended_approach": "<one sentence on how to open>",
  "fit_breakdown": {
    "company_fit": <int 0-30>,
    "role_fit": <int 0-25>,
    "problem_fit": <int 0-25>,
    "engagement_signals": <int 0-20>
  }
}
"""


class QualificationAgent(BaseAgent):
    def __init__(self):
        super().__init__("QualificationAgent")

    async def qualify_prospect(self, prospect_data: dict, icp: dict) -> dict:
        user_message = f"""
## Prospect Information
{json.dumps(prospect_data, indent=2)}

## Ideal Customer Profile (ICP)
{json.dumps(icp, indent=2)}

Evaluate this prospect against the ICP and return a JSON qualification assessment.
Focus on realistic scoring - not every prospect should score high.
"""
        result = await self.think(
            system_prompt=QUALIFICATION_SYSTEM_PROMPT,
            user_message=user_message,
            temperature=0.3,
        )

        try:
            text = result["text"].strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            assessment = json.loads(text)
            logger.info(
                f"[QualificationAgent] Scored prospect '{prospect_data.get('full_name')}': {assessment.get('score')}/100"
            )
            return assessment
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error(f"[QualificationAgent] Failed to parse response: {e}")
            return {
                "score": 0,
                "reasoning": "Failed to parse AI response",
                "recommended_channel": prospect_data.get("source_channel", "email"),
                "personalization_hints": [],
                "disqualification_reason": "Parse error",
                "recommended_approach": "Manual review required",
                "fit_breakdown": {
                    "company_fit": 0,
                    "role_fit": 0,
                    "problem_fit": 0,
                    "engagement_signals": 0,
                },
            }

    async def batch_qualify(self, prospects: list[dict], icp: dict) -> list[dict]:
        results = []
        for prospect in prospects:
            assessment = await self.qualify_prospect(prospect, icp)
            results.append({
                "prospect": prospect,
                "assessment": assessment,
            })
        return results
