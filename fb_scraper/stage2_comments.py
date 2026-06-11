"""
Stage 2 — Scrape Facebook comments per batch using apify/facebook-comments-scraper.
Input: keyword-filtered post URLs from Stage 1.
Output: language-filtered, deduplicated comment list.
"""

import json
import time
import logging
from pathlib import Path

from apify_client import ApifyClient
from tqdm import tqdm

import config
from language_filter import detect_language, is_relevant

log = logging.getLogger(__name__)


# ── Apify helpers ─────────────────────────────────────────────────────────────

def _poll_until_done(client: ApifyClient, run_id: str, label: str = ""):
    while True:
        run = client.run(run_id).get()
        status = run.status
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            return run
        log.debug("  Comments run %s [%s]: %s", run_id, label, status)
        time.sleep(config.POLL_INTERVAL_SECONDS)


def _start_with_retry(
    client: ApifyClient,
    actor_id: str,
    run_input: dict,
    label: str,
) -> str | None:
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            run = client.actor(actor_id).start(
                run_input=run_input,
                memory_mbytes=1024,     # stay within free plan 8192MB total
            )
            log.info("  Started %s attempt %d — run_id: %s", actor_id, attempt, run.id)
            return run.id
        except Exception as exc:
            wait = config.BASE_BACKOFF_SECONDS ** attempt
            log.warning(
                "  Attempt %d/%d FAILED for %s [%s]: %s — retry in %ds",
                attempt, config.MAX_RETRIES, actor_id, label, exc, wait,
            )
            if attempt == config.MAX_RETRIES:
                log.error("  All retries exhausted for %s [%s].", actor_id, label)
                return None
            time.sleep(wait)
    return None


# ── Comment normalisation ─────────────────────────────────────────────────────

def _coerce_int(val) -> int:
    if val is None:
        return 0
    if isinstance(val, dict):
        val = val.get("count", 0)
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def _normalize_comment(item: dict, post_map: dict[str, dict], post_id_map: dict[str, dict]) -> dict | None:
    """
    Map a raw Apify comment item to our internal schema.
    post_map     : {post_url  → post_dict} — primary join key
    post_id_map  : {post_id   → post_dict} — fallback join key
    Apify's comment output postUrl often differs in format from the URL we
    submitted (e.g. permalink.php vs /posts/123), so both lookups are needed.
    Returns None if both comment_id and comment_text are empty.
    """
    comment_id = (
        item.get("id")
        or item.get("commentId")
        or item.get("fbid")
        or ""
    )
    text = (
        item.get("text")
        or item.get("message")
        or item.get("commentText")
        or ""
    )
    if not comment_id and not text:
        return None

    author = (
        item.get("profileName")
        or item.get("authorName")
        or item.get("userName")
        or ""
    )
    raw_date = item.get("date") or item.get("time") or item.get("publishedAt") or ""
    likes = _coerce_int(item.get("likes") or item.get("likesCount"))
    is_reply = bool(item.get("isReply") or item.get("parentCommentId"))
    parent_comment_id = str(
        item.get("parentCommentId") or item.get("replyToId") or ""
    )

    # Post URL from comment item
    post_url = (
        item.get("postUrl")
        or item.get("url")
        or item.get("pageUrl")
        or ""
    )

    # Join: try exact URL match first, then fall back to post_id embedded in URL
    post_meta = post_map.get(post_url, {})
    if not post_meta:
        # Extract numeric post ID from URL (works for both /posts/ID and story_fbid=ID)
        import re
        id_match = re.search(r"(?:posts/|story_fbid=|fbid=)(\d+)", post_url)
        if id_match:
            post_meta = post_id_map.get(id_match.group(1), {})
    if not post_meta:
        # Last resort: check if comment item carries postId directly
        raw_pid = str(item.get("postId") or item.get("pageId") or "")
        if raw_pid:
            post_meta = post_id_map.get(raw_pid, {})

    return {
        "comment_id": str(comment_id),
        "comment_text": text,
        "comment_author": author,
        "comment_date": str(raw_date),
        "comment_likes": likes,
        "is_reply": is_reply,
        "parent_comment_id": parent_comment_id,
        "post_id": post_meta.get("post_id", ""),
        "post_url": post_url,
        "post_text": post_meta.get("post_text", ""),
        "post_date": post_meta.get("post_date", ""),
        "page_name": post_meta.get("page_name", ""),
        "matched_keyword": post_meta.get("matched_keyword", ""),
        # language fields added later in the filter pass
        "language": "",
        "detected_script": "",
    }


# ── Single batch scraper ──────────────────────────────────────────────────────

