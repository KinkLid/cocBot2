from __future__ import annotations

from pathlib import Path

from app.models.enums import ViolationCode
from app.models.violation import Violation


def test_cwl_missed_attack_is_regular_violation_code() -> None:
    assert ViolationCode.CWL_MISSED_ATTACK.value == "cwl_missed_attack"


def test_no_separate_cwl_violation_table_or_model_is_used() -> None:
    assert not Path("app/models/cwl_missed_attack_violation.py").exists()
    assert not Path("app/repositories/cwl_missed_attack_violation.py").exists()
    assert not Path("app/services/cwl_missed_attack_violation.py").exists()
    assert Violation.__tablename__ == "violations"


def test_cwl_missed_attack_is_stored_in_violations_table() -> None:
    columns = Violation.__table__.columns
    assert columns.attack_id.nullable is True
    assert columns.target_position.nullable is True
    assert "uq_violations_cwl_missed_attack_per_war_player" in {idx.name for idx in Violation.__table__.indexes}
