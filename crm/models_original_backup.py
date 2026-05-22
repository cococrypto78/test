import enum
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, Boolean,
    ForeignKey, Enum, JSON, func
)
from sqlalchemy.orm import relationship
from .database import Base


class ProspectStatus(str, enum.Enum):
    DISCOVERED = "discovered"
    CONTACTED = "contacted"
    RESPONDING = "responding"
    QUALIFIED = "qualified"
    CONVERTED = "converted"
    REJECTED = "rejected"
    HANDOFF = "handoff"


class InteractionDirection(str, enum.Enum):
    INBOUND = "in"
    OUTBOUND = "out"


class HandoffUrgency(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Prospect(Base):
    __tablename__ = "prospects"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True, index=True)
    phone = Column(String(50), nullable=True)
    company = Column(String(255), nullable=True)
    title = Column(String(255), nullable=True)
    linkedin_url = Column(String(500), nullable=True, unique=True)
    twitter_handle = Column(String(100), nullable=True, unique=True)
    instagram_handle = Column(String(100), nullable=True, unique=True)
    tiktok_handle = Column(String(100), nullable=True, unique=True)
    source_channel = Column(String(50), nullable=False)
    status = Column(Enum(ProspectStatus), default=ProspectStatus.DISCOVERED, nullable=False, index=True)
    score = Column(Float, default=0.0)
    qualification_data = Column(JSON, nullable=True)
    sentiment = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    last_interaction = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    interactions = relationship("Interaction", back_populates="prospect", cascade="all, delete-orphan")
    agent_logs = relationship("AgentLog", back_populates="prospect")
    handoffs = relationship("HumanHandoff", back_populates="prospect", cascade="all, delete-orphan")


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    target_icp = Column(JSON, nullable=False)
    channels = Column(JSON, nullable=False, default=list)
    is_active = Column(Boolean, default=True, nullable=False)
    product_description = Column(Text, nullable=True)
    value_proposition = Column(Text, nullable=True)
    target_outcome = Column(String(255), nullable=True, default="Book a discovery call")
    min_qualification_score = Column(Integer, default=50)
    daily_limit = Column(Integer, default=50)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    interactions = relationship("Interaction", back_populates="campaign")


class Interaction(Base):
    __tablename__ = "interactions"

    id = Column(Integer, primary_key=True, index=True)
    prospect_id = Column(Integer, ForeignKey("prospects.id"), nullable=False, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    channel = Column(String(50), nullable=False)
    direction = Column(Enum(InteractionDirection), nullable=False)
    content = Column(Text, nullable=False)
    sentiment_score = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=func.now(), nullable=False)

    prospect = relationship("Prospect", back_populates="interactions")
    campaign = relationship("Campaign", back_populates="interactions")


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id = Column(Integer, primary_key=True, index=True)
    agent_name = Column(String(100), nullable=False)
    action = Column(String(255), nullable=False)
    prospect_id = Column(Integer, ForeignKey("prospects.id"), nullable=True)
    details = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=func.now(), nullable=False)

    prospect = relationship("Prospect", back_populates="agent_logs")


class HumanHandoff(Base):
    __tablename__ = "human_handoffs"

    id = Column(Integer, primary_key=True, index=True)
    prospect_id = Column(Integer, ForeignKey("prospects.id"), nullable=False, index=True)
    reason = Column(Text, nullable=False)
    urgency = Column(Enum(HandoffUrgency), default=HandoffUrgency.MEDIUM, nullable=False)
    notified_at = Column(DateTime, default=func.now(), nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    prospect = relationship("Prospect", back_populates="handoffs")
