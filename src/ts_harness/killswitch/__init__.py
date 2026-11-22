"""Kill switch management for global, workflow, and connector scopes."""

from ts_harness.killswitch.manager import (
    KillSwitchActiveError,
    KillSwitchManager,
    KillSwitchState,
)

__all__ = [
    "KillSwitchActiveError",
    "KillSwitchManager",
    "KillSwitchState",
]
