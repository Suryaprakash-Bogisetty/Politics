import os
import re
from dotenv import load_dotenv
from groq import Groq
from youtube_transcript_api import YouTubeTranscriptApi

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def extract_video_id(url):
    pattern = r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    else:
        raise ValueError("Invalid YouTube URL provided.")

def get_youtube_transcript(video_id):
    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=["te", "en"])
        transcript_text = " ".join([
            seg.text if hasattr(seg, 'text') else seg.get('text', '')
            for seg in fetched
        ])
        return transcript_text
    except Exception as e:
        return f"Error fetching transcript: {str(e)}"

def summarize_in_telugu(transcript):
    system_prompt = (
        "You are an expert translator and summarizer. "
        "Analyze the provided video transcript and generate a comprehensive, "
        "clear, and bulleted summary completely in Telugu (తెలుగు). "
        "Ensure the Telugu is natural, grammatically correct, and easy to read."
    )
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Transcript:\n{transcript}"}
            ],
            temperature=0.3,
            max_tokens=2048
        )
        return completion.choices[0].message.content  # fixed: choices[0]
    except Exception as e:
        return f"Groq API Error: {str(e)}"

if __name__ == "__main__":
    YOUTUBE_URL = "https://www.youtube.com/watch?v=lMfye4oL6mQ"

    try:
        print("Parsing URL...")
        video_id = extract_video_id(YOUTUBE_URL)
        print(f"Extracted Video ID: {video_id}")

        print("Fetching transcript...")
        video_transcript = get_youtube_transcript(video_id)
        print("video script ,", video_transcript, "...")  # Print the first 200 characters of the transcript for verification

        if "Error" not in video_transcript:
            print("Generating Telugu summary using Groq Llama 3...")
            telugu_summary = summarize_in_telugu(video_transcript)
            print("\n--- తెలుగు సారాంశం (Telugu Summary) ---\n")
            print(telugu_summary)
        else:
            print(video_transcript)

    except ValueError as ve:
        print(f"URL Error: {ve}")
