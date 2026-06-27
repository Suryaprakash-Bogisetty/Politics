# AP Pulse — Politician Sentiment Intelligence Platform

Real-time sentiment analysis of YouTube videos and news articles for Andhra Pradesh politicians. Fetches data on demand, summarizes transcripts and articles using Groq AI, and classifies public sentiment as positive / negative / neutral.

---

## What It Does

1. You pick a **politician** and a **date** in the dashboard
2. The backend searches **YouTube** for videos published on that date and fetches comments + transcripts
3. It also fetches **Google News RSS** articles for that date
4. **Groq AI** summarizes each video/article and classifies every comment's sentiment
5. The dashboard displays sentiment scores, platform breakdowns, and a clickable live feed of results

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| pip | any recent |

### API Keys needed

| Key | Where to get it | Used for |
|---|---|---|
| `YOUTUBE_API_KEY` | [Google Cloud Console](https://console.cloud.google.com) → Enable YouTube Data API v3 | Searching videos + fetching comments |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) | Summarization + sentiment classification |

---

## Setup & Run (Backend + UI)

### 1. Clone / navigate to the project

```bash
cd Politics/
```

### 2. Install dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 3. Configure API keys

Create `backend/.env`:

```env
YOUTUBE_API_KEY=your_youtube_api_key_here
GROQ_API_KEY=your_groq_api_key_here
```

### 4. Start the server

```bash
cd backend
python3 server.py
```

You should see:

```
====================================================
  AP Pulse backend starting…
  UI  →  http://localhost:5000
  API →  http://localhost:5000/api/analyze
====================================================
```

### 5. Open the UI

Open your browser at: **http://localhost:5000**

---

## Using the App

1. **Login** — use the demo credentials `admin@appulse.in` / `password`, or click "click here" for instant access
2. **Select a politician** from the sidebar (Chandrababu Naidu, Pawan Kalyan, Nara Lokesh, Gottipati Ravi Kumar)
3. **Pick a date** in the analysis bar at the top
4. **Click "⚡ Run Analysis"** — this triggers the full pipeline (takes 30–60 seconds)
5. Results appear in:
   - Overall Positive / Negative sentiment cards
   - YouTube platform card (real video count + comment count)
   - Recent Mentions feed — each tile is **clickable** and opens the YouTube video or news article

> **Note:** The dashboard shows static demo data on first load. Real data only appears after clicking "Run Analysis".

---

## API Reference

### `POST /api/analyze`

```json
{
  "politician": "Chandrababu Naidu",
  "date": "2025-06-15"
}
```

**Response:**

```json
{
  "youtube": [
    {
      "video_id": "...",
      "title": "...",
      "url": "https://www.youtube.com/watch?v=...",
      "channel": "TV9 Telugu",
      "channel_url": "https://www.youtube.com/channel/...",
      "publish_date": "2025-06-15",
      "thumbnail": "...",
      "has_transcript": true,
      "transcript_summary": "2-3 sentence AI summary...",
      "sentiment": {
        "positive": 68,
        "negative": 32,
        "total_comments": 47
      },
      "top_comments": [...]
    }
  ],
  "news": [
    {
      "title": "...",
      "url": "https://...",
      "source": "Eenadu",
      "published_date": "2025-06-15",
      "summary": "AI summary...",
      "sentiment": "positive"
    }
  ],
  "overall": {
    "positive": 71,
    "negative": 29,
    "total_analyzed": 312
  }
}
```

### `GET /health`

Returns `{"status": "ok"}` if the server is running.

---

## Project Structure

```
Politics/
├── backend/                  ← Flask API server (the core app)
│   ├── server.py             ← Entry point, routes, sentiment aggregation
│   ├── youtube_analyzer.py   ← YouTube search, transcript, comments
│   ├── news_analyzer.py      ← Google News RSS, URL resolve, content extract
│   ├── sentiment.py          ← Groq AI: summarize + classify sentiment
│   ├── requirements.txt
│   └── .env                  ← API keys (not committed)
│
├── ui/
│   ├── index.html            ← Full dashboard (single-file SPA)
│   └── gottipati_profile.html
│
├── fb_scraper/               ← Standalone Facebook scraper (Apify-based)
├── news_scraper/             ← Standalone news scraper (CSV/JSON output)
├── youtube_scraper/          ← Standalone YouTube scraper (v1)
└── youtube_scraper_v2/       ← Standalone YouTube scraper (v2, proxy support)
```

> The 4 standalone scraper folders (`fb_scraper`, `news_scraper`, `youtube_scraper`, `youtube_scraper_v2`) are **not used** by the running web app — they are independent data-collection tools built separately.

---

## Supported Politicians

| Name | Party | Keywords searched |
|---|---|---|
| Chandrababu Naidu | TDP | Chandrababu Naidu, Chandrababu, చంద్రబాబు |
| Pawan Kalyan | Jana Sena | Pawan Kalyan, పవన్ కళ్యాణ్ |
| Nara Lokesh | TDP | Nara Lokesh, Lokesh, నారా లోకేష్ |
| Gottipati Ravi Kumar | TDP | Gottipati Ravi Kumar, Gottipati, గొట్టిపాటి |

---

## How the Pipeline Works

```
Browser
  │
  └── POST /api/analyze { politician, date }
            │
            ├── YouTube Data API v3
            │     ├── search videos (up to 10 across 2 keywords)
            │     ├── fetch transcript (Telugu → English → any)
            │     ├── fetch top 50 comments
            │     └── Groq AI → summarize transcript + classify each comment
            │
            └── Google News RSS
                  ├── Telugu sites: Eenadu, Sakshi, NTV, TV9, ABN, Andhra Jyothy
                  ├── English sites: The Hindu, TOI, Deccan Chronicle, Indian Express
                  ├── resolve redirect URLs → extract article content
                  └── Groq AI → summarize article + classify sentiment
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `YOUTUBE_API_KEY not set` | Add the key to `backend/.env` |
| `GROQ_API_KEY not set` | Add the key to `backend/.env` — sentiment defaults to "neutral" without it |
| Port 5000 already in use | `pkill -f "python3 server.py"` then restart |
| No results for a date | Try a more recent date — YouTube API only indexes recent videos reliably |
| Transcript not available | Normal — not all videos have transcripts; summary will show "No transcript available" |
