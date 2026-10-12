"""
normalize.py – deterministic cleanup of raw Level 1 LLM output.

All functions are pure Python (no LLM calls).
"""
from __future__ import annotations
import logging
import re
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

VALID_CHARGE_TYPES = {
    "energy", "fixed", "fpa", "quarterly_adjustment",
    "surcharge", "meter_rent", "subsidy", "other",
}
VALID_TAX_TYPES = {
    "gst", "electricity_duty", "income_tax", "municipal_tax", "other_tax",
}

SCHEMA_KEYS = [
    "provider", "tariff", "sanctioned_load_kw", "bill_month",
    "reading_date", "issue_date", "due_date",
    "previous_reading", "current_reading", "units_consumed",
    "charges", "total_charges",
    "taxes", "total_taxes",
    "current_bill", "arrears",
    "payable_within_due_date", "payable_after_due_date",
]


# ── number coercion ───────────────────────────────────────────────────────────

def parse_amount(raw: Any) -> Optional[float]:
    """
    Convert a raw value to float.
    - Strips Rs., commas, spaces.
    - CR suffix → negative.
    - Text that is not a number → None.
    - Already a number → pass through.
    - 0 → 0.0 (zero is a real value).
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return None
    # Handle "NOT TO BE PAID" or other non-numeric text
    s_upper = s.upper()
    if s_upper in ("NOT TO BE PAID", "N/A", "-", "—", "NIL", "NULL"):
        return None
    # CR suffix
    negative = False
    if s_upper.endswith("CR"):
        negative = True
        s = s[:-2].strip()
    # Leading minus
    if s.startswith("-"):
        negative = not negative
        s = s[1:].strip()
    # Strip currency symbols, spaces, commas — but NOT the decimal point
    s = s.replace("Rs.", "").replace("Rs", "").replace("PKR", "")
    s = re.sub(r"[\s,]", "", s).strip()
    try:
        val = float(s)
        return -val if negative else val
    except ValueError:
        logger.warning("parse_amount: could not parse %r", raw)
        return None


# ── date parsing ──────────────────────────────────────────────────────────────

_DATE_FMTS_FULL = [
    "%Y-%m-%d",        # 2026-09-22
    "%d-%m-%Y",        # 22-09-2026
    "%d/%m/%Y",        # 22/09/2026
    "%d %b %Y",        # 22 Sep 2026
    "%dst %b %Y", "%dnd %b %Y", "%drd %b %Y", "%dth %b %Y",  # ordinal
    "%d-%b-%Y",        # 22-Sep-2026
    "%d %B %Y",        # 22 September 2026
    "%d-%b-%y",        # 22-Sep-26
    "%d %b %y",        # 22 Sep 26
    "%d-%B-%Y",
]
_DATE_FMTS_MONTH = [
    "%b-%y",           # Sep-26
    "%B-%y",
    "%b %Y",           # Sep 2026
    "%B %Y",
    "%b-%Y",
    "%Y-%m",
    "%b%y",            # Sep26
]


def _fix_ordinal(s: str) -> str:
    """Remove ordinal suffixes: 13th → 13, 22nd → 22."""
    return re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", s, flags=re.IGNORECASE)


def _fix_2digit_year(s: str) -> str:
    """Expand 2-digit years: 26 → 2026 in date strings."""
    # Pattern: ends with space/dash + 2 digits (i.e. -26 or " 26")
    return re.sub(r"[-\s](\d{2})$", lambda m: ("-" if m.group(0)[0] == "-" else " ") + "20" + m.group(1), s)


def parse_date(raw: Any, field: str = "") -> Optional[str]:
    """
    Parse a date string into YYYY-MM-DD (or YYYY-MM for month-only values).
    Returns None and logs a warning if unparseable.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # Already ISO
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    if re.match(r"^\d{4}-\d{2}$", s):
        return s  # month-only bill_month

    s_fixed = _fix_ordinal(s)

    # Try full date formats
    for fmt in _DATE_FMTS_FULL:
        for candidate in (s_fixed, _fix_2digit_year(s_fixed)):
            try:
                dt = datetime.strptime(candidate.strip(), fmt)
                # Expand 2-digit year
                if dt.year < 100:
                    dt = dt.replace(year=2000 + dt.year)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                pass

    # Try month-only formats
    for fmt in _DATE_FMTS_MONTH:
        for candidate in (s_fixed, _fix_2digit_year(s_fixed)):
            try:
                dt = datetime.strptime(candidate.strip(), fmt)
                if dt.year < 100:
                    dt = dt.replace(year=2000 + dt.year)
                return dt.strftime("%Y-%m")
            except ValueError:
                pass

    logger.warning("parse_date: could not parse %r for field %r", raw, field)
    return None


