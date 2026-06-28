"""
AP Pulse — Backend Server (FastAPI)
Run:  cd backend && uvicorn server:app --host 0.0.0.0 --port 5000 --reload
UI:   http://localhost:5000
API:  POST http://localhost:5000/api/analyze
Docs: http://localhost:5000/docs
"""

import asyncio
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from youtube_analyzer import analyze_youtube
from news_analyzer import analyze_news
from twitter_analyzer import analyze_twitter
from facebook_analyzer import analyze_facebook
from reddit_analyzer import analyze_reddit
from topic_extractor import extract_topics

UI_DIR = Path(__file__).parent.parent / "ui"

app = FastAPI(
    title="AP Pulse API",
    description="Politician sentiment intelligence across YouTube, News, Twitter, and Facebook.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Politician → search keywords + Facebook page IDs ──────────────────────────
POLITICIAN_KEYWORDS: dict[str, list[str]] = {
    "Chandrababu Naidu": ["Chandrababu Naidu", "Chandrababu", "చంద్రబాబు"],
    "Pawan Kalyan":      ["Pawan Kalyan", "పవన్ కళ్యాణ్", "PawanKalyan"],
    "Nara Lokesh":       ["Nara Lokesh", "Lokesh", "నారా లోకేష్"],
    "Gottipati Ravi Kumar": ["Gottipati Ravi Kumar", "Gottipati", "గొట్టిపాటి"],
}

POLITICIAN_FB_PAGES: dict[str, list[str]] = {
    "Chandrababu Naidu":    ["ncbn.official", "telugudesam"],
    "Pawan Kalyan":         ["PawanKalyan", "JanaSenaParty"],
    "Nara Lokesh":          ["NaraLokesh"],
    "Gottipati Ravi Kumar": ["telugudesam"],
}

# Aggregation weights across platforms (5 — Reddit added; sum = 1.0)
WEIGHTS = {"yt": 0.34, "news": 0.28, "tw": 0.16, "fb": 0.12, "reddit": 0.10}

# Evidence "floor" per platform — the decisive-item count at which a platform
# earns its full WEIGHTS share. Below it, its influence shrinks proportionally so
# a platform that returned almost nothing barely moves the headline number.
EVIDENCE_FLOOR = {"yt": 30, "news": 5, "tw": 20, "fb": 20, "reddit": 15}

# Below this many decisive items on a platform, pull its % toward 50 (no signal → no bias).
_THIN_EVIDENCE = 15


# ── Request / Response models ──────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    politician: str
    date: str  # YYYY-MM-DD format


class SentimentBreakdown(BaseModel):
    positive: int
    negative: int
    total_analyzed: int


class OverallSentiment(BaseModel):
    positive: int
    negative: int
    total_analyzed: int
    youtube_weight: float
    news_weight: float
    twitter_weight: float
    facebook_weight: float


# ── Helpers ────────────────────────────────────────────────────────────────────

def _platform_pos_pct(results: list[dict], comment_key: str = "sentiment") -> tuple[float, int]:
    """
    Weighted average positive % across videos/posts, plus the platform's total
    decisive-evidence count.

    Weight per item = decisive × channel_credibility × reliability. When the whole
    platform has thin evidence (< _THIN_EVIDENCE decisive items) the result is
    pulled toward 50 so a 2-comment day can't print "90% positive".

    Returns (pos_pct, total_decisive).
    """
    total_weight = 0.0
    weighted_pos = 0.0
    total_decisive = 0
    for item in results:
        s = item.get(comment_key, {})
        if isinstance(s, dict):
            decisive    = s.get("decisive", 0) or s.get("total_comments", 0) or s.get("total", 0)
            ch_weight   = s.get("channel_weight", 1.0)
            reliability = s.get("reliability", 1.0)
            weight      = decisive * ch_weight * reliability
            pos_pct     = s.get("positive", 0)
            if weight > 0:
                weighted_pos += pos_pct * weight
                total_weight += weight
            total_decisive += int(decisive)

    if total_weight <= 0:
        return 50.0, 0
    pct = weighted_pos / total_weight

    # Thin-evidence damping — lerp toward 50 proportionally to how far below floor.
    if total_decisive < _THIN_EVIDENCE:
        trust = total_decisive / _THIN_EVIDENCE
        pct = 50.0 + (pct - 50.0) * trust
    return pct, total_decisive


def _news_pos_pct(articles: list[dict]) -> tuple[float, int]:
    pos = sum(1 for a in articles if a.get("sentiment") == "positive")
    neg = sum(1 for a in articles if a.get("sentiment") == "negative")
    total = pos + neg
    # If no positive/negative signal (all neutral or empty), return 50 — no bias
    return ((pos / total * 100) if total > 0 else 50.0), total


def _twitter_pos_pct(tweets: list[dict]) -> tuple[float, int]:
    pos = sum(1 for t in tweets if t.get("sentiment") == "positive")
    neg = sum(1 for t in tweets if t.get("sentiment") == "negative")
    total = pos + neg
    return ((pos / total * 100) if total > 0 else 50.0), total


def _blend(pcts: dict[str, float], evidence: dict[str, int]) -> int:
    """
    Weighted blend across present platforms.

    Each active platform's effective weight = WEIGHTS[k] × min(1, evidence_k/floor_k),
    so a platform that returned little contributes proportionally less. Missing
    platforms (not in pcts) are skipped and the rest renormalized.
    """
    eff = {}
    for k, pct in pcts.items():
        ev = evidence.get(k, 0)
        if ev <= 0:
            continue
        eff[k] = WEIGHTS[k] * min(1.0, ev / EVIDENCE_FLOOR.get(k, 20))
    total_w = sum(eff.values())
    if total_w <= 0:
        return 50
    blended = sum(eff[k] * pcts[k] for k in eff) / total_w
    return round(blended)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "version": "2.0.0"}


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    """
    Run multi-platform sentiment analysis for a politician on a given date.

    Returns YouTube videos, news articles, tweets, Facebook posts, and an
    overall blended sentiment score weighted across all four platforms.
    """
    politician = req.politician.strip()
    date = req.date.strip()

    if not politician or not date:
        raise HTTPException(status_code=400, detail="politician and date are required")

    # Normalize date — accept YYYY-MM-DD (standard) or DDMMYYYY (sent by some browsers)
    if len(date) == 8 and "-" not in date:
        try:
            from datetime import datetime as _dt
            date = _dt.strptime(date, "%d%m%Y").strftime("%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid date format '{date}'. Use YYYY-MM-DD.")

    if politician not in POLITICIAN_KEYWORDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown politician '{politician}'. Valid: {list(POLITICIAN_KEYWORDS)}"
        )

    keywords = POLITICIAN_KEYWORDS[politician]
    fb_pages = POLITICIAN_FB_PAGES.get(politician, [])

    # Run all five platform analyses concurrently
    yt_task     = asyncio.to_thread(analyze_youtube,  keywords, date, politician)
    news_task   = asyncio.to_thread(analyze_news,     keywords[0], date, politician)
    tw_task     = asyncio.to_thread(analyze_twitter,  keywords, date, politician)
    fb_task     = asyncio.to_thread(analyze_facebook, fb_pages, keywords[0], date, politician)
    reddit_task = asyncio.to_thread(analyze_reddit,   keywords, date, politician)

    yt_results, news_results, tw_results, fb_results, reddit_results = await asyncio.gather(
        yt_task, news_task, tw_task, fb_task, reddit_task
    )

    # Per-platform positive % + evidence (decisive-item count)
    yt_pos,   yt_ev   = _platform_pos_pct(yt_results)
    news_pos, news_ev = _news_pos_pct(news_results)
    tw_pos,   tw_ev   = _twitter_pos_pct(tw_results)
    fb_pos,   fb_ev   = _platform_pos_pct(fb_results)
    rd_pos,   rd_ev   = _platform_pos_pct(reddit_results)

    pcts     = {"yt": yt_pos, "news": news_pos, "tw": tw_pos, "fb": fb_pos, "reddit": rd_pos}
    evidence = {"yt": yt_ev,  "news": news_ev,  "tw": tw_ev,  "fb": fb_ev,  "reddit": rd_ev}
    overall_pos = _blend(pcts, evidence)
    overall_neg = 100 - overall_pos

    # Topic / keyword extraction across the strongest comments + headlines
    topics = extract_topics(yt_results, news_results, reddit_results, politician)

    # Total items analyzed
    yt_comments  = sum(v["sentiment"]["total_comments"] for v in yt_results if v.get("sentiment"))
    news_count   = len(news_results)
    tw_count     = len(tw_results)
    fb_comments  = sum(p.get("comment_count", 0) for p in fb_results)
    rd_comments  = sum(p.get("sentiment", {}).get("total_comments", 0) for p in reddit_results)
    total_analyzed = yt_comments + news_count + tw_count + fb_comments + rd_comments

    # Strip internal helper fields before returning
    for v in yt_results:
        v.pop("_scored_comments", None)
    for p in reddit_results:
        p.pop("_scored_comments", None)

    return {
        "youtube":  yt_results,
        "news":     news_results,
        "twitter":  tw_results,
        "facebook": fb_results,
        "reddit":   reddit_results,
        "topics":   topics,
        "overall": {
            "positive":         overall_pos,
            "negative":         overall_neg,
            "total_analyzed":   total_analyzed,
            "youtube_positive":  round(yt_pos),
            "news_positive":     round(news_pos),
            "twitter_positive":  round(tw_pos),
            "facebook_positive": round(fb_pos),
            "reddit_positive":   round(rd_pos),
            "weights": WEIGHTS,
        },
    }


@app.get("/api/politicians")
async def list_politicians():
    """Return the list of supported politician names and their keywords."""
    return {
        "politicians": [
            {"name": name, "keywords": kws}
            for name, kws in POLITICIAN_KEYWORDS.items()
        ]
    }


# ── Serve UI (must be after all API routes) ────────────────────────────────────
if UI_DIR.exists():
    @app.get("/")
    async def serve_ui():
        return FileResponse(str(UI_DIR / "index.html"))

    app.mount("/", StaticFiles(directory=str(UI_DIR)), name="ui")


if __name__ == "__main__":
    import uvicorn
    print("=" * 56)
    print("  AP Pulse v2 backend starting…")
    print("  UI   →  http://localhost:5000")
    print("  API  →  http://localhost:5000/api/analyze")
    print("  Docs →  http://localhost:5000/docs")
    print("=" * 56)
    uvicorn.run("server:app", host="0.0.0.0", port=5000, reload=True)
