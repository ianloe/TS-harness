"""User preferences supporting style rules, paper size, and currency."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from ts_harness.config import Currency


class UserPreferences(BaseModel):
    """Durable user style and formatting preferences."""

    language: Literal["en-GB"] = Field(default="en-GB")
    no_em_dashes: bool = Field(default=True)
    word_page_size: Literal["A4"] = Field(default="A4")
    currency: Currency = Field(default="SGD")
    working_hours_utc: str = Field(default="01:00-10:00")

    @classmethod
    def from_yaml(cls, path: Path) -> UserPreferences:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(**raw)

    def to_yaml(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        dumped = yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False)
        path.write_text(dumped, encoding="utf-8")
