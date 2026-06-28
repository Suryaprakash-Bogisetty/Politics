"""
comment_filter.py — Strip bot / spam / brigading noise before sentiment.

Political YouTube & social comments are heavily polluted by:
  - Copy-paste brigading ("Jai TDP 🚩" posted 200×)
  - Emoji-only / link-only / single-word reactions that carry no real opinion
  - Near-duplicate slogans with trivial variation

These inflate whichever side brigades harder, not genuine public sentiment.
We remove the obvious junk and collapse near-duplicates to a single vote so a
coordinated flood counts once, not a hundred times.

Public API:
    clean_comments(comments) → (kept_comments, stats)
        comments: list of dicts each having at least a "text" key
        kept_comments: filtered list (same dict objects, order preserved)
        stats: {"removed_spam", "removed_duplicate", "kept", "original"}
"""

import re
from difflib import SequenceMatcher

# A comment must have at least this many letters to be a real opinion.
# Kept low because a single Telugu word (e.g. బాగుంది / చెత్త) is a valid opinion.
_MIN_ALPHA_CHARS = 3

# Telugu Unicode block — Python's str.isalpha() doesn't count combining vowel
# signs (matras), which undercounts Telugu words, so we count this range too.
_TELUGU_RANGE = range(0x0C00, 0x0C80)

# Near-duplicate threshold — collapse slogans that are essentially identical.
_DUP_THRESHOLD = 0.90

# Common low-signal slogan stubs (substring match, case-insensitive). These are
# pure cheerleading/abuse with no analyzable sentiment nuance on their own; when
# they appear *as the entire comment* they're treated as brigading noise.
_SLOGAN_ONLY = {
    "jai", "jaihind", "jaitdp", "jaiysrcp", "jaijanasena", "jaiap",
    "first", "super", "nice", "good", "wow", "ok", "okay",
}

_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF←-⇿⬀-⯿]+"
)
_URL_RE = re.compile(r"https?://\S+|www\.\S+")


def _normalize(text: str) -> str:
    """Lowercase, drop URLs/emoji/punctuation, collapse whitespace — for dup keys."""
    t = _URL_RE.sub(" ", text.lower())
    t = _EMOJI_RE.sub(" ", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _alpha_count(text: str) -> int:
    return sum(1 for ch in text if ch.isalpha() or ord(ch) in _TELUGU_RANGE)


def _is_spam(text: str, norm: str) -> bool:
    """True if the comment carries no analyzable opinion."""
    if not norm:
        return True
    if _alpha_count(norm) < _MIN_ALPHA_CHARS:
        return True
    # Single-token cheerleading / generic reaction with nothing else.
    collapsed = norm.replace(" ", "")
    if collapsed in _SLOGAN_ONLY:
        return True
    return False


def clean_comments(comments: list[dict]) -> tuple[list[dict], dict]:
    """Remove spam and collapse near-duplicate comments. See module docstring."""
    original = len(comments)
    kept: list[dict] = []
    seen_norms: list[str] = []
    removed_spam = 0
    removed_dup = 0

    for c in comments:
        text = (c.get("text") or "").strip()
        norm = _normalize(text)

        if _is_spam(text, norm):
            removed_spam += 1
            continue

        # Exact-normalized duplicate (the fast common case for copy-paste floods).
        if norm in seen_norms:
            removed_dup += 1
            continue

        # Fuzzy near-duplicate — only check against recent slogans to stay cheap.
        is_dup = False
        for prev in seen_norms[-200:]:
            if SequenceMatcher(None, norm, prev).ratio() >= _DUP_THRESHOLD:
                is_dup = True
                break
        if is_dup:
            removed_dup += 1
            continue

        seen_norms.append(norm)
        kept.append(c)

    stats = {
        "original":          original,
        "kept":              len(kept),
        "removed_spam":      removed_spam,
        "removed_duplicate": removed_dup,
    }
    return kept, stats
