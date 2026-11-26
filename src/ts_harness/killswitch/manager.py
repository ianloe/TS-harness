"""Kill switch manager checked before every node and tool execution."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ts_harness.audit.logger import AuditLogger
from ts_harness.db.models import KillSwitchRecord

GLOBAL_SCOPE = "global"


class KillSwitchActiveError(RuntimeError):
    """Raised when execution is blocked by an active kill switch."""


class KillSwitchState(BaseModel):
    """Representation of a kill switch entry."""

    scope: str
    active: bool
    reason: str
    activated_by: str
    activated_at: datetime
    deactivated_at: datetime | None = None


class KillSwitchManager:
    """Manages global, workflow, and connector kill switches."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        audit_logger: AuditLogger,
    ) -> None:
        self._session_factory = session_factory
        self._audit = audit_logger

    def pause_all(self, reason: str, actor: str = "cli") -> KillSwitchState:
        """Activate the global kill switch."""
        return self._activate(GLOBAL_SCOPE, reason, actor)

    def resume_all(self, actor: str = "cli") -> KillSwitchState | None:
        """Deactivate the global kill switch."""
        return self._deactivate(GLOBAL_SCOPE, actor)

    def pause_workflow(
        self, workflow_name: str, reason: str, actor: str = "cli"
    ) -> KillSwitchState:
        """Pause a specific workflow."""
        return self._activate(f"workflow:{workflow_name}", reason, actor)

    def resume_workflow(self, workflow_name: str, actor: str = "cli") -> KillSwitchState | None:
        """Resume a specific workflow."""
        return self._deactivate(f"workflow:{workflow_name}", actor)

    def revoke_connector(
        self, connector_name: str, reason: str, actor: str = "cli"
    ) -> KillSwitchState:
        """Revoke access for a specific connector."""
        return self._activate(f"connector:{connector_name}", reason, actor)

    def restore_connector(
        self, connector_name: str, actor: str = "cli"
    ) -> KillSwitchState | None:
        """Restore access for a specific connector."""
        return self._deactivate(f"connector:{connector_name}", actor)

    def is_blocked(
        self,
        *,
        workflow_name: str | None = None,
        connector_name: str | None = None,
    ) -> tuple[bool, str | None]:
        """Check whether global, workflow, or connector kill switch is active."""
        scopes = [GLOBAL_SCOPE]
        if workflow_name is not None:
            scopes.append(f"workflow:{workflow_name}")
        if connector_name is not None:
            scopes.append(f"connector:{connector_name}")

        with self._session_factory() as session:
            stmt = select(KillSwitchRecord).where(
                KillSwitchRecord.scope.in_(scopes),
                KillSwitchRecord.active.is_(True),
            )
            record = session.scalar(stmt)
            if record is not None:
                return True, f"Kill switch active for '{record.scope}': {record.reason}"
        return False, None

    def list_states(self, *, active_only: bool = True) -> list[KillSwitchState]:
        """List kill switch states."""
        with self._session_factory() as session:
            stmt = select(KillSwitchRecord).order_by(KillSwitchRecord.activated_at.desc())
            if active_only:
                stmt = stmt.where(KillSwitchRecord.active.is_(True))
            return [self._to_state(r) for r in session.scalars(stmt).all()]

    def _activate(self, scope: str, reason: str, actor: str) -> KillSwitchState:
        now = datetime.now(UTC)
        with self._session_factory() as session:
            record = session.scalar(
                select(KillSwitchRecord).where(KillSwitchRecord.scope == scope)
            )
            if record is None:
                record = KillSwitchRecord(
                    id=str(uuid.uuid4()),
                    scope=scope,
                    active=True,
                    reason=reason,
                    activated_by=actor,
                    activated_at=now,
                    deactivated_at=None,
                )
                session.add(record)
            else:
                record.active = True
                record.reason = reason
                record.activated_by = actor
                record.activated_at = now
                record.deactivated_at = None
            session.commit()
            session.refresh(record)
            state = self._to_state(record)

        self._audit.append(
            event_type="killswitch.activated",
            actor=actor,
            payload={"scope": scope, "reason": reason},
        )
        return state

    def _deactivate(self, scope: str, actor: str) -> KillSwitchState | None:
        now = datetime.now(UTC)
        with self._session_factory() as session:
            record = session.scalar(
                select(KillSwitchRecord).where(KillSwitchRecord.scope == scope)
            )
            if record is None or not record.active:
                return None
            record.active = False
            record.deactivated_at = now
            session.commit()
            session.refresh(record)
            state = self._to_state(record)

        self._audit.append(
            event_type="killswitch.deactivated",
            actor=actor,
            payload={"scope": scope},
        )
        return state

    @staticmethod
    def _to_state(record: KillSwitchRecord) -> KillSwitchState:
        return KillSwitchState(
            scope=record.scope,
            active=record.active,
            reason=record.reason,
            activated_by=record.activated_by,
            activated_at=record.activated_at,
            deactivated_at=record.deactivated_at,
        )
