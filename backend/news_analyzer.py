"""
news_analyzer.py — Google News RSS fetch, URL resolution, content extraction,
                   Groq summarization, and Groq sentiment for news articles.

Public API:
    analyze_news(keyword, date_str) → list of article result dicts
"""

import urllib.parse
from datetime import datetime

import feedparser
import requests
from bs4 import BeautifulSoup

import sentiment as sent

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    )
}

TELUGU_SITES = {
    "eenadu":      ("Eenadu",       "eenadu.net"),
    "sakshi":      ("Sakshi",       "sakshi.com"),
    "andhrajyothy":("Andhra Jyothy","andhrajyothy.com"),
    "ntv":         ("NTV Telugu",   "ntvtelugu.com"),
    "tv9":         ("TV9 Telugu",   "tv9telugu.com"),
    "abn":         ("ABN Telugu",   "abntelugu.com"),
}

ENGLISH_SITES = {
    "thehindu":     ("The Hindu",        "thehindu.com"),
    "toi":          ("Times of India",   "timesofindia.indiatimes.com"),
    "deccan":       ("Deccan Chronicle", "deccanchronicle.com"),
    "indianexpress":("Indian Express",   "indianexpress.com"),
}


# ── RSS helpers ────────────────────────────────────────────────────────────────

def _rss_url(keyword: str, site_domain: str | None, lang: str) -> str:
    hl_map = {"te": ("te-IN", "IN:te"), "en": ("en-IN", "IN:en")}
    hl, ceid = hl_map[lang]
    query = f"{keyword} site:{site_domain}" if site_domain else keyword
    return (
        f"https://news.google.com/rss/search"
        f"?q={urllib.parse.quote(query)}&hl={hl}&gl=IN&ceid={ceid}"
    )


def _fetch_feed(url: str) -> list:
    try:
        resp = requests.get(url, timeout=12, headers=HEADERS)
        resp.raise_for_status()
        return feedparser.parse(resp.content).entries
    except Exception:
        return []


def _fetch_all_entries(keyword: str) -> list:
    entries: list = []
    for lang, sites in (("te", TELUGU_SITES), ("en", ENGLISH_SITES)):
        # General feed (no site restriction)
        for entry in _fetch_feed(_rss_url(keyword, None, lang)):
            entry.source_hint = "News"
            entries.append(entry)
        # Per-site feeds
        for _, (display_name, domain) in sites.items():
            for entry in _fetch_feed(_rss_url(keyword, domain, lang)):
                entry.source_hint = display_name
                entries.append(entry)
    return entries


# ── Date helpers ───────────────────────────────────────────────────────────────

def _entry_date(entry) -> str:
    """Return YYYY-MM-DD from feedparser's published_parsed, or ''."""
    parsed = getattr(entry, "published_parsed", None)
    if not parsed:
        return ""
    try:
        return datetime(*parsed[:6]).strftime("%Y-%m-%d")
    except Exception:
        return ""


# ── URL resolution ─────────────────────────────────────────────────────────────

def _resolve_url(google_url: str) -> str:
    """Follow Google News redirect to get the actual article URL."""
    try:
        resp = requests.get(
            google_url, timeout=12, allow_redirects=True, headers=HEADERS
        )
        final = resp.url
        # If still a Google URL (JS redirect, not HTTP), return original
        if "google.com" in final:
            return google_url
        return final
    except Exception:
        return google_url


def _strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    if not text:
        return ""
    return BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)


# ── Content extraction ─────────────────────────────────────────────────────────

def _extract_content(url: str) -> str:
    """Download article HTML and extract main text with BeautifulSoup."""
    try:
        resp = requests.get(url, timeout=15, headers=HEADERS)
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        for selector in ["article", "main", ".article-body", ".content", "body"]:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(separator=" ", strip=True)
                if len(text) > 200:
                    return text[:6000]
    except Exception:
        pass
    return ""


# ── Main entry point ───────────────────────────────────────────────────────────

def analyze_news(keyword: str, date_str: str) -> list[dict]:
    """
    Fetch Google News RSS for keyword, filter by date_str (YYYY-MM-DD),
    resolve URLs, extract content, summarize, and classify sentiment.
    Returns list of article dicts for the frontend.
    """
    all_entries = _fetch_all_entries(keyword)

    # Deduplicate by title, filter by date (exact match or no date in entry)
    seen_titles: set[str] = set()
    filtered: list = []
    for entry in all_entries:
        title = getattr(entry, "title", "").strip()
        if not title or title in seen_titles:
            continue
        entry_date = _entry_date(entry)
        if entry_date and entry_date != date_str:
            continue
        seen_titles.add(title)
        filtered.append(entry)

    results: list[dict] = []
    for entry in filtered[:10]:  # cap processing to 10 articles
        title = getattr(entry, "title", "").strip()
        google_url = getattr(entry, "link", "")

        real_url = _resolve_url(google_url)
        content = _extract_content(real_url)
        if not content:
            raw_summary = getattr(entry, "summary", "")
            content = _strip_html(raw_summary)

        summary = sent.summarize(content, title) if content else title

        # Sentiment on the summary (1 item batch)
        art_sentiment = "neutral"
        if summary or content:
            batch = sent.analyze_batch([(summary or content)[:500]])
            art_sentiment = batch[0] if batch else "neutral"

        results.append({
            "title": title,
            "url": real_url,
            "source": getattr(entry, "source_hint", "News"),
            "published_date": _entry_date(entry) or date_str,
            "summary": summary,
            "sentiment": art_sentiment,
        })

    return results
