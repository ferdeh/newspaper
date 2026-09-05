from __future__ import annotations

from typing import Any

from app.models import MasterTbbm


def runtime_tbbm_conditions() -> tuple[Any, ...]:
    """Canonical SQL predicates for TBBM records allowed in operational reads."""
    return (
        MasterTbbm.deleted_at.is_(None),
        MasterTbbm.verification_status == "VERIFIED",
    )


def verified_tbbm(row: MasterTbbm | None) -> MasterTbbm | None:
    """Hide deleted or unverified records even when a historical FK still points to one."""
    if row and row.deleted_at is None and row.verification_status == "VERIFIED":
        return row
    return None
