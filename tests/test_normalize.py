"""
test_normalize.py – unit tests for normalize.py
"""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.normalize import parse_amount, parse_date, normalize


class TestParseAmount:
    def test_zero_is_real(self):
        assert parse_amount(0) == 0.0
        assert parse_amount("0") == 0.0

    def test_cr_suffix(self):
        assert parse_amount("54770CR") == -54770.0
        assert parse_amount("38209CR") == -38209.0

    def test_negative_text(self):
        assert parse_amount("-0.53") == -0.53
        assert parse_amount("Rs. -0.53") == -0.53

    def test_not_to_be_paid(self):
        assert parse_amount("NOT TO BE PAID") is None

    def test_commas_and_rs(self):
        assert parse_amount("Rs. 3,430.24") == 3430.24
        assert parse_amount("1,54,000") == 154000.0

    def test_none_input(self):
        assert parse_amount(None) is None

    def test_plain_number(self):
        assert parse_amount(900) == 900.0
        assert parse_amount(3430.24) == 3430.24


class TestParseDate:
    def test_iso_passthrough(self):
        assert parse_date("2026-04-21") == "2026-04-21"

    def test_two_digit_year(self):
        assert parse_date("25 SEP 26") == "2026-09-25"
        assert parse_date("17 JUL 26") == "2026-07-17"
        assert parse_date("13th Jul 2026") == "2026-07-13"

    def test_month_only(self):
        result = parse_date("Jun-26")
        assert result == "2026-06"
        result2 = parse_date("JUL 2026")
        assert result2 == "2026-07"

    def test_apr_26(self):
        assert parse_date("Apr-26") == "2026-04"

    def test_none_input(self):
        assert parse_date(None) is None

    def test_bad_date(self):
        assert parse_date("not a date") is None


class TestNormalize:
    def test_subsidy_forced_negative(self):
        raw = {
            "provider": "IESCO", "tariff": "A-1a(01)", "sanctioned_load_kw": 3,
            "bill_month": "2026-09", "reading_date": "2026-09-25", "issue_date": "2026-09-26",
            "due_date": "2026-10-08",
            "previous_reading": 9301, "current_reading": 9459, "units_consumed": 158,
            "charges": [
                {"type": "energy", "amount": 6102},
                {"type": "subsidy", "amount": 3332},   # positive → should be negated
            ],
            "total_charges": 2770,
            "taxes": [], "total_taxes": 498,
            "current_bill": 3267, "arrears": 0,
            "payable_within_due_date": 3535, "payable_after_due_date": None,
        }
        result = normalize(raw)
        assert result["charges"][1]["amount"] == -3332

    def test_zero_charges_dropped(self):
        raw = {
            "provider": "KE", "tariff": "A1-R", "sanctioned_load_kw": 3,
            "bill_month": "2026-04", "reading_date": None, "issue_date": None, "due_date": None,
            "previous_reading": None, "current_reading": None, "units_consumed": None,
            "charges": [
                {"type": "energy", "amount": 0},
                {"type": "fixed", "amount": 900},
            ],
            "total_charges": 900, "taxes": [], "total_taxes": None,
            "current_bill": None, "arrears": None,
            "payable_within_due_date": None, "payable_after_due_date": None,
        }
        result = normalize(raw)
        assert len(result["charges"]) == 1  # zero line dropped
        assert result["charges"][0]["amount"] == 900.0

    def test_late_payment_amounts(self):
        raw = {
            "provider": "KE", "tariff": "A1-R", "sanctioned_load_kw": 3,
            "bill_month": "2026-04", "reading_date": None, "issue_date": None, "due_date": None,
            "previous_reading": None, "current_reading": None, "units_consumed": None,
            "charges": [], "total_charges": None, "taxes": [], "total_taxes": None,
            "current_bill": None, "arrears": None, "payable_within_due_date": None,
            "late_payment_amounts": [3574, 3716],
            "payable_after_due_date": None,
        }
        result = normalize(raw)
        assert result["payable_after_due_date"] == 3716.0

    def test_schema_keys_present(self):
        from src.normalize import SCHEMA_KEYS
        raw = {"provider": "KE"}
        result = normalize(raw)
        for k in SCHEMA_KEYS:
            assert k in result, f"Missing key: {k}"
