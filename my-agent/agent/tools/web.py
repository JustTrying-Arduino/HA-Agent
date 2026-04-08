"""Tools: web search (Brave) and URL fetch."""

import re
import logging
import requests

from agent.config import cfg
from agent.tools import register

logger = logging.getLogger(__name__)

MAX_FETCH = 20000


# --- web_search: only registered if Brave API key is set ---
if cfg.brave_api_key:
    @register(
        name="web_search",
        description="Search the web using Brave Search. Returns top results with title, URL, and snippet.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    )
    def web_search(query: str) -> str:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": 5},
            headers={"X-Subscription-Token": cfg.brave_api_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("web", {}).get("results", [])
        if not results:
            return "No results found."
        lines = []
        for r in results:
            lines.append(f"**{r.get('title', '')}**")
            lines.append(r.get("url", ""))
            lines.append(r.get("description", ""))
            lines.append("")
        return "\n".join(lines).strip()


@register(
    name="web_fetch",
    description="Fetch a URL and return its text content (HTML tags stripped).",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
        },
        "required": ["url"],
    },
)
def web_fetch(url: str) -> str:
    resp = requests.get(
        url,
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0 (compatible; MyAgent/1.0)"},
    )
    resp.raise_for_status()
    text = re.sub(r"<script[^>]*>.*?</script>", "", resp.text, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_FETCH:
        text = text[:MAX_FETCH] + "\n... (truncated)"
    return text
