"""
Stage 1 — Find Facebook post URLs by scraping pages directly via Apify.
Uses apify/facebook-posts-scraper — no search engine, no Google billing.

One Apify run covers all configured pages. Posts are filtered by date
(last DATE_RANGE_DAYS days) and tagged with the first matched keyword.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from apify_client import ApifyClient
from dotenv import load_dotenv
from tqdm import tqdm

import config
from keyword_filter import first_match, keyword_stats

log = logging.getLogger(__name__)
load_dotenv()

ACTOR = "apify/facebook-posts-scraper"


# ── Credentials ───────────────────────────────────────────────────────────────

def _get_client() -> ApifyClient:
    token = os.getenv("APIFY_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("APIFY_API_TOKEN not set in .env")
    return ApifyClient(token)


# ── Normaliser ────────────────────────────────────────────────────────────────

def _is_post_url(url: str) -> bool:
    return any(s in url for s in ["/posts/", "story_fbid=", "pfbid", "permalink.php", "/videos/", "/reel/"])


def _normalize_post(item: dict) -> dict | None:
    """Convert Apify facebook-posts-scraper item to our post schema."""
    post_url = item.get("topLevelUrl") or item.get("url", "")
    if not post_url or not _is_post_url(post_url):
        return None

    input_url  = item.get("inputUrl") or item.get("facebookUrl", "")
    page_slug  = item.get("pageName") or input_url.rstrip("/").split("/")[-1]
    text       = item.get("text", "")
    matched_kw = first_match(text)

    return {
        "post_id":         item.get("postId", ""),
        "post_url":        post_url,
        "post_text":       text,
        "post_date":       item.get("time", ""),
        "page_name":       page_slug,
        "page_url":        input_url,
        "likes":           item.get("likes", 0),
        "comments_count":  item.get("comments", 0),
        "shares_count":    item.get("shares", 0),
        "matched_keyword": matched_kw,
    }


# ── Date filter ───────────────────────────────────────────────────────────────

def _is_recent(post: dict) -> bool:
    """Return True if post is within DATE_RANGE_DAYS or has no date."""
    date_str = post.get("post_date", "")
    if not date_str:
        return True
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days <= config.DATE_RANGE_DAYS
    except Exception:
        return True


# ── Stage 1 entry point ───────────────────────────────────────────────────────

def run_stage1(pages: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    """
    Scrape Facebook pages directly via Apify facebook-posts-scraper.
    Returns (all_posts, keyword_filtered_posts).
    Saves raw_posts.json and filtered_posts.json as side effects.

    Args:
        pages: override page list (used by --test mode in main.py)
    """
    client    = _get_client()
    page_list = pages or config.FACEBOOK_PAGES

    log.info(
        "Running %s for %d pages (resultsLimit=%d per page)...",
        ACTOR, len(page_list), config.MAX_POSTS_PER_PAGE,
    )

    # ── Single Apify run for all pages ────────────────────────────────────────
    run = client.actor(ACTOR).call(run_input={
        "startUrls":       [{"url": u} for u in page_list],
        "resultsLimit":    config.MAX_POSTS_PER_PAGE,
        "maxPostComments": 0,
    })

    log.info("Actor run status: %s", run.status)

    if run.status != "SUCCEEDED":
        log.error("Actor run failed — status: %s", run.status)
        return [], []

    # ── Fetch results ─────────────────────────────────────────────────────────
    raw_items = list(client.dataset(run.default_dataset_id).iterate_items())
    log.info("Total raw items from Apify: %d", len(raw_items))

    # Per-page count logging
    page_counts: dict[str, int] = {}
    for item in raw_items:
        input_url = item.get("inputUrl") or item.get("facebookUrl", "unknown")
        slug = input_url.rstrip("/").split("/")[-1]
        page_counts[slug] = page_counts.get(slug, 0) + 1
    for slug, cnt in page_counts.items():
        log.info("  Page %-25s → %d raw posts", slug, cnt)

    # ── Normalize + date filter ───────────────────────────────────────────────
    all_posts: list[dict] = []
    for item in raw_items:
        post = _normalize_post(item)
        if post and _is_recent(post):
            all_posts.append(post)

    log.info("After date filter: %d posts", len(all_posts))

    # ── Deduplicate by post_url ───────────────────────────────────────────────
    seen: set[str] = set()
    deduped: list[dict] = []
    for p in all_posts:
        if p["post_url"] not in seen:
            seen.add(p["post_url"])
            deduped.append(p)
    if len(deduped) < len(all_posts):
        log.info("Deduped %d duplicate post URLs", len(all_posts) - len(deduped))
    all_posts = deduped

    # Save raw (pre-keyword-filter) posts
    Path(config.RAW_POSTS_FILE).write_text(
        json.dumps(all_posts, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ── Keyword filter ────────────────────────────────────────────────────────
    # Posts come from political pages so all are relevant.
    # Tag each with a keyword (from text match, or default first keyword).
    filtered: list[dict] = []
    for post in all_posts:
        if not post.get("matched_keyword"):
            kw = first_match(post["post_text"])
            post["matched_keyword"] = kw if kw else config.KEYWORDS[0]
        filtered.append(post)

    # ── Keyword stats ─────────────────────────────────────────────────────────
    print("\n--- Keyword Stats (Stage 1) ---")
    stats = keyword_stats(filtered)
    for kw, count in stats.items():
        print(f"  {kw}: {count} posts")
    print(f"  Total keyword-matched posts: {len(filtered)}")
    print()

    Path(config.FILTERED_POSTS_FILE).write_text(
        json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    log.info("Stage 1 complete — %d posts saved to %s", len(filtered), config.FILTERED_POSTS_FILE)
    return all_posts, filtered
