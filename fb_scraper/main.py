"""
Facebook Telugu Political Scraper — full pipeline entry point.

Usage:
    python main.py                  # full run — all pages, all posts, all comments
    python main.py --stage1-only    # fetch posts only, print real URLs, stop before comments
    python main.py --test           # 2 pages × 5 posts — quick real-URL sanity check
"""

import sys
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from apify_client import ApifyClient
import os

import config
from stage1_posts import run_stage1
from stage2_comments import run_stage2

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def _load_api_token() -> str:
    load_dotenv()
    token = os.getenv("APIFY_API_TOKEN", "").strip()
    if not token:
        log.error("APIFY_API_TOKEN not set in .env — aborting.")
        sys.exit(1)
    return token


def _save_csv(comments: list[dict]) -> None:
    """Write final comments list to CSV with UTF-8 BOM (Excel-safe)."""
    Path(config.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    # Build DataFrame with exactly the columns we want, in order
    rows = []
    for c in comments:
        rows.append({col: c.get(col, "") for col in config.CSV_COLUMNS})

    df = pd.DataFrame(rows, columns=config.CSV_COLUMNS)
    df.to_csv(config.FINAL_CSV_FILE, index=False, encoding="utf-8-sig")


def _print_summary(
    pages_scraped: int,
    total_posts: int,
    filtered_posts: int,
    stage2_stats: dict,
    final_count: int,
) -> None:
    print()
    print("=" * 52)
    print("SUMMARY")
    print("=" * 52)
    print(f"  Total pages scraped        : {pages_scraped}")
    print(f"  Total posts fetched        : {total_posts}")
    print(f"  Keyword-matched posts      : {filtered_posts}")
    print(f"  Total raw comments         : {stage2_stats['raw_total']}")
    print(f"  Telugu comments            : {stage2_stats['telugu']}")
    print(f"  English comments           : {stage2_stats['english']}")
    print(f"  Unknown language kept      : {stage2_stats['unknown_kept']}")
    print(f"  Duplicates removed         : {stage2_stats['duplicates_removed']}")
    print(f"  Final comments saved       : {final_count}")
    print(f"  Output                     : {config.FINAL_CSV_FILE}")
    print("=" * 52)


def main() -> None:
    started_at = datetime.now(timezone.utc)
    log.info("Pipeline started at %s", started_at.strftime("%Y-%m-%d %H:%M:%S UTC"))
    log.info("Date filter: posts since %s", config.PUBLISHED_AFTER)

    token = _load_api_token()
    client = ApifyClient(token)

    # ── Stage 1: Posts (Google CSE — no Apify) ───────────────────────────────
    log.info("─" * 52)
    log.info("STAGE 1 — Finding post URLs via Google Custom Search")
    log.info("─" * 52)
    all_posts, filtered_posts = run_stage1()

    if not filtered_posts:
        log.warning("No keyword-matched posts found. Exiting — nothing to scrape for comments.")
        _print_summary(
            pages_scraped=len(config.FACEBOOK_PAGES),
            total_posts=len(all_posts),
            filtered_posts=0,
            stage2_stats={"raw_total": 0, "telugu": 0, "english": 0, "unknown_kept": 0, "duplicates_removed": 0},
            final_count=0,
        )
        return

    # ── Stage 2: Comments ─────────────────────────────────────────────────────
    log.info("─" * 52)
    log.info("STAGE 2 — Scraping comments for %d posts", len(filtered_posts))
    log.info("─" * 52)
    final_comments, stage2_stats = run_stage2(client, filtered_posts)

    # ── Save CSV ──────────────────────────────────────────────────────────────
    _save_csv(final_comments)
    log.info("CSV written to %s", config.FINAL_CSV_FILE)

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    log.info("Total elapsed: %.1f seconds", elapsed)

    _print_summary(
        pages_scraped=len(config.FACEBOOK_PAGES),
        total_posts=len(all_posts),
        filtered_posts=len(filtered_posts),
        stage2_stats=stage2_stats,
        final_count=len(final_comments),
    )


def test_run() -> None:
    """
    Lightweight real run — 2 pages, 10 posts max each.
    Uses Google CSE (no Apify) to fetch real Facebook post URLs.
    Stops after Stage 1 so you can click the links and verify them.
    Costs only 2 Google CSE API calls.
    """
    original_max = config.MAX_POSTS_PER_PAGE
    config.MAX_POSTS_PER_PAGE = 10

    log.info("TEST MODE — 2 pages × 10 posts (Google CSE)")
    all_posts, filtered_posts = run_stage1(pages=config.FACEBOOK_PAGES[:2])

    config.MAX_POSTS_PER_PAGE = original_max

    print("\n--- Real Post URLs (open these in your browser) ---")
    if not all_posts:
        print("  No posts returned. Check GOOGLE_API_KEY and GOOGLE_CSE_ID in .env")
        return
    for p in all_posts:
        print(f"  [{p['page_name']}]  {p['post_url']}")
    print(f"\nfiltered_posts.json saved → {config.FILTERED_POSTS_FILE}")
    print("If URLs open correctly, run:  python main.py --stage1-only")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""

    if arg == "--test":
        test_run()

    elif arg == "--stage1-only":
        all_posts, filtered_posts = run_stage1()
        print(f"\nStage 1 complete — {len(filtered_posts)} keyword-matched posts.")
        print(f"Real post URLs saved to: {config.FILTERED_POSTS_FILE}")
        print("Review the file, then run:  python main.py --stage2-only   to scrape comments.")

    elif arg == "--stage2-only":
        import json
        fp = Path(config.FILTERED_POSTS_FILE)
        if not fp.exists():
            log.error("No filtered_posts.json found. Run --stage1-only first.")
            sys.exit(1)
        filtered_posts = json.loads(fp.read_text(encoding="utf-8"))
        log.info("Loaded %d posts from %s", len(filtered_posts), config.FILTERED_POSTS_FILE)
        token = _load_api_token()
        client = ApifyClient(token)
        final_comments, stage2_stats = run_stage2(client, filtered_posts)
        _save_csv(final_comments)
        log.info("CSV written to %s", config.FINAL_CSV_FILE)
        _print_summary(
            pages_scraped=len(config.FACEBOOK_PAGES),
            total_posts=len(filtered_posts),
            filtered_posts=len(filtered_posts),
            stage2_stats=stage2_stats,
            final_count=len(final_comments),
        )

    else:
        main()
