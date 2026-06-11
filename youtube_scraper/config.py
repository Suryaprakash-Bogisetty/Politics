from datetime import datetime, timedelta, timezone

KEYWORDS = [
    "Chandrababu",
    "Revanth Reddy",
    "TDP",
    "BRS",
    "YSRCP",
    "Pawan Kalyan",
    "AP politics",
    "Telangana politics",
    "Jagan",
    "KTR",
    "Telugu politics",
]

MAX_VIDEOS_PER_KEYWORD = 20

DAYS_BACK = 30

PUBLISHED_AFTER: str = (
    datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
).strftime("%Y-%m-%dT%H:%M:%SZ")

SEARCH_ORDER = "date"          # first pass: recent
SEARCH_ORDER_VIRAL = "viewCount"  # second pass: viral — merged and deduplicated

MAX_RETRIES = 3
BASE_BACKOFF = 2               # seconds; doubles each retry

QUOTA_PAUSE_SECONDS = 60       # pause duration when quota hit

OUTPUT_DIR = "output"
OUTPUT_FILE = "output/comments.csv"

CSV_COLUMNS = [
    "video_id",
    "video_title",
    "channel_name",
    "keyword_used",
    "comment_id",
    "author",
    "comment_text",
    "language",
    "published_at",
    "like_count",
    "is_reply",
    "parent_comment_id",
]

TELUGU_UNICODE_RANGE = (0x0C00, 0x0C7F)
KEEP_LANGUAGES = {"te", "en"}
