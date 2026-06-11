"""
YouTube Comments Scraper — Telugu Political Sentiment Analysis
"""

import os
import sys
import time
import logging
from pathlib import Path

import pandas as pd
from tqdm import tqdm
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from langdetect import detect, LangDetectException

import config

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
load_dotenv()
API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
if not API_KEY:
    log.error("YOUTUBE_API_KEY not set in .env — aborting.")
    sys.exit(1)

Path(config.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_client():
    return build("youtube", "v3", developerKey=API_KEY, cache_discovery=False)


def with_retry(fn, *args, keyword="", video_id="", **kwargs):
    """Call fn with exponential backoff. Returns None on quota exhaustion."""
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except HttpError as exc:
            reason = exc.reason if hasattr(exc, "reason") else str(exc)
            code = exc.resp.status

            if code == 403 and "quotaExceeded" in str(exc.content):
                log.warning(
                    "Quota exceeded (keyword=%r, video=%s). "
                    "Pausing %ds before retry %d/%d.",
                    keyword, video_id, config.QUOTA_PAUSE_SECONDS,
                    attempt, config.MAX_RETRIES,
                )
                time.sleep(config.QUOTA_PAUSE_SECONDS)

            elif code == 403 and "commentsDisabled" in str(exc.content):
                log.info("Comments disabled — skipping video %s", video_id)
                return None

            elif code in (400, 404):
                log.warning("Unrecoverable API error %d for video %s: %s", code, video_id, reason)
                return None

            else:
                wait = config.BASE_BACKOFF ** attempt
                log.warning(
                    "HTTP %d on attempt %d/%d for video=%s — retrying in %ds. %s",
                    code, attempt, config.MAX_RETRIES, video_id, wait, reason,
                )
                time.sleep(wait)

    log.error("All retries exhausted (keyword=%r, video=%s).", keyword, video_id)
    return None


def contains_telugu(text: str) -> bool:
    lo, hi = config.TELUGU_UNICODE_RANGE
    return any(lo <= ord(ch) <= hi for ch in text)


def detect_language(text: str) -> str:
    """Return ISO 639-1 code. Falls back to 'te' if text has Telugu chars, else 'unknown'."""
    try:
        return detect(text)
    except LangDetectException:
        return "te" if contains_telugu(text) else "unknown"


def is_relevant_language(text: str, lang: str) -> bool:
    if lang in config.KEEP_LANGUAGES:
        return True
    # langdetect sometimes misclassifies Telugu → keep by Unicode fallback
    if contains_telugu(text):
        return True
    return False


# ---------------------------------------------------------------------------
# YouTube API calls
# ---------------------------------------------------------------------------

def search_videos(youtube, keyword: str, order: str) -> list[dict]:
    """Return up to MAX_VIDEOS_PER_KEYWORD video stubs for a keyword + sort order."""
    videos: list[dict] = []
    page_token = None

    while len(videos) < config.MAX_VIDEOS_PER_KEYWORD:
        remaining = config.MAX_VIDEOS_PER_KEYWORD - len(videos)
        per_page = min(50, remaining)

        def _call():
            req = youtube.search().list(
                part="snippet",
                q=keyword,
                type="video",
                order=order,
                publishedAfter=config.PUBLISHED_AFTER,
                maxResults=per_page,
                pageToken=page_token,
                relevanceLanguage="te",
                regionCode="IN",
            )
            return req.execute()

        result = with_retry(_call, keyword=keyword)
        if result is None:
            break

        for item in result.get("items", []):
            vid_id = item["id"].get("videoId")
            if not vid_id:
                continue
            snippet = item.get("snippet", {})
            videos.append({
                "video_id": vid_id,
                "video_title": snippet.get("title", ""),
                "channel_name": snippet.get("channelTitle", ""),
            })

        page_token = result.get("nextPageToken")
        if not page_token or len(videos) >= config.MAX_VIDEOS_PER_KEYWORD:
            break

    return videos[:config.MAX_VIDEOS_PER_KEYWORD]


def fetch_all_videos_for_keyword(youtube, keyword: str) -> list[dict]:
    """Fetch recent + viral videos, deduplicate, return combined list."""
    recent = search_videos(youtube, keyword, config.SEARCH_ORDER)
    viral = search_videos(youtube, keyword, config.SEARCH_ORDER_VIRAL)

    seen: set[str] = set()
    combined: list[dict] = []
    for v in recent + viral:
        if v["video_id"] not in seen:
            seen.add(v["video_id"])
            combined.append(v)

    log.info("Keyword %r — %d unique videos found.", keyword, len(combined))
    return combined[:config.MAX_VIDEOS_PER_KEYWORD]


def fetch_comments_for_video(
    youtube,
    video: dict,
    keyword: str,
) -> list[dict]:
    """Fetch all top-level comments + replies for a video, filtered by language."""
    video_id = video["video_id"]
    rows: list[dict] = []
    page_token = None

    while True:
        def _call(pt=page_token):
            req = youtube.commentThreads().list(
                part="snippet,replies",
                videoId=video_id,
                maxResults=100,
                pageToken=pt,
                textFormat="plainText",
            )
            return req.execute()

        result = with_retry(_call, keyword=keyword, video_id=video_id)
        if result is None:
            break

        for thread in result.get("items", []):
            top = thread["snippet"]["topLevelComment"]
            top_snip = top["snippet"]
            top_text = top_snip.get("textDisplay", "")
            top_lang = detect_language(top_text)

            if is_relevant_language(top_text, top_lang):
                rows.append({
                    "video_id": video_id,
                    "video_title": video["video_title"],
                    "channel_name": video["channel_name"],
                    "keyword_used": keyword,
                    "comment_id": top["id"],
                    "author": top_snip.get("authorDisplayName", ""),
                    "comment_text": top_text,
                    "language": top_lang,
                    "published_at": top_snip.get("publishedAt", ""),
                    "like_count": top_snip.get("likeCount", 0),
                    "is_reply": False,
                    "parent_comment_id": "",
                })

            # Replies embedded in the thread
            for reply in thread.get("replies", {}).get("comments", []):
                r_snip = reply["snippet"]
                r_text = r_snip.get("textDisplay", "")
                r_lang = detect_language(r_text)

                if is_relevant_language(r_text, r_lang):
                    rows.append({
                        "video_id": video_id,
                        "video_title": video["video_title"],
                        "channel_name": video["channel_name"],
                        "keyword_used": keyword,
                        "comment_id": reply["id"],
                        "author": r_snip.get("authorDisplayName", ""),
                        "comment_text": r_text,
                        "language": r_lang,
                        "published_at": r_snip.get("publishedAt", ""),
                        "like_count": r_snip.get("likeCount", 0),
                        "is_reply": True,
                        "parent_comment_id": r_snip.get("parentId", ""),
                    })

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    youtube = build_client()
    all_rows: list[dict] = []

    # Track unique comment IDs globally to deduplicate across keywords
    seen_comment_ids: set[str] = set()
    duplicates_removed = 0

    total_videos = 0
    telugu_count = 0
    english_count = 0

    for keyword in config.KEYWORDS:
        log.info("=" * 60)
        log.info("Processing keyword: %r", keyword)

        videos = fetch_all_videos_for_keyword(youtube, keyword)
        if not videos:
            log.warning("No videos found for keyword %r — skipping.", keyword)
            continue

        keyword_comments = 0

        with tqdm(videos, desc=f"  [{keyword}]", unit="video", ncols=80) as pbar:
            for video in pbar:
                rows = fetch_comments_for_video(youtube, video, keyword)
                video_new = 0

                for row in rows:
                    cid = row["comment_id"]
                    if cid in seen_comment_ids:
                        duplicates_removed += 1
                        continue
                    seen_comment_ids.add(cid)
                    all_rows.append(row)
                    video_new += 1

                    if row["language"] == "te" or contains_telugu(row["comment_text"]):
                        telugu_count += 1
                    elif row["language"] == "en":
                        english_count += 1

                pbar.set_postfix(new=video_new)
                log.info(
                    "    video=%s  fetched=%d  kept=%d",
                    video["video_id"], len(rows), video_new,
                )
                keyword_comments += video_new
                total_videos += 1

        log.info("Keyword %r — total new comments: %d", keyword, keyword_comments)

    # -------------------------------------------------------------------
    # Save CSV
    # -------------------------------------------------------------------
    if all_rows:
        df = pd.DataFrame(all_rows, columns=config.CSV_COLUMNS)
        df.to_csv(config.OUTPUT_FILE, index=False, encoding="utf-8-sig")
    else:
        log.warning("No comments collected — empty CSV will be written.")
        pd.DataFrame(columns=config.CSV_COLUMNS).to_csv(
            config.OUTPUT_FILE, index=False, encoding="utf-8-sig"
        )

    # -------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------
    print()
    print("=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"Total videos processed : {total_videos}")
    print(f"Total comments collected: {len(all_rows)}")
    print(f"Telugu comments         : {telugu_count}")
    print(f"English comments        : {english_count}")
    print(f"Duplicates removed      : {duplicates_removed}")
    print(f"Output saved to         : {config.OUTPUT_FILE}")
    print("=" * 50)


if __name__ == "__main__":
    main()