# ── charge / tax type normalisation ──────────────────────────────────────────

def normalize_charge_type(t: Any) -> str:
    s = str(t).strip().lower() if t else ""
    return s if s in VALID_CHARGE_TYPES else "other"


def normalize_tax_type(t: Any) -> str:
    s = str(t).strip().lower() if t else ""
    return s if s in VALID_TAX_TYPES else "other_tax"


# ── main normaliser ───────────────────────────────────────────────────────────

def normalize(raw: dict) -> dict:
    """
    Takes the raw LLM output dict and returns a clean normalised Level 1 dict.
    Fills all 17 schema keys (never adds or removes keys).
    """
    out: dict = {}

    # provider
    prov = str(raw.get("provider") or "").strip().upper()
    out["provider"] = prov if prov in ("KE", "LESCO", "IESCO") else (prov or None)

    # tariff
    out["tariff"] = str(raw.get("tariff") or "").strip() or None

    # sanctioned_load_kw
    out["sanctioned_load_kw"] = parse_amount(raw.get("sanctioned_load_kw"))

    # dates
    out["bill_month"] = parse_date(raw.get("bill_month"), "bill_month")
    out["reading_date"] = parse_date(raw.get("reading_date"), "reading_date")
    out["issue_date"] = parse_date(raw.get("issue_date"), "issue_date")
    out["due_date"] = parse_date(raw.get("due_date"), "due_date")

    # readings / units
    out["previous_reading"] = parse_amount(raw.get("previous_reading"))
    out["current_reading"] = parse_amount(raw.get("current_reading"))
    out["units_consumed"] = parse_amount(raw.get("units_consumed"))

    # charges – drop zero-amount lines, normalise types, force subsidy negative
    raw_charges = raw.get("charges") or []
    charges = []
    for item in raw_charges:
        if not isinstance(item, dict):
            continue
        amt = parse_amount(item.get("amount"))
        if amt is None:
            continue                          # null amount → skip
        if amt == 0.0:
            continue                          # zero lines dropped per spec
        ctype = normalize_charge_type(item.get("type"))
        if ctype == "subsidy" and amt > 0:
            amt = -amt                        # subsidy must be negative
        charges.append({"type": ctype, "amount": amt})
    out["charges"] = charges
    out["total_charges"] = parse_amount(raw.get("total_charges"))

    # taxes
    raw_taxes = raw.get("taxes") or []
    taxes = []
    for item in raw_taxes:
        if not isinstance(item, dict):
            continue
        amt = parse_amount(item.get("amount"))
        if amt is None:
            continue
        ttype = normalize_tax_type(item.get("type"))
        taxes.append({"type": ttype, "amount": amt})
    out["taxes"] = taxes
    out["total_taxes"] = parse_amount(raw.get("total_taxes"))

    # monetary scalars
    out["current_bill"] = parse_amount(raw.get("current_bill"))
    out["arrears"] = parse_amount(raw.get("arrears"))
    out["payable_within_due_date"] = parse_amount(raw.get("payable_within_due_date"))

    # late_payment_amounts → max → payable_after_due_date
    lpa = raw.get("late_payment_amounts")
    if lpa and isinstance(lpa, list):
        parsed_lpa = [parse_amount(x) for x in lpa]
        parsed_lpa = [x for x in parsed_lpa if x is not None]
        if parsed_lpa:
            out["payable_after_due_date"] = max(parsed_lpa)
        else:
            out["payable_after_due_date"] = parse_amount(raw.get("payable_after_due_date"))
    else:
        out["payable_after_due_date"] = parse_amount(raw.get("payable_after_due_date"))

    # enforce all 17 schema keys in schema order
    ordered = {k: out.get(k) for k in SCHEMA_KEYS}
    # default missing list fields
    if ordered["charges"] is None:
        ordered["charges"] = []
    if ordered["taxes"] is None:
        ordered["taxes"] = []

    return ordered
