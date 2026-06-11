import time
from googleapiclient.discovery import build
import config


def _build_client():
    return build("youtube", "v3", developerKey=config.YOUTUBE_API_KEY)


def search_videos(keyword: str, max_results: int = 5) -> list[dict]:
    """Search YouTube for a keyword. Returns list of {video_id, title, publish_date}."""
    try:
        yt = _build_client()
        resp = yt.search().list(
            q=keyword,
            part="snippet",
            type="video",
            maxResults=max_results,
            order="relevance",
        ).execute()

        videos = []
        for item in resp.get("items", []):
            if item.get("id", {}).get("kind") != "youtube#video":
                continue
            videos.append({
                "video_id":    item["id"]["videoId"],
                "title":       item["snippet"]["title"],
                "publish_date": item["snippet"]["publishedAt"][:10],  # YYYY-MM-DD
            })
        return videos

    except Exception as exc:
        print(f"  [YouTube] Search failed for '{keyword}': {exc}")
        return []


def get_all_comments(video_id: str) -> list[dict]:
    """Fetch all top-level comments for a video (paginated). Returns list of {author, text, likes}."""
    try:
        yt = _build_client()
        comments = []
        page_token = None

        while True:
            kwargs = {
                "videoId":    video_id,
                "part":       "snippet",
                "maxResults": 100,
                "order":      "relevance",
                "textFormat": "plainText",
            }
            if page_token:
                kwargs["pageToken"] = page_token

            resp = yt.commentThreads().list(**kwargs).execute()

            for item in resp.get("items", []):
                top = item["snippet"]["topLevelComment"]["snippet"]
                comments.append({
                    "author": top.get("authorDisplayName", ""),
                    "text":   top.get("textDisplay", ""),
                    "likes":  top.get("likeCount", 0),
                })

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

            time.sleep(0.3)

        return comments

    except Exception as exc:
        msg = str(exc)
        if "commentsDisabled" in msg or "403" in msg:
            print(f"  [YouTube] Comments disabled for video {video_id} — skipping.")
        else:
            print(f"  [YouTube] Failed to fetch comments for {video_id}: {exc}")
        return []
