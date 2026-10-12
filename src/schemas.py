"""Pydantic schemas for Level 1, BillFacts, and Level 2 plan/write."""
from __future__ import annotations
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────
# Level 1
# ──────────────────────────────────────────────────────────────

class ChargeItem(BaseModel):
    type: str   # energy|fixed|fpa|quarterly_adjustment|surcharge|meter_rent|subsidy|other
    amount: Optional[float] = None

class TaxItem(BaseModel):
    type: str   # gst|electricity_duty|income_tax|municipal_tax|other_tax
    amount: Optional[float] = None

class Level1Bill(BaseModel):
    provider: Optional[str] = None          # KE | LESCO | IESCO
    tariff: Optional[str] = None
    sanctioned_load_kw: Optional[float] = None
    bill_month: Optional[str] = None        # YYYY-MM
    reading_date: Optional[str] = None      # YYYY-MM-DD
    issue_date: Optional[str] = None        # YYYY-MM-DD
    due_date: Optional[str] = None          # YYYY-MM-DD
    previous_reading: Optional[float] = None
    current_reading: Optional[float] = None
    units_consumed: Optional[float] = None
    charges: List[ChargeItem] = Field(default_factory=list)
    total_charges: Optional[float] = None
    taxes: List[TaxItem] = Field(default_factory=list)
    total_taxes: Optional[float] = None
    current_bill: Optional[float] = None
    arrears: Optional[float] = None
    payable_within_due_date: Optional[float] = None
    payable_after_due_date: Optional[float] = None
    # internal field – Python resolves this, then deletes it
    late_payment_amounts: Optional[List[float]] = None


# ──────────────────────────────────────────────────────────────
# Bill Facts (Level 2 input)
# ──────────────────────────────────────────────────────────────

class UsageMonth(BaseModel):
    month: Optional[str] = None
    units: Optional[float] = None

class BillingMonth(BaseModel):
    month: Optional[str] = None
    billed: Optional[float] = None
    paid_date: Optional[str] = None
    paid: Optional[float] = None

class LineItem(BaseModel):
    section: Optional[str] = None
    label: Optional[str] = None
    units: Optional[float] = None
    rate: Optional[float] = None
    amount: Optional[float] = None

class PrintedPercentages(BaseModel):
    energy_pct: Optional[float] = None
    taxes_pct: Optional[float] = None

class BillFacts(BaseModel):
    usage_history: List[UsageMonth] = Field(default_factory=list)
    billing_history: List[BillingMonth] = Field(default_factory=list)
    line_items: List[LineItem] = Field(default_factory=list)
    printed_percentages: Optional[PrintedPercentages] = None
    late_payment_info: List[str] = Field(default_factory=list)
    message_board: List[str] = Field(default_factory=list)
    unclear_or_unreadable: List[str] = Field(default_factory=list)
    other_notes: List[str] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────
# Level 2 plan
# ──────────────────────────────────────────────────────────────

class Calculation(BaseModel):
    name: str
    expression: str

class L2PlanItem(BaseModel):
    question_id: str
    interpretation: Optional[str] = None
    answerable_from_bill: bool = True
    calculations: List[Calculation] = Field(default_factory=list)
    missing_info: Optional[str] = None

class L2Plan(BaseModel):
    items: List[L2PlanItem] = Field(default_factory=list)
