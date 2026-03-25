from __future__ import annotations

import re
import unicodedata


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = str(value).strip().lower()
    value = "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch))
    value = re.sub(r"\s+", " ", value)
    return value


def extract_number(value: str | int | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = normalize_text(str(value))
    if not text:
        return None
    text = text.replace("r$", "").replace(".", "").replace(" ", "")
    text = text.replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def boolean_from_text(text: str, patterns: list[str]) -> bool:
    t = normalize_text(text)
    return any(re.search(p, t) for p in patterns)


def first_non_empty(*values: object) -> str:
    for value in values:
        if value is None:
            continue
        s = str(value).strip()
        if s and s.lower() != "nan":
            return s
    return ""
