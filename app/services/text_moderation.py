from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.config.settings import TextModerationConfig

_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_WORD_RE = re.compile(r"\w+", re.UNICODE)

# Common Latin look-alikes used to bypass Cyrillic word filters.
_CYRILLIC_CONFUSABLES = str.maketrans(
    {
        "a": "а",
        "c": "с",
        "e": "е",
        "o": "о",
        "p": "р",
        "x": "х",
        "y": "у",
        "k": "к",
        "m": "м",
        "t": "т",
        "b": "в",
    }
)

# Keep the built-in list deliberately conservative: only high-confidence slurs.
# More clan-specific terms can be added through text_moderation.blocked_terms.
_RUSSIAN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ru_nword",
        re.compile(
            r"(?<!\w)н[\W_]*и[\W_]*г[\W_]*г?[\W_]*е[\W_]*р(?:а|ы|ов|ам|ами|ах|ский|ская|ское|ские|ского|ских)?(?!\w)",
            re.IGNORECASE,
        ),
    ),
    ("ru_black_slur", re.compile(r"(?<!\w)черножоп\w*(?!\w)", re.IGNORECASE)),
    (
        "ru_caucasus_slur",
        re.compile(r"(?<!\w)хач(?:и|ей|ами|ах|ик(?:и|а|у|ом|е|ов|ам|ами|ах)?)?(?!\w)", re.IGNORECASE),
    ),
    (
        "ru_ethnic_slur",
        re.compile(r"(?<!\w)чурк(?:а|и|е|у|ой|ою|ам|ами|ах)?(?!\w)", re.IGNORECASE),
    ),
    ("ru_asian_slur", re.compile(r"(?<!\w)узкоглаз\w*(?!\w)", re.IGNORECASE)),
    (
        "ru_antisemitic_slur",
        re.compile(r"(?<!\w)жид(?:ы|а|у|ом|е|ов|ам|ами|ах)?(?!\w)", re.IGNORECASE),
    ),
)

_ENGLISH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "en_nword",
        re.compile(
            r"(?<![a-z0-9])n[^a-z0-9]*[i1!][^a-z0-9]*g[^a-z0-9]*g+[^a-z0-9]*(?:e[^a-z0-9]*r|a)(?:s)?(?![a-z0-9])",
            re.IGNORECASE,
        ),
    ),
    ("en_antisemitic_slur", re.compile(r"(?<![a-z0-9])kikes?(?![a-z0-9])", re.IGNORECASE)),
    ("en_asian_slur", re.compile(r"(?<![a-z0-9])chinks?(?![a-z0-9])", re.IGNORECASE)),
    ("en_hispanic_slur", re.compile(r"(?<![a-z0-9])spics?(?![a-z0-9])", re.IGNORECASE)),
)


@dataclass(frozen=True, slots=True)
class TextModerationMatch:
    rule_id: str


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")
    return _ZERO_WIDTH_RE.sub("", normalized)


def _word_sequence(text: str) -> tuple[str, ...]:
    normalized = _normalize(text).translate(_CYRILLIC_CONFUSABLES)
    return tuple(_WORD_RE.findall(normalized))


def _contains_term(words: tuple[str, ...], term: str) -> bool:
    term_words = _word_sequence(term)
    if not term_words or len(term_words) > len(words):
        return False
    width = len(term_words)
    return any(words[index : index + width] == term_words for index in range(len(words) - width + 1))


class TextModerationDetector:
    def __init__(self, config: TextModerationConfig) -> None:
        self._blocked_terms = tuple(term.strip() for term in config.blocked_terms if term.strip())

    def detect(self, text: str | None) -> TextModerationMatch | None:
        if not text:
            return None

        normalized = _normalize(text)
        for rule_id, pattern in _ENGLISH_PATTERNS:
            if pattern.search(normalized):
                return TextModerationMatch(rule_id=rule_id)

        cyrillicized = normalized.translate(_CYRILLIC_CONFUSABLES)
        for rule_id, pattern in _RUSSIAN_PATTERNS:
            if pattern.search(cyrillicized):
                return TextModerationMatch(rule_id=rule_id)

        words = _word_sequence(text)
        for index, term in enumerate(self._blocked_terms):
            if _contains_term(words, term):
                return TextModerationMatch(rule_id=f"configured_term_{index + 1}")
        return None
