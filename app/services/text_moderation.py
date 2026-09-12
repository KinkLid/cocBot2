from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.config.settings import TextModerationConfig

_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_REPEATED_LETTER_RE = re.compile(r"([^\W\d_])\1{2,}", re.UNICODE)

# Common Latin look-alikes used by the built-in legacy patterns.
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

# A broader moderation-only transliteration/leet view. This never changes the
# original Telegram message; it is used only for matching.
_HARDENED_TRANSLATION = str.maketrans(
    {
        "a": "а",
        "b": "б",
        "c": "с",
        "d": "д",
        "e": "е",
        "f": "ф",
        "g": "г",
        "h": "х",
        "i": "и",
        "j": "й",
        "k": "к",
        "l": "л",
        "m": "м",
        "n": "н",
        "o": "о",
        "p": "р",
        "r": "р",
        "s": "с",
        "t": "т",
        "u": "у",
        "v": "в",
        "x": "х",
        "y": "у",
        "z": "з",
        "0": "о",
        "1": "и",
        "3": "з",
        "4": "ч",
        "6": "б",
        "8": "в",
        "@": "а",
        "$": "с",
    }
)

# Per-character alternatives for configured blocked terms. Ambiguous symbols
# may intentionally occur in more than one class (for example 1 can imitate
# both и and л); matching is term-driven, so we do not have to pick one global
# interpretation.
_TERM_CHAR_ALIASES: dict[str, str] = {
    "а": "аa@",
    "б": "бb6",
    "в": "вvb8",
    "г": "гg",
    "д": "дd",
    "е": "еe",
    "ж": "ж",
    "з": "зz3",
    "и": "иi1!",
    "й": "йi",
    "к": "кk",
    "л": "лl1|",
    "м": "мm",
    "н": "нnh",
    "о": "оo0",
    "п": "пn",
    "р": "рpr",
    "с": "сcs$",
    "т": "тt",
    "у": "уyu",
    "ф": "фf",
    "х": "хxh",
    "ц": "цc",
    "ч": "ч4",
    "ш": "шw",
    "щ": "щw",
    "ы": "ыy",
    "э": "эe3",
    "ю": "юu",
    "я": "яr",
}

# High-confidence slurs. Neutral identity words are intentionally excluded;
# they are handled only when combined with dehumanization/violence below.
_RUSSIAN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ru_nword",
        re.compile(
            r"(?<!\w)н[\W_]*и[\W_]*г[\W_]*г?[\W_]*е[\W_]*р(?:а|ы|ов|ам|ами|ах|ский|ская|ское|ские|ского|ских)?(?!\w)",
            re.IGNORECASE,
        ),
    ),
    (
        "ru_nword_nigga",
        re.compile(
            r"(?<!\w)н[\W_]*и[\W_]*г[\W_]*г?[\W_]*а(?:м|ми|х)?(?!\w)",
            re.IGNORECASE,
        ),
    ),
    ("ru_black_slur", re.compile(r"(?<!\w)черножоп\w*(?!\w)", re.IGNORECASE)),
    ("ru_black_slur_secondary", re.compile(r"(?<!\w)черномаз\w*(?!\w)", re.IGNORECASE)),
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
    (
        "ru_antisemitic_compound_slur",
        re.compile(
            r"(?<!\w)(?:жидяр\w*|жидовн\w*|жидобольшев\w*|жидомасон\w*)(?!\w)",
            re.IGNORECASE,
        ),
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
    ("en_black_slur_coon", re.compile(r"(?<![a-z0-9])coons?(?![a-z0-9])", re.IGNORECASE)),
    ("en_black_slur_darkie", re.compile(r"(?<![a-z0-9])dark(?:ie|y)s?(?![a-z0-9])", re.IGNORECASE)),
    (
        "en_black_slur_phrase",
        re.compile(r"(?<![a-z0-9])porch[^a-z0-9]+monkeys?(?![a-z0-9])", re.IGNORECASE),
    ),
    ("en_antisemitic_slur", re.compile(r"(?<![a-z0-9])kikes?(?![a-z0-9])", re.IGNORECASE)),
    ("en_antisemitic_slur_heeb", re.compile(r"(?<![a-z0-9])heebs?(?![a-z0-9])", re.IGNORECASE)),
    ("en_asian_slur", re.compile(r"(?<![a-z0-9])chinks?(?![a-z0-9])", re.IGNORECASE)),
    ("en_hispanic_slur", re.compile(r"(?<![a-z0-9])spics?(?![a-z0-9])", re.IGNORECASE)),
    ("en_hispanic_slur_wetback", re.compile(r"(?<![a-z0-9])wetbacks?(?![a-z0-9])", re.IGNORECASE)),
    ("en_south_asian_slur", re.compile(r"(?<![a-z0-9])pakis?(?![a-z0-9])", re.IGNORECASE)),
    ("en_middle_east_slur", re.compile(r"(?<![a-z0-9])ragheads?(?![a-z0-9])", re.IGNORECASE)),
)

