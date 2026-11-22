"""Tests for the task router and data-class model filtering."""

from __future__ import annotations

from ts_harness.config import ModelRoleConfig, ModelsConfig
from ts_harness.core.models import DataClass, RiskTier
from ts_harness.router.router import TaskRouter


def test_router_classifies_workflows_and_enforces_data_class_providers() -> None:
    models = ModelsConfig(
        planner=ModelRoleConfig(provider="openai", model_name="gpt-4o"),
        executor=ModelRoleConfig(provider="anthropic", model_name="claude-sonnet-4-20250514"),
        verifier=ModelRoleConfig(provider="gemini", model_name="gemini-2.5-flash"),
    )
    router = TaskRouter(models=models, currency="SGD")

    email_cls = router.classify("Triage my morning inbox and draft replies")
    assert email_cls.workflow_name == "inbox_triage"
    assert email_cls.risk_tier == RiskTier.T1
    assert email_cls.data_class == DataClass.PERSONAL
    # Personal data class only allows anthropic/ollama, so openai/gemini fall back to anthropic
    assert email_cls.models.planner.provider == "anthropic"
    assert email_cls.models.verifier.provider == "anthropic"

    research_cls = router.classify("Research recent AI safety papers on the web")
    assert research_cls.workflow_name == "research_digest"
    assert research_cls.data_class == DataClass.PUBLIC
    assert research_cls.models.planner.provider == "openai"

    forbidden_cls = router.classify("Make a wire transfer payment of 500 SGD")
    assert forbidden_cls.risk_tier == RiskTier.T3
