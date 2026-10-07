"""Shared normal-entry window invariant for schemas and persisted exam state."""

from datetime import datetime


def validate_normal_entry_window(
    scheduled_start_at: datetime | None,
    latest_normal_start_at: datetime | None,
) -> None:
    if latest_normal_start_at is None:
        return
    if scheduled_start_at is None:
        raise ValueError("latest_normal_start_at requires scheduled_start_at")
    if latest_normal_start_at <= scheduled_start_at:
        raise ValueError(
            "Normal entry deadline must be later than the scheduled start. "
            "Equal times leave no time for candidates to enter without late-start "
            "authorization. Choose a later deadline or leave it unset."
        )