# High-confidence Russian-language slurs evaluated on a hardened moderation-only
# representation, so mixed Latin, leetspeak and punctuation-separated spellings
# are normalized first.
_HARDENED_SLUR_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ru_ukrainian_slur",
        re.compile(
            r"(?<!\w)(?:хохол\w*|хохл\w*|хохлуш\w*|хохляц\w*|салоед\w*|укробыдл\w*)(?!\w)",
            re.IGNORECASE,
        ),
    ),
    (
        "ru_russian_slur",
        re.compile(r"(?<!\w)(?:кацап\w*|москал\w*|русня)(?!\w)", re.IGNORECASE),
    ),
    (
        "ru_black_slur_hardened",
        re.compile(r"(?<!\w)(?:черножоп\w*|черномаз\w*)(?!\w)", re.IGNORECASE),
    ),
    (
        "ru_antisemitic_slur_hardened",
        re.compile(
            r"(?<!\w)(?:жидяр\w*|жидовн\w*|жидобольшев\w*|жидомасон\w*)(?!\w)",
            re.IGNORECASE,
        ),
    ),
)

_IDENTITY = (
    r"(?:украинц\w*|русс?к\w*|русня|евре\w*|иуде\w*|"
    r"чернокож\w*|негр\w*|африканц\w*|"
    r"кавказц\w*|чеченц\w*|дагестанц\w*|армян\w*|грузин\w*|азербайджанц\w*|"
    r"азиат\w*|китайц\w*|корейц\w*|узбек\w*|таджик\w*|киргиз\w*|казах\w*|"
    r"араб\w*|мусулман\w*|цыган\w*|"
    r"хохол\w*|хохл\w*|кацап\w*|москал\w*)"
)
_DEHUMANIZING = (
    r"(?:не\s+люди|нелюди|недолюди|мрази|твари|паразиты|отбросы|"
    r"животн\w*|обезьян\w*|свинь\w*|скот\w*|крысы|тараканы|"
    r"биомусор|мусор|грязь|выродк\w*)"
)
_ADVOCACY = r"(?:надо|нужно|следует|пора)"
_NON_NEGATED_WORDS = r"(?:\s+(?!не\b)\w+){0,3}"
_VIOLENCE_VERB = (
    r"(?:убить|убивать|уничтож(?:ить|ать|ай\w*|ают|ал\w*)|"
    r"истреб(?:ить|лять|ляй\w*|ляют|лял\w*)|"
    r"вырез(?:ать|ай\w*|ают|ал\w*)|резать|"
    r"расстрел(?:ять|ивать|ивай\w*|ивают|ивал\w*)|"
    r"сжечь|жечь|бить)"
)
_IMPERATIVE_VIOLENCE = (
    r"(?:убивай\w*|уничтожай\w*|истребляй\w*|вырезай\w*|"
    r"режь\w*|расстреливай\w*|стреляй\w*|бей\w*|жги\w*)"
)
_EXCLUSION_VERB = r"(?:выгнать|изгнать|депортировать|выселить)"
_ANTISEMITIC_SUBJECT = r"(?:евре\w*|жид(?:ы|а|у|ом|е|ов|ам|ами|ах)?)"
_CONSPIRACY_VERB = r"(?:управляют|контролируют|захватили|правят)"
_CONSPIRACY_OBJECT = r"(?:мир\w*|бан\w*|сми|правительств\w*|экономик\w*|финанс\w*)"

