import re
from difflib import SequenceMatcher

from config import TITLE_SIMILARITY_THRESHOLD


def normalize_title(title):
    title = title.lower()
    title = re.sub(r"\s*[-|]\s*[^-|]+$", "", title)  # strip trailing " - Source" / " | Source"
    title = re.sub(r"[^\w\s]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def dedup_articles(articles):
    """Pass 1: exact URL dedup. Pass 2: fuzzy title dedup (SequenceMatcher, threshold)."""
    seen_urls = set()
    url_deduped = []
    for article in articles:
        url = article.get("url")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        url_deduped.append(article)

    result = []
    normalized_kept = []
    for article in url_deduped:
        norm = normalize_title(article.get("title", ""))
        is_dup = False
        for kept_norm in normalized_kept:
            if SequenceMatcher(None, norm, kept_norm).ratio() >= TITLE_SIMILARITY_THRESHOLD:
                is_dup = True
                break
        if not is_dup:
            result.append(article)
            normalized_kept.append(norm)

    return result
