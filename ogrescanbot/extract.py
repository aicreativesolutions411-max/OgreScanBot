from __future__ import annotations

import re
from urllib.parse import unquote, urlparse


SOLANA_ADDRESS_RE = re.compile(r"(?<![A-Za-z0-9])[1-9A-HJ-NP-Za-km-z]{32,44}(?![A-Za-z0-9])")
TICKER_RE = re.compile(r"(?<![A-Za-z0-9_])\$([A-Za-z][A-Za-z0-9_]{1,20})(?![A-Za-z0-9_])")
X_STATUS_RE = re.compile(
    r"https?://(?:www\.|mobile\.)?(?:x\.com|twitter\.com)/([^/\s?]+)/status(?:es)?/(\d+)[^\s]*",
    re.IGNORECASE,
)


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


def extract_ticker_queries(text: str | None) -> list[str]:
    if not text:
        return []

    candidates = [match.upper() for match in TICKER_RE.findall(unquote(text))]
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)
    return unique


def extract_token_queries(text: str | None) -> list[str]:
    return extract_solana_addresses(text) + extract_ticker_queries(text)


def is_solana_address(value: str | None) -> bool:
    return bool(value and SOLANA_ADDRESS_RE.fullmatch(value.strip()))


def extract_x_post_links(text: str | None) -> list[tuple[str, str, str]]:
    if not text:
        return []

    links: list[tuple[str, str, str]] = []
    for raw_user, status_id in X_STATUS_RE.findall(unquote(text)):
        username = raw_user.strip("@")
        if username.lower() in {"i", "home", "search"}:
            continue
        embed_url = f"https://fxtwitter.com/{username}/status/{status_id}"
        links.append((username, status_id, embed_url))

    seen: set[str] = set()
    unique: list[tuple[str, str, str]] = []
    for item in links:
        key = item[1]
        if key not in seen:
            unique.append(item)
            seen.add(key)
    return unique
