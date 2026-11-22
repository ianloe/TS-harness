"""Provider-agnostic model client interface and stub adapter."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel

from ts_harness.config import Currency, ModelRoleConfig
from ts_harness.guardrails.filters import redact_pii_and_secrets
from ts_harness.security.vault import SecretsVault


class ModelProviderError(RuntimeError):
    """Raised when an upstream LLM provider returns an HTTP or API error."""


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


_PROVIDER_SECRET_KEY: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "agnes-ai": "AGNES_AI_API_KEY",
}

_OPENAI_COMPAT_ENDPOINTS: dict[str, str] = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
}


class VaultModelClient:
    """Provider-agnostic live model client reading API keys from SecretsVault."""

    def __init__(self, vault: SecretsVault, currency: Currency = "SGD") -> None:
        self._vault = vault
        self._currency: Currency = currency
        self._stub = StubModelClient(currency=currency)

    def complete(
        self,
        messages: list[ModelMessage],
        *,
        role_config: ModelRoleConfig,
        system_prompt: str | None = None,
    ) -> ModelResponse:
        safe_messages = [
            ModelMessage(role=m.role, content=redact_pii_and_secrets(m.content).text)
            for m in messages
        ]
        secret_key = _PROVIDER_SECRET_KEY.get(role_config.provider)
        api_key = self._vault.get_secret(secret_key) if secret_key else None
        if not api_key:
            return self._stub.complete(
                safe_messages, role_config=role_config, system_prompt=system_prompt
            )

        if role_config.provider == "anthropic":
            return self._call_anthropic(api_key, safe_messages, role_config, system_prompt)
        if role_config.provider in _OPENAI_COMPAT_ENDPOINTS:
            return self._call_openai_compat(
                _OPENAI_COMPAT_ENDPOINTS[role_config.provider],
                api_key,
                safe_messages,
                role_config,
                system_prompt,
            )
        if role_config.provider == "gemini":
            return self._call_gemini(api_key, safe_messages, role_config, system_prompt)
        return self._stub.complete(
            safe_messages, role_config=role_config, system_prompt=system_prompt
        )

    def _call_anthropic(
        self,
        api_key: str,
        messages: list[ModelMessage],
        role_config: ModelRoleConfig,
        system_prompt: str | None,
    ) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": role_config.model_name,
            "max_tokens": role_config.max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if system_prompt:
            payload["system"] = system_prompt
        data = self._post_json(
            "https://api.anthropic.com/v1/messages",
            payload,
            {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        content_blocks = data.get("content", [])
        text = "\n".join(
            str(b.get("text", "")) for b in content_blocks if isinstance(b, dict)
        ).strip()
        usage = data.get("usage", {})
        return ModelResponse(
            content=text or "(empty response)",
            model_name=role_config.model_name,
            provider=role_config.provider,
            tokens_in=int(usage.get("input_tokens", 0)),
            tokens_out=int(usage.get("output_tokens", 0)),
            cost_amount=0.002,
            currency=self._currency,
        )

    def _call_openai_compat(
        self,
        url: str,
        api_key: str,
        messages: list[ModelMessage],
        role_config: ModelRoleConfig,
        system_prompt: str | None,
    ) -> ModelResponse:
        msgs: list[dict[str, str]] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.extend({"role": m.role, "content": m.content} for m in messages)
        payload = {
            "model": role_config.model_name,
            "temperature": role_config.temperature,
            "max_tokens": role_config.max_tokens,
            "messages": msgs,
        }
        data = self._post_json(url, payload, {"Authorization": f"Bearer {api_key}"})
        choices = data.get("choices", [])
        text = str(choices[0]["message"]["content"]) if choices else "(empty response)"
        usage = data.get("usage", {})
        return ModelResponse(
            content=text,
            model_name=role_config.model_name,
            provider=role_config.provider,
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
            cost_amount=0.002,
            currency=self._currency,
        )

    def _call_gemini(
        self,
        api_key: str,
        messages: list[ModelMessage],
        role_config: ModelRoleConfig,
        system_prompt: str | None,
    ) -> ModelResponse:
        prompt = "\n".join(m.content for m in messages)
        if system_prompt:
            prompt = f"{system_prompt}\n\n{prompt}"
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{role_config.model_name}:generateContent?key={api_key}"
        )
        data = self._post_json(
            url,
            {"contents": [{"parts": [{"text": prompt}]}]},
            {},
        )
        candidates = data.get("candidates", [])
        text = (
            str(candidates[0]["content"]["parts"][0]["text"])
            if candidates
            else "(empty response)"
        )
        return ModelResponse(
            content=text,
            model_name=role_config.model_name,
            provider=role_config.provider,
            cost_amount=0.002,
            currency=self._currency,
        )

    @staticmethod
    def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                result: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                return result
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise ModelProviderError(
                f"Provider returned HTTP {exc.code}: {err_body[:300]}"
            ) from exc
