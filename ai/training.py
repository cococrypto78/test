"""
Couches d'entraînement IA multi-tenant.
Couche 1 : system prompt statique avec prompt caching Anthropic (cache_control).
Couche 2 : top 10 exemples approuvés des 30 derniers jours.
Couche 3 : pgvector retrieval (activé si tenant.examples_count > 200).
"""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from crm.models import VoiceProfile, VoiceExample, VoiceEmbedding, ChannelEnum
from utils.logger import logger


async def build_system_prompt(tenant_id: str, session: AsyncSession) -> dict:
    """Couche 1 : persona statique. cache_control=ephemeral activé pour Anthropic caching."""
    result = await session.execute(
        select(VoiceProfile).where(VoiceProfile.tenant_id == tenant_id)
    )
    profile = result.scalar_one_or_none()

    if not profile:
        text = (
            "You are a professional sales outreach assistant. "
            "Write personalized, authentic prospecting messages. "
            "Be concise, human, and focus on value for the recipient."
        )
    else:
        taboo = ", ".join(profile.taboo_phrases or []) or "none"
        text = f"""You are the AI writing assistant for {profile.founder_name}.

PERSONA:
- Tone: {profile.tone or 'professional and direct'}
- Target outcome: {profile.target_outcome or 'book a discovery call'}
- Signature style: {profile.signature or ''}
- Style notes: {profile.style_notes or ''}

RULES:
- NEVER use these phrases: {taboo}
- Write as {profile.founder_name}, not as an AI
- Be personalized, concise, and human
- Focus on value for the recipient, not on the sender"""

    return {
        "type": "text",
        "text": text,
        "cache_control": {"type": "ephemeral"},
    }


async def get_few_shot_examples(
    tenant_id: str, channel: str, session: AsyncSession, limit: int = 10
) -> list[dict]:
    """Couche 2 : top exemples approuvés des 30 derniers jours."""
    cutoff = datetime.utcnow() - timedelta(days=30)
    try:
        channel_enum = ChannelEnum(channel)
    except ValueError:
        logger.warning(f"[AI] Unknown channel '{channel}', using email")
        channel_enum = ChannelEnum.email

    result = await session.execute(
        select(VoiceExample)
        .where(
            VoiceExample.tenant_id == tenant_id,
            VoiceExample.channel == channel_enum,
            VoiceExample.refreshed_at >= cutoff,
        )
        .order_by(desc(VoiceExample.refreshed_at))
        .limit(limit)
    )
    examples = result.scalars().all()

    return [
        {"role": "assistant", "content": ex.final_text}
        for ex in examples
    ]


async def get_similar_examples(
    tenant_id: str,
    prospect_summary: str,
    channel: str,
    session: AsyncSession,
    k: int = 3,
) -> list[dict]:
    """Couche 3 : pgvector retrieval. Activé uniquement si examples_count > 200."""
    from pgvector.sqlalchemy import Vector
    from sqlalchemy import func, cast

    try:
        from anthropic import Anthropic
        from config.settings import settings
        client = Anthropic(api_key=settings.anthropic_api_key)
        embed_resp = client.messages.create(
            model=settings.claude_classification_model,
            max_tokens=10,
            messages=[{"role": "user", "content": f"embed: {prospect_summary[:500]}"}],
        )
        # Anthropic doesn't have embeddings API; use a stub zero vector for now
        # In production, use an embedding model (OpenAI text-embedding-3-small or similar)
        query_vec = [0.0] * 1536
    except Exception as e:
        logger.warning(f"[AI] Embedding generation failed: {e}")
        return []

    try:
        result = await session.execute(
            select(VoiceEmbedding)
            .where(VoiceEmbedding.tenant_id == tenant_id)
            .order_by(VoiceEmbedding.embedding.cosine_distance(query_vec))
            .limit(k)
        )
        embeddings = result.scalars().all()
        return [
            {"role": "assistant", "content": emb.context or ""}
            for emb in embeddings if emb.context
        ]
    except Exception as e:
        logger.warning(f"[AI] pgvector retrieval failed: {e}")
        return []
