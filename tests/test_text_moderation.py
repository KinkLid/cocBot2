from __future__ import annotations

from app.config.settings import TextModerationConfig
from app.services.text_moderation import TextModerationDetector


def test_text_moderation_disabled_by_default() -> None:
    config = TextModerationConfig()

    assert config.enabled is False
    assert config.chat_ids == []
    assert config.mute_minutes == 60
    assert config.blocked_terms == []


def test_configured_blocked_term_is_normalized() -> None:
    detector = TextModerationDetector(
        TextModerationConfig(blocked_terms=["запрещенная фраза"])
    )

    match = detector.detect("Это ЗАПРЕЩЕННАЯ   ФРАЗА здесь")

    assert match is not None
    assert match.rule_id == "configured_term_1"


def test_configured_term_does_not_match_inside_other_word() -> None:
    detector = TextModerationDetector(TextModerationConfig(blocked_terms=["abc"]))

    assert detector.detect("zabcx") is None


def test_regular_text_is_not_flagged() -> None:
    detector = TextModerationDetector(TextModerationConfig())

    assert detector.detect("Ребята, кто сегодня идет на КВ?") is None
