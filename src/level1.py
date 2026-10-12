"""
level1.py – Level 1 extraction: call LLM, normalise, validate, optional re-read.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path

from src.image_prep import prepare_images
from src.llm_client import call_gemini
from src.normalize import normalize
from src.validate import check, build_reread_prompt
from src.schemas import Level1Bill
from src.config import PROMPTS_DIR

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
    return (PROMPTS_DIR / "level1_system.md").read_text(encoding="utf-8")


def extract_level1(
    bill_path: Path,
    use_cache: bool = True,
) -> dict:
    """
    Full Level 1 pipeline for one bill:
      1. Prepare images (full + top + bottom)
      2. Call Gemini with level1_system.md prompt
      3. Normalise
      4. Validate → if fails: one targeted re-read
      5. Return clean dict

    Never raises on extraction failure – returns a dict with null fields and logs the error.
    """
    bill_id = bill_path.stem
    prompt = _load_prompt()
    full_bytes, top_bytes, bot_bytes = prepare_images(bill_path)
    images = [full_bytes, top_bytes, bot_bytes]

    try:
        raw = call_gemini(
            prompt=prompt,
            images=images,
            schema_class=Level1Bill,
            tag=f"{bill_id}/L1",
            use_cache=use_cache,
        )
        bill = normalize(raw)

        # Provider cross-check (trust image, just log mismatches)
        expected_provider = _provider_from_filename(bill_id)
        if expected_provider and bill.get("provider") and bill["provider"] != expected_provider:
            logger.warning("[%s] provider mismatch: file says %s, image says %s",
                           bill_id, expected_provider, bill["provider"])

        # Validation
        failures = check(bill)
        if failures:
            logger.warning("[%s] validation failures: %s", bill_id, failures)
            reread_prompt = build_reread_prompt(failures, bill) + "\n\n" + prompt
            try:
                raw2 = call_gemini(
                    prompt=reread_prompt,
                    images=images,
                    schema_class=Level1Bill,
                    tag=f"{bill_id}/L1-reread",
                    use_cache=use_cache,
                )
                bill2 = normalize(raw2)
                failures2 = check(bill2)
                if failures2:
                    logger.warning("[%s] re-read still has failures (accepted): %s", bill_id, failures2)
                bill = bill2
            except Exception as exc:
                logger.warning("[%s] re-read failed (%s), keeping first result", bill_id, exc)

        logger.info("[%s] Level 1 done: provider=%s tariff=%s",
                    bill_id, bill.get("provider"), bill.get("tariff"))
        return bill

    except Exception as exc:
        logger.error("[%s] Level 1 extraction failed: %s", bill_id, exc)
        return _null_bill()


def _provider_from_filename(stem: str) -> str | None:
    stem_upper = stem.upper()
    if stem_upper.startswith("KESC"):
        return "KE"
    if stem_upper.startswith("LESCO"):
        return "LESCO"
    if stem_upper.startswith("IESCO"):
        return "IESCO"
    return None


def _null_bill() -> dict:
    return {
        "provider": None, "tariff": None, "sanctioned_load_kw": None,
        "bill_month": None, "reading_date": None, "issue_date": None, "due_date": None,
        "previous_reading": None, "current_reading": None, "units_consumed": None,
        "charges": [], "total_charges": None,
        "taxes": [], "total_taxes": None,
        "current_bill": None, "arrears": None,
        "payable_within_due_date": None, "payable_after_due_date": None,
    }
