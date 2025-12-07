"""
Configuration for Infra AI Telegram Bot.
"""

import os
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings
from typing import Optional
from enum import Enum


class DiscoveryMode(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Settings(BaseSettings):
    """Bot configuration."""

    # Telegram (required)
    telegram_bot_token: str = Field(..., description="Telegram Bot API token")

    # Whitelist (empty = allow all)
    allowed_user_ids: list[int] = Field(default_factory=list)

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def parse_user_ids(cls, v):
        """Parse user IDs from string (comma-separated) or list."""
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            if not v or v.strip() == "":
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return []

    # Dashboard
    dashboard_refresh_interval: int = Field(default=30)

    # Discovery
    discovery_mode: DiscoveryMode = Field(default=DiscoveryMode.AUTO)

    # Gateway (optional)
    gateway_url: str = Field(default="http://localhost:8080")
    gateway_token: Optional[str] = Field(default=None)

    # Alert settings
    alert_min_level: AlertLevel = Field(default=AlertLevel.WARNING)
    alert_cooldown: int = Field(default=300)  # seconds
    alert_grouping: bool = Field(default=True)

    # 2FA
    twofa_enabled: bool = Field(default=True)
    twofa_timeout: int = Field(default=300)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Load settings
try:
    settings = Settings()
except Exception as e:
    print(f"Config error: {e}")
    print("Make sure .env file exists with TELEGRAM_BOT_TOKEN")
    raise
