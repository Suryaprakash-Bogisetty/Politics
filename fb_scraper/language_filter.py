from langdetect import detect, LangDetectException
from config import TELUGU_UNICODE_RANGE, KEEP_LANGUAGES


def contains_telugu(text: str) -> bool:
    lo, hi = TELUGU_UNICODE_RANGE
    return any(lo <= ord(ch) <= hi for ch in text)


def _script_label(text: str) -> str:
    """
    Classify the dominant script in text.
    Returns 'telugu' | 'latin' | 'mixed' | 'unknown'.
    """
    if not text.strip():
        return "unknown"
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return "unknown"
    lo, hi = TELUGU_UNICODE_RANGE
    telugu_chars = sum(1 for c in alpha_chars if lo <= ord(c) <= hi)
    ratio = telugu_chars / len(alpha_chars)
    if ratio >= 0.8:
        return "telugu"
    if ratio <= 0.1:
        return "latin"
    return "mixed"


def detect_language(text: str) -> tuple[str, str]:
    """
    Returns (language_code, detected_script).
    - language_code: ISO 639-1 from langdetect, or 'te'/'unknown' as fallback
    - detected_script: 'telugu' | 'latin' | 'mixed' | 'unknown'
    """
    has_telugu = contains_telugu(text)
    script = _script_label(text)

    try:
        lang = detect(text)
    except LangDetectException:
        # If Unicode scan found Telugu chars, label as Telugu
        lang = "te" if has_telugu else "unknown"

    return lang, script


def is_relevant(text: str, lang: str) -> bool:
    """
    Keep comment if:
    - langdetect classified it as Telugu ('te') or English ('en'), OR
    - Unicode scan found Telugu script regardless of langdetect label.
    """
    if lang in KEEP_LANGUAGES:
        return True
    if contains_telugu(text):
        return True
    return False
