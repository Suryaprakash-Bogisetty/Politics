# news_scraper

Collects news articles for a given keyword and date, from Google News (Telugu +
English sources), and writes structured JSON + CSV output. Sibling project to
`fb_scraper/` and `youtube_scraper_v2/` — same conventions (dotenv config,
retry/backoff, pandas CSV, Groq summarization).

## Setup

```bash
cd news_scraper
pip install -r requirements.txt --break-system-packages   # or use a venv
cp .env.example .env
# edit .env and set GROQ_API_KEY
```

## Usage

```bash
python main.py --keyword "Gottipati Ravi Kumar" --date 2026-06-16
```

Output is written to `output/<keyword>_<date>.json` and `.csv`.

## Configuring sources

Edit `TELUGU_SITES` / `ENGLISH_SITES` in [config.py](config.py) — each entry is
`key: (display_name, domain)`. Adding a site adds one more RSS query per run;
no other code changes needed.

## Sample output

Real run: `python main.py --keyword "Chandrababu Naidu" --date 2026-06-16` —
120 articles after dedup, all `published_date == "2026-06-16"`, zero duplicate
URLs.

```json
{
  "keyword": "Chandrababu Naidu",
  "date": "2026-06-16",
  "article_count": 120,
  "articles": [
    {
      "title": "సింగపూర్ తర్వాత పెట్టుబడులకు ఏపీనే ఉత్తమ గమ్యస్థానం: సీఎం చంద్రబాబు - Andhrajyothy",
      "source": "Andhrajyothy",
      "published_date": "2026-06-16",
      "url": "https://www.andhrajyothy.com/2026/andhra-pradesh/guntur/...",
      "author": "ABN",
      "summary": "సింగపూర్ తర్వాత పెట్టుబడులకు ఏపీనే ఉత్తమ గమ్యస్థానం అని ముఖ్యమంత్రి...",
      "content": "సింగపూర్ తర్వాత పెట్టుబడులకు ఏపీనే ఉత్తమ గమ్యస్థానం: సీఎం చంద్రబాబు\n..."
    }
  ]
}
```

Note: `author` is included beyond the originally specified schema, since
`content_extractor.py` extracts it whenever the publisher's page exposes it.

CSV has the same fields flattened, written with `utf-8-sig` encoding so Telugu
text opens correctly in Excel.

## Design notes

- **Discovery:** Google News RSS only (`news.google.com/rss/search`), no paid
  API. One query per configured site per language (`site:domain.com`) plus one
  general query per language — this query fan-out is the practical equivalent
  of pagination, since Google News RSS has no `page=` parameter.
- **Redirect resolution:** Google News `<link>` values are obfuscated
  `news.google.com/rss/articles/...` URLs, not real article URLs. Empirically
  verified (`tests/smoke_test_resolver.py`) that `googlenewsdecoder.gnewsdecoder()`
  resolves these reliably (3/3 in testing); plain HTTP redirect-following does
  **not** work, since these links aren't real HTTP redirects. `url_resolver.py`
  tries `gnewsdecoder` first, falls back to redirect-following, and as a last
  resort keeps the Google URL and logs a warning — it never raises.
- **Content extraction:** `trafilatura` — gets body text + author/date metadata
  in one call using structure/density heuristics, so it works on both Telugu
  and English sites without per-site parsers. Verified manually against
  eenadu.net (Telugu) and thehindu.com (English).
- **Date filtering:** `feedparser` parses `pubDate` into a UTC `struct_time`;
  converted to IST with stdlib only (`timezone(timedelta(hours=5, minutes=30))`
  — no DST in India, so no `pytz` needed). Article is kept only if its IST date
  equals the target date.
- **Deduplication:** Pass 1 — exact match on resolved URL. Pass 2 — fuzzy title
  match via stdlib `difflib.SequenceMatcher`, threshold `0.85` (catches the same
  story re-titled with a trailing `" - Source"` suffix across outlets).
- **Summarization:** Groq LLM (`llama-3.3-70b-versatile` by default — the
  `llama3-*-8192` models are decommissioned). On any failure (rate limit,
  network, etc.) falls back to a truncated excerpt of the content instead of
  crashing the pipeline. In the sample run above, a shared Groq key hit its
  daily token quota partway through and the remaining ~40 articles correctly
  fell back to truncated summaries — confirming this path works.

## Future options (not implemented)

- **PostgreSQL storage** — a simple schema sketch:
  ```sql
  CREATE TABLE articles (
    id SERIAL PRIMARY KEY,
    keyword TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT,
    published_date DATE,
    url TEXT UNIQUE NOT NULL,
    author TEXT,
    summary TEXT,
    content TEXT,
    fetched_at TIMESTAMP DEFAULT now()
  );
  ```
  Swap `json_writer.py`/`csv_writer.py` for an `INSERT ... ON CONFLICT (url) DO NOTHING`.

- **Scheduling** — run daily via cron:
  ```bash
  0 7 * * * cd /path/to/news_scraper && python main.py --keyword "X" --date $(date +%F) >> cron.log 2>&1
  ```
  or via APScheduler (`BackgroundScheduler` with a daily `CronTrigger`), matching
  the pattern in other projects in this repo if they add scheduling later.

## Known limitations

- `site:domain.com` indexing in Google News varies by publisher — some sites
  are indexed lightly even when they published the relevant article, so the
  per-site queries can under-return relative to the general query.
- Paywalled or heavily JS-rendered pages degrade `trafilatura` extraction; the
  pipeline falls back to the RSS `<description>` snippet as `content` rather
  than failing the article.
- `gnewsdecoder` depends on reverse-engineering Google's internal batchexecute
  endpoint. If Google changes this endpoint, resolution will silently shift to
  the redirect-follow fallback (likely also broken, since it failed in testing)
  and then to raw Google URLs — re-run `tests/smoke_test_resolver.py` to check
  if this ever appears to regress.
- Groq has a per-day token quota on the free/on-demand tier; high-volume runs
  can exhaust it mid-run. This degrades gracefully (truncated summaries) but
  does not raise an error — check logs for `rate_limit_exceeded` if summaries
  look unexpectedly short.
