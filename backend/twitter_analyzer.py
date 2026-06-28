"""
twitter_analyzer.py — Twitter/X API v2 search + Groq sentiment.

Public API:
    analyze_twitter(keywords, date_str, politician_name) → list of tweet result dicts

Requires:
    TWITTER_BEARER_TOKEN in .env (Twitter Basic tier, $100/month)
    pip install tweepy>=4.14.0
"""

import os
from datetime import datetime, timedelta, timezone

import sentiment as sent
from comment_filter import clean_comments

TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")
MAX_TWEETS = 100


def analyze_twitter(keywords: list[str], date_str: str, politician_name: str = "") -> list[dict]:
    """
    Search Twitter/X for tweets about the politician on date_str.
    Returns list of tweet dicts with sentiment classification.

    Falls back to [] gracefully if no API token is configured.
    """
    if not TWITTER_BEARER_TOKEN:
        print("[Twitter] TWITTER_BEARER_TOKEN not set — skipping Twitter analysis")
        return []

    try:
        import tweepy
    except ImportError:
        print("[Twitter] tweepy not installed — run: pip install tweepy")
        return []

    try:
        client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN, wait_on_rate_limit=True)

        # Build query: OR of first 3 keywords, Telugu + English, no retweets
        terms = " OR ".join(f'"{k}"' for k in keywords[:3])
        query = f"({terms}) (lang:te OR lang:en) -is:retweet"

        # Date window: full calendar day in UTC
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        start_time = dt
        end_time   = dt + timedelta(days=1)

        response = client.search_recent_tweets(
            query=query,
            start_time=start_time,
            end_time=end_time,
            max_results=min(MAX_TWEETS, 100),
            tweet_fields=["text", "created_at", "public_metrics", "lang", "author_id"],
            expansions=["author_id"],
            user_fields=["name", "username", "public_metrics"],
        )

        if not response.data:
            return []

        # Build author lookup map
        users = {u.id: u for u in (response.includes.get("users") or [])}

        tweets_raw = []
        for tweet in response.data:
            author = users.get(tweet.author_id)
            metrics = tweet.public_metrics or {}
            tweets_raw.append({
                "tweet_id":      tweet.id,
                "text":          tweet.text,
                "lang":          tweet.lang or "unknown",
                "created_at":    tweet.created_at.strftime("%Y-%m-%d %H:%M") if tweet.created_at else date_str,
                "likes":         metrics.get("like_count", 0),
                "retweets":      metrics.get("retweet_count", 0),
                "replies":       metrics.get("reply_count", 0),
                "author_name":   author.name if author else "",
                "author_handle": f"@{author.username}" if author else "",
                "author_followers": author.public_metrics.get("followers_count", 0) if author and author.public_metrics else 0,
                "url":           f"https://twitter.com/i/web/status/{tweet.id}",
            })

        # Strip spam / brigading duplicates before sentiment.
        tweets_raw, _ = clean_comments(tweets_raw)

        # Classify sentiment in batches
        texts      = [t["text"] for t in tweets_raw]
        sentiments = sent.analyze_batch(texts, politician_name=politician_name)

        results = []
        for tweet, senti in zip(tweets_raw, sentiments):
            tweet["sentiment"] = senti
            results.append(tweet)

        return results

    except Exception as exc:
        print(f"[Twitter] error: {exc}")
        return []
