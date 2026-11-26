"""Configuration schemas, loader, and YAML persistence for TS-harness."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Currency = Literal["SGD", "USD"]
ModelProvider = Literal[
    "anthropic",
    "openai",
    "gemini",
    "ollama",
    "openrouter",
    "agnes-ai",
    "deepseek",
]
SUPPORTED_CURRENCIES: tuple[str, ...] = ("SGD", "USD")


class DatabaseConfig(BaseModel):
    """Database connection configuration."""

    url: str = Field(default="sqlite:///ts_harness.db")
    echo: bool = Field(default=False)


class BudgetConfig(BaseModel):
    """FinOps budget limits and thresholds in SGD or USD."""

    currency: Currency = Field(default="SGD")
    task_limit: float = Field(default=2.0, gt=0.0)
    workflow_limit: float = Field(default=10.0, gt=0.0)
    daily_limit: float = Field(default=25.0, gt=0.0)
    monthly_limit: float = Field(default=200.0, gt=0.0)
    soft_limit_pct: float = Field(default=0.75, gt=0.0, le=1.0)
    hard_limit_pct: float = Field(default=1.0, gt=0.0, le=1.0)
    preflight_approval_threshold: float = Field(default=1.0, ge=0.0)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if value not in SUPPORTED_CURRENCIES:
            raise ValueError(f"Unsupported currency '{value}'. Allowed: SGD, USD.")
        return value


class ModelRoleConfig(BaseModel):
    """Model configuration for a specific agent role."""

    provider: ModelProvider = Field(default="anthropic")
    model_name: str = Field(default="claude-sonnet-4-20250514", min_length=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=128, le=200000)


class ModelsConfig(BaseModel):
    """Role-based model routing configuration (never hard-coded in agents)."""

    planner: ModelRoleConfig = Field(
        default_factory=lambda: ModelRoleConfig(
            provider="anthropic",
            model_name="claude-sonnet-4-20250514",
            temperature=0.0,
            max_tokens=4096,
        )
    )
    executor: ModelRoleConfig = Field(
        default_factory=lambda: ModelRoleConfig(
            provider="anthropic",
            model_name="claude-sonnet-4-20250514",
            temperature=0.0,
            max_tokens=4096,
        )
    )
    verifier: ModelRoleConfig = Field(
        default_factory=lambda: ModelRoleConfig(
            provider="anthropic",
            model_name="claude-haiku-4-5-20251001",
            temperature=0.0,
            max_tokens=2048,
        )
    )


class TelemetryConfig(BaseModel):
    """Optional OpenTelemetry and Aegis export configuration."""

    enabled: bool = Field(default=False)
    service_name: str = Field(default="ts-harness")
    aegis_export_url: str | None = Field(default=None)

    @field_validator("aegis_export_url")
    @classmethod
    def validate_export_url(cls, value: str | None) -> str | None:
        if value is not None and not (
            value.startswith("https://") or value.startswith("http://")
        ):
            raise ValueError("aegis_export_url must start with http:// or https://")
        return value


class LoggingConfig(BaseModel):
    """Structured logging configuration."""

    level: str = Field(default="INFO")
    json_format: bool = Field(default=True)


class Settings(BaseSettings):
    """Top-level application settings (secrets are never stored here)."""

    model_config = SettingsConfigDict(
        env_prefix="TS_HARNESS_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    environment: str = Field(default="development")
    data_dir: str = Field(default=".ts_harness_data")
    db: DatabaseConfig = Field(default_factory=DatabaseConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def resolve_config_path(config_path: Path | None = None) -> Path | None:
    """Resolve explicit config path or TS_HARNESS_CONFIG_PATH env var."""
    if config_path is not None:
        return config_path
    env_path = os.environ.get("TS_HARNESS_CONFIG_PATH")
    if env_path:
        return Path(env_path)
    return None


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from optional YAML file and environment variables."""
    resolved = resolve_config_path(config_path)
    if resolved is not None and resolved.exists():
        raw: dict[str, Any] = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
        return Settings(**raw)
    return Settings()


def save_settings(settings: Settings, config_path: Path) -> None:
    """Persist non-secret settings to a YAML file."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = settings.model_dump(mode="json")
    config_path.write_text(
        yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
