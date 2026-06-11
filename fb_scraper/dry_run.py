"""
Dry run — exercises the full pipeline with mock API responses.
Stage 1 mocks Google CSE (requests.get).
Stage 2 mocks Apify client.
No real API calls made.

Usage:
    cd fb_scraper
    python3 dry_run.py
"""

import json
import time
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd

import config
from keyword_filter import match_keywords, first_match, keyword_stats
from language_filter import detect_language, is_relevant, contains_telugu
from stage2_comments import _normalize_comment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Mock Google CSE responses (Stage 1) ───────────────────────────────────────
# Simulates what Google Custom Search API returns for each page.
# 'link' field = real-looking Facebook post URL.

MOCK_CSE_BY_PAGE = {
    "NaraLokesh": [
        {"link": "https://www.facebook.com/NaraLokesh/posts/1001",
         "title": "Nara Lokesh visits flood-affected villages",
         "snippet": "Nara Lokesh visits flood-affected villages in AP and announces relief fund.",
         "pagemap": {}},
        {"link": "https://www.facebook.com/NaraLokesh/posts/1002",
         "title": "TDP government 100 days",
         "snippet": "TDP government completes 100 days of promises fulfilled.",
         "pagemap": {}},
        # Non-post URL — should be filtered out
        {"link": "https://www.facebook.com/NaraLokesh/about",
         "title": "About NaraLokesh",
         "snippet": "About page",
         "pagemap": {}},
    ],
    "ncbn.official": [
        {"link": "https://www.facebook.com/ncbn.official/posts/2001",
         "title": "చంద్రబాబు రైతులకు మద్దతు",
         "snippet": "చంద్రబాబు నాయుడు గారు రైతులకు మద్దతు ప్రకటించారు.",
         "pagemap": {}},
        {"link": "https://www.facebook.com/ncbn.official/posts/2002",
         "title": "Chandrababu IT corridor",
         "snippet": "Chandrababu inaugurates new IT corridor in Amaravathi.",
         "pagemap": {}},
    ],
    "PawanKalyan": [
        {"link": "https://www.facebook.com/PawanKalyan/posts/3001",
         "title": "పవన్ కళ్యాణ్ సభ విజయవాడ",
         "snippet": "పవన్ కళ్యాణ్ జన సేన పార్టీ బహిరంగ సభ విజయవాడలో జరిగింది.",
         "pagemap": {}},
        {"link": "https://www.facebook.com/PawanKalyan/posts/3002",
         "title": "Pawan Kalyan press meet",
         "snippet": "Pawan Kalyan addresses press meet on AP development plans.",
         "pagemap": {}},
    ],
    "telugudesam": [
        {"link": "https://www.facebook.com/telugudesam/posts/4001",
         "title": "Telugu Desam foundation day",
         "snippet": "Telugu Desam Party celebrates foundation day with grand event.",
         "pagemap": {}},
    ],
    "JanaSenaParty": [
        {"link": "https://www.facebook.com/JanaSenaParty/posts/5001",
         "title": "తెలుగుదేశం జన సేన కలిసి",
         "snippet": "తెలుగుదేశం పార్టీ మరియు జన సేన కలిసి ప్రజల కోసం పని చేస్తున్నారు.",
         "pagemap": {}},
    ],
    "tv9telugu": [
        {"link": "https://www.facebook.com/tv9telugu/posts/6001",
         "title": "Nara Chandrababu cabinet meeting",
         "snippet": "Nara Chandrababu Naidu holds cabinet meeting on infrastructure projects.",
         "pagemap": {}},
    ],
    "abntelugu": [],   # empty — tests skip logic
    "ntvtelugu": [
        {"link": "https://www.facebook.com/ntvtelugu/posts/7001",
         "title": "నారా లోకేష్ విద్యార్థులతో",
         "snippet": "నారా లోకేష్ విద్యార్థులతో సమావేశం నిర్వహించారు.",
         "pagemap": {}},
    ],
}

