import os
import pandas as pd

from config import OUTPUT_DIR

FIELDS = ["title", "source", "published_date", "url", "author", "summary", "content"]


def write_csv(keyword, target_date, articles):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe_keyword = keyword.replace(" ", "_")
    path = os.path.join(OUTPUT_DIR, f"{safe_keyword}_{target_date}.csv")
    df = pd.DataFrame(articles, columns=FIELDS)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path
