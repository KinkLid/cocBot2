from __future__ import annotations

from datetime import UTC, datetime


COC_TIME_FORMAT = "%Y%m%dT%H%M%S.000Z"


def parse_coc_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, COC_TIME_FORMAT).replace(tzinfo=UTC)


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def normalize_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime, treating persisted naive values as UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
