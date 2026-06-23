import logging
import requests
from googlenewsdecoder import gnewsdecoder

logger = logging.getLogger("news_scraper")


def resolve(google_url):
    """Resolve a Google News RSS redirect link to the real publisher URL.

    Confirmed empirically (tests/smoke_test_resolver.py): gnewsdecoder resolves
    these links reliably; plain HTTP redirect-following does not, since the
    Google News link isn't a real HTTP redirect.

    Returns (real_url, method_used). Never raises.
    """
    try:
        result = gnewsdecoder(google_url)
        decoded = result.get("decoded_url") if result and result.get("status") else None
        if decoded and "news.google.com" not in decoded:
            return decoded, "gnewsdecoder"
    except Exception as e:
        logger.warning("gnewsdecoder failed for %s: %s", google_url, e)

    try:
        resp = requests.get(google_url, allow_redirects=True, timeout=10)
        if resp.url and "news.google.com" not in resp.url:
            return resp.url, "redirect_follow"
    except Exception as e:
        logger.warning("redirect-follow failed for %s: %s", google_url, e)

    logger.warning("Could not resolve real URL for %s — using Google URL as-is", google_url)
    return google_url, "unresolved"
