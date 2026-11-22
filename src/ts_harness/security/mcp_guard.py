"""MCP server allowlist with pinned versions and tool-description scanning."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ts_harness.guardrails.injection import InjectionScanResult, detect_injection_signals


class McpServerEntry(BaseModel):
    """Allowlisted MCP server with a pinned version."""

    name: str
    pinned_version: str
    allowed_tools: list[str] = Field(default_factory=list)


class McpServerAllowlist(BaseModel):
    """Deny-by-default allowlist for MCP servers and their tools."""

    servers: dict[str, McpServerEntry] = Field(default_factory=dict)

    def is_allowed(
        self,
        server_name: str,
        version: str,
        tool_name: str,
    ) -> tuple[bool, str]:
        """Verify server allowlist membership, pinned version, and tool name."""
        entry = self.servers.get(server_name)
        if entry is None:
            return False, f"MCP server '{server_name}' is not in the allowlist."
        if entry.pinned_version != version:
            return (
                False,
                f"MCP server '{server_name}' version '{version}' does not match "
                f"pinned version '{entry.pinned_version}'.",
            )
        if tool_name not in entry.allowed_tools:
            return (
                False,
                f"Tool '{tool_name}' is not allowlisted for MCP server '{server_name}'.",
            )
        return True, "MCP server and tool allowlisted."


def scan_tool_description(description: str) -> InjectionScanResult:
    """Scan an MCP tool description for hidden prompt-injection instructions."""
    result = detect_injection_signals(description)
    signals = list(result.matched_signals)
    if len(description) > 2000:
        signals.append("excessive_description_length")
    return InjectionScanResult(suspicious=len(signals) > 0, matched_signals=signals)
