from __future__ import annotations

from datetime import UTC, datetime


COC_TIME_FORMAT = "%Y%m%dT%H%M%S.000Z"


def parse_coc_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, COC_TIME_FORMAT).replace(tzinfo=UTC)


def utcnow() -> datetime:
    return datetime.now(tz=UTC)
