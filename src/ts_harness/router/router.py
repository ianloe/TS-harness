"""Task classification and workflow/model routing."""

from __future__ import annotations

from pydantic import BaseModel

from ts_harness.config import Currency, ModelRoleConfig, ModelsConfig
from ts_harness.core.models import DataClass, RiskTier
from ts_harness.security.classification import DataClassificationPolicy


class TaskClassification(BaseModel):
    """Classification output used to select workflow, risk tier, and models."""

    task_type: str
    workflow_name: str
    risk_tier: RiskTier
    data_class: DataClass
    estimated_cost: float
    currency: Currency
    models: ModelsConfig


_WORKFLOW_KEYWORDS: tuple[tuple[str, str, tuple[str, ...], RiskTier, DataClass, float], ...] = (
    (
        "email_triage",
        "inbox_triage",
        ("email", "inbox", "triage", "reply", "mail"),
        RiskTier.T1,
        DataClass.PERSONAL,
        0.08,
    ),
    (
        "meeting_prep",
        "meeting_prep",
        ("meeting", "calendar", "agenda", "brief", "prep"),
        RiskTier.T0,
        DataClass.INTERNAL,
        0.10,
    ),
    (
        "research_digest",
        "research_digest",
        ("research", "digest", "search", "paper", "article", "web"),
        RiskTier.T0,
        DataClass.PUBLIC,
        0.15,
    ),
    (
        "weekly_review",
        "weekly_review",
        ("weekly", "review", "spend", "summary", "report"),
        RiskTier.T0,
        DataClass.INTERNAL,
        0.12,
    ),
    (
        "document_draft",
        "document_draft",
        ("draft", "document", "memo", "write", "note"),
        RiskTier.T1,
        DataClass.INTERNAL,
        0.10,
    ),
)

_FORBIDDEN_KEYWORDS = ("pay ", "payment", "wire transfer", "trade ", "buy stock", "password")


class TaskRouter:
    """Classifies tasks by type, risk tier, data class, and estimated cost."""

    def __init__(
        self,
        *,
        models: ModelsConfig,
        currency: Currency = "SGD",
        classification_policy: DataClassificationPolicy | None = None,
    ) -> None:
        self._models = models
        self._currency: Currency = currency
        self._policy = classification_policy or DataClassificationPolicy()

    def classify(
        self,
        description: str,
        *,
        data_class: DataClass | None = None,
        risk_tier: RiskTier | None = None,
    ) -> TaskClassification:
        """Classify a natural-language task request."""
        lower = description.lower()

        if any(kw in lower for kw in _FORBIDDEN_KEYWORDS):
            resolved_tier = RiskTier.T3
            task_type = "forbidden"
            workflow_name = "blocked"
            resolved_data = data_class or DataClass.CONFIDENTIAL
            est_cost = 0.0
        else:
            task_type = "general"
            workflow_name = "general"
            resolved_tier = risk_tier or RiskTier.T0
            resolved_data = data_class or DataClass.INTERNAL
            est_cost = 0.05
            for t_type, wf_name, keywords, default_tier, default_data, cost in _WORKFLOW_KEYWORDS:
                if any(kw in lower for kw in keywords):
                    task_type = t_type
                    workflow_name = wf_name
                    resolved_tier = risk_tier or default_tier
                    resolved_data = data_class or default_data
                    est_cost = cost
                    break

        routed_models = self._filter_models_for_data_class(resolved_data)
        return TaskClassification(
            task_type=task_type,
            workflow_name=workflow_name,
            risk_tier=resolved_tier,
            data_class=resolved_data,
            estimated_cost=est_cost,
            currency=self._currency,
            models=routed_models,
        )

    def _filter_models_for_data_class(self, data_class: DataClass) -> ModelsConfig:
        """Ensure every role model provider is allowed for ``data_class``."""
        def _safe_role(role_cfg: ModelRoleConfig) -> ModelRoleConfig:
            if self._policy.is_provider_allowed(data_class, role_cfg.provider):
                return role_cfg
            # Fall back to anthropic (default allowed for confidential/personal)
            return ModelRoleConfig(
                provider="anthropic",
                model_name="claude-sonnet-4-20250514",
                temperature=role_cfg.temperature,
                max_tokens=role_cfg.max_tokens,
            )

        return ModelsConfig(
            planner=_safe_role(self._models.planner),
            executor=_safe_role(self._models.executor),
            verifier=_safe_role(self._models.verifier),
        )
