"""
youtube_analyzer.py — YouTube search by date, transcript fetch, comment fetch, sentiment.

Public API:
    analyze_youtube(keywords, date_str) → list of video result dicts
"""

import os
import time
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
)

import sentiment as sent

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")


# ── YouTube client ─────────────────────────────────────────────────────────────

def _build_yt():
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY, cache_discovery=False)


# ── Date helpers ───────────────────────────────────────────────────────────────

def _date_range(date_str: str) -> tuple[str, str]:
    """Return ISO 8601 publishedAfter/publishedBefore for a single calendar day."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return dt.isoformat(), (dt + timedelta(days=1)).isoformat()


# ── Video search ───────────────────────────────────────────────────────────────

def _search_videos(keyword: str, date_str: str, max_results: int = 5) -> list[dict]:
    published_after, published_before = _date_range(date_str)
    try:
        yt = _build_yt()
        resp = yt.search().list(
            q=keyword,
            part="snippet",
            type="video",
            maxResults=max_results,
            publishedAfter=published_after,
            publishedBefore=published_before,
            order="relevance",
            regionCode="IN",
        ).execute()
        return [
            {
                "video_id": item["id"]["videoId"],
                "title": item["snippet"]["title"],
                "channel": item["snippet"]["channelTitle"],
                "channel_id": item["snippet"]["channelId"],
                "publish_date": item["snippet"]["publishedAt"][:10],
                "thumbnail": (
                    item["snippet"].get("thumbnails", {})
                    .get("default", {})
                    .get("url", "")
                ),
            }
            for item in resp.get("items", [])
            if item.get("id", {}).get("kind") == "youtube#video"
        ]
    except Exception as exc:
        print(f"[YouTube search] '{keyword}' on {date_str}: {exc}")
        return []


# ── Transcript ─────────────────────────────────────────────────────────────────

def _get_transcript(video_id: str) -> tuple[str | None, str | None]:
    """Try Telugu then English then any available transcript. Returns (text, lang)."""
    try:
        api = YouTubeTranscriptApi()
        for langs in (["te"], ["en"], None):
            try:
                if langs is not None:
                    fetched = api.fetch(video_id, languages=langs)
                else:
                    tlist = api.list(video_id)
                    first = next(iter(tlist), None)
                    if first is None:
                        return None, None
                    fetched = first.fetch()

                text = " ".join(
                    seg.text if hasattr(seg, "text") else seg.get("text", "")
                    for seg in fetched
                ).strip()
                if text:
                    lang = langs[0] if langs else "unknown"
                    return text, lang
            except NoTranscriptFound:
                continue
    except (TranscriptsDisabled, Exception) as exc:
        print(f"[Transcript] {video_id}: {exc}")
    return None, None


# ── Comments ───────────────────────────────────────────────────────────────────

def _get_comments(video_id: str, max_comments: int = 50) -> list[dict]:
    yt = _build_yt()
    comments: list[dict] = []
    page_token = None

    while len(comments) < max_comments:
        try:
            kwargs: dict = {
                "videoId": video_id,
                "part": "snippet",
                "maxResults": min(100, max_comments - len(comments)),
                "order": "relevance",
                "textFormat": "plainText",
            }
            if page_token:
                kwargs["pageToken"] = page_token

            resp = yt.commentThreads().list(**kwargs).execute()
            for item in resp.get("items", []):
                top = item["snippet"]["topLevelComment"]["snippet"]
                comments.append({
                    "author": top.get("authorDisplayName", ""),
                    "text": top.get("textDisplay", ""),
                    "likes": top.get("likeCount", 0),
                })
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        except Exception as exc:
            msg = str(exc)
            if "commentsDisabled" not in msg and "403" not in msg:
                print(f"[Comments] {video_id}: {exc}")
            break

    return comments


# ── Main entry point ───────────────────────────────────────────────────────────

def analyze_youtube(keywords: list[str], date_str: str) -> list[dict]:
    """
    Search YouTube for each keyword on date_str, deduplicate by video ID,
    then for each video fetch transcript + summary + comments + sentiment.
    Returns list of result dicts for the frontend.
    """
    results: list[dict] = []
    seen_ids: set[str] = set()

    for keyword in keywords[:2]:  # cap at 2 keywords to preserve API quota
        videos = _search_videos(keyword, date_str, max_results=5)
        for video in videos:
            vid_id = video["video_id"]
            if vid_id in seen_ids:
                continue
            seen_ids.add(vid_id)

            url = f"https://www.youtube.com/watch?v={vid_id}"
            channel_url = f"https://www.youtube.com/channel/{video['channel_id']}"

            # Transcript
            transcript_text, _ = _get_transcript(vid_id)

            # Summary via Groq
            summary = (
                sent.summarize(transcript_text, video["title"])
                if transcript_text
                else None
            )

            # Comments
            comments = _get_comments(vid_id, max_comments=50)

            # Sentiment on comment texts
            comment_texts = [c["text"] for c in comments if c.get("text")]
            sentiments = sent.analyze_batch(comment_texts) if comment_texts else []

            pos_count = sum(1 for s in sentiments if s == "positive")
            neg_count = sum(1 for s in sentiments if s == "negative")
            total = len(sentiments) or 1

            # Top 5 comments sorted by likes
            top_comments = sorted(comments, key=lambda c: c.get("likes", 0), reverse=True)[:5]

            results.append({
                "video_id": vid_id,
                "title": video["title"],
                "url": url,
                "channel": video["channel"],
                "channel_url": channel_url,
                "publish_date": video["publish_date"],
                "thumbnail": video.get("thumbnail", ""),
                "has_transcript": bool(transcript_text),
                "transcript_summary": summary,
                "sentiment": {
                    "positive": round(pos_count / total * 100),
                    "negative": round(neg_count / total * 100),
                    "total_comments": len(comments),
                },
                "top_comments": top_comments,
            })

        time.sleep(0.5)  # brief pause between keyword searches

    return results