_HARDENED_CONTEXT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "hate_dehumanization",
        re.compile(
            rf"(?<!\w){_IDENTITY}(?:\s+\w+){{0,3}}\s+{_DEHUMANIZING}(?!\w)",
            re.IGNORECASE,
        ),
    ),
    (
        "hate_violence_advocacy",
        re.compile(
            rf"(?<!не )\b{_ADVOCACY}\b{_NON_NEGATED_WORDS}\s+{_VIOLENCE_VERB}"
            rf"(?:\s+\w+){{0,3}}\s+{_IDENTITY}(?!\w)|"
            rf"(?<!\w){_IDENTITY}(?:\s+\w+){{0,3}}\s+(?<!не )\b{_ADVOCACY}\b"
            rf"{_NON_NEGATED_WORDS}\s+{_VIOLENCE_VERB}(?!\w)",
            re.IGNORECASE,
        ),
    ),
    (
        "hate_violence_imperative",
        re.compile(
            rf"(?<!не )\b{_IMPERATIVE_VIOLENCE}\b(?:\s+\w+){{0,3}}\s+{_IDENTITY}(?!\w)",
            re.IGNORECASE,
        ),
    ),
    (
        "hate_death_slogan",
        re.compile(rf"(?<!\w)смерть(?:\s+\w+){{0,2}}\s+{_IDENTITY}(?!\w)", re.IGNORECASE),
    ),
    (
        "hate_exclusion_advocacy",
        re.compile(
            rf"(?<!не )\b{_ADVOCACY}\b{_NON_NEGATED_WORDS}\s+{_EXCLUSION_VERB}"
            rf"(?:\s+\w+){{0,3}}\s+{_IDENTITY}(?!\w)|"
            rf"(?<!\w){_IDENTITY}(?:\s+\w+){{0,3}}\s+(?<!не )\b{_ADVOCACY}\b"
            rf"{_NON_NEGATED_WORDS}\s+{_EXCLUSION_VERB}(?!\w)",
            re.IGNORECASE,
        ),
    ),
    (
        "antisemitic_conspiracy",
        re.compile(
            rf"(?<!\w){_ANTISEMITIC_SUBJECT}{_NON_NEGATED_WORDS}\s+{_CONSPIRACY_VERB}"
            rf"(?:\s+\w+){{0,2}}\s+{_CONSPIRACY_OBJECT}(?!\w)|"
            rf"(?<!не )\b{_CONSPIRACY_OBJECT}\b(?:\s+\w+){{0,2}}\s+{_CONSPIRACY_VERB}"
            rf"(?:\s+\w+){{0,2}}\s+{_ANTISEMITIC_SUBJECT}(?!\w)",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class TextModerationMatch:
    rule_id: str


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")
    normalized = _ZERO_WIDTH_RE.sub("", normalized)
    return "".join(
        char
        for char in normalized
        if unicodedata.category(char) != "Cf" and not unicodedata.category(char).startswith("M")
    )


def _word_sequence(text: str) -> tuple[str, ...]:
    normalized = _normalize(text).translate(_CYRILLIC_CONFUSABLES)
    return tuple(_WORD_RE.findall(normalized))


def _join_single_character_runs(words: list[str]) -> list[str]:
    result: list[str] = []
    index = 0
    while index < len(words):
        if len(words[index]) != 1:
            result.append(words[index])
            index += 1
            continue

        end = index
        while end < len(words) and len(words[end]) == 1:
            end += 1
        run = words[index:end]
        if len(run) >= 3:
            result.append("".join(run))
        else:
            result.extend(run)
        index = end
    return result


def _hardened_text(text: str) -> str:
    normalized = _normalize(text).translate(_HARDENED_TRANSLATION)
    separated = "".join(char if char.isalnum() else " " for char in normalized)
    words = _join_single_character_runs(separated.split())
    collapsed = [_REPEATED_LETTER_RE.sub(r"\1", word) for word in words]
    return " ".join(collapsed)


def _compile_configured_term(term: str) -> re.Pattern[str] | None:
    normalized = _normalize(term)
    chars = [char for char in normalized if char.isalnum()]
    if not chars:
        return None

    pieces: list[str] = []
    for char in chars:
        aliases = _TERM_CHAR_ALIASES.get(char, char)
        char_class = f"[{re.escape(aliases)}]"
        # Allow a few repeated copies of the expected character, with optional
        # punctuation/space between them: хоооохол, х.o.х.o.л, etc.
        pieces.append(rf"(?:{char_class}(?:[\W_]*{char_class}){{0,4}})")

    body = r"[\W_]*".join(pieces)
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE | re.UNICODE)


class TextModerationDetector:
    def __init__(self, config: TextModerationConfig) -> None:
        blocked_terms = tuple(term.strip() for term in config.blocked_terms if term.strip())
        self._blocked_patterns = tuple(
            (index, pattern)
            for index, term in enumerate(blocked_terms, start=1)
            if (pattern := _compile_configured_term(term)) is not None
        )

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

        hardened = _hardened_text(text)
        for rule_id, pattern in _HARDENED_SLUR_PATTERNS:
            if pattern.search(hardened):
                return TextModerationMatch(rule_id=rule_id)

        for rule_id, pattern in _HARDENED_CONTEXT_PATTERNS:
            if pattern.search(hardened):
                return TextModerationMatch(rule_id=rule_id)

        for index, pattern in self._blocked_patterns:
            if pattern.search(normalized):
                return TextModerationMatch(rule_id=f"configured_term_{index}")
        return None
