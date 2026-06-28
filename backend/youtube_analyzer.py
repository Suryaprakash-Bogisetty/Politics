"""
youtube_analyzer.py — YouTube search by date, transcript fetch, comment fetch, sentiment.

Public API:
    analyze_youtube(keywords, date_str, politician_name) → list of video result dicts
"""

import contextlib
import io
import math
import os
import time
from datetime import datetime, timedelta, timezone

import xml.etree.ElementTree as _ET

from googleapiclient.discovery import build
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
)

import sentiment as sent
from comment_filter import clean_comments

# Channels with these substrings are known credible Telugu news channels.
# Videos from channels NOT in this list are not removed, just down-weighted.
_CREDIBLE_CHANNELS = {
    "tv9", "ntv", "abn", "tv5", "sakshi", "eenadu", "hmtv", "vanitha",
    "zee telugu", "gemini", "etv", "bharat", "studio n", "10tv",
    "ys tv", "janasena", "tdp", "ycp", "ap government",
}

# Subscriber threshold below which a channel is treated as low-credibility
_MIN_SUBSCRIBERS = 10_000

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")


# ── YouTube client ─────────────────────────────────────────────────────────────

def _build_yt():
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY, cache_discovery=False)


# ── Date helpers ───────────────────────────────────────────────────────────────

def _date_range(date_str: str) -> tuple[str, str]:
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
                "video_id":    item["id"]["videoId"],
                "title":       item["snippet"]["title"],
                "channel":     item["snippet"]["channelTitle"],
                "channel_id":  item["snippet"]["channelId"],
                "publish_date": item["snippet"]["publishedAt"][:10],
                "thumbnail": (
                    item["snippet"].get("thumbnails", {})
                    .get("medium", item["snippet"].get("thumbnails", {}).get("default", {}))
                    .get("url", "")
                ),
            }
            for item in resp.get("items", [])
            if item.get("id", {}).get("kind") == "youtube#video"
        ]
    except Exception as exc:
        print(f"[YouTube search] '{keyword}' on {date_str}: {exc}")
        return []


def _is_relevant(video: dict, keywords: list[str]) -> bool:
    """Return True if any keyword appears in the video title (case-insensitive)."""
    title_lower = video["title"].lower()
    return any(k.lower() in title_lower for k in keywords if len(k) > 3)


def _fetch_channel_subscribers(channel_ids: list[str]) -> dict[str, int]:
    """Return {channel_id: subscriber_count} for up to 50 channel IDs in one API call."""
    if not channel_ids:
        return {}
    try:
        yt = _build_yt()
        resp = yt.channels().list(
            part="statistics",
            id=",".join(channel_ids[:50]),
        ).execute()
        out: dict[str, int] = {}
        for item in resp.get("items", []):
            subs = item.get("statistics", {}).get("subscriberCount")
            if subs is not None:
                out[item["id"]] = int(subs)
        return out
    except Exception as exc:
        print(f"[Channel stats] {exc}")
        return {}


def _channel_weight(channel_name: str, subscribers: int) -> float:
    """
    Return a credibility multiplier 0.5–1.5 for a channel.
    Known major news channels → 1.5. Unknown tiny channels → 0.5.
    """
    name_lower = channel_name.lower()
    is_known = any(kw in name_lower for kw in _CREDIBLE_CHANNELS)
    if is_known:
        return 1.5
    if subscribers >= 1_000_000:
        return 1.3
    if subscribers >= 100_000:
        return 1.0
    if subscribers >= _MIN_SUBSCRIBERS:
        return 0.7
    return 0.5  # very small channel — low credibility


# ── Transcript ─────────────────────────────────────────────────────────────────

def _get_transcript(video_id: str) -> tuple[str | None, str | None]:
    """Try Telugu then English then Hindi transcript. Returns (text, lang)."""
    for langs in (["te"], ["en"], ["hi"]):
        try:
            # Suppress the library's verbose multi-line error essay to stdout
            with contextlib.redirect_stdout(io.StringIO()):
                data = YouTubeTranscriptApi.get_transcript(video_id, languages=langs)
            text = " ".join(seg.get("text", "") for seg in data).strip()
            if text:
                return text, langs[0]
        except NoTranscriptFound:
            continue
        except TranscriptsDisabled:
            return None, None
        except _ET.ParseError:
            return None, None
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or "Too Many Requests" in msg:
                print(f"[Transcript] {video_id}: YouTube rate-limited (GCP IP blocked)")
            else:
                print(f"[Transcript] {video_id}: {msg[:120]}")
            return None, None
    return None, None


# ── Comments ───────────────────────────────────────────────────────────────────

