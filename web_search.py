from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
# Wikimedia asks API clients to identify themselves with a descriptive User-Agent.
USER_AGENT = "Polaris/1.0 (student RAG chatbot project; https://github.com/Prachkacha0/Chatbot)"


@dataclass(frozen=True)
class WebSource:
    title: str
    url: str
    text: str

    def to_payload(self) -> dict[str, Any]:
        return {"title": self.title, "url": self.url}


def search_wikipedia(
    query: str,
    *,
    limit: int = 2,
    timeout: float = 6.0,
    max_chars: int = 1500,
) -> list[WebSource]:
    """Return the lead sections of the top English Wikipedia articles for
    `query`, or an empty list on any network/parse failure so callers can fall
    back to answering without web context."""
    params = urllib.parse.urlencode({
        "action": "query",
        "format": "json",
        "formatversion": 2,
        "generator": "search",
        "gsrsearch": query,
        "gsrlimit": limit,
        "prop": "extracts|info",
        "exintro": 1,
        "explaintext": 1,
        "exlimit": limit,
        "inprop": "url",
        "redirects": 1,
    })
    request = urllib.request.Request(f"{WIKIPEDIA_API}?{params}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except (OSError, ValueError) as exc:
        logger.warning("Wikipedia search failed for %r: %s", query, exc)
        return []

    pages = sorted(data.get("query", {}).get("pages", []), key=lambda page: page.get("index", 0))
    sources: list[WebSource] = []
    for page in pages:
        text = (page.get("extract") or "").strip()
        url = page.get("fullurl") or ""
        if text and url.startswith("https://"):
            sources.append(WebSource(title=page.get("title", ""), url=url, text=text[:max_chars]))
    return sources
