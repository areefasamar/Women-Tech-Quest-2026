"""
level2.py – Plan → compute → write pipeline for Level 2 answers.

Uses the MVP shortcut (pre-computed generic metrics + one write call)
which is fast and reliable. Upgrade path: plan → compute → write is
also implemented and can be enabled by setting USE_PLAN_FLOW=True.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional

from src.llm_client import call_gemini
from src.safe_calc import safe_eval, avg, pct, pluck
from src.pii_guard import scrub, check_no_pii
from src.schemas import BillFacts
from src.config import PROMPTS_DIR

logger = logging.getLogger(__name__)

USE_PLAN_FLOW = False  # set to False for MVP shortcut per build spec


# ── prompt loaders ────────────────────────────────────────────────────────────

def _plan_prompt() -> str:
    return (PROMPTS_DIR / "l2_plan_system.md").read_text(encoding="utf-8")

def _write_prompt() -> str:
    return (PROMPTS_DIR / "l2_write_system.md").read_text(encoding="utf-8")


# ── generic pre-computed metrics (MVP shortcut base) ─────────────────────────

def _compute_metrics(l1: dict, facts: dict) -> dict:
    usage = pluck(facts.get("usage_history") or [], "units")
    billing = pluck(facts.get("billing_history") or [], "billed")

    cb = l1.get("current_bill") or 0
    tt = l1.get("total_taxes") or 0
    tc = l1.get("total_charges") or 0
    uc = l1.get("units_consumed") or 0
    arrears = l1.get("arrears")
    pwdd = l1.get("payable_within_due_date")
    padd = l1.get("payable_after_due_date")

    late_surcharge = None
    if pwdd is not None and padd is not None:
        late_surcharge = round(padd - pwdd, 2)

    cost_per_unit = round(cb / uc, 4) if uc and uc > 0 else None
    tax_share_pct = pct(tt, cb) if cb else None
    energy_share_pct = pct(tc, cb) if cb else None

    metrics = {
        "cost_per_unit_pkr": cost_per_unit,
        "tax_share_pct": tax_share_pct,
        "energy_share_pct": energy_share_pct,
        "usage_avg_units": round(avg(usage), 1) if usage else None,
        "usage_max_units": max(usage) if usage else None,
        "usage_min_units": min(usage) if usage else None,
        "usage_months_count": len(usage),
        "change_vs_last_month_units": None,
        "late_payment_surcharge_pkr": late_surcharge,
        "arrears_is_credit": (arrears is not None and arrears < 0),
        "total_charges": tc,
        "total_taxes": tt,
        "current_bill": cb,
        "units_consumed": uc,
        "arrears": arrears,
        "payable_within_due_date": pwdd,
        "payable_after_due_date": padd,
    }

    # Month-over-month change
    if len(usage) >= 2:
        metrics["change_vs_last_month_units"] = round(usage[-1] - usage[-2], 1)

    return metrics


# ── dynamic schema for write output ──────────────────────────────────────────

from pydantic import BaseModel, create_model
from typing import Dict


def _make_write_schema(question_ids: list[str]):
    """Create a pydantic model with one str field per question_id."""
    fields = {qid: (Optional[str], None) for qid in question_ids}
    return create_model("L2WriteOutput", **fields)


# ── main Level 2 function ─────────────────────────────────────────────────────

def answer_questions(
    bill_id: str,
    questions: list[dict],   # [{question_id, question}, ...]
    l1: dict,
    facts: dict,
    bill_images: list[bytes],
    use_cache: bool = True,
) -> dict[str, str]:
    """
    Returns {question_id: answer_string} for all questions.
    Never raises – falls back to error string per question.
    """
    if not questions:
        return {}

    question_ids = [q["question_id"] for q in questions]
    metrics = _compute_metrics(l1, facts)

    if USE_PLAN_FLOW:
        return _plan_compute_write(
            bill_id, questions, l1, facts, metrics, bill_images, use_cache
        )
    else:
        return _mvp_write(bill_id, questions, l1, facts, metrics, bill_images, use_cache)


def _plan_compute_write(
    bill_id: str,
    questions: list[dict],
    l1: dict,
    facts: dict,
    metrics: dict,
    bill_images: list[bytes],
    use_cache: bool,
) -> dict[str, str]:
    """Full plan → compute → write flow."""
    from pydantic import BaseModel, Field
    from typing import List as PList

    class CalcItem(BaseModel):
        name: str
        expression: str

    class PlanItem(BaseModel):
        question_id: str
        interpretation: Optional[str] = None
        answerable_from_bill: bool = True
        calculations: PList[CalcItem] = Field(default_factory=list)
        missing_info: Optional[str] = None

    class PlanOutput(BaseModel):
        items: PList[PlanItem] = Field(default_factory=list)

    # Build plan prompt
    plan_sys = _plan_prompt()
    plan_input = json.dumps({
        "questions": questions,
        "level1": l1,
        "facts": facts,
        "pre_computed_metrics": metrics,
    }, ensure_ascii=False, default=str)

    plan_prompt = plan_sys + "\n\n---\n\n" + plan_input
    question_ids = [q["question_id"] for q in questions]

    computed_per_q: dict[str, dict] = {}
    plan_items: list = []

    try:
        raw_plan = call_gemini(
            prompt=plan_prompt,
            images=bill_images,
            schema_class=PlanOutput,
            tag=f"{bill_id}/L2-plan",
            use_cache=use_cache,
        )
        plan_items = raw_plan.get("items") or []

        # Compute expressions
        for item in plan_items:
            qid = item.get("question_id", "")
            computed = {}
            # Always include pre-computed metrics
            computed.update(metrics)
            for calc in item.get("calculations") or []:
                name = calc.get("name", "")
                expr = calc.get("expression", "")
                if name and expr:
                    computed[name] = safe_eval(expr, l1, facts)
            computed_per_q[qid] = computed

    except Exception as exc:
        logger.warning("[%s] plan call failed (%s), falling back to MVP", bill_id, exc)
        for qid in question_ids:
            computed_per_q[qid] = metrics

    # Write answers
    return _write_answers(
        bill_id, questions, l1, facts, computed_per_q, plan_items, bill_images, use_cache
    )


def _write_answers(
    bill_id: str,
    questions: list[dict],
    l1: dict,
    facts: dict,
    computed_per_q: dict,
    plan_items: list,
    bill_images: list[bytes],
    use_cache: bool,
) -> dict[str, str]:
    write_sys = _write_prompt()
    question_ids = [q["question_id"] for q in questions]
    WriteSchema = _make_write_schema(question_ids)

    # Build plan lookup
    plan_lookup = {item.get("question_id"): item for item in plan_items}

    write_input = json.dumps({
        "questions": questions,
        "plans": plan_items,
        "computed_per_question": computed_per_q,
        "level1": l1,
        "facts": facts,
    }, ensure_ascii=False, default=str)

    write_prompt = write_sys + "\n\n---\n\n" + write_input

    try:
        raw_answers = call_gemini(
            prompt=write_prompt,
            images=bill_images,
            schema_class=WriteSchema,
            tag=f"{bill_id}/L2-write",
            use_cache=use_cache,
        )
        answers = {}
        for q in questions:
            qid = q["question_id"]
            ans = raw_answers.get(qid) or ""
            ans = str(ans).strip()
            if not ans:
                ans = _fallback_answer(qid, q["question"], l1, facts, computed_per_q.get(qid, {}))
            answers[qid] = scrub(ans)
        return answers

    except Exception as exc:
        logger.error("[%s] write call failed: %s", bill_id, exc)
        # Single-question fallbacks
        answers = {}
        for q in questions:
            qid = q["question_id"]
            answers[qid] = _single_question_fallback(
                bill_id, q, l1, facts, computed_per_q.get(qid, {}), bill_images, use_cache
            )
        return answers


def _mvp_write(
    bill_id: str,
    questions: list[dict],
    l1: dict,
    facts: dict,
    metrics: dict,
    bill_images: list[bytes],
    use_cache: bool,
) -> dict[str, str]:
    """MVP: skip plan, pass pre-computed metrics directly to write."""
    computed_per_q = {q["question_id"]: metrics for q in questions}
    return _write_answers(bill_id, questions, l1, facts, computed_per_q, [], bill_images, use_cache)


def _fallback_answer(qid: str, question: str, l1: dict, facts: dict, computed: dict) -> str:
    """Generate a simple fallback answer from computed metrics."""
    cb = l1.get("current_bill")
    uc = l1.get("units_consumed")
    if cb is not None:
        return (
            f"Based on the bill data: current bill is PKR {cb:,.2f}, "
            f"units consumed {uc}. Full details could not be computed for this question."
        )
    return "This information is not shown on this bill."


def _single_question_fallback(
    bill_id: str,
    question: dict,
    l1: dict,
    facts: dict,
    computed: dict,
    bill_images: list[bytes],
    use_cache: bool,
) -> str:
    """One more LLM call for a single question as last resort."""
    from pydantic import BaseModel

    class SingleAnswer(BaseModel):
        answer: str

    qid = question["question_id"]
    write_sys = _write_prompt()
    mini_prompt = (
        write_sys + "\n\nAnswer ONLY this question:\n"
        + json.dumps(question, ensure_ascii=False)
        + "\n\nComputed values:\n"
        + json.dumps(computed, ensure_ascii=False, default=str)
        + "\n\nLevel 1:\n"
        + json.dumps(l1, ensure_ascii=False, default=str)
        + '\n\nReturn JSON: {"answer": "..."}'
    )
    try:
        raw = call_gemini(
            prompt=mini_prompt,
            images=bill_images,
            schema_class=SingleAnswer,
            tag=f"{bill_id}/L2-single-{qid}",
            use_cache=use_cache,
        )
        ans = str(raw.get("answer") or "").strip()
        return scrub(ans) if ans else "The answer could not be determined from this bill image."
    except Exception:
        return "The answer could not be determined from this bill image."
