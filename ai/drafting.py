"""
Orchestration du drafting de messages via Claude.
- claude-sonnet-4-6 pour le drafting
- claude-haiku-4-5-20251001 pour la classification/qualification
- Prompt caching sur le system prompt (Anthropic cache_control)
- Logging dans api_usage pour l'observabilité des coûts
"""
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ai.training import build_system_prompt, get_few_shot_examples, get_similar_examples
from crm.models import ApiUsage, ChannelEnum
from config.settings import settings
from utils.logger import logger


# Coût approximatif en USD par 1M tokens (Sonnet 4.6)
COST_PER_1M_INPUT = 3.0
COST_PER_1M_OUTPUT = 15.0


async def draft_message(
    tenant_id: str,
    prospect,
    channel: str,
    campaign_context: str,
    session: AsyncSession,
    examples_count: int = 0,
) -> str:
    """
    Drafte un message de prospection pour le canal donné.
    Retourne le texte du message drafté.
    """
    from anthropic import Anthropic
    client = Anthropic(api_key=settings.anthropic_api_key)

    system_block = await build_system_prompt(tenant_id, session)
    few_shot = await get_few_shot_examples(tenant_id, channel, session)
    similar = []
    if examples_count > 200:
        prospect_summary = f"{getattr(prospect, 'name', '')} - {getattr(prospect, 'title', '')} at {getattr(prospect, 'company', '')}"
        similar = await get_similar_examples(tenant_id, prospect_summary, channel, session)

    channel_instructions = _channel_instructions(channel)

    user_content = (
        f"Write a {channel} prospecting message for this prospect:\n"
        f"Name: {getattr(prospect, 'name', 'Unknown')}\n"
        f"Title: {getattr(prospect, 'title', '')}\n"
        f"Company: {getattr(prospect, 'company', '')}\n"
        f"Campaign context: {campaign_context}\n\n"
        f"{channel_instructions}\n\n"
        f"Write ONLY the message text, no preamble."
    )

    messages = [*few_shot, *similar, {"role": "user", "content": user_content}]

    try:
        response = client.messages.create(
            model=settings.claude_drafting_model,
            max_tokens=settings.claude_max_tokens,
            system=[system_block],
            messages=messages,
        )

        draft = response.content[0].text if response.content else ""

        # Log token usage
        usage = response.usage
        tokens_in = usage.input_tokens
        tokens_out = usage.output_tokens
        cost = (tokens_in / 1_000_000 * COST_PER_1M_INPUT) + (tokens_out / 1_000_000 * COST_PER_1M_OUTPUT)

        log = ApiUsage(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            model=settings.claude_drafting_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            ts=datetime.utcnow(),
        )
        session.add(log)
        await session.commit()

        logger.info(f"[Drafting] tenant={tenant_id} channel={channel} tokens_in={tokens_in} tokens_out={tokens_out} cost=${cost:.4f}")
        return draft

    except Exception as e:
        logger.error(f"[Drafting] Claude API error: {e}")
        raise


async def classify_reply(
    tenant_id: str,
    reply_text: str,
    session: AsyncSession,
) -> tuple[str, float]:
    """
    Classifie une réponse avec Haiku (rapide et économique).
    Retourne (intent, confidence).
    """
    from anthropic import Anthropic
    client = Anthropic(api_key=settings.anthropic_api_key)

    try:
        response = client.messages.create(
            model=settings.claude_classification_model,
            max_tokens=50,
            messages=[{
                "role": "user",
                "content": (
                    f"Classify this reply intent in ONE word from: "
                    f"[interested, not_interested, question, meeting_request, referral, unsubscribe, out_of_office, other].\n\n"
                    f"Reply: {reply_text[:500]}\n\n"
                    f"Respond with JSON: {{\"intent\": \"word\", \"confidence\": 0.0-1.0}}"
                ),
            }],
        )

        import json
        text = response.content[0].text if response.content else "{}"
        data = json.loads(text)
        intent = data.get("intent", "other")
        confidence = float(data.get("confidence", 0.5))

        # Log usage
        usage = response.usage
        cost = (usage.input_tokens / 1_000_000 * 0.25) + (usage.output_tokens / 1_000_000 * 1.25)
        log = ApiUsage(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            model=settings.claude_classification_model,
            tokens_in=usage.input_tokens,
            tokens_out=usage.output_tokens,
            cost_usd=cost,
            ts=datetime.utcnow(),
        )
        session.add(log)
        await session.commit()

        return intent, confidence

    except Exception as e:
        logger.warning(f"[Classify] Error: {e}")
        return "other", 0.5


def _channel_instructions(channel: str) -> str:
    instructions = {
        "email": "Email format: start with Subject: line. Keep under 150 words. Professional but warm.",
        "linkedin": "LinkedIn DM: under 300 characters. No jargon. Connect first, pitch second.",
        "twitter": "Twitter DM: under 280 characters. Casual, specific, no spam vibes.",
        "instagram": "Instagram DM: under 200 characters. Friendly, genuine, specific to their content.",
        "tiktok": "TikTok DM: under 150 characters. Very casual, reference their content specifically.",
    }
    return instructions.get(channel, "Keep it concise and personalized.")
