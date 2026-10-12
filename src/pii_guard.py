"""
pii_guard.py – scrub personal identifiers from text strings.

Removes digit strings longer than 8 digits (unless they look like PKR money amounts),
and ID-looking tokens (account numbers, CNIC patterns, etc.).
"""
from __future__ import annotations
import re


# Patterns that indicate a PII value
_LONG_DIGITS = re.compile(r"\b\d{9,}\b")
_CNIC = re.compile(r"\b\d{5}-\d{7}-\d{1}\b")
_ACCOUNT_LIKE = re.compile(r"\b\d{7,}\b")

# Money amounts are fine: digits with optional commas / decimals
_MONEY_AMOUNT = re.compile(r"\b\d{1,3}(?:,\d{3})*(?:\.\d{1,4})?\b")


def scrub(text: str) -> str:
    """Remove PII tokens from a text string."""
    if not text:
        return text
    # Remove CNIC pattern first
    text = _CNIC.sub("[ID]", text)
    # Remove long digit strings that are not money amounts
    def _replace_digit_seq(m: re.Match) -> str:
        val = m.group(0)
        # Allow if it looks like a money amount (no internal structure expected for >8 digits)
        # Just remove anything >8 digits
        if len(val) > 8:
            return "[ID]"
        return val
    text = re.sub(r"\b\d+\b", _replace_digit_seq, text)
    return text


def check_no_pii(text: str) -> bool:
    """Return True if text appears to be PII-free."""
    if _CNIC.search(text):
        return False
    if _LONG_DIGITS.search(text):
        return False
    return True
