"""
topic_extractor.py — "What's driving this" topic/keyword extraction.

Instead of generic noun-phrase keywords ("development", "leader"), we ask Groq to
cluster the strongest public comments + news headlines into the CONCRETE ISSUES
people are actually discussing (e.g. "Polavaram delays", "Amaravati capital"),
each with a stance and a one-line reason.

Public API:
    extract_topics(yt_results, news_results, reddit_results, politician_name) -> dict
        {
          "keywords": [ {"word": str, "count": int, "type": "pos"|"neg"|"neu"} ],  # drop-in for _renderKeywords
          "drivers":  [ {"topic": str, "stance": "pos"|"neg"|"mixed", "why": str} ]
        }
Degrades to {"keywords": [], "drivers": []} on any failure.
"""

import json

import sentiment as sent

# How many of the highest-signal comments to feed the model.
_MAX_COMMENTS = 80
_COMMENT_TRUNC = 200


def _collect_signals(yt_results: list[dict], news_results: list[dict],
                     reddit_results: list[dict]) -> list[dict]:
    """Gather the strongest comments (by signal) + news headlines into one pool."""
    pool: list[dict] = []

    for bucket in (yt_results, reddit_results):
        for item in bucket or []:
            for c in item.get("_scored_comments", []):
                text = (c.get("text") or "").strip()
                if text:
                    pool.append({"text": text[:_COMMENT_TRUNC], "signal": c.get("signal", 0.0)})

    # News headlines + summaries carry strong signal too (one each, fixed weight).
    for a in news_results or []:
        title = (a.get("title") or "").strip()
        if title:
            pool.append({"text": title[:_COMMENT_TRUNC], "signal": 3.0})

    pool.sort(key=lambda x: x["signal"], reverse=True)
    return pool[:_MAX_COMMENTS]


def _norm_type(stance: str) -> str:
    s = (stance or "").lower()
    if s.startswith("pos"):
        return "pos"
    if s.startswith("neg"):
        return "neg"
    return "neu"


def extract_topics(yt_results: list[dict], news_results: list[dict],
                   reddit_results: list[dict], politician_name: str = "") -> dict:
    empty = {"keywords": [], "drivers": []}

    pool = _collect_signals(yt_results, news_results, reddit_results)
    if not pool or not sent.GROQ_API_KEY:
        return empty

    who = politician_name or "the politician"
    numbered = "\n".join(f"{i+1}. {p['text']}" for i, p in enumerate(pool))
    prompt = (
        f"Below are public comments and news headlines about {who}.\n"
        "Identify the 6-8 CONCRETE ISSUES or TOPICS people are actually discussing "
        "— real subjects like 'Polavaram project delays', 'Amaravati capital', "
        "'liquor policy', 'job promises', 'pension scheme'. Do NOT return generic "
        "words like 'development', 'leader', 'politics', 'good', 'bad'.\n\n"
        "For each issue return an object:\n"
        '  {"topic": "<short issue name, 1-4 words>", '
        '"stance": "positive"|"negative"|"mixed", '
        '"mentions": <approx how many comments touch it>, '
        '"why": "<one short sentence on why people feel this way>"}\n\n'
        "Reply ONLY with a JSON array of these objects, ordered by how often the "
        "issue appears (most discussed first). No explanation.\n\n"
        f"Comments and headlines:\n{numbered}\n\nJSON array:"
    )

    raw = sent._call_groq(
        model=sent._SENTIMENT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=700,
    )
    if not raw:
        return empty

    try:
        start, end = raw.find("["), raw.rfind("]") + 1
        if start < 0 or end <= start:
            return empty
        parsed = json.loads(raw[start:end])
    except Exception as exc:
        print(f"[Topics] JSON parse error: {exc}")
        return empty

    keywords: list[dict] = []
    drivers: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic", "")).strip()
        if not topic:
            continue
        ttype = _norm_type(item.get("stance"))
        try:
            count = int(item.get("mentions", 0))
        except (TypeError, ValueError):
            count = 0
        keywords.append({"word": topic, "count": max(count, 1), "type": ttype})
        drivers.append({
            "topic": topic,
            "stance": ttype,
            "why": str(item.get("why", "")).strip(),
        })

    if not keywords:
        return empty
    return {"keywords": keywords[:8], "drivers": drivers[:8]}
