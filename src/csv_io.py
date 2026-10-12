"""
csv_io.py – read templates and write level1.csv and level2.csv.

Uses only the csv module. UTF-8. QUOTE_MINIMAL.
Verifies output after writing.
"""
from __future__ import annotations
import csv
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

LEVEL1_JSON_KEYS = [
    "provider", "tariff", "sanctioned_load_kw", "bill_month",
    "reading_date", "issue_date", "due_date",
    "previous_reading", "current_reading", "units_consumed",
    "charges", "total_charges",
    "taxes", "total_taxes",
    "current_bill", "arrears",
    "payable_within_due_date", "payable_after_due_date",
]


def read_level1_template(template_path: Path) -> list[dict]:
    """Read the level1 template CSV. Returns list of row dicts."""
    rows = []
    with open(template_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def read_level2_template(template_path: Path) -> list[dict]:
    """Read the level2 template CSV. Returns list of row dicts."""
    rows = []
    with open(template_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def write_level1_csv(
    template_path: Path,
    output_path: Path,
    results: dict[str, dict],  # bill_id → level1 dict
) -> None:
    """
    Fill in the 'json' column of level1 template and write output CSV.
    """
    rows = read_level1_template(template_path)
    out_rows = []
    for row in rows:
        bill_id = row.get("bill_id", "")
        bill_data = results.get(bill_id, {})
        # Enforce schema key order, replace None→null
        ordered = {k: bill_data.get(k) for k in LEVEL1_JSON_KEYS}
        # Ensure list fields are lists not None
        if ordered["charges"] is None:
            ordered["charges"] = []
        if ordered["taxes"] is None:
            ordered["taxes"] = []
        row["json"] = json.dumps(ordered, separators=(",", ":"), ensure_ascii=False)
        out_rows.append(row)

    _write_csv(output_path, out_rows)
    _verify_level1(output_path, len(rows))
    logger.info("level1.csv written: %d rows -> %s", len(out_rows), output_path)


def write_level2_csv(
    template_path: Path,
    output_path: Path,
    answers: dict[str, dict[str, str]],  # bill_id → {question_id → answer}
) -> None:
    """
    Fill in the 'answer' column of level2 template and write output CSV.
    """
    rows = read_level2_template(template_path)
    out_rows = []
    for row in rows:
        bill_id = row.get("bill_id", "")
        question_id = row.get("question_id", "")
        bill_answers = answers.get(bill_id, {})
        ans = bill_answers.get(question_id, "")
        if not ans:
            ans = "The answer could not be determined from this bill image."
        row["answer"] = ans
        out_rows.append(row)

    _write_csv(output_path, out_rows)
    _verify_level2(output_path, len(rows))
    logger.info("level2.csv written: %d rows -> %s", len(out_rows), output_path)


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(rows[0].keys()),
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writeheader()
        writer.writerows(rows)


def _verify_level1(path: Path, expected_rows: int) -> None:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == expected_rows, f"level1.csv: expected {expected_rows} rows, got {len(rows)}"
    for row in rows:
        # No empty cells
        for k, v in row.items():
            assert v is not None and str(v).strip() != "", f"Empty cell in level1.csv col={k} bill={row.get('bill_id')}"
        # JSON parseable with exactly 18 keys
        obj = json.loads(row["json"])
        assert set(obj.keys()) == set(LEVEL1_JSON_KEYS), \
            f"JSON key mismatch for {row.get('bill_id')}: {set(obj.keys()) ^ set(LEVEL1_JSON_KEYS)}"


def _verify_level2(path: Path, expected_rows: int) -> None:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == expected_rows, f"level2.csv: expected {expected_rows} rows, got {len(rows)}"
    for row in rows:
        for k, v in row.items():
            assert v is not None and str(v).strip() != "", \
                f"Empty cell in level2.csv col={k} bill={row.get('bill_id')} q={row.get('question_id')}"
