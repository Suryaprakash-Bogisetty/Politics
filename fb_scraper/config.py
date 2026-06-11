from datetime import datetime, timedelta, timezone

# ── Facebook pages to scrape ──────────────────────────────────────────────────
FACEBOOK_PAGES = [
    "https://www.facebook.com/NaraLokesh",
    "https://www.facebook.com/ncbn.official",
    "https://www.facebook.com/PawanKalyan",
    "https://www.facebook.com/telugudesam",
    "https://www.facebook.com/JanaSenaParty",
    "https://www.facebook.com/tv9telugu",
    "https://www.facebook.com/abntelugu",
    "https://www.facebook.com/ntvtelugu",
]

# ── Keywords for post filtering (English + Telugu) ────────────────────────────
KEYWORDS = [
    "Nara Lokesh",
    "Nara Chandrababu",
    "Chandrababu",
    "Pawan Kalyan",
    "TDP",
    "Telugu Desam",
    "నారా లోకేష్",
    "చంద్రబాబు",
    "పవన్ కళ్యాణ్",
    "తెలుగుదేశం",
]

# ── Date range ────────────────────────────────────────────────────────────────
DATE_RANGE_DAYS = 30
PUBLISHED_AFTER: str = (
    datetime.now(timezone.utc) - timedelta(days=DATE_RANGE_DAYS)
).strftime("%Y-%m-%d")

# ── Scraping limits ───────────────────────────────────────────────────────────
MAX_POSTS_PER_PAGE = 50      # max post URLs collected per Facebook page
CSE_RESULTS_PER_CALL = 10    # Google CSE max per API call (hard limit)
CSE_CALL_DELAY = 0.5         # seconds between paginated CSE calls
COMMENTS_BATCH_SIZE = 50     # post URLs per Apify comments-actor call
POLL_INTERVAL_SECONDS = 10
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 2

# ── Google Custom Search API (Stage 1) ────────────────────────────────────────
GOOGLE_CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"

# ── Apify actor (Stage 2 only) ────────────────────────────────────────────────
ACTOR_COMMENTS = "apify/facebook-comments-scraper"

# ── Language settings ─────────────────────────────────────────────────────────
TELUGU_UNICODE_RANGE = (0x0C00, 0x0C7F)
KEEP_LANGUAGES = {"te", "en"}

# ── Output paths ──────────────────────────────────────────────────────────────
OUTPUT_DIR = "output"
RAW_POSTS_FILE = "output/raw_posts.json"
FILTERED_POSTS_FILE = "output/filtered_posts.json"
RAW_COMMENTS_FILE = "output/raw_comments.json"
FINAL_CSV_FILE = "output/comments_final.csv"

# ── Final CSV column order ────────────────────────────────────────────────────
CSV_COLUMNS = [
    "page_name",
    "matched_keyword",
    "post_id",
    "post_url",
    "post_date",
    "post_text",
    "comment_id",
    "comment_text",
    "comment_author",
    "comment_date",
    "comment_likes",
    "is_reply",
    "parent_comment_id",
    "language",
    "detected_script",
]
