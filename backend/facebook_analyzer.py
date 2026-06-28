"""
facebook_analyzer.py — Facebook Graph API posts + comments + Groq sentiment.

Public API:
    analyze_facebook(page_ids, keyword, date_str, politician_name) → list of post result dicts

Requires:
    FACEBOOK_ACCESS_TOKEN in .env (free permanent page token from Meta Developer Portal)
    pip install requests

Graph API endpoints used:
    GET /{page_id}/posts  — fetch recent posts with engagement metrics
    GET /{post_id}/comments — fetch comments on filtered posts
"""

import os
from datetime import datetime, timezone

import requests

import sentiment as sent

FACEBOOK_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN", "")
GRAPH_BASE = "https://graph.facebook.com/v19.0"
MAX_POSTS_PER_PAGE = 25
MAX_COMMENTS_PER_POST = 50


def _get(endpoint: str, params: dict) -> dict:
    params["access_token"] = FACEBOOK_ACCESS_TOKEN
    try:
        resp = requests.get(f"{GRAPH_BASE}/{endpoint}", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"[Facebook] GET /{endpoint}: {exc}")
        return {}


def _fetch_posts(page_id: str, date_str: str) -> list[dict]:
    """Fetch posts from a page published on the target date."""
    data = _get(f"{page_id}/posts", {
        "fields": "id,message,story,created_time,permalink_url,likes.summary(true),comments.summary(true)",
        "limit":  MAX_POSTS_PER_PAGE,
    })
    posts = []
    for item in data.get("data", []):
        created = item.get("created_time", "")
        # Parse ISO 8601 → date string
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            post_date = dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            post_date = ""

        if post_date != date_str:
            continue

        posts.append({
            "post_id":       item.get("id", ""),
            "text":          item.get("message") or item.get("story") or "",
            "created_time":  created,
            "post_date":     post_date,
            "url":           item.get("permalink_url", ""),
            "likes":         item.get("likes", {}).get("summary", {}).get("total_count", 0),
            "comment_count": item.get("comments", {}).get("summary", {}).get("total_count", 0),
            "page_id":       page_id,
        })
    return posts


def _fetch_comments(post_id: str) -> list[str]:
    """Fetch top-level comment texts for a post."""
    data = _get(f"{post_id}/comments", {
        "fields": "message,like_count",
        "limit":  MAX_COMMENTS_PER_POST,
    })
    return [
        item.get("message", "")
        for item in data.get("data", [])
        if item.get("message", "").strip()
    ]


def analyze_facebook(
    page_ids: list[str],
    keyword: str,
    date_str: str,
    politician_name: str = "",
) -> list[dict]:
    """
    Fetch posts + comments from Facebook pages for the target date.
    Classifies comment sentiment via Groq.
    Falls back to [] if no access token is configured.
    """
    if not FACEBOOK_ACCESS_TOKEN:
        print("[Facebook] FACEBOOK_ACCESS_TOKEN not set — skipping Facebook analysis")
        return []

    results: list[dict] = []

    for page_id in page_ids:
        posts = _fetch_posts(page_id, date_str)

        for post in posts:
            # Filter: post text must mention keyword (case-insensitive)
            text_lower = post["text"].lower()
            kw_lower   = keyword.lower()
            if kw_lower and kw_lower not in text_lower:
                continue

            comments = _fetch_comments(post["post_id"])

            sentiments: list[str] = []
            if comments:
                sentiments = sent.analyze_batch(comments, politician_name=politician_name)

            pos = sum(1 for s in sentiments if s == "positive")
            neg = sum(1 for s in sentiments if s == "negative")
            total = len(sentiments) or 1

            results.append({
                "post_id":      post["post_id"],
                "page_id":      page_id,
                "text":         post["text"],
                "url":          post["url"],
                "post_date":    post["post_date"],
                "likes":        post["likes"],
                "comment_count": post["comment_count"],
                "sentiment": {
                    "positive":       round(pos / total * 100),
                    "negative":       round(neg / total * 100),
                    "total_comments": len(comments),
                    "total":          len(comments),
                },
                "sample_comments": comments[:3],
            })

    return results
