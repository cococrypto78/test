"""
Schéma multi-tenant. Toutes les tables (sauf tenants) ont tenant_id non-null
avec un index obligatoire. Aucune query ne doit omettre le filtre tenant_id.
"""
import enum
import uuid

from sqlalchemy import (
    Column, String, Text, DateTime, Boolean, Integer, Float,
    ForeignKey, Enum as SAEnum, JSON, Index, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from .database import Base


# ── Enums ─────────────────────────────────────────────────────────────────────

class ChannelEnum(str, enum.Enum):
    email = "email"
    linkedin = "linkedin"
    twitter = "twitter"
    instagram = "instagram"
    tiktok = "tiktok"


class MessageStatus(str, enum.Enum):
    drafted = "drafted"
    approved = "approved"
    sent = "sent"
    failed = "failed"
    replied = "replied"
    skipped = "skipped"


class CredentialStatus(str, enum.Enum):
    connected = "connected"
    disconnected = "disconnected"
    error = "error"


class TenantPlan(str, enum.Enum):
    starter = "starter"
    growth = "growth"
    pro = "pro"
    enterprise = "enterprise"


class TenantStatus(str, enum.Enum):
    active = "active"
    suspended = "suspended"
    trial = "trial"
    cancelled = "cancelled"


class UserRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"


# ── Core ──────────────────────────────────────────────────────────────────────

class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    stripe_customer_id = Column(String(255), nullable=True, index=True)
    plan = Column(SAEnum(TenantPlan), default=TenantPlan.starter, nullable=False)
    status = Column(SAEnum(TenantStatus), default=TenantStatus.trial, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    voice_profile = relationship("VoiceProfile", back_populates="tenant", uselist=False, cascade="all, delete-orphan")
    prospects = relationship("Prospect", back_populates="tenant", cascade="all, delete-orphan")
    campaigns = relationship("Campaign", back_populates="tenant", cascade="all, delete-orphan")
    channel_credentials = relationship("ChannelCredential", back_populates="tenant", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(SAEnum(UserRole), default=UserRole.member, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    tenant = relationship("Tenant", back_populates="users")

    __table_args__ = (
        Index("ix_users_tenant_id", "tenant_id"),
        Index("ix_users_tenant_email", "tenant_id", "email", unique=True),
    )


# ── Voice / Persona ───────────────────────────────────────────────────────────

class VoiceProfile(Base):
    __tablename__ = "voice_profiles"

    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    founder_name = Column(String(255), nullable=False)
    tone = Column(String(100), nullable=True)
    signature = Column(Text, nullable=True)
    taboo_phrases = Column(JSON, nullable=True, default=list)
    target_outcome = Column(String(255), nullable=True)
    style_notes = Column(Text, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    tenant = relationship("Tenant", back_populates="voice_profile")


class VoiceExample(Base):
    __tablename__ = "voice_examples"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    channel = Column(SAEnum(ChannelEnum), nullable=False)
    context_summary = Column(Text, nullable=True)
    final_text = Column(Text, nullable=False)
    refreshed_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_voice_examples_tenant_channel_refreshed", "tenant_id", "channel", "refreshed_at"),
    )


class VoiceEmbedding(Base):
    __tablename__ = "voice_embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=True)
    embedding = Column(Vector(1536), nullable=False)
    context = Column(Text, nullable=True)

    message = relationship("Message", back_populates="embeddings")

    __table_args__ = (
        Index("ix_voice_embeddings_tenant_id", "tenant_id"),
    )


# ── Prospects & Campaigns ─────────────────────────────────────────────────────

class Prospect(Base):
    __tablename__ = "prospects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    title = Column(String(255), nullable=True)
    company = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    linkedin_url = Column(String(500), nullable=True)
    twitter_handle = Column(String(100), nullable=True)
    instagram_handle = Column(String(100), nullable=True)
    tiktok_handle = Column(String(100), nullable=True)
    score = Column(Float, default=0.0)
    status = Column(String(50), default="discovered", nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    tenant = relationship("Tenant", back_populates="prospects")
    messages = relationship("Message", back_populates="prospect")

    __table_args__ = (
        Index("ix_prospects_tenant_id", "tenant_id"),
    )


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    icp_config = Column(JSON, nullable=True, default=dict)
    sequence = Column(JSON, nullable=True, default=list)
    status = Column(String(50), default="draft", nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    tenant = relationship("Tenant", back_populates="campaigns")
    messages = relationship("Message", back_populates="campaign")

    __table_args__ = (
        Index("ix_campaigns_tenant_id", "tenant_id"),
    )


# ── Messages & Interactions ───────────────────────────────────────────────────

class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    prospect_id = Column(UUID(as_uuid=True), ForeignKey("prospects.id", ondelete="CASCADE"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True)
    channel = Column(SAEnum(ChannelEnum), nullable=False)
    status = Column(SAEnum(MessageStatus), default=MessageStatus.drafted, nullable=False)
    draft_text = Column(Text, nullable=True)
    final_text = Column(Text, nullable=True)
    edit_count = Column(Integer, default=0, nullable=False)
    sent_at = Column(DateTime, nullable=True)
    reply_received_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    tenant = relationship("Tenant")
    prospect = relationship("Prospect", back_populates="messages")
    campaign = relationship("Campaign", back_populates="messages")
    edits = relationship("Edit", back_populates="message", cascade="all, delete-orphan")
    replies = relationship("Reply", back_populates="message", cascade="all, delete-orphan")
    embeddings = relationship("VoiceEmbedding", back_populates="message")

    __table_args__ = (
        Index("ix_messages_tenant_status", "tenant_id", "status"),
        Index("ix_messages_tenant_id", "tenant_id"),
    )


class Edit(Base):
    __tablename__ = "edits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    before = Column(Text, nullable=False)
    after = Column(Text, nullable=False)
    edit_type = Column(String(50), nullable=True)
    ts = Column(DateTime, server_default=func.now(), nullable=False)

    message = relationship("Message", back_populates="edits")

    __table_args__ = (
        Index("ix_edits_tenant_id", "tenant_id"),
    )


class Reply(Base):
    __tablename__ = "replies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    classified_intent = Column(String(100), nullable=True)
    confidence = Column(Float, nullable=True)
    received_at = Column(DateTime, server_default=func.now(), nullable=False)

    message = relationship("Message", back_populates="replies")

    __table_args__ = (
        Index("ix_replies_tenant_id", "tenant_id"),
    )


# ── Observabilité & Coûts ─────────────────────────────────────────────────────

class ApiUsage(Base):
    __tablename__ = "api_usage"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    model = Column(String(100), nullable=False)
    tokens_in = Column(Integer, default=0, nullable=False)
    tokens_out = Column(Integer, default=0, nullable=False)
    cost_usd = Column(Float, default=0.0, nullable=False)
    ts = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_api_usage_tenant_id", "tenant_id"),
    )


# ── Credentials canaux ────────────────────────────────────────────────────────

class ChannelCredential(Base):
    __tablename__ = "channel_credentials"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    channel = Column(SAEnum(ChannelEnum), nullable=False)
    status = Column(SAEnum(CredentialStatus), default=CredentialStatus.disconnected, nullable=False)
    config = Column(JSON, nullable=True, default=dict)
    connected_at = Column(DateTime, nullable=True)

    tenant = relationship("Tenant", back_populates="channel_credentials")

    __table_args__ = (
        Index("ix_channel_credentials_tenant_id", "tenant_id"),
        Index("ix_channel_credentials_tenant_channel", "tenant_id", "channel", unique=True),
    )
