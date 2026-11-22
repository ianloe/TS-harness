"""Provider-agnostic model client interface and stub adapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel

from ts_harness.config import Currency, ModelRoleConfig
from ts_harness.guardrails.filters import redact_pii_and_secrets


class ModelMessage(BaseModel):
    """A single message in a model prompt."""

    role: str
    content: str


class ModelResponse(BaseModel):
    """Normalised response from any model provider."""

    content: str
    model_name: str
    provider: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_amount: float = 0.0
    currency: Currency = "SGD"


class ModelClient(Protocol):
    """Provider-agnostic model completion interface."""

    def complete(
        self,
        messages: list[ModelMessage],
        *,
        role_config: ModelRoleConfig,
        system_prompt: str | None = None,
    ) -> ModelResponse:
        """Execute a completion using the configured role model."""
        ...


class StubModelClient:
    """Deterministic model client for offline runs, tests, and stubbed providers."""

    def __init__(
        self,
        responder: Callable[[list[ModelMessage], ModelRoleConfig, str | None], str] | None = None,
        currency: Currency = "SGD",
    ) -> None:
        self._responder = responder
        self._currency: Currency = currency
        self.calls: list[dict[str, object]] = []

    def complete(
        self,
        messages: list[ModelMessage],
        *,
        role_config: ModelRoleConfig,
        system_prompt: str | None = None,
    ) -> ModelResponse:
        # Redact PII and secrets before any model call leaves the harness boundary.
        safe_messages = [
            ModelMessage(role=m.role, content=redact_pii_and_secrets(m.content).text)
            for m in messages
        ]
        self.calls.append(
            {
                "provider": role_config.provider,
                "model_name": role_config.model_name,
                "messages": [m.model_dump() for m in safe_messages],
            }
        )
        if self._responder is not None:
            text = self._responder(safe_messages, role_config, system_prompt)
        else:
            last_user = safe_messages[-1].content if safe_messages else ""
            text = f"[{role_config.provider}:{role_config.model_name}] {last_user[:120]}"

        tokens_in = sum(max(1, len(m.content.split())) for m in safe_messages)
        tokens_out = max(1, len(text.split()))
        return ModelResponse(
            content=text,
            model_name=role_config.model_name,
            provider=role_config.provider,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_amount=0.001,
            currency=self._currency,
        )
