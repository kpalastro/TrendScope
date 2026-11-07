"""Name normalisation and slugs shared by the importer and the mock connector."""

from __future__ import annotations

import re
import unicodedata

STOPWORDS = {"the", "a", "an", "with", "for", "and", "of", "set", "pack"}


def normalise_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [t for t in text.split() if t and t not in STOPWORDS]
    return " ".join(tokens)


def slugify(value: str, max_length: int = 120) -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:max_length].rstrip("-") or "product"


def keywords_from_name(name: str, limit: int = 5) -> list[str]:
    tokens = [t for t in normalise_name(name).split() if len(t) > 2]
    seen: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
    return seen[:limit]
