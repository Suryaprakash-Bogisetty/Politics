import re
from config import KEYWORDS


def match_keywords(text: str) -> list[str]:
    """
    Return every keyword from KEYWORDS that appears in text.
    Case-insensitive for ASCII keywords; substring match for Telugu script.
    """
    if not text:
        return []
    matched: list[str] = []
    for kw in KEYWORDS:
        # re.escape handles both ASCII and Telugu safely
        if re.search(re.escape(kw), text, re.IGNORECASE):
            matched.append(kw)
    return matched


def first_match(text: str) -> str:
    """Return the first matched keyword or empty string."""
    hits = match_keywords(text)
    return hits[0] if hits else ""


def post_matches(text: str) -> bool:
    return bool(match_keywords(text))


def keyword_stats(posts: list[dict]) -> dict[str, int]:
    """
    Count how many posts contain each keyword.
    A post may appear under multiple keywords; each is counted separately.
    """
    counts: dict[str, int] = {kw: 0 for kw in KEYWORDS}
    for post in posts:
        text = post.get("post_text", "")
        for kw in match_keywords(text):
            counts[kw] += 1
    return {kw: v for kw, v in counts.items() if v > 0}
