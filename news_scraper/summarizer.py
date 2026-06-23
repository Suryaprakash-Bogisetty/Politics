import logging
from groq import Groq

from config import GROQ_API_KEY, GROQ_MODEL

logger = logging.getLogger("news_scraper")

_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

SYSTEM_PROMPT = (
    "You are a news summarizer. Read the article and write a concise 2-3 sentence "
    "summary in the same language as the article. Do not add information not present "
    "in the article."
)


def summarize(content, title):
    """Summarize article content via Groq. Falls back to truncation on any failure."""
    if not _client or not content:
        return _fallback_summary(content)

    try:
        completion = _client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Title: {title}\n\nArticle:\n{content[:6000]}"},
            ],
            temperature=0.3,
            max_tokens=300,
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        logger.warning("Groq summarization failed: %s", e)
        return _fallback_summary(content)


def _fallback_summary(content):
    if not content:
        return ""
    return content[:300] + ("..." if len(content) > 300 else "")
