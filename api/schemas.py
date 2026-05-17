from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, EmailStr


class ProspectCreate(BaseModel):
    full_name: str
    email: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    linkedin_url: Optional[str] = None
    twitter_handle: Optional[str] = None
    instagram_handle: Optional[str] = None
    tiktok_handle: Optional[str] = None
    source_channel: str
    notes: Optional[str] = None


class ProspectOut(BaseModel):
    id: int
    full_name: str
    email: Optional[str]
    company: Optional[str]
    title: Optional[str]
    source_channel: str
    status: str
    score: Optional[int]
    linkedin_url: Optional[str]
    twitter_handle: Optional[str]
    instagram_handle: Optional[str]
    tiktok_handle: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class CampaignCreate(BaseModel):
    name: str
    product_description: str
    value_proposition: str
    target_outcome: str = "Book a discovery call"
    target_icp: dict
    channels: list[str]
    daily_limit: int = 20
    min_qualification_score: int = 50


class CampaignOut(BaseModel):
    id: int
    name: str
    is_active: bool
    channels: list[str]
    daily_limit: int
    created_at: datetime

    class Config:
        from_attributes = True


class InteractionOut(BaseModel):
    id: int
    channel: str
    direction: str
    content: str
    sentiment_score: Optional[float]
    timestamp: datetime

    class Config:
        from_attributes = True


class HandoffOut(BaseModel):
    id: int
    prospect_id: int
    reason: str
    urgency: str
    notified_at: datetime
    resolved_at: Optional[datetime]
    prospect: Optional[ProspectOut]

    class Config:
        from_attributes = True


class HandoffResolve(BaseModel):
    notes: str = ""


class AgentRunRequest(BaseModel):
    campaign_id: Optional[int] = None


class StatsOut(BaseModel):
    discovered: int
    qualified: int
    contacted: int
    responding: int
    handoff: int
    rejected: int
    converted: int
    response_rate: float
    avg_score: float


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    username: str
    password: str
