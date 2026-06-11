import os
import pandas as pd


COLUMNS = [
    "keyword",
    "video_title",
    "video_url",
    "publish_date",
    "transcript_source",
    "transcript_language",
    "summary",
    "comment_author",
    "comment_text",
    "comment_likes",
]


def save_to_csv(rows: list[dict], filename: str = "output.csv") -> None:
    """Append rows to CSV (create with headers if file doesn't exist)."""
    if not rows:
        print("  [CSV] No rows to save.")
        return

    df = pd.DataFrame(rows, columns=COLUMNS)

    if os.path.exists(filename):
        df.to_csv(filename, mode="a", header=False, index=False, encoding="utf-8-sig")
    else:
        df.to_csv(filename, mode="w", header=True, index=False, encoding="utf-8-sig")

    print(f"  [CSV] Saved {len(rows)} rows to {filename}")