def _scrape_batch(
    client: ApifyClient,
    post_urls: list[str],
    post_map: dict[str, dict],
    post_id_map: dict[str, dict],
    batch_num: int,
) -> list[dict]:
    """Run comments actor for one batch of post URLs."""
    label = f"batch-{batch_num}"
    log.info("Comments %s — %d post URLs", label, len(post_urls))

    run_input = {
        "startUrls": [{"url": url} for url in post_urls],
        "maxComments": None,        # None/null = no limit (0 means zero on most actors)
        "maxReplies": None,         # None/null = fetch all replies
        "includeReplies": True,     # correct field name for this actor
    }

    run_id = _start_with_retry(client, config.ACTOR_COMMENTS, run_input, label=label)
    if run_id is None:
        return []

    run_info = _poll_until_done(client, run_id, label=label)
    if run_info.status != "SUCCEEDED":
        log.error("Comments actor FAILED for %s — skipping batch.", label)
        return []

    dataset_id = run_info.default_dataset_id
    if not dataset_id:
        log.warning("No dataset ID from comments run %s.", label)
        return []

    raw_items = list(client.dataset(dataset_id).iterate_items())
    log.info("  %s — %d raw comment items fetched", label, len(raw_items))

    comments: list[dict] = []
    for item in raw_items:
        c = _normalize_comment(item, post_map, post_id_map)
        if c:
            comments.append(c)
    return comments


# ── Stage 2 entry point ───────────────────────────────────────────────────────

def run_stage2(
    client: ApifyClient,
    filtered_posts: list[dict],
) -> tuple[list[dict], dict]:
    """
    Scrape, language-filter, and deduplicate comments for all filtered posts.

    Returns:
        (final_comments, stats) where stats has keys:
        raw_total, telugu, english, unknown_kept, duplicates_removed
    """
    if not filtered_posts:
        log.warning("No filtered posts provided — Stage 2 skipped.")
        return [], {"raw_total": 0, "telugu": 0, "english": 0, "unknown_kept": 0, "duplicates_removed": 0}

    # Primary lookup: post_url → post dict
    post_map: dict[str, dict] = {
        p["post_url"]: p for p in filtered_posts if p.get("post_url")
    }
    # Fallback lookup: post_id → post dict (for URL format mismatches)
    post_id_map: dict[str, dict] = {
        p["post_id"]: p for p in filtered_posts if p.get("post_id")
    }
    post_urls = list(post_map.keys())
    log.info("Stage 2 — %d post URLs across %d batches of %d",
             len(post_urls),
             -(-len(post_urls) // config.COMMENTS_BATCH_SIZE),
             config.COMMENTS_BATCH_SIZE)

    # Split into batches
    batches = [
        post_urls[i: i + config.COMMENTS_BATCH_SIZE]
        for i in range(0, len(post_urls), config.COMMENTS_BATCH_SIZE)
    ]

    all_raw: list[dict] = []
    with tqdm(batches, desc="Stage 2 — batches", unit="batch", ncols=90) as pbar:
        for batch_num, batch in enumerate(pbar, start=1):
            pbar.set_description(f"Stage 2 — batch {batch_num}/{len(batches)}")
            comments = _scrape_batch(client, batch, post_map, post_id_map, batch_num)
            all_raw.extend(comments)

    log.info("Stage 2 raw total: %d comments", len(all_raw))

    # Persist raw comments before filtering
    Path(config.RAW_COMMENTS_FILE).write_text(
        json.dumps(all_raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ── Language filter ───────────────────────────────────────────────────────
    lang_filtered: list[dict] = []
    te_count = en_count = unknown_kept = 0

    for c in all_raw:
        text = c.get("comment_text", "")
        lang, script = detect_language(text)
        c["language"] = lang
        c["detected_script"] = script

        if is_relevant(text, lang):
            lang_filtered.append(c)
            if lang == "te":
                te_count += 1
            elif lang == "en":
                en_count += 1
        elif lang == "unknown":
            # langdetect failed — keep by default as per spec
            c["language"] = "unknown"
            lang_filtered.append(c)
            unknown_kept += 1

    log.info("After language filter: %d kept (te=%d, en=%d, unknown=%d)",
             len(lang_filtered), te_count, en_count, unknown_kept)

    # ── Deduplication by comment_id ───────────────────────────────────────────
    seen: set[str] = set()
    final: list[dict] = []
    duplicates_removed = 0

    for c in lang_filtered:
        cid = c["comment_id"]
        if cid in seen:
            duplicates_removed += 1
            continue
        seen.add(cid)
        final.append(c)

    log.info("Duplicates removed: %d — final count: %d", duplicates_removed, len(final))

    stats = {
        "raw_total": len(all_raw),
        "telugu": te_count,
        "english": en_count,
        "unknown_kept": unknown_kept,
        "duplicates_removed": duplicates_removed,
    }
    return final, stats
