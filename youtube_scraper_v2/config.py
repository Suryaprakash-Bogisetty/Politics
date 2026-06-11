import os
from dotenv import load_dotenv

load_dotenv()

YOUTUBE_API_KEY    = os.getenv("YOUTUBE_API_KEY", "")
GROQ_API_KEY       = os.getenv("GROQ_API_KEY", "")
SUPADATA_API_KEY   = os.getenv("SUPADATA_API_KEY", "")
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY", "")

KEYWORDS = [
    "Chandrababu Naidu",
    "Nara Lokesh",
    "Pawan Kalyan",
    "TDP Telugu Desam",
    "Jana Sena Party",
    "చంద్రబాబు నాయుడు",
    "పవన్ కళ్యాణ్",
]

MAX_VIDEOS_PER_KEYWORD = 5
GROQ_MODEL             = "llama-3.1-8b-instant"
OUTPUT_FILE            = "output.csv"
