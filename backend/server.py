"""
AP Pulse — Backend Server
Run:  cd backend && python server.py
UI:   http://localhost:5000
API:  POST http://localhost:5000/api/analyze
"""

import os
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv

load_dotenv()

from youtube_analyzer import analyze_youtube
from news_analyzer import analyze_news

# Serve the UI from ../ui/
UI_DIR = Path(__file__).parent.parent / "ui"

app = Flask(__name__, static_folder=str(UI_DIR), static_url_path="")

# ── Politician → search keywords mapping ──────────────────────────────────────
POLITICIAN_KEYWORDS: dict[str, list[str]] = {
    "Chandrababu Naidu": ["Chandrababu Naidu", "Chandrababu", "చంద్రబాబు"],
    "Pawan Kalyan":      ["Pawan Kalyan", "పవన్ కళ్యాణ్"],
    "Nara Lokesh":       ["Nara Lokesh", "Lokesh", "నారా లోకేష్"],
    "Gottipati Ravi Kumar": ["Gottipati Ravi Kumar", "Gottipati", "గొట్టిపాటి"],
}


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.get_json(force=True) or {}
    politician = data.get("politician", "").strip()
    date = data.get("date", "").strip()

    if not politician or not date:
        return jsonify({"error": "politician and date are required"}), 400

    keywords = POLITICIAN_KEYWORDS.get(politician, [politician])

    # Run both analyses
    yt_results = analyze_youtube(keywords, date)
    news_results = analyze_news(keywords[0], date)

    # Aggregate overall sentiment across all YouTube comment sets
    pos_total = neg_total = 0
    for video in yt_results:
        s = video.get("sentiment", {})
        total_c = s.get("total_comments", 0)
        if total_c > 0:
            pos_total += round(s.get("positive", 0) / 100 * total_c)
            neg_total += round(s.get("negative", 0) / 100 * total_c)

    # Add news sentiment to the tally
    for article in news_results:
        art_s = article.get("sentiment", "neutral")
        if art_s == "positive":
            pos_total += 1
        elif art_s == "negative":
            neg_total += 1

    grand_total = pos_total + neg_total or 1
    overall_pos = round(pos_total / grand_total * 100)
    overall_neg = 100 - overall_pos

    return jsonify({
        "youtube": yt_results,
        "news": news_results,
        "overall": {
            "positive": overall_pos,
            "negative": overall_neg,
            "total_analyzed": pos_total + neg_total,
        },
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    print("=" * 52)
    print("  AP Pulse backend starting…")
    print("  UI  →  http://localhost:5000")
    print("  API →  http://localhost:5000/api/analyze")
    print("=" * 52)
    app.run(host="0.0.0.0", port=5000, debug=False)
