"""Declarative directed-graph workflow schemas."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class NodeType(StrEnum):
    """Supported workflow graph node types."""

    PLAN = "plan"
    ACT = "act"
    VERIFY = "verify"
    APPROVE = "approve"
    BRANCH = "branch"
    LOOP = "loop"
    END = "end"


class LoopPolicy(BaseModel):
    """Mandatory bounds for any loop node."""

    max_iterations: int = Field(default=5, ge=1, le=50)
    timeout_seconds: float = Field(default=120.0, gt=0.0)
    max_cost: float = Field(default=1.0, ge=0.0)
    no_progress_threshold: int = Field(default=3, ge=2, le=10)


class GraphEdge(BaseModel):
    """Directed edge with an optional branch condition key."""

    source: str
    target: str
    condition: str | None = None


class GraphNode(BaseModel):
    """A single node in a workflow graph."""

    id: str
    node_type: NodeType
    handler_name: str | None = None
    loop_policy: LoopPolicy | None = None
    approval_summary: str | None = None


class WorkflowGraph(BaseModel):
    """Explicit directed graph defining a workflow."""

    name: str
    version: str = "1.0.0"
    entry_node: str
    draft_only: bool = True
    nodes: dict[str, GraphNode]
    edges: list[GraphEdge] = Field(default_factory=list)

    def next_target(self, node_id: str, branch_key: str | None = None) -> str | None:
        """Resolve the next node ID from outgoing edges."""
        candidates = [e for e in self.edges if e.source == node_id]
        if branch_key is not None:
            for edge in candidates:
                if edge.condition == branch_key:
                    return edge.target
        for edge in candidates:
            if edge.condition is None:
                return edge.target
        return candidates[0].target if candidates else None
