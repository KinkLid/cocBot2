from __future__ import annotations

import pytest

from app.config.settings import TextModerationConfig
from app.services.text_moderation import TextModerationDetector


def test_text_moderation_disabled_by_default() -> None:
    config = TextModerationConfig()

    assert config.enabled is False
    assert config.chat_ids == []
    assert config.mute_minutes == 60
    assert config.blocked_terms == []


def test_configured_blocked_term_is_normalized() -> None:
    detector = TextModerationDetector(TextModerationConfig(blocked_terms=["запрещенная фраза"]))

    match = detector.detect("Это ЗАПРЕЩЕННАЯ   ФРАЗА здесь")

    assert match is not None
    assert match.rule_id == "configured_term_1"


@pytest.mark.parametrize(
    "text",
    [
        "хохол",
        "ХОХОЛ",
        "X0xол",
        "xoxol",
        "h0h0l",
        "х.о.х.о.л",
        "х_о_х_о_л",
        "х-о-х-о-л",
        "х о х о л",
        "х\u200bо\u200bх\u200bо\u200bл",
        "хоооохол",
    ],
)
def test_ukrainian_slur_obfuscations_are_detected(text: str) -> None:
    detector = TextModerationDetector(TextModerationConfig(blocked_terms=["хохол"]))

    assert detector.detect(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "кацап",
        "kacaп",
        "к.а.ц.а.п",
        "м0скаль",
        "рyсня",
    ],
)
def test_russian_slur_obfuscations_are_detected(text: str) -> None:
    detector = TextModerationDetector(
        TextModerationConfig(blocked_terms=["кацап", "москаль", "русня"])
    )

    assert detector.detect(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "ниггер",
        "нигга",
        "черножопый",
        "черномазый",
        "nigger",
        "n1gger",
        "nigga",
        "coon",
        "darkie",
        "porch monkey",
    ],
)
def test_black_slurs_are_detected(text: str) -> None:
    detector = TextModerationDetector(TextModerationConfig())

    assert detector.detect(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "жид",
        "жиды",
        "жидяра",
        "жидовня",
        "жидобольшевики",
        "жидомасоны",
        "kike",
        "heeb",
    ],
)
def test_antisemitic_slurs_are_detected(text: str) -> None:
    detector = TextModerationDetector(TextModerationConfig())

    assert detector.detect(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "хач",
        "хачик",
        "чурка",
        "узкоглазый",
        "chink",
        "spic",
        "wetback",
        "paki",
        "raghead",
    ],
)
def test_other_ethnic_slurs_are_detected(text: str) -> None:
    detector = TextModerationDetector(TextModerationConfig())

    assert detector.detect(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "украинцы не люди",
        "украинцы вообще не люди",
        "украинцы мерзкие недолюди",
        "русские не люди",
        "евреи недолюди",
        "чернокожие не люди",
        "негры животные",
        "африканцы обезьяны",
        "чеченцы тараканы",
        "узбеки биомусор",
        "арабы выродки",
    ],
)
def test_dehumanizing_identity_phrases_are_detected(text: str) -> None:
    detector = TextModerationDetector(TextModerationConfig())

    assert detector.detect(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "надо убивать украинцев",
        "надо срочно убивать украинцев",
        "украинцев надо уничтожить",
        "украинцев давно пора уничтожить",
        "смерть украинцам",
        "убивайте украинцев",
        "русских нужно истребить",
        "смерть русским",
        "евреев надо уничтожить",
        "чернокожих нужно убивать",
        "смерть неграм",
        "узбеков надо вырезать",
        "арабов нужно расстреливать",
    ],
)
def test_identity_violence_advocacy_is_detected(text: str) -> None:
    detector = TextModerationDetector(TextModerationConfig())

    assert detector.detect(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "евреев надо выгнать",
        "нужно депортировать всех узбеков",
        "чернокожих нужно выселить",
        "арабов пора изгнать",
    ],
)
def test_identity_exclusion_advocacy_is_detected(text: str) -> None:
    detector = TextModerationDetector(TextModerationConfig())

    assert detector.detect(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "евреи управляют миром",
        "евреи контролируют все банки",
        "жиды захватили сми",
        "евреи правят мировой экономикой",
    ],
)
def test_antisemitic_conspiracy_claims_are_detected(text: str) -> None:
    detector = TextModerationDetector(TextModerationConfig())

    assert detector.detect(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "не надо убивать украинцев",
        "украинцев не надо убивать",
        "не нужно уничтожать русских",
        "я против того чтобы убивать украинцев",
        "не надо выгонять евреев",
        "евреев не нужно депортировать",
    ],
)
def test_common_non_advocacy_contexts_are_not_flagged(text: str) -> None:
    detector = TextModerationDetector(TextModerationConfig())

    assert detector.detect(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "он еврей",
        "она чернокожая",
        "он африканец",
        "он узбек",
        "она казашка",
        "он араб",
        "он мусульманин",
        "он китаец",
        "он чеченец",
        "он украинец",
        "он русский",
    ],
)
def test_neutral_identity_mentions_are_not_flagged(text: str) -> None:
    detector = TextModerationDetector(TextModerationConfig())

    assert detector.detect(text) is None


def test_configured_term_does_not_match_inside_other_word() -> None:
    detector = TextModerationDetector(TextModerationConfig(blocked_terms=["abc"]))

    assert detector.detect("zabcx") is None


def test_regular_text_is_not_flagged() -> None:
    detector = TextModerationDetector(TextModerationConfig())

    assert detector.detect("Ребята, кто сегодня идет на КВ?") is None
