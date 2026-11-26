"""YAML workflow definition loader with budget, scope contract, and risk tier."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from ts_harness.core.models import DataClass, RiskTier
from ts_harness.graph.schema import WorkflowGraph
from ts_harness.security.classification import ScopeContract


class WorkflowDefinition(BaseModel):
    """Declarative workflow metadata, budget, scope contract, and graph."""

    name: str
    version: str = "1.0.0"
    draft_only: bool = True
    risk_tier: RiskTier = RiskTier.T0
    data_class: DataClass = DataClass.INTERNAL
    budget_limit: float = Field(default=1.0, gt=0.0)
    scope_contract: ScopeContract = Field(default_factory=ScopeContract)
    graph: WorkflowGraph


def load_workflow_definition(path: Path) -> WorkflowDefinition:
    """Load and validate a declarative workflow YAML file."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return WorkflowDefinition(**raw)
