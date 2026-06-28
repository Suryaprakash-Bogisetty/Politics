"""
sentiment.py — Dual-engine sentiment classification and summarization.

Two engines run in concert:
  1. Groq llama-3.3-70b  — primary, context-aware (understands politician name + language)
  2. XLM-RoBERTa         — local HuggingFace model, 100-language multilingual including Telugu
                           used as a confidence-gated second opinion

Reconciliation produces a SOFT score per comment (a signed value in [-1, +1])
plus a confidence weight in [0, 1], not just a hard label:
  - Both engines agree           → high confidence, full-strength score
  - Groq neutral, local decisive → local wins, confidence scaled by local score
  - Engines strongly disagree    → low confidence, score pulled toward 0 (down-weighted)

Public API:
    analyze_batch(texts, politician_name)          → list of "positive"|"negative"|"neutral"
    analyze_batch_detailed(texts, politician_name) → list of dicts:
        {"label", "score" (-1..1), "confidence" (0..1)}
    summarize(text, title)                         → 2-3 sentence summary in article's language
"""

import json
import os
import time

from groq import Groq

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
_client = None

BATCH_SIZE = 20
_SENTIMENT_MODEL = "llama-3.3-70b-versatile"
_SUMMARIZE_MODEL = "llama-3.1-8b-instant"
_MAX_RETRIES = 3
_RETRY_DELAY = 8
_COMMENT_MAX_CHARS = 300

# Local model confidence threshold — only override Groq "neutral" when local
# model is this confident about a positive/negative label
_LOCAL_CONFIDENCE_THRESHOLD = 0.70

# HuggingFace model — loaded lazily on first use
_local_clf = None
_LOCAL_MODEL = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
# Maps raw model labels to our 3-class scheme
_LOCAL_LABEL_MAP = {
    "positive": "positive",
    "negative": "negative",
    "neutral":  "neutral",
    "label_0":  "negative",
    "label_1":  "neutral",
    "label_2":  "positive",
}


# ── Local model ────────────────────────────────────────────────────────────────

def _get_local_clf():
    global _local_clf
    if _local_clf is None:
        try:
            import os as _os
            import warnings
            _os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
            warnings.filterwarnings("ignore", message=".*unauthenticated.*")
            from transformers import pipeline as hf_pipeline
            _local_clf = hf_pipeline(
                "text-classification",
                model=_LOCAL_MODEL,
                device=-1,          # CPU — no GPU needed
                truncation=True,
                max_length=512,
            )
            print(f"[LocalNLP] Loaded {_LOCAL_MODEL}")
        except Exception as exc:
            print(f"[LocalNLP] Could not load model: {exc}")
            _local_clf = None
    return _local_clf


def _local_classify(texts: list[str]) -> list[tuple[str, float]]:
    """Return [(label, confidence), ...] for each text. Falls back to ('neutral', 0.0)."""
    clf = _get_local_clf()
    if clf is None:
        return [("neutral", 0.0)] * len(texts)
    try:
        outputs = clf([t[:512] for t in texts], batch_size=16)
        result = []
        for o in outputs:
            raw = o["label"].lower()
            label = _LOCAL_LABEL_MAP.get(raw, "neutral")
            result.append((label, float(o["score"])))
        return result
    except Exception as exc:
        print(f"[LocalNLP] inference error: {exc}")
        return [("neutral", 0.0)] * len(texts)


# ── Groq client ────────────────────────────────────────────────────────────────

def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def _call_groq(model: str, messages: list, temperature: float, max_tokens: int) -> str | None:
    for attempt in range(_MAX_RETRIES):
        try:
            resp = _get_client().chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or "rate_limit" in msg:
                if attempt < _MAX_RETRIES - 1:
                    wait = _RETRY_DELAY * (2 ** attempt)
                    print(f"[Groq] rate limit hit, retrying in {wait}s…")
                    time.sleep(wait)
                else:
                    print(f"[Groq] rate limit exceeded after {_MAX_RETRIES} retries: {msg[:120]}")
            else:
                print(f"[Groq] error: {exc}")
                break
    return None


# ── Sentiment ──────────────────────────────────────────────────────────────────

_LABEL_SIGN = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}


def analyze_batch(texts: list[str], politician_name: str = "") -> list[str]:
    """
    Classify each text as 'positive', 'negative', or 'neutral' (hard label).

    Thin wrapper over analyze_batch_detailed for callers (news, twitter) that
    only need the discrete label.
    """
    return [d["label"] for d in analyze_batch_detailed(texts, politician_name)]


