# SETUP INSTRUCTIONS:
# 1. Install dependencies:  pip install -r requirements.txt
# 2. Copy .env.example to .env:  cp .env.example .env
# 3. Add your API keys to .env:
#    - YOUTUBE_API_KEY    : https://console.cloud.google.com → Enable YouTube Data API v3
#    - GROQ_API_KEY       : https://console.groq.com
#    - SUPADATA_API_KEY   : https://supadata.ai  (optional)
#    - ASSEMBLYAI_API_KEY : https://assemblyai.com  (optional)
# 4. Edit KEYWORDS in config.py to your desired search terms
# 5. Run:  python main.py
# 6. Output saved to: output.csv

import time
import os
from collections import defaultdict

import config
from youtube_client    import search_videos, get_all_comments
from transcript_client import get_transcript
from summarizer        import summarize
from csv_writer        import save_to_csv
from proxy_manager     import ProxyManager


def main() -> None:
    if os.path.exists(config.OUTPUT_FILE):
        os.remove(config.OUTPUT_FILE)
        print(f"Cleared previous {config.OUTPUT_FILE}\n")

    # Build proxy pool once at startup (~30 seconds)
    proxy_manager = ProxyManager()
    proxy_manager.build_pool(min_proxies=20)
    print()

    total_rows = 0
    transcript_stats: dict[str, int] = defaultdict(int)

    for keyword in config.KEYWORDS:
        print(f"\n{'='*60}")
        print(f"Keyword: {keyword}")
        print(f"{'='*60}")

        videos = search_videos(keyword, max_results=config.MAX_VIDEOS_PER_KEYWORD)
        if not videos:
            print(f"  No videos found for '{keyword}' — skipping.")
            continue

        for idx, video in enumerate(videos, start=1):
            vid_id   = video["video_id"]
            title    = video["title"]
            url      = f"https://www.youtube.com/watch?v={vid_id}"
            pub_date = video["publish_date"]

            print(f"\n  Video {idx}/{len(videos)}: {title}")
            print(f"  URL: {url}")

            # Transcript (3-layer fallback)
            print("  → Fetching transcript...")
            result = get_transcript(vid_id, proxy_manager)
            transcript_text = result["text"]
            transcript_src  = result["source"]
            transcript_lang = result["language"] or ""
            transcript_stats[transcript_src] += 1
            time.sleep(3)  # breathing room between yt-dlp calls

            # Summary — only if we got a transcript
            print("  → Summarizing with Groq Llama 3 8B...")
            summary = summarize(transcript_text, title) if transcript_text else "No transcript available."
            time.sleep(0.5)

            # Comments
            print("  → Fetching comments...")
            comments = get_all_comments(vid_id)
            print(f"  → {len(comments)} comments found.")
            time.sleep(0.5)

            # Build rows — one per comment (or one blank row if no comments)
            rows = []
            base = {
                "keyword":             keyword,
                "video_title":         title,
                "video_url":           url,
                "publish_date":        pub_date,
                "transcript_source":   transcript_src,
                "transcript_language": transcript_lang,
                "summary":             summary,
            }
            if comments:
                for c in comments:
                    rows.append({**base,
                        "comment_author": c["author"],
                        "comment_text":   c["text"],
                        "comment_likes":  c["likes"],
                    })
            else:
                rows.append({**base,
                    "comment_author": "",
                    "comment_text":   "",
                    "comment_likes":  0,
                })

            save_to_csv(rows, filename=config.OUTPUT_FILE)
            total_rows += len(rows)

    # ── End-of-run summary ────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Done! Saved {total_rows} rows to {config.OUTPUT_FILE}")
    print()
    print("Transcript source breakdown:")
    for src in ("ytapi", "ytdlp", "supadata", "assemblyai", "failed"):
        count = transcript_stats.get(src, 0)
        bar   = "█" * count
        print(f"  {src:<12} {bar} {count}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
