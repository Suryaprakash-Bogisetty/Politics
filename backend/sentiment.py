"""
sentiment.py — Groq-based sentiment classification and summarization.

analyze_batch(texts)  → list of "positive" | "negative" | "neutral"
summarize(text, title) → 2-3 sentence English summary
"""

import json
import os

from groq import Groq

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
_client = None

BATCH_SIZE = 15  # comments per Groq call


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


# ── Sentiment ─────────────────────────────────────────────────────────────────

def analyze_batch(texts: list[str]) -> list[str]:
    """Classify each text as 'positive', 'negative', or 'neutral'."""
    if not texts or not GROQ_API_KEY:
        return ["neutral"] * len(texts)

    results: list[str] = []
    for i in range(0, len(texts), BATCH_SIZE):
        chunk = texts[i : i + BATCH_SIZE]
        results.extend(_classify_chunk(chunk))
    return results


def _classify_chunk(texts: list[str]) -> list[str]:
    numbered = "\n".join(f"{j+1}. {t[:300]}" for j, t in enumerate(texts))
    prompt = (
        "Classify the sentiment of each comment about an Indian politician. "
        "Reply ONLY with a JSON array of strings — one per comment — each being "
        'exactly "positive", "negative", or "neutral". No explanation.\n\n'
        f"Comments:\n{numbered}\n\nJSON array:"
    )
    try:
        resp = _get_client().chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=250,
        )
        raw = resp.choices[0].message.content.strip()
        start, end = raw.find("["), raw.rfind("]") + 1
        if start >= 0 and end > start:
            parsed = json.loads(raw[start:end])
            normalized: list[str] = []
            for s in parsed[: len(texts)]:
                s = str(s).lower().strip().strip('"')
                normalized.append(s if s in ("positive", "negative", "neutral") else "neutral")
            while len(normalized) < len(texts):
                normalized.append("neutral")
            return normalized
    except Exception as exc:
        print(f"[Groq sentiment] error: {exc}")
    return ["neutral"] * len(texts)


# ── Summarization ─────────────────────────────────────────────────────────────

def summarize(text: str, title: str) -> str:
    """Summarize a transcript or article in 2-3 sentences (English)."""
    if not text or not GROQ_API_KEY:
        return text[:300] + ("..." if len(text) > 300 else "") if text else ""
    try:
        resp = _get_client().chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a concise political news summarizer. "
                        "Write a 2-3 sentence summary in English, "
                        "focusing on the key political points and events."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Title: {title}\n\nContent:\n{text[:8000]}",
                },
            ],
            temperature=0.3,
            max_tokens=350,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        print(f"[Groq summarize] error: {exc}")
        return text[:300] + ("..." if len(text) > 300 else "")
