import argparse

from logging_setup import setup_logging
from rss_client import fetch_all
from date_utils import matches_target_date, to_ist_date
from url_resolver import resolve
from content_extractor import extract
from dedup import dedup_articles
from summarizer import summarize
from json_writer import write_json
from csv_writer import write_csv

logger = setup_logging()


def get_source_name(entry):
    source = getattr(entry, "source", None)
    if source and source.get("title"):
        return source["title"]
    return getattr(entry, "source_hint", "Unknown")


def run(keyword, target_date):
    logger.info("Fetching feeds for keyword=%r date=%s", keyword, target_date)
    entries = fetch_all(keyword)
    logger.info("Fetched %d raw entries", len(entries))

    date_filtered = [e for e in entries if matches_target_date(e, target_date)]
    logger.info("%d entries match target date", len(date_filtered))

    articles = []
    for entry in date_filtered:
        google_url = entry.link
        real_url, method = resolve(google_url)
        logger.info("Resolved (%s): %s", method, real_url)

        extraction = extract(real_url)
        content = extraction["content"]
        author = extraction["author"]

        if not extraction["extraction_ok"]:
            content = getattr(entry, "summary", "") or ""
            logger.warning("Falling back to RSS summary for %s", real_url)

        title = entry.title
        published_struct = getattr(entry, "published_parsed", None)
        ist_date = to_ist_date(published_struct)

        articles.append({
            "title": title,
            "source": get_source_name(entry),
            "published_date": str(ist_date) if ist_date else target_date,
            "url": real_url,
            "author": author,
            "summary": "",
            "content": content,
        })

    logger.info("Deduplicating %d articles", len(articles))
    deduped = dedup_articles(articles)
    logger.info("%d articles after dedup", len(deduped))

    for article in deduped:
        article["summary"] = summarize(article["content"], article["title"])

    json_path = write_json(keyword, target_date, deduped)
    csv_path = write_csv(keyword, target_date, deduped)

    logger.info("Wrote %s", json_path)
    logger.info("Wrote %s", csv_path)

    print(f"\nKeyword: {keyword}")
    print(f"Date: {target_date}")
    print(f"Article count: {len(deduped)}")
    print(f"JSON: {json_path}")
    print(f"CSV: {csv_path}")

    return deduped


def main():
    parser = argparse.ArgumentParser(description="News monitoring app — collects news for a keyword and date.")
    parser.add_argument("--keyword", required=True, help='Search keyword, e.g. "Gottipati Ravi Kumar"')
    parser.add_argument("--date", required=True, help="Target date, format YYYY-MM-DD")
    args = parser.parse_args()

    run(args.keyword, args.date)


if __name__ == "__main__":
    main()
