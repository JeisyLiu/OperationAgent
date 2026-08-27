import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Paths that are search/home pages, not individual content.
_NON_CONTENT_PATH_PATTERNS = (
    re.compile(r"/search", re.I),
    re.compile(r"/search_result", re.I),
    re.compile(r"/login", re.I),
    re.compile(r"/passport", re.I),
    re.compile(r"/upload", re.I),
    re.compile(r"/publish", re.I),
    re.compile(r"/creator", re.I),
)


@dataclass
class WebSearchResult:
    url: str
    title: str
    snippet: str


def _normalize_url(url: str) -> str:
    normalized = (url or "").strip()
    while normalized.endswith("/"):
        normalized = normalized[:-1]
    return normalized


def _host_matches(url: str, domain: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    domain = domain.lower().lstrip(".")
    return host == domain or host.endswith("." + domain)


def _is_content_url(url: str, domain: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    if not _host_matches(url, domain):
        return False
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path or "/"
    except Exception:
        return False
    if host.startswith("search.") or host.split(".")[0] == "search":
        return False
    if path in ("", "/"):
        return False
    for pattern in _NON_CONTENT_PATH_PATTERNS:
        if pattern.search(path):
            return False
    return True


def _ddg_text_search(query: str, *, max_results: int) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
    except ImportError as exc:
        raise RuntimeError(
            "duckduckgo-search is not installed; add duckduckgo-search to dependencies"
        ) from exc

    rows: list[dict] = []
    with DDGS() as ddgs:
        for row in ddgs.text(query, max_results=max_results):
            if isinstance(row, dict):
                rows.append(row)
    return rows


class WebSearchService:
    def search(self, query: str, *, max_results: int = 10) -> list[WebSearchResult]:
        query = (query or "").strip()
        if not query:
            return []
        try:
            raw_rows = _ddg_text_search(query, max_results=max_results)
        except Exception:
            logger.exception("web_search failed for query=%r", query)
            return []

        results: list[WebSearchResult] = []
        for row in raw_rows:
            url = _normalize_url(str(row.get("href") or row.get("url") or ""))
            if not url:
                continue
            title = str(row.get("title") or "").strip()
            snippet = str(row.get("body") or row.get("snippet") or "").strip()
            results.append(WebSearchResult(url=url, title=title, snippet=snippet))
        return results

    def search_site(
        self,
        domain: str,
        keyword: str,
        *,
        max_results: int = 10,
    ) -> list[WebSearchResult]:
        domain = (domain or "").strip().lower()
        keyword = (keyword or "").strip()
        if not domain or not keyword:
            return []

        query = f"site:{domain} {keyword}"
        seen: set[str] = set()
        filtered: list[WebSearchResult] = []
        for row in self.search(query, max_results=max_results * 2):
            if not _is_content_url(row.url, domain):
                continue
            norm = _normalize_url(row.url)
            if norm in seen:
                continue
            seen.add(norm)
            filtered.append(
                WebSearchResult(url=norm, title=row.title, snippet=row.snippet)
            )
            if len(filtered) >= max_results:
                break
        logger.info(
            "web_search site:%s keyword=%r -> %s hits",
            domain,
            keyword,
            len(filtered),
        )
        return filtered


web_search_service = WebSearchService()
