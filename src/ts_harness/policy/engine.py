"""Policy engine with deny-by-default evaluation, dry-run, and explain mode."""

from __future__ import annotations

from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field

from ts_harness.core.models import RiskTier
from ts_harness.gateway.gateway import ExecutionContext, PolicyDecision
from ts_harness.guardrails.injection import TrustLevel, can_trigger_action
from ts_harness.policy.schema import PolicyRule, PolicySet, RuleEffect
from ts_harness.risk.tiers import is_forbidden


class RuleEvaluationTrace(BaseModel):
    """Trace of a single rule during policy explanation."""

    rule_id: str
    effect: RuleEffect
    matched: bool
    reasons: list[str] = Field(default_factory=list)


class PolicyExplanation(BaseModel):
    """Detailed explanation answering why a tool call was allowed or blocked."""

    decision: PolicyDecision
    policy_name: str
    policy_version: str
    dry_run: bool = True
    summary: str
    traces: list[RuleEvaluationTrace] = Field(default_factory=list)


class PolicyEngine:
    """Evaluates every tool call against versioned YAML rules and hard safety invariants."""

    def __init__(self, policy_set: PolicySet) -> None:
        self._policy_set = policy_set

    @classmethod
    def from_yaml(cls, path: Path) -> PolicyEngine:
        """Load and schema-validate a YAML policy file."""
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        policy_set = PolicySet(**raw)
        return cls(policy_set)

    @property
    def policy_set(self) -> PolicySet:
        return self._policy_set

    def evaluate(
        self,
        tool_name: str,
        risk_tier: RiskTier,
        args: dict[str, Any],
        context: ExecutionContext,
        *,
        now: datetime | None = None,
    ) -> PolicyDecision:
        """Evaluate whether a tool invocation is allowed."""
        return self.explain(tool_name, risk_tier, args, context, now=now, dry_run=False).decision

    def explain(
        self,
        tool_name: str,
        risk_tier: RiskTier,
        args: dict[str, Any],
        context: ExecutionContext,
        *,
        now: datetime | None = None,
        dry_run: bool = True,
    ) -> PolicyExplanation:
        """Evaluate a tool call and return a full explanation trace."""
        category = str(args.get("category") or context.metadata.get("category") or "")
        if is_forbidden(risk_tier, category or None):
            decision = PolicyDecision(
                allowed=False,
                reason=f"T3 forbidden action ({risk_tier.value}); cannot be overridden by policy.",
                rule_id="invariant-t3-forbidden",
            )
            return PolicyExplanation(
                decision=decision,
                policy_name=self._policy_set.name,
                policy_version=self._policy_set.version,
                dry_run=dry_run,
                summary=decision.reason,
            )

        approved = bool(context.metadata.get("approved", False))
        trust_levels = self._extract_trust_levels(context)
        trust_ok, trust_reason = can_trigger_action(risk_tier, trust_levels, approved=approved)
        if not trust_ok:
            decision = PolicyDecision(
                allowed=False,
                reason=trust_reason,
                rule_id="invariant-untrusted-provenance",
            )
            return PolicyExplanation(
                decision=decision,
                policy_name=self._policy_set.name,
                policy_version=self._policy_set.version,
                dry_run=dry_run,
                summary=trust_reason,
            )

        current_time = now or datetime.now(UTC)
        traces: list[RuleEvaluationTrace] = []
        matched_rule: PolicyRule | None = None

        for rule in self._policy_set.rules:
            matched, reasons = self._match_rule(
                rule, tool_name, risk_tier, args, context, current_time
            )
            traces.append(
                RuleEvaluationTrace(
                    rule_id=rule.id,
                    effect=rule.effect,
                    matched=matched,
                    reasons=reasons,
                )
            )
            if matched and matched_rule is None:
                matched_rule = rule

        if matched_rule is None:
            decision = PolicyDecision(
                allowed=False,
                reason=(
                    f"Deny by default: no rule in '{self._policy_set.name}' "
                    f"matched '{tool_name}'."
                ),
                rule_id="default-deny",
            )
            return PolicyExplanation(
                decision=decision,
                policy_name=self._policy_set.name,
                policy_version=self._policy_set.version,
                dry_run=dry_run,
                summary=decision.reason,
                traces=traces,
            )

        if matched_rule.effect == RuleEffect.DENY:
            decision = PolicyDecision(
                allowed=False,
                reason=f"Denied by rule '{matched_rule.id}': {matched_rule.description}",
                rule_id=matched_rule.id,
            )
        elif matched_rule.effect == RuleEffect.REQUIRE_APPROVAL or (
            risk_tier == RiskTier.T2 and not approved
        ):
            decision = PolicyDecision(
                allowed=approved,
                reason=(
                    f"Approved for rule '{matched_rule.id}'."
                    if approved
                    else f"Human approval required by rule '{matched_rule.id}' ({risk_tier.value})."
                ),
                rule_id=matched_rule.id,
            )
        else:
            decision = PolicyDecision(
                allowed=True,
                reason=f"Allowed by rule '{matched_rule.id}': {matched_rule.description}",
                rule_id=matched_rule.id,
            )

        return PolicyExplanation(
            decision=decision,
            policy_name=self._policy_set.name,
            policy_version=self._policy_set.version,
            dry_run=dry_run,
            summary=decision.reason,
            traces=traces,
        )

    @staticmethod
    def _extract_trust_levels(context: ExecutionContext) -> list[TrustLevel]:
        raw_list = context.metadata.get("triggering_trust_levels")
        if isinstance(raw_list, list) and raw_list:
            return [TrustLevel(str(item)) for item in raw_list]
        return [TrustLevel(context.trust_level)]

    def _match_rule(
        self,
        rule: PolicyRule,
        tool_name: str,
        risk_tier: RiskTier,
        args: dict[str, Any],
        context: ExecutionContext,
        now: datetime,
    ) -> tuple[bool, list[str]]:
        m = rule.match
        mismatches: list[str] = []

        if not any(fnmatch(tool_name, pat) for pat in m.tools):
            mismatches.append(f"tool '{tool_name}' not in {m.tools}")

        if m.action_tiers is not None and risk_tier not in m.action_tiers:
            allowed_tiers = [t.value for t in m.action_tiers]
            mismatches.append(f"tier '{risk_tier.value}' not in {allowed_tiers}")

        if m.data_classes is not None and context.data_class not in m.data_classes:
            allowed_classes = [d.value for d in m.data_classes]
            mismatches.append(
                f"data_class '{context.data_class.value}' not in {allowed_classes}"
            )

        if m.trust_levels is not None:
            try:
                tl = TrustLevel(context.trust_level)
            except ValueError:
                tl = TrustLevel.UNTRUSTED_EXTERNAL
            if tl not in m.trust_levels:
                allowed_trust = [t.value for t in m.trust_levels]
                mismatches.append(f"trust_level '{tl.value}' not in {allowed_trust}")

        if m.resource_scopes is not None:
            resource = str(
                args.get("resource")
                or args.get("path")
                or args.get("folder")
                or args.get("mailbox")
                or ""
            )
            if not resource or not any(fnmatch(resource, pat) for pat in m.resource_scopes):
                mismatches.append(f"resource '{resource}' did not match {m.resource_scopes}")

        if m.recipients_or_domains is not None:
            target = self._extract_recipient_or_domain(args)
            if not target or not any(fnmatch(target, pat) for pat in m.recipients_or_domains):
                mismatches.append(
                    f"recipient/domain '{target}' did not match {m.recipients_or_domains}"
                )

        if m.max_amount is not None:
            raw_amt = args.get("amount", 0.0)
            amount = float(raw_amt) if isinstance(raw_amt, (int, float)) else 0.0
            if amount > m.max_amount:
                mismatches.append(f"amount {amount} exceeds max_amount {m.max_amount}")

        if m.time_window is not None:
            tw = m.time_window
            if now.weekday() not in tw.days_of_week:
                mismatches.append(f"weekday {now.weekday()} outside {tw.days_of_week}")
            if not self._hour_in_window(now.hour, tw.start_hour_utc, tw.end_hour_utc):
                mismatches.append(
                    f"hour {now.hour} UTC outside {tw.start_hour_utc}-{tw.end_hour_utc}"
                )

        if mismatches:
            return False, mismatches
        return True, ["all dimensions matched"]

    @staticmethod
    def _extract_recipient_or_domain(args: dict[str, Any]) -> str:
        raw = str(
            args.get("recipient")
            or args.get("to")
            or args.get("domain")
            or args.get("url")
            or ""
        ).strip()
        if raw.startswith("http://") or raw.startswith("https://"):
            return urlparse(raw).netloc.lower()
        return raw.lower()

    @staticmethod
    def _hour_in_window(hour: int, start: int, end: int) -> bool:
        if start <= end:
            return start <= hour <= end
        return hour >= start or hour <= end
