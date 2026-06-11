from groq import Groq
import config

_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=config.GROQ_API_KEY)
    return _client


def summarize(transcript_text: str | None, video_title: str) -> str:
    """
    Summarize a YouTube transcript using Groq Llama 3 8B.
    Returns a 2-3 paragraph summary, or a fallback message if transcript is None.
    """
    if not transcript_text:
        return "Transcript not available — summary skipped."

    # Truncate to ~12 000 chars to stay within Llama 8B context limits
    text = transcript_text[:12_000]

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=config.GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant that summarizes YouTube video transcripts "
                        "clearly and concisely in English. Focus on the key political points, "
                        "statements, and events discussed."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Summarize the following transcript from a YouTube video titled "
                        f"'{video_title}' in 2-3 paragraphs:\n\n{text}"
                    ),
                },
            ],
            temperature=0.4,
            max_tokens=512,
        )
        return response.choices[0].message.content.strip()

    except Exception as exc:
        print(f"  [Groq] Summarization failed for '{video_title}': {exc}")
        return "Summary generation failed."
