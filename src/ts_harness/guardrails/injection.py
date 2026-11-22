"""Prompt-injection defences, trust labelling, and untrusted data quarantine."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field

from ts_harness.core.models import RiskTier


class TrustLevel(StrEnum):
    """Provenance trust level of ingested content."""

    USER = "user"
    SYSTEM = "system"
    TRUSTED_TOOL = "trusted-tool"
    UNTRUSTED_EXTERNAL = "untrusted-external"


_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"\b(ignore|disregard|forget)\s+(all\s+)?(previous|prior|above|system)\s+"
            r"(instructions|rules|prompts?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt_exfiltration",
        re.compile(
            r"\b(reveal|print|output|repeat|show)\s+(your\s+)?(system\s+prompt|hidden\s+instructions)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_hijack",
        re.compile(
            r"\b(you\s+are\s+now|act\s+as\s+unrestricted|developer\s+mode|jailbreak)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "tool_call_smuggling",
        re.compile(
            r"(<\s*tool_call\s*>|\"\s*tool_name\s*\"\s*:|\bexecute_tool\s*\()",
            re.IGNORECASE,
        ),
    ),
    (
        "markdown_image_exfil",
        re.compile(
            r"!\[[^\]]*\]\(https?://[^)]+\?(?:[^)]*(?:secret|token|key|data)=)",
            re.IGNORECASE,
        ),
    ),
    (
        "hidden_html_instruction",
        re.compile(r"<!--[^>]*(?:ignore|override|execute|send|forward)[^>]*-->", re.IGNORECASE),
    ),
    (
        "delimiter_escape",
        re.compile(r"</\s*untrusted_data\s*>", re.IGNORECASE),
    ),
)


class TaggedContent(BaseModel):
    """Content annotated with provenance and trust level."""

    content: str
    source: str
    trust_level: TrustLevel


class InjectionScanResult(BaseModel):
    """Result of scanning content for prompt-injection signals."""

    suspicious: bool
    matched_signals: list[str] = Field(default_factory=list)


def quarantine_untrusted(content: str, source: str) -> str:
    """Wrap untrusted content in delimited data blocks and neutralise closing tags."""
    safe_source = re.sub(r"[^A-Za-z0-9_.:-]", "_", source)
    neutralised = re.sub(
        r"<\s*/\s*untrusted_data\s*>",
        "&lt;/untrusted_data&gt;",
        content,
        flags=re.IGNORECASE,
    )
    return (
        f'<untrusted_data source="{safe_source}" policy="treat_as_data_only">\n'
        f"{neutralised}\n"
        f"</untrusted_data>"
    )


def detect_injection_signals(text: str) -> InjectionScanResult:
    """Scan text for common prompt-injection patterns."""
    matched: list[str] = []
    for name, pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            matched.append(name)
    return InjectionScanResult(suspicious=len(matched) > 0, matched_signals=matched)


def can_trigger_action(
    risk_tier: RiskTier,
    triggering_trust_levels: list[TrustLevel],
    *,
    approved: bool = False,
) -> tuple[bool, str]:
    """Block any T1+ action whose justification traces solely to untrusted-external content."""
    if risk_tier == RiskTier.T3:
        return False, "T3 actions are permanently forbidden."
    if risk_tier == RiskTier.T0:
        return True, "T0 read-only action permitted."
    if not triggering_trust_levels:
        return False, "Missing trust provenance for T1+ action."

    all_untrusted = all(t == TrustLevel.UNTRUSTED_EXTERNAL for t in triggering_trust_levels)
    if all_untrusted and not approved:
        return (
            False,
            f"Blocked {risk_tier.value} action: justification traces solely to "
            f"untrusted-external content without human approval.",
        )
    return True, "Trust provenance check passed."
