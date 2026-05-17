import json
from .base_agent import BaseAgent
from utils.logger import logger

OUTREACH_SYSTEM_PROMPT = """You are an expert B2B sales copywriter specializing in cold outreach.
You write messages that feel genuinely human, personalized, and non-spammy.

Core principles:
- Lead with value, not product pitches
- Reference something specific about the prospect (recent post, company news, shared interest)
- Keep it short: LinkedIn/DM under 150 words, email under 200 words
- One clear CTA (call-to-action) — never multiple asks
- No exclamation marks, no "I hope this message finds you well"
- Sound like a peer, not a salesperson

Channel-specific tone:
- LinkedIn: Professional but warm, focus on shared industry context
- Twitter/X: Casual, reference a tweet or thread they wrote
- Instagram: Conversational, reference their content/brand aesthetic
- TikTok: Very casual, reference their videos or niche
- Email: Structured with subject line, slightly more formal but still personal

Always return a JSON object:
{
  "subject": "<email subject or null>",
  "body": "<message body>",
  "variant_b": "<alternative version for A/B testing>",
  "tone": "<tone used>",
  "hook": "<what personalization hook was used>"
}
"""


class OutreachAgent(BaseAgent):
    def __init__(self):
        super().__init__("OutreachAgent")

    async def draft_message(
        self,
        prospect: dict,
        campaign: dict,
        channel: str,
    ) -> dict:
        user_message = f"""
## Channel: {channel}

## Prospect Profile
{json.dumps(prospect, indent=2)}

## Campaign Context
Product/Service: {campaign.get("product_description", "N/A")}
Value Proposition: {campaign.get("value_proposition", "N/A")}
Target Outcome: {campaign.get("target_outcome", "Book a discovery call")}
Personalization Hints: {json.dumps(prospect.get("personalization_hints", []))}

Write a {channel} outreach message for this prospect.
Use the personalization hints to make it feel custom-written for them specifically.
"""
        result = await self.think(
            system_prompt=OUTREACH_SYSTEM_PROMPT,
            user_message=user_message,
            temperature=0.8,
        )

        try:
            text = result["text"].strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            message = json.loads(text)
            logger.info(
                f"[OutreachAgent] Drafted {channel} message for '{prospect.get('full_name')}'"
            )
            return message
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error(f"[OutreachAgent] Failed to parse response: {e}")
            return {
                "subject": None,
                "body": result.get("text", ""),
                "variant_b": "",
                "tone": "unknown",
                "hook": "none",
            }

    async def draft_bulk(
        self,
        prospects: list[dict],
        campaign: dict,
        channel: str,
    ) -> list[dict]:
        results = []
        for prospect in prospects:
            draft = await self.draft_message(prospect, campaign, channel)
            results.append({"prospect_id": prospect.get("id"), "draft": draft})
        return results
