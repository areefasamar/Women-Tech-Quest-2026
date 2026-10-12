"""
test_safe_calc.py – unit tests for safe_calc.py
"""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.safe_calc import safe_eval, pct, avg, pluck, count_where


class TestSafeEval:
    def test_basic_arithmetic(self):
        assert safe_eval("1 + 2", {}, {}) == 3
        assert safe_eval("10 / 4", {}, {}) == 2.5

    def test_l1_access(self):
        l1 = {"current_bill": 3430.24, "total_taxes": 569.62}
        result = safe_eval("l1['total_taxes']", l1, {})
        assert result == 569.62

    def test_pct_helper(self):
        l1 = {"current_bill": 3430.24, "total_taxes": 569.62}
        result = safe_eval("pct(l1['total_taxes'], l1['current_bill'])", l1, {})
        assert abs(result - 16.606) < 0.01

    def test_pct_zero_whole(self):
        assert pct(100, 0) == 0.0
        assert pct(100, None) == 0.0

    def test_avg_helper(self):
        facts = {"usage_history": [{"units": 100}, {"units": 200}, {"units": 150}]}
        result = safe_eval("avg(pluck(facts['usage_history'], 'units'))", {}, facts)
        assert result == 150.0

    def test_error_on_import(self):
        result = safe_eval("__import__('os')", {}, {})
        assert result == "error"

    def test_error_on_long_expr(self):
        result = safe_eval("1+" * 300, {}, {})
        assert result == "error"

    def test_null_guard(self):
        l1 = {"current_bill": None}
        result = safe_eval("(l1['current_bill'] or 0) + 100", l1, {})
        assert result == 100

    def test_pluck(self):
        lst = [{"units": 100}, {"units": 200}, {"units": None}]
        result = pluck(lst, "units")
        assert result == [100, 200]

    def test_count_where(self):
        lst = [{"units": 100}, {"units": 200}, {"units": 50}]
        assert count_where(lst, "units", ">", 100) == 1
