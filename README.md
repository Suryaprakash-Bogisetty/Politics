# AP Pulse — Politician Sentiment Intelligence Platform

Multi-platform real-time sentiment analysis for Andhra Pradesh politicians across YouTube, Google News, Twitter/X, and Facebook. Combines YouTube Data API, Google News RSS, dual-engine AI sentiment (Groq LLM + local XLM-RoBERTa), and a live web dashboard.

---

## Table of Contents

1. [What Is This?](#1-what-is-this)
2. [Politicians Tracked](#2-politicians-tracked)
3. [Architecture Overview](#3-architecture-overview)
4. [Repository Structure](#4-repository-structure)
5. [How Sentiment Works](#5-how-sentiment-works)
6. [API Reference](#6-api-reference)
7. [Configuration & Secrets](#7-configuration--secrets)
8. [Running with Docker](#8-running-with-docker)
9. [Running Locally](#9-running-locally)
10. [Standalone Scrapers](#10-standalone-scrapers)
11. [Known Limitations](#11-known-limitations)
12. [Roadmap](#12-roadmap)

---

## 1. What Is This?

**AP Pulse** is a political sentiment intelligence platform that answers: *"What does the public think about this politician today?"*

Every analysis run:
1. Searches YouTube for videos published on the target date
2. Fetches all YouTube comments and classifies each one positive/negative/neutral
3. Fetches Google News RSS from 10 Telugu + English sources
4. Extracts full article body text via `trafilatura`
5. Runs dual-engine sentiment: **Groq Llama-3.3-70B** (primary) + **XLM-RoBERTa** (local 100-language model, second opinion)
6. Blends results across platforms using configurable weights
7. Returns everything as a single JSON response rendered in the dashboard

**Language support:** Telugu and English throughout — keywords, RSS queries, article extraction, and sentiment classification all handle both natively.

---

## 2. Politicians Tracked

| Politician | Party | Role | Keywords |
|---|---|---|---|
| **N. Chandrababu Naidu** | TDP | Chief Minister, AP | Chandrababu Naidu · Chandrababu · చంద్రబాబు |
| **Pawan Kalyan** | Jana Sena | Deputy CM, AP | Pawan Kalyan · పవన్ కళ్యాణ్ · PawanKalyan |
| **Nara Lokesh** | TDP | Cabinet Minister | Nara Lokesh · Lokesh · నారా లోకేష్ |
| **Gottipati Ravi Kumar** | TDP/Ally | Political figure | Gottipati Ravi Kumar · Gottipati · గొట్టిపాటి |

Each politician has English + Telugu script keyword variants. All three keywords are searched on YouTube; the first keyword is used for Google News RSS.

---

## 3. Architecture Overview

```
Browser (ui/index.html)
    │  POST /api/analyze {politician, date}
    ▼
FastAPI server (backend/server.py)
    │
    ├─── asyncio.gather() — all 4 platforms run concurrently
    │
    ├── YouTube Analyzer (youtube_analyzer.py)
    │     ├── YouTube Data API v3 search (3 keywords × 5 videos)
    │     ├── Channel subscriber count fetch (one batch API call)
    │     ├── youtube-transcript-api (te → en → hi fallback)
    │     ├── Groq summarize transcript
    │     ├── YouTube commentThreads API (75 comments/video)
    │     └── Dual-engine sentiment → like-weighted + channel-weighted score
    │
    ├── News Analyzer (news_analyzer.py)
    │     ├── Google News RSS (general + 10 site-specific feeds, Telugu + English)
    │     ├── Date filter + fuzzy title dedup (difflib SequenceMatcher 0.85)
    │     ├── gnewsdecoder URL resolution + HTTP redirect fallback
    │     ├── trafilatura full article body extraction
    │     ├── Dual-engine sentiment on raw article body (not summary)
    │     └── Groq summarize in article's language
    │
    ├── Twitter Analyzer (twitter_analyzer.py)
    │     └── Tweepy v2 (requires TWITTER_BEARER_TOKEN; returns [] if not set)
    │
    └── Facebook Analyzer (facebook_analyzer.py)
          └── Graph API (requires FACEBOOK_ACCESS_TOKEN; returns [] if not set)

Sentiment Engine (sentiment.py)
    ├── PRIMARY: Groq llama-3.3-70b-versatile
    │     Batches 20 texts/call, context-aware, politician name injected into prompt
    └── SECONDARY: cardiffnlp/twitter-xlm-roberta-base-sentiment (HuggingFace, CPU)
          100-language multilingual model, cached in Docker image
          Overrides Groq "neutral" when local confidence ≥ 70%

Blending (server.py)
    Weights: YouTube 35% · News 30% · Twitter 20% · Facebook 15%
    Denominator excludes missing platforms (renormalized, not padded with 50%)
    Per-video YouTube score: like-weighted × channel-credibility-weighted
```

---

## 4. Repository Structure

```
Politics/
├── backend/
│   ├── server.py               # FastAPI routes, politician keywords, blend logic
│   ├── sentiment.py            # Dual-engine: Groq 70B + XLM-RoBERTa local model
│   ├── youtube_analyzer.py     # YouTube search, subscriber fetch, like-weighted sentiment
│   ├── news_analyzer.py        # Google News RSS, trafilatura, gnewsdecoder
│   ├── twitter_analyzer.py     # Tweepy v2 Twitter/X search
│   ├── facebook_analyzer.py    # Facebook Graph API
│   ├── requirements.txt
│   └── .env                    # API keys (never commit)
│
├── ui/
│   ├── index.html              # Single-page dashboard (login → analysis)
│   ├── gottipati_profile.html  # Politician profile page
│   └── images/                 # Politician photos
│
├── news_scraper/               # Standalone Google News → JSON/CSV batch scraper
├── youtube_scraper_v2/         # Production YouTube scraper (transcript + proxy)
├── youtube_scraper/            # Legacy comment-only YouTube scraper (v1)
├── fb_scraper/                 # Facebook scraper via Apify
│
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## 5. How Sentiment Works

### Dual-Engine Classification

Every comment or article text goes through two classifiers:

**Engine 1 — Groq Llama-3.3-70B (primary)**
- Batches 20 texts per API call
- Prompt includes politician name for context: *"Classify sentiment toward Chandrababu Naidu"*
- Returns `positive / negative / neutral` per text
- Handles Telugu, English, and Hindi natively via the 70B model

**Engine 2 — XLM-RoBERTa (local, runs on CPU in Docker)**
- Model: `cardiffnlp/twitter-xlm-roberta-base-sentiment`
- Trained on 100 languages including Telugu
- Pre-downloaded and cached in the Docker image (no download at runtime)
- Runs on every text in parallel with Groq

**Reconciliation rule:**
```
if Groq == "neutral" AND local_model != "neutral" AND local_confidence >= 0.70:
    use local_model label   ← Groq was unsure; local model is confident
else:
    use Groq label          ← Groq wins by default
```

This catches cases where Groq hedges to "neutral" on ambiguous Telugu text while the XLM-RoBERTa model trained on social media text is confident about the label.

### Like-Weighted YouTube Sentiment

Comments are not equal. A comment with 500 likes carries far more weight than a comment with 0.

```python
weight = log(likes + 1) + 1.0   # 0-like = 1.0 weight, 500-like ≈ 7.2 weight

weighted_pos = sum(weight for c, label in zip(comments, sentiments)
                   if label == "positive")
weighted_neg = sum(weight for c, label in zip(comments, sentiments)
                   if label == "negative")

pos_pct = weighted_pos / (weighted_pos + weighted_neg) * 100
```

Neutral comments are excluded from the denominator entirely — absence of opinion is not negativity.

### Channel Credibility Weighting

YouTube search results include videos from 200-subscriber channels alongside TV9 Telugu (10M+ subscribers). Channels are weighted by credibility when blending scores across videos:

| Channel type | Weight multiplier |
|---|---|
| Known major news channel (TV9, ABN, NTV, ETV, etc.) | 1.5× |
| 1M+ subscribers (unknown channel) | 1.3× |
| 100K–1M subscribers | 1.0× |
| 10K–100K subscribers | 0.7× |
| Under 10K subscribers | 0.5× |

Subscriber counts are fetched in a single batch YouTube API call per analysis run.

### Platform Blend

```python
WEIGHTS = {"yt": 0.35, "news": 0.30, "tw": 0.20, "fb": 0.15}

# Only include platforms that returned data
active = {k: score for k, score in scores.items() if platform_has_data[k]}
total_w = sum(WEIGHTS[k] for k in active)
overall_pos = sum(WEIGHTS[k] * v for k, v in active.items()) / total_w
```

If Twitter and Facebook return no data (no token configured), their weights are dropped and YouTube + News are renormalized to sum to 1.0. The score is never padded with an arbitrary 50%.

### News Sentiment: Classify Body, Then Summarize

News articles are classified on the **raw article body** (up to 2000 chars), not on the Groq summary. The summary is generated afterward. This prevents the summarizer from flattening a strongly negative article into a neutral-sounding summary before classification.

---

## 6. API Reference

Base URL: `http://localhost:5000`  
Interactive docs: `http://localhost:5000/docs`

### `GET /health`

```json
{ "status": "ok", "version": "2.0.0" }
```

### `GET /api/politicians`

```json
{
  "politicians": [
    { "name": "Chandrababu Naidu", "keywords": ["Chandrababu Naidu", "Chandrababu", "చంద్రబాబు"] },
    ...
  ]
}
```

### `POST /api/analyze`

**Request:**
```json
{ "politician": "Chandrababu Naidu", "date": "2025-06-20" }
```

**Response `200 OK`:**
```json
{
  "youtube": [
    {
      "video_id": "abcXYZ123",
      "title": "Video title",
      "channel": "TV9 Telugu",
      "channel_url": "https://youtube.com/channel/UCxxx",
      "url": "https://youtube.com/watch?v=abcXYZ123",
      "thumbnail": "https://i.ytimg.com/vi/abcXYZ123/mqdefault.jpg",
      "publish_date": "2025-06-20",
      "subscribers": 10200000,
      "channel_weight": 1.5,
      "has_transcript": false,
      "transcript_summary": null,
      "sentiment": {
        "positive": 72,
        "negative": 28,
        "total_comments": 48,
        "decisive": 31,
        "channel_weight": 1.5
      },
      "top_comments": [
        { "author": "User1", "text": "బాబు గారు చాలా మంచి నాయకుడు!", "likes": 342 }
      ]
    }
  ],
  "news": [
    {
      "title": "AP CM Chandrababu Naidu unveils budget",
      "url": "https://thehindu.com/...",
      "source": "The Hindu",
      "published_date": "2025-06-20",
      "summary": "2-3 sentence summary in article language...",
      "sentiment": "positive"
    }
  ],
  "twitter": [],
  "facebook": [],
  "overall": {
    "positive": 62,
    "negative": 38,
    "total_analyzed": 63,
    "youtube_positive": 72,
    "news_positive": 45,
    "twitter_positive": 50,
    "facebook_positive": 50,
    "weights": { "yt": 0.35, "news": 0.30, "tw": 0.20, "fb": 0.15 }
  }
}
```

**Errors:**

| Status | When |
|---|---|
| `400` | Unknown politician name |
| `422` | Missing or wrong-type fields (Pydantic) |
| `500` | Unexpected server error |

---

## 7. Configuration & Secrets

All secrets live in `backend/.env`. Never commit this file.

```env
# Required
YOUTUBE_API_KEY=your_youtube_data_api_v3_key
GROQ_API_KEY=your_groq_api_key

# Optional — Twitter/X sentiment (returns [] without this)
TWITTER_BEARER_TOKEN=

# Optional — Facebook sentiment (returns [] without this)
FACEBOOK_ACCESS_TOKEN=
```

**How to get each key:**

| Key | Where |
|---|---|
| `YOUTUBE_API_KEY` | Google Cloud Console → Enable YouTube Data API v3 → Create API Key |
| `GROQ_API_KEY` | console.groq.com → API Keys (free tier: 100K tokens/day) |
| `TWITTER_BEARER_TOKEN` | developer.twitter.com → Basic tier ($100/mo) |
| `FACEBOOK_ACCESS_TOKEN` | developers.facebook.com → App → Page Access Token (free) |

---

## 8. Running with Docker

```bash
# Build and start
docker compose up -d --build

# View logs
docker logs ap-pulse -f

# Stop
docker compose down
```

The Docker image pre-downloads the XLM-RoBERTa model at build time so startup is instant. Build takes ~5 minutes on first run (downloads torch + CUDA + model weights ~2GB total).

Access the dashboard at `http://localhost:5000`.

---

## 9. Running Locally

```bash
cd backend
pip install -r requirements.txt
# Edit .env with your API keys
uvicorn server:app --host 0.0.0.0 --port 5000 --reload
```

The XLM-RoBERTa model is downloaded from HuggingFace Hub on first use and cached in `~/.cache/huggingface/`.

---

## 10. Standalone Scrapers

These run independently and write to files. They are not connected to the live API.

### News Scraper (`news_scraper/`)

Batch Google News → JSON + CSV. More thorough than the backend news analyzer (full dedup pipeline, IST date conversion, separate logging).

```bash
cd news_scraper && pip install -r requirements.txt
python main.py --keyword "Chandrababu Naidu" --date 2025-06-20
# Output: output/Chandrababu Naidu_2025-06-20.json
#         output/Chandrababu Naidu_2025-06-20.csv
```

### YouTube Scraper v2 (`youtube_scraper_v2/`)

Production-grade with 4-layer transcript fallback and rotating proxy pool.

```bash
cd youtube_scraper_v2 && pip install -r requirements.txt
python main.py
# Output: output.csv (one row per comment)
```

Transcript layers (tried in order):
1. `youtube-transcript-api` + rotating free proxy (Telugu → English → any)
2. `yt-dlp` + proxy (downloads VTT subtitle file, strips timestamps)
3. `yt-dlp` direct (no proxy)
4. Supadata API (paid, optional)
5. AssemblyAI speech-to-text (paid, optional — downloads audio and transcribes)

### Facebook Scraper (`fb_scraper/`)

Two-stage scraper via Apify cloud actors.

```bash
cd fb_scraper && pip install -r requirements.txt
python main.py          # Full run (posts + comments)
python main.py --test   # Quick test: 2 pages × 10 posts
# Output: output/comments_final.csv
```

Stage 1: Apify `facebook-posts-scraper` → keyword filter  
Stage 2: Apify `facebook-comments-scraper` → language detection → Telugu/English filter

Requires `APIFY_API_TOKEN` in `fb_scraper/.env`.

---

## 11. Known Limitations

**YouTube transcripts:** YouTube blocks transcript fetches from GCP/datacenter IP addresses (serves HTML bot-challenge instead of XML transcript data). Running on GCP means `has_transcript: false` for all videos. The standalone `youtube_scraper_v2` with proxy rotation works around this.

**Groq rate limits:** Free tier is 100K tokens/day. One full analysis run (3 keywords × 5 videos × 75 comments + 15 news articles) uses ~30K–60K tokens. Two runs/day is safe; more requires a second API key or paid tier.

**News neutrals:** Factual reporting (tributes, event coverage) gets classified as "neutral" correctly. If a date has only ceremonial news, neutral percentage will be high.

**Twitter/Facebook empty:** Both analyzers return `[]` until their respective tokens are configured. The blend renormalizes to YouTube + News only in that case.

**XLM-RoBERTa on CPU:** The local model adds ~2–4 seconds per batch of 16 texts. For 75 comments across 11 videos this adds ~10–20 seconds total to analysis time.

---

## 12. Roadmap

| Priority | Feature | Notes |
|---|---|---|
| High | Reddit integration | r/AndhraPradesh, r/telugu — free PRAW API, English English signal |
| High | Facebook Graph API token | Free — public page posts + comments from politician pages |
| Medium | Supadata.ai transcripts | $10/mo — unlocks video content on GCP (currently 0 transcripts) |
| Medium | Twitter Basic API | $100/mo — most impactful paid addition |
| Low | PostgreSQL persistence | Store analysis history → enable trend graphs |
| Low | Daily cron scheduling | Auto-run at midnight IST for each politician |
| Low | Confidence scoring | Expose per-text confidence from XLM-RoBERTa in response |

---

*AP Pulse — tracking Andhra Pradesh political sentiment across YouTube, Google News, Twitter/X, and Facebook.*