# ── Mock Apify comments responses (Stage 2) ───────────────────────────────────

MOCK_COMMENTS_BY_POST = {
    "https://www.facebook.com/NaraLokesh/posts/1001": [
        {"id": "c001", "text": "Great initiative! Well done Lokesh garu.", "profileName": "Ravi Kumar", "date": "2026-06-01T10:00:00Z", "likes": 45, "isReply": False},
        {"id": "c002", "text": "లోకేష్ గారు చాలా మంచి పని చేస్తున్నారు! అభివందనాలు.", "profileName": "Sudha Rani", "date": "2026-06-01T10:05:00Z", "likes": 78, "isReply": False},
        {"id": "c003", "text": "TDP is doing excellent work for AP farmers.", "profileName": "Srinivas", "date": "2026-06-01T10:10:00Z", "likes": 33, "isReply": True, "parentCommentId": "c001"},
        {"id": "c004", "text": "Bonjour tout le monde", "profileName": "Jean", "date": "2026-06-01T10:15:00Z", "likes": 2, "isReply": False},
        {"id": "c001", "text": "duplicate — should be dropped", "profileName": "Dup", "date": "2026-06-01T10:20:00Z", "likes": 0, "isReply": False},
    ],
    "https://www.facebook.com/ncbn.official/posts/2001": [
        {"id": "c005", "text": "చంద్రబాబు నాయుడు గారు రైతుల పక్షాన నిలబడతారు.", "profileName": "Venkat Rao", "date": "2026-06-02T09:00:00Z", "likes": 120, "isReply": False},
        {"id": "c006", "text": "Chandrababu's vision for AP is commendable.", "profileName": "Anand", "date": "2026-06-02T09:05:00Z", "likes": 95, "isReply": False},
        {"id": "c007", "text": "ఇది నిజమైన నాయకత్వం!", "profileName": "Lakshmi", "date": "2026-06-02T09:10:00Z", "likes": 67, "isReply": True, "parentCommentId": "c005"},
        {"id": "c008", "text": "Nara Chandrababu is the best CM AP ever had.", "profileName": "Kiran", "date": "2026-06-02T09:15:00Z", "likes": 88, "isReply": False},
    ],
    "https://www.facebook.com/PawanKalyan/posts/3001": [
        {"id": "c009", "text": "పవన్ కళ్యాణ్ గారికి జయహో! జన సేన జిందాబాద్!", "profileName": "Mahesh", "date": "2026-06-03T08:00:00Z", "likes": 230, "isReply": False},
        {"id": "c010", "text": "Pawan Kalyan is a true hero — on screen and in politics!", "profileName": "Priya", "date": "2026-06-03T08:05:00Z", "likes": 175, "isReply": False},
        {"id": "c011", "text": "Well done RamaKrishna… Pawala gadu abadhalu cheptadu but vadini real ga question cheste thatukoledu coolie gadu,en", "profileName": "Anil", "date": "2026-06-03T08:10:00Z", "likes": 55, "isReply": True, "parentCommentId": "c009"},
        {"id": "c012", "text": "", "profileName": "Empty", "date": "2026-06-03T08:15:00Z", "likes": 0, "isReply": False},
    ],
    "https://www.facebook.com/ntvtelugu/posts/7001": [
        {"id": "c013", "text": "నారా లోకేష్ గారి విద్యా సంస్కరణలు అద్భుతంగా ఉన్నాయి.", "profileName": "Deepa", "date": "2026-06-04T07:00:00Z", "likes": 144, "isReply": False},
        {"id": "c014", "text": "Lokesh is transforming education in AP. Keep it up!", "profileName": "Suresh", "date": "2026-06-04T07:05:00Z", "likes": 99, "isReply": False},
    ],
}


# ── Mock requests.get for Google CSE ─────────────────────────────────────────

