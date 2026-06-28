"""
news_analyzer.py — Google News RSS fetch, URL resolution, content extraction,
                   Groq summarization, and Groq sentiment for news articles.

Public API:
    analyze_news(keyword, date_str, politician_name) → list of article result dicts
"""

import difflib
import re
import urllib.parse
from datetime import datetime

import feedparser
import requests
import trafilatura
from googlenewsdecoder import gnewsdecoder

import sentiment as sent

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    )
}

TELUGU_SITES = {
    "eenadu":       ("Eenadu",        "eenadu.net"),
    "sakshi":       ("Sakshi",        "sakshi.com"),
    "andhrajyothy": ("Andhra Jyothy", "andhrajyothy.com"),
    "ntv":          ("NTV Telugu",    "ntvtelugu.com"),
    "tv9":          ("TV9 Telugu",    "tv9telugu.com"),
    "abn":          ("ABN Telugu",    "abntelugu.com"),
}

ENGLISH_SITES = {
    "thehindu":      ("The Hindu",        "thehindu.com"),
    "toi":           ("Times of India",   "timesofindia.indiatimes.com"),
    "deccan":        ("Deccan Chronicle", "deccanchronicle.com"),
    "indianexpress": ("Indian Express",   "indianexpress.com"),
}

TITLE_SIMILARITY_THRESHOLD = 0.85


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
        for entry in _fetch_feed(_rss_url(keyword, None, lang)):
            entry.source_hint = "News"
            entries.append(entry)
        for _, (display_name, domain) in sites.items():
            for entry in _fetch_feed(_rss_url(keyword, domain, lang)):
                entry.source_hint = display_name
                entries.append(entry)
    return entries


# ── Date helpers ───────────────────────────────────────────────────────────────

def _entry_date(entry) -> str:
    parsed = getattr(entry, "published_parsed", None)
    if not parsed:
        return ""
    try:
        return datetime(*parsed[:6]).strftime("%Y-%m-%d")
    except Exception:
        return ""


# ── URL resolution (gnewsdecoder first, HTTP redirect fallback) ───────────────

def _resolve_url(google_url: str) -> str:
    # gnewsdecoder requires /articles/ not /rss/articles/
    decode_url = google_url.replace("/rss/articles/", "/articles/")
    try:
        result = gnewsdecoder(decode_url)
        if result and result.get("status"):
            url = result.get("decoded_url") or result.get("url", "")
            if url and "google.com" not in url:
                return url
    except Exception:
        pass
    # HTTP redirect fallback
    try:
        resp = requests.get(google_url, timeout=12, allow_redirects=True, headers=HEADERS)
        if "google.com" not in resp.url:
            return resp.url
    except Exception:
        pass
    return google_url


# ── Content extraction via trafilatura ────────────────────────────────────────

def _extract_content(url: str) -> str:
    try:
        downloaded = trafilatura.fetch_url(url)
        result = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        return result or ""
    except Exception:
        return ""


def _rss_text(entry) -> str:
    """Fallback: strip HTML from RSS summary field."""
    raw = getattr(entry, "summary", "") or ""
    return re.sub(r"<[^>]+>", " ", raw).strip()


# ── Fuzzy title deduplication ─────────────────────────────────────────────────

def _normalize_title(title: str) -> str:
    """Lowercase, strip trailing '- Source' suffixes, collapse whitespace."""
    title = re.sub(r"\s*[-–|]\s*\S+\s*$", "", title.lower())
    return re.sub(r"\s+", " ", title).strip()


def _is_fuzzy_duplicate(title: str, seen_titles: list[str]) -> bool:
    norm = _normalize_title(title)
    for seen in seen_titles:
        ratio = difflib.SequenceMatcher(None, norm, seen).ratio()
        if ratio >= TITLE_SIMILARITY_THRESHOLD:
            return True
    return False


# ── Main entry point ───────────────────────────────────────────────────────────

def analyze_news(keyword: str, date_str: str, politician_name: str = "") -> list[dict]:
    """
    Fetch Google News RSS for keyword, filter by date_str (YYYY-MM-DD),
    resolve URLs, extract full article content via trafilatura,
    summarize and classify sentiment via Groq.
    Returns list of article dicts for the frontend.
    """
    all_entries = _fetch_all_entries(keyword)

    # Pass 1: exact title dedup + date filter
    seen_exact: set[str] = set()
    date_filtered: list = []
    for entry in all_entries:
        title = getattr(entry, "title", "").strip()
        if not title or title in seen_exact:
            continue
        entry_date = _entry_date(entry)
        if entry_date and entry_date != date_str:
            continue
        seen_exact.add(title)
        date_filtered.append(entry)

    # Pass 2: fuzzy title dedup
    seen_normalized: list[str] = []
    filtered: list = []
    for entry in date_filtered:
        title = getattr(entry, "title", "").strip()
        if _is_fuzzy_duplicate(title, seen_normalized):
            continue
        seen_normalized.append(_normalize_title(title))
        filtered.append(entry)

    results: list[dict] = []
    for entry in filtered[:15]:  # process up to 15 articles
        title = getattr(entry, "title", "").strip()
        google_url = getattr(entry, "link", "")

        real_url = _resolve_url(google_url)
        content = _extract_content(real_url)
        if not content:
            content = _rss_text(entry)

        # Classify sentiment on raw article body (not summary) for accuracy
        art_sentiment = "neutral"
        classify_text = content or title
        if classify_text:
            batch = sent.analyze_batch(
                [classify_text[:2000]],
                politician_name=politician_name,
            )
            art_sentiment = batch[0] if batch else "neutral"

        # Summarize separately — after sentiment so summary bias doesn't affect classification
        summary = sent.summarize(content, title) if content else title

        results.append({
            "title":          title,
            "url":            real_url,
            "source":         getattr(entry, "source_hint", "News"),
            "published_date": _entry_date(entry) or date_str,
            "summary":        summary,
            "sentiment":      art_sentiment,
        })

    return results