def analyze_batch_detailed(texts: list[str], politician_name: str = "") -> list[dict]:
    """
    Classify each text and return a soft, confidence-aware result.

    Returns one dict per text:
        {
          "label":      "positive" | "negative" | "neutral",
          "score":      float in [-1, +1]  (signed sentiment strength),
          "confidence": float in [0, 1]    (how much to trust this judgment),
        }

    Reconciliation (Groq 70B + local XLM-RoBERTa):
      - Agree on pos/neg          → score ±1, confidence boosted by local score
      - Groq neutral, local sure  → local label wins, score = local_score * sign
      - Strong disagreement       → confidence halved, score pulled toward 0
      - Groq decisive, local weak  → trust Groq at moderate confidence
    """
    if not texts:
        return []

    # Run local model on all texts (fast, CPU, no rate limit)
    local_results = _local_classify(texts)

    # Run Groq in batches
    groq_results: list[dict] = []
    if GROQ_API_KEY:
        for i in range(0, len(texts), BATCH_SIZE):
            chunk = texts[i: i + BATCH_SIZE]
            groq_results.extend(_classify_chunk_groq(chunk, politician_name))
    else:
        groq_results = [{"label": "neutral", "groq_score": 0.0, "sarcasm": 0}] * len(texts)

    out: list[dict] = []
    for text, groq, (local_label, local_conf) in zip(texts, groq_results, local_results):
        out.append(_reconcile(text, groq, local_label, local_conf))
    return out


# Romanized-Telugu (Tenglish) marker WORDS. If a latin-script comment contains
# these as whole tokens, the local XLM-RoBERTa model (trained on native script +
# English) is unreliable on it, so we down-weight its vote. Matched on word
# boundaries so short markers don't false-match inside English words
# (e.g. "le"/"ra"/"ga" must not match "leader"/"great").
_TENGLISH_MARKERS = {
    "chesadu", "chesaru", "cheyyi", "cheyali", "chestunnadu", "chestunnaru",
    "manchi", "chedu", "chedda", "ledu", "ledhu", "kaadu", "kadu", "baga", "bagundi",
    "chala", "chaala", "enti", "ento", "emo", "ela", "ekkada", "appudu",
    "ra", "le", "ga", "andi", "garu", "gari", "nayudu", "babu", "anna", "thammudu",
    "vesi", "tisi", "pettadu", "ayyindi", "avvale", "cheyandi", "chudandi",
}

import re as _re
_TENGLISH_RE = _re.compile(
    r"\b(" + "|".join(_re.escape(m) for m in _TENGLISH_MARKERS) + r")\b"
)


def _is_tenglish(text: str) -> bool:
    """True if the text looks like romanized Telugu (latin script + Telugu marker words)."""
    if not text:
        return False
    # If it contains Telugu script, it's native — not Tenglish.
    if any(0x0C00 <= ord(ch) <= 0x0C7F for ch in text):
        return False
    return len(set(_TENGLISH_RE.findall(text.lower()))) >= 2


def _reconcile(text: str, groq: dict, local_label: str, local_conf: float) -> dict:
    """
    Combine Groq (signed score + sarcasm flag) with the local model into a soft
    {label, score, confidence}.

    Order of precedence:
      - Sarcasm → trust Groq, ignore local (local reads sarcasm literally).
      - Tenglish → halve local influence (local is weak on romanized Telugu).
      - Otherwise blend, preserving Groq's signed intensity.
    """
    groq_label = groq.get("label", "neutral")
    groq_score = float(groq.get("groq_score", 0.0))
    sarcasm    = int(groq.get("sarcasm", 0))

    g_sign = _LABEL_SIGN.get(groq_label, 0.0)
    l_sign = _LABEL_SIGN.get(local_label, 0.0)

    # Sarcasm gate — the local model can't read sarcasm; trust Groq outright.
    if sarcasm == 1:
        return {"label": groq_label, "score": groq_score, "confidence": 0.85}

    # Tenglish gate — discount the local model's vote on romanized Telugu.
    if _is_tenglish(text):
        local_conf *= 0.5

    # Case 1 — both decisive AND agree: highest confidence, keep Groq's intensity.
    if g_sign != 0 and g_sign == l_sign:
        confidence = min(1.0, 0.85 + 0.15 * local_conf)
        return {"label": groq_label, "score": groq_score, "confidence": confidence}

    # Case 2 — Groq neutral, local confidently decisive: local wins, scaled.
    if g_sign == 0 and l_sign != 0 and local_conf >= _LOCAL_CONFIDENCE_THRESHOLD:
        return {"label": local_label, "score": l_sign * local_conf, "confidence": local_conf}

    # Case 3 — strong disagreement (both decisive, opposite signs): trust neither.
    # Keep Groq's label (context-aware) but slash confidence and pull score toward 0.
    if g_sign != 0 and l_sign != 0 and g_sign != l_sign:
        confidence = max(0.2, 0.5 * (1.0 - local_conf))
        return {"label": groq_label, "score": groq_score * confidence, "confidence": confidence}

    # Case 4 — Groq decisive, local neutral/weak: trust Groq at moderate confidence.
    if g_sign != 0:
        return {"label": groq_label, "score": groq_score, "confidence": 0.7}

    # Case 5 — everything neutral.
    return {"label": "neutral", "score": 0.0, "confidence": local_conf if local_conf else 0.5}


