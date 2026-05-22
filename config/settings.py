from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    # AI
    anthropic_api_key: str = ""
    claude_drafting_model: str = "claude-sonnet-4-6"
    claude_classification_model: str = "claude-haiku-4-5-20251001"
    claude_max_tokens: int = 4096

    # Database
    database_url: str = "postgresql+psycopg2://sales_agent:changeme@localhost:5432/sales_agent_prod"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Twitter/X — API officielle v2 uniquement
    x_api_bearer_token: str = ""
    x_api_key: str = ""
    x_api_secret: str = ""
    x_access_token: str = ""
    x_access_token_secret: str = ""

    # Instagram — Meta Graph API uniquement (compte Business requis)
    meta_graph_access_token: str = ""
    meta_page_id: str = ""
    instagram_business_account_id: str = ""

    # Email — Postmark uniquement
    postmark_server_token: str = ""
    email_sending_domain: str = ""

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # API Security
    secret_key: str = "change-me-in-production-32chars!!"
    access_token_expire_minutes: int = 60 * 24

    # Monitoring
    sentry_dsn: str = ""

    # Backup — Scaleway Object Storage
    scw_access_key: str = ""
    scw_secret_key: str = ""
    scw_bucket_name: str = ""
    scw_region: str = "fr-par"

    # Rate limits
    max_daily_messages_per_tenant: int = 100

    # App
    app_env: str = "production"
    log_level: str = "INFO"
    api_port: int = 8000

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}


settings = Settings()
