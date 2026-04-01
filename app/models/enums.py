from __future__ import annotations

import enum


class WarType(str, enum.Enum):
    REGULAR = "regular"
    CWL = "cwl"


class WarState(str, enum.Enum):
    PREPARATION = "preparation"
    IN_WAR = "in_war"
    WAR_ENDED = "war_ended"
    NOT_IN_WAR = "not_in_war"


class ViolationCode(str, enum.Enum):
    ABOVE_SELF = "above_self"
    TOO_LOW = "too_low"


class PeriodKind(str, enum.Enum):
    CURRENT_CYCLE = "current_cycle"
    PREVIOUS_CYCLE = "previous_cycle"
    CUSTOM = "custom"
