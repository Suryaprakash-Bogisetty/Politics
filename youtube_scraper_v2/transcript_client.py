"""
transcript_client.py — Transcript fetching with proxy rotation + 3-layer fallback.

Flow per video:
  1a. youtube-transcript-api + proxy  (fast, no disk I/O)
  1b. yt-dlp + proxy                  (downloads VTT directly)
  1c. yt-dlp without proxy            (last free attempt)
   2. Supadata API                    (paid, no proxy needed)
   3. AssemblyAI                      (paid, audio STT)
"""

import os
import re
import time
import tempfile

import requests
import yt_dlp
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
)

import config


# ── VTT cleaner ───────────────────────────────────────────────────────────────

def _clean_vtt(raw: str) -> str:
    cleaned = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        if re.match(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->", line):
            continue
        if re.match(r"^(align|position|line|size):", line):
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line:
            cleaned.append(line)
    deduped, prev = [], None
    for line in cleaned:
        if line != prev:
            deduped.append(line)
        prev = line
    return " ".join(deduped).strip()


# ── Step 1a: youtube-transcript-api + proxy ───────────────────────────────────

def _try_transcript_api(
    video_id: str, proxy_manager=None
) -> tuple[str | None, str | None]:
    """
    Quick attempt using youtube-transcript-api (no VTT download needed).
    Returns (text, language). Marks proxy dead on network failure.
    """
    proxy_dict = None
    proxy_str  = None

    if proxy_manager:
        proxy_dict = proxy_manager.get_proxy()
        if proxy_dict:
            proxy_str = proxy_dict["http"].replace("http://", "")
            print(f"  [Transcript] Trying transcript-api + proxy {proxy_str}...")

    try:
        api = YouTubeTranscriptApi(proxies=proxy_dict) if proxy_dict else YouTubeTranscriptApi()

        for langs in (["te"], ["en"], None):
            try:
                if langs is not None:
                    fetched = api.fetch(video_id, languages=langs)
                else:
                    tlist = api.list(video_id)
                    first = next(iter(tlist), None)
                    if first is None:
                        break
                    fetched = first.fetch()

                text = " ".join(
                    seg.text if hasattr(seg, "text") else seg.get("text", "")
                    for seg in fetched
                ).strip()
                if text:
                    lang = langs[0] if langs else "unknown"
                    return text, lang
            except NoTranscriptFound:
                continue

    except (NoTranscriptFound, TranscriptsDisabled):
        pass  # Transcript absent — not a proxy fault, don't mark dead
    except Exception:
        if proxy_str and proxy_manager:
            proxy_manager.mark_dead(proxy_str)

    return None, None


# ── Step 1b/1c: yt-dlp + optional proxy ──────────────────────────────────────

class _YtdlpResult:
    """Carries download outcome without raising exceptions into the caller."""
    def __init__(self, text=None, lang=None, rate_limited=False):
        self.text         = text
        self.lang         = lang
        self.rate_limited = rate_limited  # True when YouTube returned 429


def _ytdlp_download(video_id: str, proxy_str: str | None) -> _YtdlpResult:
    """
    Run yt-dlp subtitle download for one video, optionally via proxy.
    Returns _YtdlpResult with text/lang on success, or rate_limited flag on 429.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"

    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts: dict = {
            "writeautomaticsub":       True,
            "writesubtitles":          False,
            "skip_download":           True,
            "subtitleslangs":          ["te", "en"],
            "subtitlesformat":         "vtt",
            "outtmpl":                 os.path.join(tmpdir, "%(id)s"),
            "quiet":                   True,
            "no_warnings":             True,
            "sleep_interval_requests": 1,
            "cookiesfrombrowser":      ("chrome",),   # bypass bot-check
        }
        if proxy_str:
            ydl_opts["proxy"] = f"http://{proxy_str}"

        download_exc: str = ""
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as exc:
            download_exc = str(exc)
            # Don't return yet — subtitles may have been written before the error

        for lang in ("te", "en"):
            vtt = os.path.join(tmpdir, f"{video_id}.{lang}.vtt")
            if os.path.exists(vtt):
                try:
                    text = _clean_vtt(open(vtt, encoding="utf-8").read())
                    if text:
                        return _YtdlpResult(text=text, lang=lang)
                except Exception:
                    pass

        # Fallback: any .vtt present
        try:
            for fname in os.listdir(tmpdir):
                if not fname.endswith(".vtt"):
                    continue
                lang = "te" if ".te." in fname else "en" if ".en." in fname else "unknown"
                text = _clean_vtt(open(os.path.join(tmpdir, fname), encoding="utf-8").read())
                if text:
                    return _YtdlpResult(text=text, lang=lang)
        except Exception:
            pass

        # No VTT found — propagate original error type
        return _YtdlpResult(rate_limited="429" in download_exc)

    return _YtdlpResult()


def get_transcript_ytdlp(
    video_id: str, proxy_manager=None
) -> tuple[str | None, str | None]:
    """
    yt-dlp subtitle download with proxy rotation.
    Tries: proxy → on failure mark dead + direct fallback with 429 backoff.
    Returns (text, language).
    """
    # Step 1b — with proxy
    if proxy_manager:
        proxy_str = proxy_manager.get_proxy_string()
        if proxy_str:
            print(f"  [yt-dlp] Trying proxy {proxy_str}...")
            res = _ytdlp_download(video_id, proxy_str)
            if res.text:
                return res.text, res.lang
            proxy_manager.mark_dead(proxy_str)
            print(f"  [yt-dlp] Proxy failed — retrying without proxy...")

    # Step 1c — direct, with 429 backoff only when YouTube is rate-limiting
    backoffs = [5, 15, 30]
    for attempt in range(1, 5):
        res = _ytdlp_download(video_id, None)
        if res.text:
            return res.text, res.lang
        if not res.rate_limited or not backoffs:
            break  # non-transient failure — no point retrying
        delay = backoffs.pop(0)
        print(f"  [yt-dlp] 429 — waiting {delay}s (retry {attempt}/3)...")
        time.sleep(delay)

    return None, None


# ── Layer 2: Supadata API ─────────────────────────────────────────────────────

def get_transcript_supadata(video_id: str) -> tuple[str | None, str | None]:
    if not config.SUPADATA_API_KEY:
        return None, None

    headers = {"x-api-key": config.SUPADATA_API_KEY}
    for lang in ("te", "en"):
        try:
            resp = requests.get(
                "https://api.supadata.ai/v1/youtube/transcript",
                params={"videoId": video_id, "lang": lang},
                headers=headers,
                timeout=30,
            )
            if resp.status_code == 200:
                content = resp.json().get("content", [])
                text = " ".join(
                    seg["text"] for seg in content if seg.get("text", "").strip()
                ).strip()
                if text:
                    return text, lang
            time.sleep(0.5)
        except Exception as exc:
            print(f"  [Supadata] Error for {video_id} ({lang}): {exc}")

    return None, None


# ── Layer 3: AssemblyAI ───────────────────────────────────────────────────────

def get_transcript_assemblyai(video_id: str) -> tuple[str | None, str | None]:
    if not config.ASSEMBLYAI_API_KEY:
        return None, None

    try:
        import assemblyai as aai
    except ImportError:
        print("  [AssemblyAI] assemblyai package not installed — run: pip install assemblyai")
        return None, None

    aai.settings.api_key = config.ASSEMBLYAI_API_KEY
    url = f"https://www.youtube.com/watch?v={video_id}"

    os.makedirs("temp", exist_ok=True)
    audio_path = os.path.join("temp", f"{video_id}.mp3")

    try:
        ydl_opts = {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key":              "FFmpegExtractAudio",
                "preferredcodec":   "mp3",
                "preferredquality": "128",
            }],
            "outtmpl":            os.path.join("temp", "%(id)s.%(ext)s"),
            "quiet":              True,
            "no_warnings":        True,
            "cookiesfrombrowser": ("firefox",),
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if not os.path.exists(audio_path):
            print(f"  [AssemblyAI] Audio file missing for {video_id}")
            return None, None

        print("  [AssemblyAI] Transcribing audio... (30-90 seconds)")
        transcriber = aai.Transcriber()

        for lang in ("te", "en"):
            try:
                cfg = aai.TranscriptionConfig(language_code=lang)
                result = transcriber.transcribe(audio_path, config=cfg)
                if result.status == aai.TranscriptStatus.error:
                    continue
                text = (result.text or "").strip()
                if text:
                    return text, lang
            except Exception as exc:
                print(f"  [AssemblyAI] Transcription error ({lang}): {exc}")

    except Exception as exc:
        print(f"  [AssemblyAI] Error for {video_id}: {exc}")
    finally:
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except Exception:
                pass

    return None, None


# ── Main orchestrator ─────────────────────────────────────────────────────────

def get_transcript(video_id: str, proxy_manager=None) -> dict:
    """
    Full transcript fetch with proxy rotation + 3-layer fallback.

    Returns:
        {
            "text":     str | None,
            "source":   "ytapi" | "ytdlp" | "supadata" | "assemblyai" | "failed",
            "language": "te" | "en" | "unknown" | None,
        }
    """
    # 1a — youtube-transcript-api + proxy (fast path)
    text, lang = _try_transcript_api(video_id, proxy_manager)
    if text:
        src = "ytapi" if (proxy_manager and proxy_manager.working_proxies) else "ytapi"
        print(f"  [Transcript] {video_id} → transcript-api ✓ ({lang})")
        return {"text": text, "source": "ytapi", "language": lang}

    # 1b/1c — yt-dlp (with proxy then without)
    text, lang = get_transcript_ytdlp(video_id, proxy_manager)
    if text:
        via = "via proxy" if proxy_manager else "direct"
        print(f"  [Transcript] {video_id} → yt-dlp ✓ ({lang}) {via}")
        return {"text": text, "source": "ytdlp", "language": lang}

    msg = f"  [Transcript] {video_id} → yt-dlp ✗"
    time.sleep(1)

    # 2 — Supadata (uses their servers, no proxy needed)
    if config.SUPADATA_API_KEY:
        text, lang = get_transcript_supadata(video_id)
        if text:
            print(f"{msg} → Supadata ✓ ({lang})")
            return {"text": text, "source": "supadata", "language": lang}
        msg += " → Supadata ✗"
    else:
        msg += " → Supadata (no key)"
    time.sleep(0.5)

    # 3 — AssemblyAI (uses their servers, no proxy needed)
    if config.ASSEMBLYAI_API_KEY:
        text, lang = get_transcript_assemblyai(video_id)
        if text:
            print(f"{msg} → AssemblyAI ✓ ({lang})")
            return {"text": text, "source": "assemblyai", "language": lang}
        msg += " → AssemblyAI ✗"
    else:
        msg += " → AssemblyAI (no key)"

    print(f"{msg} → ALL FAILED")
    return {"text": None, "source": "failed", "language": None}
