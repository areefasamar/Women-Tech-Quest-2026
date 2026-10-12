"""
test_csv_io.py – unit tests for csv_io.py
"""
import csv, json, os, sys, tempfile
from pathlib import Path
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.csv_io import write_level1_csv, write_level2_csv


def _make_l1_template(tmp_dir: Path, bill_ids: list[str]) -> Path:
    p = tmp_dir / "l1_template.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["bill_id", "json"])
        w.writeheader()
        for bid in bill_ids:
            w.writerow({"bill_id": bid, "json": ""})
    return p


def _make_l2_template(tmp_dir: Path, bill_ids: list[str], qids: list[str]) -> Path:
    p = tmp_dir / "l2_template.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["bill_id", "question_id", "question", "answer"])
        w.writeheader()
        for bid in bill_ids:
            for qid in qids:
                w.writerow({"bill_id": bid, "question_id": qid, "question": f"Q {qid}?", "answer": ""})
    return p


def _minimal_l1(provider="KE") -> dict:
    return {
        "provider": provider, "tariff": "A1-R", "sanctioned_load_kw": 3.0,
        "bill_month": "2026-04", "reading_date": "2026-04-03",
        "issue_date": "2026-04-07", "due_date": "2026-04-21",
        "previous_reading": 8819.0, "current_reading": 8970.0, "units_consumed": 151.0,
        "charges": [{"type": "energy", "amount": 1054.0}], "total_charges": 1054.0,
        "taxes": [{"type": "gst", "amount": 50.0}], "total_taxes": 50.0,
        "current_bill": 1104.0, "arrears": 0.0,
        "payable_within_due_date": 1104.0, "payable_after_due_date": 1200.0,
    }


def test_write_level1_csv():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        bills = ["KESC_0008", "LESCO_0005"]
        tmpl = _make_l1_template(tmp, bills)
        out = tmp / "level1.csv"
        results = {bid: _minimal_l1() for bid in bills}
        write_level1_csv(tmpl, out, results)

        with open(out, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2
        for row in rows:
            obj = json.loads(row["json"])
            assert "provider" in obj
            assert row["bill_id"] in bills


def test_write_level2_csv():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        bills = ["KESC_0008"]
        qids = ["Q1", "Q2"]
        tmpl = _make_l2_template(tmp, bills, qids)
        out = tmp / "level2.csv"
        answers = {"KESC_0008": {"Q1": "First answer.", "Q2": "Second answer."}}
        write_level2_csv(tmpl, out, answers)

        with open(out, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2
        assert rows[0]["answer"] == "First answer."
        assert rows[1]["answer"] == "Second answer."


def test_no_empty_cells():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        bills = ["KESC_0008"]
        tmpl = _make_l1_template(tmp, bills)
        out = tmp / "level1.csv"
        results = {"KESC_0008": _minimal_l1()}
        write_level1_csv(tmpl, out, results)
        with open(out, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            for k, v in row.items():
                assert v is not None and str(v).strip() != "", f"Empty cell col={k}"
