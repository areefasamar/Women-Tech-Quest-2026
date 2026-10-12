"""Configuration: reads .env, exposes typed settings. Never prints the key."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()

MODEL_NAME: str = _get("MODEL_NAME", "gemini-3.5-flash-lite")
FALLBACK_MODEL_NAME: str = _get("FALLBACK_MODEL_NAME", "gemini-3.1-flash-lite")
API_KEY: str = _get("API_KEY")          # never logged or printed
TEMPERATURE: float = float(_get("TEMPERATURE", "0"))
SEED: int = int(_get("SEED", "42"))
REQUESTS_PER_MINUTE: int = int(_get("REQUESTS_PER_MINUTE", "12"))

BASE_DIR = Path(__file__).parent.parent
CACHE_DIR = BASE_DIR / "cache"
LOGS_DIR  = BASE_DIR / "logs"
OUTPUT_DIR = BASE_DIR / "output"
PROMPTS_DIR = BASE_DIR / "src" / "prompts"

CACHE_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
