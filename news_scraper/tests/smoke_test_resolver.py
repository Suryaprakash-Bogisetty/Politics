"""Empirical check: does googlenewsdecoder or redirect-following resolve
Google News RSS links to real publisher URLs, right now, in this environment?
Run directly: python tests/smoke_test_resolver.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import feedparser
import requests
from googlenewsdecoder import gnewsdecoder

FEED_URL = "https://news.google.com/rss/search?q=Chandrababu%20Naidu&hl=en-IN&gl=IN&ceid=IN:en"


def try_gnewsdecoder(url):
    try:
        result = gnewsdecoder(url)
        if result.get("status"):
            return result.get("decoded_url")
        return None
    except Exception as e:
        print(f"    gnewsdecoder raised: {e}")
        return None


def try_redirect_follow(url):
    try:
        resp = requests.get(url, allow_redirects=True, timeout=10)
        return resp.url
    except Exception as e:
        print(f"    redirect-follow raised: {e}")
        return None


def main():
    print(f"Fetching feed: {FEED_URL}")
    feed = feedparser.parse(FEED_URL)
    print(f"Entries found: {len(feed.entries)}")

    if not feed.entries:
        print("No entries — cannot test resolution. Check network/feed URL.")
        return

    test_entries = feed.entries[:3]
    for i, entry in enumerate(test_entries, 1):
        google_url = entry.link
        print(f"\n--- Entry {i} ---")
        print(f"Title: {entry.title}")
        print(f"Google URL: {google_url[:100]}...")

        decoded = try_gnewsdecoder(google_url)
        if decoded and "news.google.com" not in decoded:
            print(f"  [gnewsdecoder] SUCCESS -> {decoded}")
        else:
            print(f"  [gnewsdecoder] FAILED or unresolved (got: {decoded})")

        followed = try_redirect_follow(google_url)
        if followed and "news.google.com" not in followed:
            print(f"  [redirect-follow] SUCCESS -> {followed}")
        else:
            print(f"  [redirect-follow] FAILED or unresolved (got: {followed})")


if __name__ == "__main__":
    main()
