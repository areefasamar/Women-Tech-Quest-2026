"""
LLM client: rate-limited, retry+fallback, disk-cached Gemini wrapper.

One public function: call_gemini(prompt, images, schema_class, tag) -> dict
"""
from __future__ import annotations
import hashlib, json, logging, time, random, pickle
from pathlib import Path
from typing import Optional, Type

import google.genai as genai
from google.genai import types as gtypes
from pydantic import BaseModel

from src.config import (
    MODEL_NAME, FALLBACK_MODEL_NAME, API_KEY, TEMPERATURE, SEED,
    REQUESTS_PER_MINUTE, CACHE_DIR,
)

logger = logging.getLogger(__name__)

# ── token bucket ──────────────────────────────────────────────────────────────
_bucket_tokens: float = float(REQUESTS_PER_MINUTE)
_bucket_last: float = time.monotonic()

def _wait_for_token() -> None:
    global _bucket_tokens, _bucket_last
    now = time.monotonic()
    elapsed = now - _bucket_last
    _bucket_tokens = min(REQUESTS_PER_MINUTE, _bucket_tokens + elapsed * (REQUESTS_PER_MINUTE / 60.0))
    _bucket_last = now
    if _bucket_tokens < 1.0:
        sleep = (1.0 - _bucket_tokens) * 60.0 / REQUESTS_PER_MINUTE
        logger.debug("Rate limit: sleeping %.1fs", sleep)
        time.sleep(sleep)
        _bucket_tokens = 0.0
    else:
        _bucket_tokens -= 1.0

# ── disk cache ────────────────────────────────────────────────────────────────
def _cache_key(prompt: str, image_bytes_list: list[bytes], model: str, schema_name: str) -> str:
    h = hashlib.sha256()
    h.update(model.encode())
    h.update(schema_name.encode())
    h.update(prompt.encode())
    for b in image_bytes_list:
        h.update(b)
    return h.hexdigest()

def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.pkl"

def _cache_get(key: str) -> Optional[dict]:
    p = _cache_path(key)
    if p.exists():
        try:
            with open(p, "rb") as f:
                return pickle.load(f)
        except Exception:
            p.unlink(missing_ok=True)
    return None

def _cache_set(key: str, value: dict) -> None:
    with open(_cache_path(key), "wb") as f:
        pickle.dump(value, f)

# ── client factory ────────────────────────────────────────────────────────────
_client: Optional[genai.Client] = None

def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=API_KEY)
    return _client

# ── main call ─────────────────────────────────────────────────────────────────
def call_gemini(
    prompt: str,
    images: list[bytes],            # raw image bytes, any format Pillow can read
    schema_class: Type[BaseModel],
    tag: str = "call",
    use_cache: bool = True,
    force_fallback: bool = False,
) -> dict:
    """
    Send prompt + images to Gemini, get back a validated JSON dict.

    Returns the parsed dict on success.
    Raises on unrecoverable error after max retries.
    """
    model = FALLBACK_MODEL_NAME if force_fallback else MODEL_NAME
    schema_name = schema_class.__name__
    cache_key = _cache_key(prompt, images, model, schema_name)

    if use_cache:
        cached = _cache_get(cache_key)
        if cached is not None:
            logger.info("[%s] cache hit (model=%s)", tag, model)
            return cached

    client = _get_client()

    # Build content parts
    parts: list = []
    for i, img_bytes in enumerate(images):
        parts.append(gtypes.Part.from_bytes(data=img_bytes, mime_type=_guess_mime(img_bytes)))
    parts.append(gtypes.Part.from_text(text=prompt))

    config = gtypes.GenerateContentConfig(
        temperature=TEMPERATURE,
        seed=SEED,
        response_mime_type="application/json",
        response_schema=schema_class,
    )

    max_retries = 5
    backoff = 2.0
    last_err = None

    for attempt in range(max_retries):
        try:
            _wait_for_token()
            t0 = time.monotonic()
            response = client.models.generate_content(
                model=model,
                contents=parts,
                config=config,
            )
            elapsed = time.monotonic() - t0
            logger.info("[%s] model=%s attempt=%d elapsed=%.1fs", tag, model, attempt, elapsed)
            result = json.loads(response.text)
            if use_cache:
                _cache_set(cache_key, result)
            return result

        except Exception as exc:
            last_err = exc
            msg = str(exc)
            is_rate = "429" in msg or "quota" in msg.lower() or "rate" in msg.lower()
            is_server = "5" in msg[:3] if len(msg) >= 3 else False

            # auto-fallback model on repeated 429/5xx
            if attempt >= 2 and not force_fallback and (is_rate or is_server):
                logger.warning("[%s] switching to fallback model after %d attempts", tag, attempt + 1)
                model = FALLBACK_MODEL_NAME
                cache_key = _cache_key(prompt, images, model, schema_name)
                if use_cache:
                    cached = _cache_get(cache_key)
                    if cached is not None:
                        return cached

            sleep = backoff * (2 ** attempt) + random.uniform(0, 1)
            logger.warning("[%s] attempt=%d error=%s sleeping=%.1fs", tag, attempt, msg[:120], sleep)
            time.sleep(sleep)

    raise RuntimeError(f"[{tag}] all retries failed: {last_err}") from last_err


def _guess_mime(data: bytes) -> str:
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:2] in (b"\xff\xd8",):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"
