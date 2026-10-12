"""
main.py – CLI entry point for batch processing of electricity bills.

Usage:
  python main.py --bills input/train/bills --level1-template input/train/level1_template.csv \
                 --level2-template input/train/level2_template.csv --out output/

  python main.py --bills input/test/bills --level1-template input/test/csv/level1.csv \
                 --level2-template input/test/csv/level2.csv --out output/

Flags:
  --only KESC_0008     process a single bill (stem name)
  --no-cache           disable disk cache
  --skip-level2        skip Level 2 answers
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Configure logging before imports
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/run.log", mode="a", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

from src.level1 import extract_level1
from src.facts import extract_facts
from src.level2 import answer_questions
from src.image_prep import prepare_images
from src.csv_io import write_level1_csv, write_level2_csv, read_level2_template
from src.config import OUTPUT_DIR


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def main():
    parser = argparse.ArgumentParser(description="Electricity Bill Decoder – batch run")
    parser.add_argument("--bills", required=True, help="Directory containing bill images")
    parser.add_argument("--level1-template", required=True, help="level1 CSV template path")
    parser.add_argument("--level2-template", help="level2 CSV template path")
    parser.add_argument("--out", default="output", help="Output directory")
    parser.add_argument("--only", help="Process only this bill stem (e.g. KESC_0008)")
    parser.add_argument("--no-cache", action="store_true", help="Disable disk cache")
    parser.add_argument("--skip-level2", action="store_true", help="Skip Level 2")
    args = parser.parse_args()

    bills_dir = Path(args.bills)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    use_cache = not args.no_cache

    # Gather bill files
    bill_files = sorted(
        f for f in bills_dir.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
    )
    if args.only:
        bill_files = [f for f in bill_files if f.stem == args.only]
        if not bill_files:
            logger.error("No bill found with stem %r in %s", args.only, bills_dir)
            sys.exit(1)

    logger.info("Processing %d bill(s) from %s", len(bill_files), bills_dir)

    # ── Level 1 ──────────────────────────────────────────────────────────────
    level1_results: dict[str, dict] = {}
    t_start = time.monotonic()
    for bill_path in bill_files:
        bill_id = bill_path.stem
        logger.info("=== %s: Level 1 extraction ===", bill_id)
        result = extract_level1(bill_path, use_cache=use_cache)
        level1_results[bill_id] = result
        logger.info("%s -> %s", bill_id, json.dumps(result, separators=(",", ":"), ensure_ascii=False))

    # Write level1.csv
    level1_out = out_dir / "level1.csv"
    try:
        write_level1_csv(Path(args.level1_template), level1_out, level1_results)
        logger.info("[OK] level1.csv written to %s", level1_out)
    except Exception as exc:
        logger.error("Failed to write level1.csv: %s", exc)

    if args.skip_level2 or not args.level2_template:
        logger.info("Skipping Level 2.")
        _print_summary(level1_results, {}, time.monotonic() - t_start)
        return

    # ── Level 2 ──────────────────────────────────────────────────────────────
    level2_template = Path(args.level2_template)
    template_rows = read_level2_template(level2_template)

    # Load question list (same for all bills)
    questions_all: list[dict] = []
    seen_qids: set[str] = set()
    for row in template_rows:
        qid = row.get("question_id", "")
        if qid and qid not in seen_qids:
            questions_all.append({"question_id": qid, "question": row.get("question", "")})
            seen_qids.add(qid)

    # Get unique bill_ids from template
    template_bill_ids = []
    seen = set()
    for row in template_rows:
        bid = row.get("bill_id", "")
        if bid and bid not in seen:
            template_bill_ids.append(bid)
            seen.add(bid)

    all_answers: dict[str, dict[str, str]] = {}

    for bill_id in template_bill_ids:
        # Match bill file
        bill_path = None
        for f in bill_files:
            if f.stem == bill_id:
                bill_path = f
                break

        l1 = level1_results.get(bill_id, {})
        if bill_path is None:
            logger.warning("%s: no image found, using null L1", bill_id)
            all_answers[bill_id] = {
                q["question_id"]: "This information is not shown on this bill."
                for q in questions_all
            }
            continue

        logger.info("=== %s: facts + Level 2 ===", bill_id)
        facts = extract_facts(bill_path, use_cache=use_cache)

        full_bytes, top_bytes, bot_bytes = prepare_images(bill_path)
        bill_images = [full_bytes, top_bytes, bot_bytes]

        answers = answer_questions(
            bill_id=bill_id,
            questions=questions_all,
            l1=l1,
            facts=facts,
            bill_images=bill_images,
            use_cache=use_cache,
        )
        all_answers[bill_id] = answers

    # Write level2.csv
    level2_out = out_dir / "level2.csv"
    try:
        write_level2_csv(level2_template, level2_out, all_answers)
        logger.info("[OK] level2.csv written to %s", level2_out)
    except Exception as exc:
        logger.error("Failed to write level2.csv: %s", exc)

    _print_summary(level1_results, all_answers, time.monotonic() - t_start)


def _print_summary(l1: dict, l2: dict, elapsed: float):
    print("\n" + "=" * 60)
    print(f"DONE in {elapsed:.1f}s")
    print(f"Bills processed: {len(l1)}")
    null_count = sum(1 for v in l1.values() if v.get("provider") is None)
    if null_count:
        print(f"WARNING: {null_count} bill(s) have null provider (extraction may have failed)")
    if l2:
        print(f"Level 2 answers: {sum(len(v) for v in l2.values())} total")
    print("=" * 60)


if __name__ == "__main__":
    main()
