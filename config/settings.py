from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional, List
import os


class Settings(BaseSettings):
    # AI
    anthropic_api_key: str
    claude_model: str = "claude-sonnet-4-5"
    claude_max_tokens: int = 4096

    # Database
    database_url: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # LinkedIn
    linkedin_email: str = ""
    linkedin_password: str = ""

    # Twitter/X
    twitter_api_key: str = ""
    twitter_api_secret: str = ""
    twitter_access_token: str = ""
    twitter_access_secret: str = ""
    twitter_bearer_token: str = ""

    # Instagram
    instagram_username: str = ""
    instagram_password: str = ""
    instagram_session_file: str = "instagram_session.json"

    # TikTok
    tiktok_username: str = ""
    tiktok_password: str = ""

    # Email / SMTP
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_from_name: str = "Sales Team"

    # API Auth
    api_username: str = "admin"
    api_password_hash: str = "$2b$12$dummy.hash.change.in.production"

    # Notifications
    human_alert_email: str = ""
    webhook_url: Optional[str] = None

    # API Security
    secret_key: str = "change-me-in-production-32chars!!"
    access_token_expire_minutes: int = 60 * 24

    # Proxies
    proxy_list: str = ""

    # Rate limits
    max_daily_connections_linkedin: int = 20
    max_daily_dms_instagram: int = 50
    max_daily_dms_twitter: int = 100
    max_daily_emails: int = 200
    max_daily_dms_tiktok: int = 30

    # App
    app_env: str = "production"
    log_level: str = "INFO"
    api_port: int = 8000

    @property
    def proxies(self) -> List[str]:
        if not self.proxy_list:
            return []
        return [p.strip() for p in self.proxy_list.split(",") if p.strip()]

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}


settings = Settings()
