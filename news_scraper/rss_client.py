import logging
import time
import urllib.parse

import feedparser
import requests

from config import MAX_RETRIES, BASE_BACKOFF_SECONDS, TELUGU_SITES, ENGLISH_SITES

logger = logging.getLogger("news_scraper")

LANG_PARAMS = {
    "te": ("te-IN", "IN:te"),
    "en": ("en-IN", "IN:en"),
}


def build_query_url(keyword, site_domain, lang):
    hl, ceid = LANG_PARAMS[lang]
    query = f'{keyword} site:{site_domain}' if site_domain else keyword
    encoded = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={encoded}&hl={hl}&gl=IN&ceid={ceid}"


def fetch_feed(url):
    """Fetch and parse one RSS feed URL, with retry/backoff. Returns list of entries, never raises."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            return feed.entries
        except Exception as e:
            logger.warning("Fetch attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, url, e)
            if attempt < MAX_RETRIES:
                wait = BASE_BACKOFF_SECONDS ** attempt
                time.sleep(wait)
    logger.error("All retries exhausted for %s — skipping", url)
    return []


def fetch_all(keyword):
    """Fan out across all configured sites (Telugu + English) plus general queries per language.
    This query fan-out is the practical equivalent of pagination for Google News RSS,
    which has no page parameter.
    """
    all_entries = []

    for lang, sites in (("te", TELUGU_SITES), ("en", ENGLISH_SITES)):
        url = build_query_url(keyword, None, lang)
        logger.info("Fetching general %s feed", lang)
        all_entries.extend(fetch_feed(url))

        for key, (display_name, domain) in sites.items():
            url = build_query_url(keyword, domain, lang)
            logger.info("Fetching %s feed for %s", lang, display_name)
            entries = fetch_feed(url)
            for entry in entries:
                entry.source_hint = display_name
            all_entries.extend(entries)

    return all_entries
