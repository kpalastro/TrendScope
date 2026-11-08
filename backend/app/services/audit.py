"""Append-only audit trail for mutating requests.

Routes call :func:`record` with the domain action they performed. The helper
never stores credentials, request bodies or provider payloads: only the actor,
the action, the entity, a small JSON diff and the request id. Audit failures are
logged but never turn a successful mutation into an error.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.errors import request_id as request_id_from
from app.models import AuditLog, User

logger = logging.getLogger("trendscope.audit")


def record(
    db: Session,
    *,
    action: str,
    entity_type: str,
    user: User | None = None,
    entity_id: Any | None = None,
    changes: dict[str, Any] | None = None,
    request: Request | None = None,
    commit: bool = True,
) -> AuditLog | None:
    try:
        entry = AuditLog(
            user_id=user.id if user is not None else None,
            action=action[:80],
            entity_type=entity_type[:60],
            entity_id=str(entity_id)[:80] if entity_id is not None else None,
            changes=_json_safe(changes or {}),
            ip=(request.client.host if request is not None and request.client else None),
            request_id=request_id_from(request) if request is not None else None,
        )
        db.add(entry)
        if commit:
            db.commit()
        return entry
    except Exception:  # noqa: BLE001 - auditing must not break the request
        logger.exception("Failed to record audit entry %s on %s", action, entity_type)
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, UUID):
        return str(value)
    return str(value)
