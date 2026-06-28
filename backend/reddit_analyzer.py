"""
reddit_analyzer.py — Reddit as a free 5th platform (no API key, no PRAW).

Uses Reddit's public JSON endpoints (just needs a custom User-Agent; Reddit blocks
default UAs). Searches site-wide + AP/Telugu subreddits, fetches each post's top
comments, and runs them through the same dual-engine sentiment + weighted
aggregation as YouTube so server.py's _platform_pos_pct works unchanged.

Public API:
    analyze_reddit(keywords, date_str, politician_name) -> list[dict]
Degrades to [] on any failure (network, parse, blocked).
"""

import math
import time
from datetime import datetime, timezone

import requests

import sentiment as sent
from comment_filter import clean_comments

_UA = {"User-Agent": "ap-pulse/1.0 (sentiment research; contact via app)"}
_SUBREDDITS = ["india", "andhrapradesh", "telugu"]
_MAX_POSTS = 12
_MAX_COMMENTS_PER_POST = 30
_TIMEOUT = 12


def _get_json(url: str, params: dict | None = None) -> dict | list | None:
    try:
        resp = requests.get(url, headers=_UA, params=params, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def _search_posts(keyword: str, date_str: str) -> list[dict]:
    """Search recent posts mentioning the keyword, site-wide + target subreddits."""
    day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    day_start = day.timestamp()
    day_end = day_start + 86400

    found: dict[str, dict] = {}

    def _ingest(listing):
        for child in (listing or {}).get("data", {}).get("children", []):
            d = child.get("data", {})
            created = d.get("created_utc", 0)
            # Keep posts from the requested day (±1 day window for thin coverage)
            if not (day_start - 86400 <= created <= day_end):
                continue
            pid = d.get("id")
            if pid and pid not in found:
                found[pid] = d

    # Site-wide search
    _ingest(_get_json(
        "https://www.reddit.com/search.json",
        {"q": keyword, "sort": "new", "t": "month", "limit": 50},
    ))
    # Subreddit-scoped searches (better signal for AP/Telugu politics)
    for sub in _SUBREDDITS:
        _ingest(_get_json(
            f"https://www.reddit.com/r/{sub}/search.json",
            {"q": keyword, "restrict_sr": 1, "sort": "new", "t": "month", "limit": 25},
        ))
        time.sleep(0.3)

    posts = sorted(found.values(), key=lambda d: d.get("score", 0), reverse=True)
    return posts[:_MAX_POSTS]


def _fetch_comments(permalink: str) -> list[dict]:
    """Fetch top-level comments for a post."""
    data = _get_json(f"https://www.reddit.com{permalink}.json", {"limit": _MAX_COMMENTS_PER_POST})
    if not isinstance(data, list) or len(data) < 2:
        return []
    out: list[dict] = []
    for child in data[1].get("data", {}).get("children", []):
        d = child.get("data", {})
        body = d.get("body")
        if body and body not in ("[deleted]", "[removed]"):
            out.append({"text": body, "likes": int(d.get("score", 0) or 0)})
        if len(out) >= _MAX_COMMENTS_PER_POST:
            break
    return out


def analyze_reddit(keywords: list[str], date_str: str, politician_name: str = "") -> list[dict]:
    try:
        candidates: dict[str, dict] = {}
        for kw in keywords[:2]:
            for post in _search_posts(kw, date_str):
                candidates.setdefault(post.get("id"), post)

        results: list[dict] = []
        for post in list(candidates.values())[:_MAX_POSTS]:
            permalink = post.get("permalink", "")
            raw_comments = _fetch_comments(permalink) if permalink else []
            comments, _ = clean_comments(raw_comments)
            texts = [c["text"] for c in comments if c.get("text")]
            details = (
                sent.analyze_batch_detailed(texts, politician_name=politician_name)
                if texts else []
            )

            # Same weighted-signal/mass aggregation as YouTube.
            weighted_signal = weighted_mass = 0.0
            raw_pos = raw_neg = 0
            for c, d in zip(comments, details):
                like_w = math.log1p(c.get("likes", 0)) + 1.0
                contribution = like_w * d["confidence"]
                weighted_signal += d["score"] * contribution
                weighted_mass += contribution
                c["_score"] = d["score"]
                c["_signal"] = contribution
                if d["label"] == "positive":
                    raw_pos += 1
                elif d["label"] == "negative":
                    raw_neg += 1

            decisive = raw_pos + raw_neg
            if weighted_mass > 0:
                mean_score = weighted_signal / weighted_mass
                pos_pct = round((mean_score + 1.0) / 2.0 * 100)
            else:
                pos_pct = 50
            reliability = round(decisive / (decisive + 8), 3)

            results.append({
                "post_id":    post.get("id", ""),
                "title":      post.get("title", ""),
                "subreddit":  post.get("subreddit", ""),
                "url":        f"https://www.reddit.com{permalink}",
                "post_date":  datetime.fromtimestamp(
                                  post.get("created_utc", 0), tz=timezone.utc
                              ).strftime("%Y-%m-%d"),
                "score":      int(post.get("score", 0) or 0),
                "sentiment": {
                    "positive":       pos_pct,
                    "negative":       100 - pos_pct,
                    "total_comments": len(comments),
                    "decisive":       decisive,
                    "channel_weight": 1.0,
                    "reliability":    reliability,
                },
                "_scored_comments": [
                    {"text": c.get("text", ""), "score": c.get("_score", 0.0), "signal": c.get("_signal", 0.0)}
                    for c in comments if c.get("text")
                ],
            })
            time.sleep(0.3)

        return results
    except Exception as exc:
        print(f"[Reddit] error: {exc}")
        return []
