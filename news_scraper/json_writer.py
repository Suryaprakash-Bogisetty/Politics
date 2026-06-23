import json
import os

from config import OUTPUT_DIR


def write_json(keyword, target_date, articles):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    payload = {
        "keyword": keyword,
        "date": target_date,
        "article_count": len(articles),
        "articles": articles,
    }
    safe_keyword = keyword.replace(" ", "_")
    path = os.path.join(OUTPUT_DIR, f"{safe_keyword}_{target_date}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path