def _mock_cse_get(url, params=None, timeout=None):
    """Intercepts requests.get in stage1_posts and returns mock CSE JSON."""
    q = (params or {}).get("q", "")
    # Extract page slug from query: site:facebook.com/SLUG (...)
    import re
    m = re.search(r"site:facebook\.com/([\w.]+)", q)
    slug = m.group(1) if m else ""

    items = MOCK_CSE_BY_PAGE.get(slug, [])
    log.info("  [MOCK CSE] slug=%s  items=%d", slug, len(items))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"items": items} if items else {}
    mock_resp.raise_for_status = lambda: None
    return mock_resp


# ── Mock Apify client for Stage 2 ─────────────────────────────────────────────

class _MockDataset:
    def __init__(self, items):
        self._items = items

    def iterate_items(self):
        yield from self._items


class _MockRun:
    def __init__(self, run_id, dataset_id):
        self._run_id = run_id
        self._dataset_id = dataset_id

    def get(self):
        return {"id": self._run_id, "status": "SUCCEEDED", "defaultDatasetId": self._dataset_id}


class _MockActor:
    def __init__(self, actor_id, client):
        self._actor_id = actor_id
        self._client = client

    def start(self, run_input):
        return self._client._start(self._actor_id, run_input)


class MockApifyClient:
    def __init__(self):
        self._datasets = {}
        self._runs = {}
        self._counter = 0

    def actor(self, actor_id):
        return _MockActor(actor_id, self)

    def run(self, run_id):
        return _MockRun(run_id, self._runs[run_id])

    def dataset(self, dataset_id):
        return _MockDataset(self._datasets.get(dataset_id, []))

    def _start(self, actor_id, run_input):
        self._counter += 1
        run_id = f"run_{self._counter:04d}"
        ds_id  = f"ds_{self._counter:04d}"

        items = []
        if actor_id == config.ACTOR_COMMENTS:
            for entry in run_input.get("startUrls", []):
                post_url = entry["url"]
                for c in MOCK_COMMENTS_BY_POST.get(post_url, []):
                    items.append({**c, "postUrl": post_url})

        self._datasets[ds_id] = items
        self._runs[run_id] = ds_id
        log.info("  [MOCK Apify] actor=%s  run_id=%s  items=%d", actor_id, run_id, len(items))
        return {"id": run_id, "status": "STARTED", "defaultDatasetId": ds_id}


# ── Unit checks ───────────────────────────────────────────────────────────────

def _check_keyword_filter():
    print("\n[1] Keyword Filter")
    cases = [
        ("Chandrababu inaugurates new project", True),
        ("చంద్రబాబు రైతులకు మద్దతు", True),
        ("Pawan Kalyan meets farmers", True),
        ("పవన్ కళ్యాణ్ సభ", True),
        ("Happy birthday to everyone", False),
        ("TDP wins election", True),
        ("నారా లోకేష్ విద్యా పర్యటన", True),
    ]
    passed = 0
    for text, expected in cases:
        result = bool(match_keywords(text))
        status = "PASS" if result == expected else "FAIL"
        if status == "PASS":
            passed += 1
        print(f"  [{status}] '{text[:45]}' → match={result}")
    print(f"  {passed}/{len(cases)} passed")
    return passed == len(cases)


def _check_language_filter():
    print("\n[2] Language Filter")
    cases = [
        ("Great work Lokesh garu!", True),
        ("లోకేష్ గారు చాలా మంచి పని", True),
        ("Bonjour tout le monde", False),
        ("Nara Lokesh లోకేష్ mixed comment", True),
        ("", False),
        ("नमस्ते दिल्ली", False),
    ]
    passed = 0
    for text, expected_keep in cases:
        lang, script = detect_language(text) if text else ("unknown", "unknown")
        keep = is_relevant(text, lang)
        status = "PASS" if keep == expected_keep else "FAIL"
        if status == "PASS":
            passed += 1
        print(f"  [{status}] '{text[:35]}' → lang={lang} script={script} keep={keep}")
    print(f"  {passed}/{len(cases)} passed")
    return passed == len(cases)


