"""Central configuration. Every value can be overridden by environment variables or backend/.env."""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv()  # also honour a .env in the current working directory


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:1.7b").strip()
OLLAMA_TIMEOUT_SECONDS = _float("OLLAMA_TIMEOUT_SECONDS", 180)
OLLAMA_MAX_ATTEMPTS = max(1, _int("OLLAMA_MAX_ATTEMPTS", 2))

# Comma separated list of allowed browser origins.
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5500")
EXTRA_ORIGINS = [
    "http://localhost:5500", "http://127.0.0.1:5500",
    "http://localhost:5501", "http://127.0.0.1:5501",
]


def allowed_origins() -> list[str]:
    configured = [o.strip().rstrip("/") for o in FRONTEND_ORIGIN.split(",") if o.strip()]
    return list(dict.fromkeys(configured + EXTRA_ORIGINS))


MAX_PERSONAS_PER_REQUEST = _int("MAX_PERSONAS_PER_REQUEST", 20)
MAX_SURVEY_QUESTIONS = _int("MAX_SURVEY_QUESTIONS", 20)
MAX_SURVEY_PERSONAS = _int("MAX_SURVEY_PERSONAS", 30)
MAX_INTERVIEW_MESSAGE_CHARS = _int("MAX_INTERVIEW_MESSAGE_CHARS", 2000)
INTERVIEW_CONTEXT_MESSAGES = _int("INTERVIEW_CONTEXT_MESSAGES", 12)
# A survey stuck in "processing" longer than this is treated as abandoned (server crash).
STALE_PROCESSING_MINUTES = _int("STALE_PROCESSING_MINUTES", 30)
FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
