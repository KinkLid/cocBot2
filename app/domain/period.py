from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class PeriodRange:
    start: datetime
    end: datetime
    label: str