def _check_url_filter():
    print("\n[3] Post URL Filter")
    from stage1_posts import _is_post_url
    cases = [
        ("https://www.facebook.com/NaraLokesh/posts/1234567890", True),
        ("https://www.facebook.com/permalink.php?story_fbid=123&id=456", True),
        ("https://www.facebook.com/NaraLokesh/posts/pfbid02abc", True),
        ("https://www.facebook.com/NaraLokesh/about", False),
        ("https://www.facebook.com/NaraLokesh", False),
        ("https://www.facebook.com/NaraLokesh/videos/9876543", True),
    ]
    passed = 0
    for url, expected in cases:
        result = _is_post_url(url)
        status = "PASS" if result == expected else "FAIL"
        if status == "PASS":
            passed += 1
        print(f"  [{status}] {url.split('facebook.com')[1][:40]} → {result}")
    print(f"  {passed}/{len(cases)} passed")
    return passed == len(cases)


# ── Full pipeline dry run ─────────────────────────────────────────────────────

def run_dry_pipeline():
    from stage1_posts import run_stage1
    from stage2_comments import run_stage2

    with patch("stage1_posts.requests.get", side_effect=_mock_cse_get), \
         patch("stage1_posts.time.sleep"), \
         patch("stage2_comments.time.sleep"):

        print("\n" + "─" * 52)
        print("STAGE 1 — Google CSE (mocked)")
        print("─" * 52)
        all_posts, filtered_posts = run_stage1()
        print(f"\nStage 1: {len(all_posts)} raw posts → {len(filtered_posts)} keyword-matched")

        if not filtered_posts:
            print("ERROR: No filtered posts.")
            return None

        print("\n" + "─" * 52)
        print("STAGE 2 — Apify Comments (mocked)")
        print("─" * 52)
        client = MockApifyClient()
        final_comments, stats = run_stage2(client, filtered_posts)

    # Save CSV
    Path(config.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    rows = [{col: c.get(col, "") for col in config.CSV_COLUMNS} for c in final_comments]
    df = pd.DataFrame(rows, columns=config.CSV_COLUMNS)
    df.to_csv(config.FINAL_CSV_FILE, index=False, encoding="utf-8-sig")
    log.info("CSV written: %s (%d rows)", config.FINAL_CSV_FILE, len(df))

    # Preview
    print("\n[Preview — first 5 rows]")
    print(df[["page_name", "matched_keyword", "comment_author",
              "language", "detected_script", "comment_text"]].head(5).to_string(index=False))

    # Summary
    print()
    print("=" * 52)
    print("SUMMARY (dry run)")
    print("=" * 52)
    print(f"  Total pages scraped        : {len(config.FACEBOOK_PAGES)}")
    print(f"  Total posts fetched        : {len(all_posts)}")
    print(f"  Keyword-matched posts      : {len(filtered_posts)}")
    print(f"  Total raw comments         : {stats['raw_total']}")
    print(f"  Telugu comments            : {stats['telugu']}")
    print(f"  English comments           : {stats['english']}")
    print(f"  Unknown language kept      : {stats['unknown_kept']}")
    print(f"  Duplicates removed         : {stats['duplicates_removed']}")
    print(f"  Final comments saved       : {len(final_comments)}")
    print(f"  Output                     : {config.FINAL_CSV_FILE}")
    print("=" * 52)

    return df


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 52)
    print("DRY RUN — Telugu Political Facebook Scraper")
    print("Stage 1: Google CSE  |  Stage 2: Apify")
    print("=" * 52)

    kw_ok   = _check_keyword_filter()
    lang_ok = _check_language_filter()
    url_ok  = _check_url_filter()

    df = run_dry_pipeline()

    print()
    if kw_ok and lang_ok and url_ok and df is not None and len(df) > 0:
        print("ALL CHECKS PASSED — pipeline is ready for production.")
    else:
        print("SOME CHECKS FAILED — review output above.")
