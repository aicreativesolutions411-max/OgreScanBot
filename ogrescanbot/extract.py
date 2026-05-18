from __future__ import annotations

import re
from urllib.parse import unquote, urlparse


SOLANA_ADDRESS_RE = re.compile(r"(?<![A-Za-z0-9])[1-9A-HJ-NP-Za-km-z]{32,44}(?![A-Za-z0-9])")


def extract_solana_addresses(text: str | None) -> list[str]:
    if not text:
        return []

    candidates: list[str] = []
    normalized = unquote(text)

    for match in SOLANA_ADDRESS_RE.findall(normalized):
        candidates.append(match)

    for raw in re.findall(r"https?://\S+", normalized):
        parsed = urlparse(raw.rstrip(").,]}>"))
        parts = [part for part in parsed.path.split("/") if part]
        query = parsed.query.replace("=", " ").replace("&", " ")
        combined = " ".join(parts + [query])
        for match in SOLANA_ADDRESS_RE.findall(combined):
            candidates.append(match)

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)
    return unique
