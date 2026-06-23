import logging
import trafilatura

logger = logging.getLogger("news_scraper")


def extract(url):
    """Fetch and extract article content + author from a real publisher URL.
    Returns {"content": str, "author": str|None, "extraction_ok": bool}.
    Never raises — caller falls back to RSS summary on extraction_ok=False.
    """
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            logger.warning("Could not download %s", url)
            return {"content": "", "author": None, "extraction_ok": False}

        result = trafilatura.extract(
            downloaded, with_metadata=True, output_format="json"
        )
        if not result:
            logger.warning("Could not extract content from %s", url)
            return {"content": "", "author": None, "extraction_ok": False}

        import json
        data = json.loads(result)
        content = data.get("text", "") or ""
        author = data.get("author") or None
        if not content:
            return {"content": "", "author": author, "extraction_ok": False}
        return {"content": content, "author": author, "extraction_ok": True}
    except Exception as e:
        logger.warning("Extraction failed for %s: %s", url, e)
        return {"content": "", "author": None, "extraction_ok": False}
