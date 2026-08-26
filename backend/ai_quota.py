"""Atomic account quota consumption shared by every model-backed workflow."""

from __future__ import annotations

import hashlib
import threading

from sqlalchemy import text
from sqlalchemy.orm import Session

from auth import check_rate_limit
from models import UsageLog, User


_LOCK = threading.Lock()
# "JH" namespace keeps this transaction lock distinct from other advisory-lock users.
AI_QUOTA_ADVISORY_LOCK_NAMESPACE = 0x4A480000


def consume_ai_credit(
    user: User,
    db: Session,
    detail: str,
    *,
    operation_key: str | None = None,
    commit: bool = True,
) -> bool:
    """Consume one daily credit, or reuse the receipt for one logical operation.

    ``operation_key`` is intentionally hashed before persistence: idempotency
    keys are transport credentials, not analytics labels. The account-scoped
    database lock makes the lookup and insert atomic across application workers;
    the process lock provides the equivalent boundary for SQLite and tests.
    """

    receipt_detail = detail
    if operation_key:
        digest = hashlib.sha256(operation_key.encode()).hexdigest()
        receipt_detail = f"{detail}:{digest}"

    with _LOCK:
        try:
            if db.get_bind().dialect.name == "postgresql":
                db.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": AI_QUOTA_ADVISORY_LOCK_NAMESPACE + user.id},
                )
            if operation_key and (
                db.query(UsageLog.id)
                .filter(
                    UsageLog.user_id == user.id,
                    UsageLog.action == "ai",
                    UsageLog.detail == receipt_detail,
                )
                .first()
                is not None
            ):
                if commit:
                    # Release the PostgreSQL transaction-scoped advisory lock
                    # before handing this session back to the workflow.
                    db.commit()
                return False
            check_rate_limit(user, "ai", db)
            db.add(UsageLog(user_id=user.id, action="ai", detail=receipt_detail))
            if commit:
                db.commit()
            else:
                # Let the caller commit the credit together with the durable
                # running operation it admits.
                db.flush()
            return True
        except Exception:
            db.rollback()
            raise
