import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dedup import dedup_articles, normalize_title


def test_exact_url_dedup():
    articles = [
        {"title": "A", "url": "https://x.com/1"},
        {"title": "B", "url": "https://x.com/1"},
        {"title": "C", "url": "https://x.com/2"},
    ]
    result = dedup_articles(articles)
    assert len(result) == 2, f"expected 2, got {len(result)}"


def test_fuzzy_title_dedup():
    articles = [
        {"title": "Naidu dies at 80", "url": "https://a.com/1"},
        {"title": "Naidu dies at 80 - Eenadu", "url": "https://b.com/1"},
        {"title": "Lokesh inaugurates new IT park", "url": "https://c.com/1"},
    ]
    result = dedup_articles(articles)
    assert len(result) == 2, f"expected 2, got {len(result)}"
    titles = {a["title"] for a in result}
    assert "Lokesh inaugurates new IT park" in titles


def test_normalize_title_strips_source_suffix():
    assert normalize_title("Naidu dies at 80 - Eenadu") == "naidu dies at 80"
    assert normalize_title("Naidu dies at 80 | Sakshi") == "naidu dies at 80"


if __name__ == "__main__":
    test_exact_url_dedup()
    test_fuzzy_title_dedup()
    test_normalize_title_strips_source_suffix()
    print("All dedup tests passed.")