def _score_to_label(s: float) -> str:
    """Map a signed sentiment score in [-1, 1] to a discrete label."""
    if s >= 0.15:
        return "positive"
    if s <= -0.15:
        return "negative"
    return "neutral"


def _classify_chunk_groq(texts: list[str], politician_name: str = "") -> list[dict]:
    """
    Classify a chunk of comments via Groq.

    Returns one dict per comment: {"label", "groq_score" (-1..1), "sarcasm" (0|1)}.
    The signed score preserves intensity (a furious comment vs. a mild one) instead
    of being flattened to a hard label. The sarcasm flag lets the reconciler ignore
    the local model (which reads sarcasm literally and is usually wrong on it).
    """
    n = len(texts)
    fallback = [{"label": "neutral", "groq_score": 0.0, "sarcasm": 0}] * n

    context = f"toward {politician_name}" if politician_name else "about an Indian politician"
    numbered = "\n".join(f"{j+1}. {t[:_COMMENT_MAX_CHARS]}" for j, t in enumerate(texts))
    prompt = (
        f"You are rating the sentiment of public comments {context}.\n"
        "Comments may be in Telugu, English, or romanized Telugu (Tenglish, e.g. "
        "'chala manchi pani chesadu', 'em chestunnado chudandi', 'goppi leader ra').\n"
        "Sarcasm and mockery are VERY common in political comments — praise said "
        "mockingly is NEGATIVE. Judge the writer's TRUE stance, not the surface words.\n\n"
        "For each comment return an object:\n"
        '  {"s": <number from -1.0 to 1.0>, "sarcasm": <0 or 1>}\n'
        "where s = -1.0 (very critical) … 0 (neutral/factual) … +1.0 (strong praise), "
        "and sarcasm = 1 if the comment is sarcastic/mocking, else 0.\n\n"
        "Examples:\n"
        '  "Goppi leader le, em chesado emo" (sarcastic) -> {"s": -0.7, "sarcasm": 1}\n'
        '  "ఆయన నిజంగా గొప్ప నాయకుడు, మంచి పనులు చేస్తున్నారు" -> {"s": 0.9, "sarcasm": 0}\n'
        '  "ee govt waste, em develop avvale, total fail" -> {"s": -0.9, "sarcasm": 0}\n'
        '  "Meeting Vijayawada lo jarigindi" (factual) -> {"s": 0.0, "sarcasm": 0}\n\n'
        "Reply ONLY with a JSON array of these objects — one per comment, in order. "
        "No explanation.\n\n"
        f"Comments:\n{numbered}\n\nJSON array:"
    )
    raw = _call_groq(
        model=_SENTIMENT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=600,
    )
    if not raw:
        return list(fallback)

    try:
        start, end = raw.find("["), raw.rfind("]") + 1
        if start < 0 or end <= start:
            return list(fallback)
        parsed = json.loads(raw[start:end])
        out: list[dict] = []
        for item in parsed[:n]:
            if isinstance(item, dict):
                try:
                    s = float(item.get("s", 0.0))
                except (TypeError, ValueError):
                    s = 0.0
                s = max(-1.0, min(1.0, s))
                sarcasm = 1 if item.get("sarcasm") in (1, "1", True) else 0
            elif isinstance(item, (int, float)):
                s = max(-1.0, min(1.0, float(item)))
                sarcasm = 0
            else:  # legacy string label, just in case
                lab = str(item).lower().strip().strip('"')
                s = {"positive": 0.7, "negative": -0.7}.get(lab, 0.0)
                sarcasm = 0
            out.append({"label": _score_to_label(s), "groq_score": s, "sarcasm": sarcasm})
        while len(out) < n:
            out.append({"label": "neutral", "groq_score": 0.0, "sarcasm": 0})
        return out
    except Exception as exc:
        print(f"[Groq sentiment] JSON parse error: {exc}")
        return list(fallback)


# ── Summarization ──────────────────────────────────────────────────────────────

def summarize(text: str, title: str) -> str:
    """Summarize a transcript or article in 2-3 sentences, matching the article's language."""
    if not text or not GROQ_API_KEY:
        return text[:300] + ("..." if len(text) > 300 else "") if text else ""

    raw = _call_groq(
        model=_SUMMARIZE_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a concise political news summarizer. "
                    "Write a 2-3 sentence summary. "
                    "Match the language of the article — write in Telugu for Telugu articles, "
                    "in English for English articles. "
                    "Focus on what the politician did or said."
                ),
            },
            {
                "role": "user",
                "content": f"Title: {title}\n\nContent:\n{text[:2000]}",
            },
        ],
        temperature=0.3,
        max_tokens=200,
    )
    if raw:
        return raw
    return text[:300] + ("..." if len(text) > 300 else "")
