import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 2
TITLE_SIMILARITY_THRESHOLD = 0.85

OUTPUT_DIR = "output"

# {key: (display_name, domain)}
TELUGU_SITES = {
    "eenadu": ("Eenadu", "eenadu.net"),
    "sakshi": ("Sakshi", "sakshi.com"),
    "andhrajyothy": ("Andhra Jyothy", "andhrajyothy.com"),
    "ntv": ("NTV Telugu", "ntvtelugu.com"),
    "tv9": ("TV9 Telugu", "tv9telugu.com"),
    "abn": ("ABN Telugu", "abntelugu.com"),
}

ENGLISH_SITES = {
    "thehindu": ("The Hindu", "thehindu.com"),
    "toi": ("Times of India", "timesofindia.indiatimes.com"),
    "deccan": ("Deccan Chronicle", "deccanchronicle.com"),
    "indianexpress": ("Indian Express", "indianexpress.com"),
}
