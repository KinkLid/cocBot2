from __future__ import annotations

from urllib.parse import quote


ALLOWED_TAG_CHARS = set("0289PYLQGRJCUV")


def normalize_tag(tag: str) -> str:
    cleaned = tag.strip().upper().replace("O", "0")
    if not cleaned.startswith("#"):
        cleaned = f"#{cleaned}"
    if any(ch not in ALLOWED_TAG_CHARS for ch in cleaned[1:]):
        raise ValueError(f"Некорректный тег: {tag}")
    return cleaned


def encode_tag(tag: str) -> str:
    return quote(normalize_tag(tag), safe="")
