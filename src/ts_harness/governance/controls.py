"""FRAME and AAEF control mapping loader."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ControlMapping(BaseModel):
    """Maps a TS-Harness control to configurable FRAME and AAEF control IDs."""

    control_id: str
    name: str
    module: str
    description: str
    frame_id: str = Field(default="FRAME-PLACEHOLDER")
    aaef_id: str = Field(default="AAEF-PLACEHOLDER")


def load_control_mappings(path: Path) -> list[ControlMapping]:
    """Load and validate FRAME/AAEF control mappings from YAML."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = raw.get("controls", [])
    return [ControlMapping(**item) for item in items]
