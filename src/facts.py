"""
facts.py – bill facts extraction (Level 2 input).
"""
from __future__ import annotations
import logging
from pathlib import Path

from src.image_prep import prepare_images
from src.llm_client import call_gemini
from src.schemas import BillFacts
from src.config import PROMPTS_DIR

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
    return (PROMPTS_DIR / "facts_system.md").read_text(encoding="utf-8")


def extract_facts(
    bill_path: Path,
    use_cache: bool = True,
) -> dict:
    """
    Extract bill facts for Level 2 answering.
    Returns a dict (BillFacts schema). Never raises – returns empty facts on failure.
    """
    bill_id = bill_path.stem
    prompt = _load_prompt()
    full_bytes, top_bytes, bot_bytes = prepare_images(bill_path)

    try:
        raw = call_gemini(
            prompt=prompt,
            images=[full_bytes, top_bytes, bot_bytes],
            schema_class=BillFacts,
            tag=f"{bill_id}/facts",
            use_cache=use_cache,
        )
        # Ensure all list fields are lists (not None)
        for list_field in ("usage_history", "billing_history", "line_items",
                           "late_payment_info", "message_board",
                           "unclear_or_unreadable", "other_notes"):
            if raw.get(list_field) is None:
                raw[list_field] = []
        logger.info("[%s] facts extracted: %d usage months, %d billing months",
                    bill_id,
                    len(raw.get("usage_history") or []),
                    len(raw.get("billing_history") or []))
        return raw
    except Exception as exc:
        logger.error("[%s] facts extraction failed: %s", bill_id, exc)
        return {
            "usage_history": [], "billing_history": [], "line_items": [],
            "printed_percentages": None, "late_payment_info": [],
            "message_board": [], "unclear_or_unreadable": [], "other_notes": [],
        }
