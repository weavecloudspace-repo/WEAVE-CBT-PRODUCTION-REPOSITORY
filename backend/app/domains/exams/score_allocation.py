"""Score-allocation validation for hybrid WEAVE assessment components."""

from __future__ import annotations

from decimal import Decimal

from app.core.exceptions import AcademicScopeError


def resolved_cbt_allocation(component, chosen: Decimal | None) -> Decimal:
    """Return effective CBT marks. Draft None always preserves full-CBT behavior."""
    maximum = Decimal(component.maximum_score)
    if chosen is None:
        return maximum
    if chosen <= 0 or chosen > maximum:
        raise AcademicScopeError(
            f"CBT marks must be greater than zero and no more than {maximum}."
        )
    if chosen < maximum and not getattr(component, "is_hybrid", False):
        raise AcademicScopeError(
            "Only hybrid-examinable assessment components can reserve theory marks."
        )
    return chosen
