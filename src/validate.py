"""
validate.py – consistency checks that trigger ONE targeted re-read.

Rules: flag only, never silently correct.
Tolerance: ±2.
"""
from __future__ import annotations
import logging
from typing import Optional

logger = logging.getLogger(__name__)

TOLERANCE = 2.0


def _close(a: Optional[float], b: Optional[float], tol: float = TOLERANCE) -> bool:
    if a is None or b is None:
        return True   # can't check – not a failure
    return abs(a - b) <= tol


def _sum_list(items: list, key: str) -> Optional[float]:
    vals = [x.get(key) for x in items if isinstance(x, dict) and x.get(key) is not None]
    return sum(vals) if vals else None


def check(bill: dict) -> list[str]:
    """
    Return a list of failure descriptions. Empty list = all checks passed.
    """
    failures: list[str] = []

    # 1. readings → units_consumed
    prev = bill.get("previous_reading")
    curr = bill.get("current_reading")
    units = bill.get("units_consumed")
    provider = bill.get("provider")
    # Skip reading check for net metering bills (LESCO net metering, KESC_0004)
    # We detect net metering by multiple charges of type energy or large negative arrears
    is_net_meter = _is_net_metering(bill)
    if not is_net_meter and prev is not None and curr is not None and units is not None:
        implied = curr - prev
        if not _close(implied, units, tol=max(TOLERANCE, abs(units) * 0.01)):
            failures.append(
                f"readings: current_reading({curr}) - previous_reading({prev}) = {implied:.1f} "
                f"but units_consumed = {units}"
            )

    # 2. sum of charges ≈ total_charges
    charge_sum = _sum_list(bill.get("charges") or [], "amount")
    total_charges = bill.get("total_charges")
    if charge_sum is not None and total_charges is not None:
        if not _close(charge_sum, total_charges):
            failures.append(
                f"charges: sum({charge_sum:.2f}) ≠ total_charges({total_charges:.2f})"
            )

    # 3. sum of taxes ≈ total_taxes
    tax_sum = _sum_list(bill.get("taxes") or [], "amount")
    total_taxes = bill.get("total_taxes")
    if tax_sum is not None and total_taxes is not None:
        if not _close(tax_sum, total_taxes):
            failures.append(
                f"taxes: sum({tax_sum:.2f}) ≠ total_taxes({total_taxes:.2f})"
            )

    # 4. total_charges + total_taxes ≈ current_bill
    current_bill = bill.get("current_bill")
    if total_charges is not None and total_taxes is not None and current_bill is not None:
        implied_bill = total_charges + (total_taxes or 0)
        if not _close(implied_bill, current_bill):
            failures.append(
                f"current_bill: total_charges({total_charges}) + total_taxes({total_taxes}) = "
                f"{implied_bill:.2f} ≠ current_bill({current_bill})"
            )

    return failures


def _is_net_metering(bill: dict) -> bool:
    """Heuristic: bill has multiple energy-type charges (off-peak, peak, import)."""
    charges = bill.get("charges") or []
    energy_count = sum(1 for c in charges if c.get("type") == "energy")
    return energy_count > 1


def build_reread_prompt(failures: list[str], bill: dict) -> str:
    """Build a targeted re-read prompt that names the failing fields."""
    field_groups = set()
    for f in failures:
        if "readings" in f:
            field_groups.add("meter readings (previous_reading, current_reading, units_consumed)")
        if "charges" in f:
            field_groups.add("charges list and total_charges")
        if "taxes" in f:
            field_groups.add("taxes list and total_taxes")
        if "current_bill" in f:
            field_groups.add("current_bill, total_charges, total_taxes")

    groups_str = "; ".join(sorted(field_groups))
    return (
        f"The previous extraction had inconsistencies in: {groups_str}.\n"
        f"Please look at those sections of the bill again very carefully and re-extract "
        f"ONLY the values that appear on the bill. Return the complete JSON.\n"
        f"Failures found: {' | '.join(failures)}"
    )