def _get_comments(video_id: str, max_comments: int = 150) -> list[dict]:
    yt = _build_yt()
    comments: list[dict] = []
    page_token = None

    while len(comments) < max_comments:
        try:
            kwargs: dict = {
                "videoId":    video_id,
                "part":       "snippet",
                "maxResults": min(100, max_comments - len(comments)),
                "order":      "relevance",
                "textFormat": "plainText",
            }
            if page_token:
                kwargs["pageToken"] = page_token

            resp = yt.commentThreads().list(**kwargs).execute()
            for item in resp.get("items", []):
                top = item["snippet"]["topLevelComment"]["snippet"]
                comments.append({
                    "author": top.get("authorDisplayName", ""),
                    "text":   top.get("textDisplay", ""),
                    "likes":  top.get("likeCount", 0),
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

def analyze_youtube(keywords: list[str], date_str: str, politician_name: str = "") -> list[dict]:
    """
    Search YouTube for each keyword on date_str, deduplicate by video ID,
    filter irrelevant videos, then for each video:
      - fetch transcript + summary
      - fetch comments with like counts
      - classify sentiment, weighted by comment likes and channel credibility
    Returns list of result dicts for the frontend.
    """
    # ── Collect all unique relevant videos ────────────────────────────────────
    candidate_videos: list[dict] = []
    seen_ids: set[str] = set()

    for keyword in keywords[:3]:
        videos = _search_videos(keyword, date_str, max_results=5)
        for v in videos:
            if _is_relevant(v, keywords) and v["video_id"] not in seen_ids:
                seen_ids.add(v["video_id"])
                candidate_videos.append(v)

    # ── Fetch channel subscriber counts in one API call ───────────────────────
    channel_ids = list({v["channel_id"] for v in candidate_videos})
    subs_map = _fetch_channel_subscribers(channel_ids)

    results: list[dict] = []

    for video in candidate_videos:
        vid_id      = video["video_id"]
        url         = f"https://www.youtube.com/watch?v={vid_id}"
        channel_url = f"https://www.youtube.com/channel/{video['channel_id']}"

        subscribers   = subs_map.get(video["channel_id"], 0)
        ch_weight     = _channel_weight(video["channel"], subscribers)

        transcript_text, _ = _get_transcript(vid_id)
        summary = sent.summarize(transcript_text, video["title"]) if transcript_text else None

        raw_comments = _get_comments(vid_id, max_comments=75)

        # Strip bot/spam and collapse brigading duplicates before sentiment.
        comments, filter_stats = clean_comments(raw_comments)

        comment_texts = [c["text"] for c in comments if c.get("text")]
        details = (
            sent.analyze_batch_detailed(comment_texts, politician_name=politician_name)
            if comment_texts else []
        )

        # ── Soft, confidence- and like-weighted sentiment ──────────────────────
        # Each comment contributes:
        #   like_w     = log(likes + 1) + 1   → engagement weight
        #   confidence = 0..1 from dual-engine reconciliation
        #   score      = -1..+1 signed sentiment strength
        # A 99%-confident, highly-liked comment moves the needle far more than a
        # borderline 51%-confident one. Disagreement between engines lowers
        # confidence, so those comments barely count.
        weighted_signal = 0.0   # Σ score * like_w * confidence  (signed)
        weighted_mass   = 0.0   # Σ |contribution|               (for normalization)
        raw_pos = raw_neg = 0

        for comment, d in zip(comments, details):
            like_w     = math.log1p(comment.get("likes", 0)) + 1.0
            confidence = d["confidence"]
            score      = d["score"]
            contribution = like_w * confidence
            weighted_signal += score * contribution
            weighted_mass   += contribution
            if d["label"] == "positive":
                raw_pos += 1
            elif d["label"] == "negative":
                raw_neg += 1

        raw_decisive = raw_pos + raw_neg

        # Map mean signed score in [-1, +1] onto a positive % in [0, 100].
        if weighted_mass > 0:
            mean_score = weighted_signal / weighted_mass   # -1..+1
            pos_pct = round((mean_score + 1.0) / 2.0 * 100)
        else:
            pos_pct = 50
        neg_pct = 100 - pos_pct

        # Reliability — soft saturating curve on the decisive sample size so a
        # 4-comment video doesn't swing the platform like a 120-comment one.
        reliability = round(raw_decisive / (raw_decisive + 8), 3)

        # Carry each comment's sentiment score so topic extraction can pick the
        # highest-signal opinions later (score × engagement × confidence).
        for comment, d in zip(comments, details):
            comment["_score"]  = d["score"]
            comment["_signal"] = (math.log1p(comment.get("likes", 0)) + 1.0) * d["confidence"]

        top_comments = sorted(comments, key=lambda c: c.get("likes", 0), reverse=True)[:5]

        results.append({
            "video_id":           vid_id,
            "title":              video["title"],
            "url":                url,
            "channel":            video["channel"],
            "channel_url":        channel_url,
            "publish_date":       video["publish_date"],
            "thumbnail":          video.get("thumbnail", ""),
            "subscribers":        subscribers,
            "channel_weight":     ch_weight,
            "has_transcript":     bool(transcript_text),
            "transcript_summary": summary,
            "sentiment": {
                "positive":        pos_pct,
                "negative":        neg_pct,
                "total_comments":  len(comments),
                "decisive":        raw_decisive,
                "channel_weight":  ch_weight,
                "reliability":     reliability,
            },
            "comment_filter": filter_stats,
            "top_comments": top_comments,
            "_scored_comments": [
                {"text": c.get("text", ""), "score": c.get("_score", 0.0), "signal": c.get("_signal", 0.0)}
                for c in comments if c.get("text")
            ],
        })

        time.sleep(0.5)

    return results
