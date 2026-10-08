# -*- coding: utf-8 -*-
"""Поиск в интернете через DuckDuckGo (библиотека ddgs).
Резервный парсер — html.duckduckgo.com."""

import re
import html as html_module
from urllib.parse import unquote, urlparse, parse_qs

try:
    from ddgs import DDGS
    HAS_DDGS = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        HAS_DDGS = True
    except ImportError:
        HAS_DDGS = False


def search_duckduckgo(query: str, max_results: int = 5) -> list:
    """Возвращает [{"title", "url", "snippet"}]."""
    if not HAS_DDGS:
        return []
    try:
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
        return results
    except Exception:
        return _fallback_html(query, max_results)


def _fallback_html(query: str, max_results: int = 5) -> list:
    try:
        import requests
        r = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/120.0 Safari/537.36"),
            },
            timeout=15,
        )
        if r.status_code != 200:
            return []
        pattern = re.compile(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            re.DOTALL,
        )
        out = []
        for m in pattern.finditer(r.text):
            url = m.group(1)
            title = html_module.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
            snippet = html_module.unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip()
            if url.startswith("//duckduckgo.com/l/?uddg="):
                qs = parse_qs(urlparse(url).query)
                if "uddg" in qs:
                    url = qs["uddg"][0]
            if not url.startswith("http"):
                continue
            out.append({"title": title, "url": url, "snippet": snippet})
            if len(out) >= max_results:
                break
        return out
    except Exception:
        return []


def format_results(results: list) -> str:
    """Форматирует для промпта LLM."""
    if not results:
        return ""
    parts = []
    for i, r in enumerate(results, 1):
        parts.append(f"{i}. {r['title']}\n   URL: {r['url']}\n   {r['snippet']}")
    return "\n\n".join(parts)


def fetch_page(url: str, max_chars: int = 3000) -> str:
    """Загружает страницу, возвращает чистый текст."""
    try:
        import requests
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"},
                         timeout=15, stream=True)
        r.raise_for_status()
        if "text/html" not in r.headers.get("content-type", ""):
            return ""
        html = r.text[:100_000]
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception:
        return ""


if __name__ == "__main__":
    print("=== web_search самотест ===\n")
    print(f"ddgs доступен: {HAS_DDGS}\n")
    print("Поиск: 'python 3.13 новости'...")
    res = search_duckduckgo("python 3.13 новости", max_results=3)
    if not res:
        print("  ✗ Ничего не найдено (или нет интернета)")
    else:
        for i, r in enumerate(res, 1):
            print(f"\n  {i}. {r['title']}")
            print(f"     {r['url']}")
            print(f"     {r['snippet'][:100]}...")