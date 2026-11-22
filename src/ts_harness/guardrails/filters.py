"""Input and output filters for PII/secret redaction, URLs, and style rules."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_or_anthropic_key", re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b")),
    ("github_pat", re.compile(r"\bghp_[A-Za-z0-9]{10,}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{10,}\b", re.IGNORECASE)),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
)

_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("nric_fin", re.compile(r"\b[STFGM]\d{7}[A-Z]\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("credit_card", re.compile(r"\b(?:\d[ -]*?){13,16}\b")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
)

_URL_PATTERN = re.compile(r"https?://[^\s)\]>\"']+")

_US_SPELLING_HINTS: tuple[tuple[str, str], ...] = (
    ("summarize", "summarise"),
    ("summarized", "summarised"),
    ("organization", "organisation"),
    ("analyze", "analyse"),
    ("color", "colour"),
    ("behavior", "behaviour"),
)


class RedactionResult(BaseModel):
    """Result of redacting secrets and PII from text."""

    text: str
    redacted_categories: list[str] = Field(default_factory=list)


class OutputCheckResult(BaseModel):
    """Result of output guardrail checks."""

    passed: bool
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    ungrounded_urls: list[str] = Field(default_factory=list)


def redact_pii_and_secrets(text: str, *, redact_pii: bool = True) -> RedactionResult:
    """Redact secrets and optionally PII before sending content to a model."""
    masked = text
    categories: list[str] = []

    for name, pattern in _SECRET_PATTERNS:
        if pattern.search(masked):
            categories.append(name)
            masked = pattern.sub(f"[REDACTED:{name}]", masked)

    if redact_pii:
        for name, pattern in _PII_PATTERNS:
            if pattern.search(masked):
                categories.append(name)
                masked = pattern.sub(f"[REDACTED:{name}]", masked)

    return RedactionResult(text=masked, redacted_categories=categories)


def check_output(
    text: str,
    *,
    allowed_urls: set[str] | None = None,
    check_style: bool = True,
) -> OutputCheckResult:
    """Check model output for secret leakage, hallucinated URLs, and style rules."""
    violations: list[str] = []
    warnings: list[str] = []
    ungrounded_urls: list[str] = []

    for name, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            violations.append(f"Secret leakage detected ({name}).")

    if allowed_urls is not None:
        found_urls = _URL_PATTERN.findall(text)
        for url in found_urls:
            cleaned = url.rstrip(".,;:")
            if cleaned not in allowed_urls:
                ungrounded_urls.append(cleaned)
        if ungrounded_urls:
            violations.append(
                f"Ungrounded or hallucinated URLs detected: {', '.join(ungrounded_urls)}"
            )

    if check_style:
        if "\u2014" in text:
            warnings.append("Style violation: em dash detected.")
        lower_text = text.lower()
        for us_word, uk_word in _US_SPELLING_HINTS:
            if re.search(rf"\b{us_word}\b", lower_text):
                warnings.append(
                    f"Style warning: use British English '{uk_word}' instead of '{us_word}'."
                )

    return OutputCheckResult(
        passed=len(violations) == 0,
        violations=violations,
        warnings=warnings,
        ungrounded_urls=ungrounded_urls,
    )
