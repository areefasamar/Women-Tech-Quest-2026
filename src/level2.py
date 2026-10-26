"""
level2.py – Plan → compute → write pipeline for Level 2 answers.

Uses the MVP shortcut (pre-computed generic metrics + one write call)
which is fast and reliable. Upgrade path: plan → compute → write is
also implemented and can be enabled by setting USE_PLAN_FLOW=True.
"""
from __future__ import annotations
import ast
import json
import logging
from pathlib import Path
from typing import Any, Optional

from src.llm_client import call_gemini
from src.safe_calc import safe_eval, avg, pct, pluck, _SAFE_BUILTINS
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


# ── calc_text helper functions ────────────────────────────────────────────────

_OP_SYMBOLS = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.FloorDiv: "//",
    ast.Mod: "%",
    ast.Pow: "**",
}

_CMP_SYMBOLS = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
}


def _format_operand(val: Any, is_result: bool = False) -> str:
    if val is None or val == "error":
        return ""
    if isinstance(val, bool):
        return str(val)
    if isinstance(val, (int, float)):
        if isinstance(val, float):
            if is_result:
                val = round(val, 2)
            if val.is_integer():
                return f"{int(val):,}"
            return f"{val:,.2f}"
        if isinstance(val, int):
            return f"{val:,}"
    return str(val)


def _build_calc_text(expr: str, l1: dict, facts: dict, result: Any) -> Optional[str]:
    """
    Build a calc_text string from the real operands and result,
    e.g. '3,430.24 / 151 = 22.72'.
    """
    if result == "error" or result is None:
        return None
    try:
        tree = ast.parse(expr, mode="eval")
        body = tree.body
        if isinstance(body, ast.Call) and getattr(body.func, "id", None) == "round" and len(body.args) >= 1:
            body = body.args[0]

        ns = dict(_SAFE_BUILTINS)
        ns["l1"] = l1
        ns["facts"] = facts

        if isinstance(body, ast.BinOp):
            op_sym = _OP_SYMBOLS.get(type(body.op), "?")
            left_val = eval(compile(ast.Expression(body.left), "<left>", "eval"), {"__builtins__": {}}, ns)
            right_val = eval(compile(ast.Expression(body.right), "<right>", "eval"), {"__builtins__": {}}, ns)
            return f"{_format_operand(left_val)} {op_sym} {_format_operand(right_val)} = {_format_operand(result, is_result=True)}"

        elif isinstance(body, ast.Call):
            func_name = getattr(body.func, "id", "")
            if func_name == "pct" and len(body.args) == 2:
                p_val = eval(compile(ast.Expression(body.args[0]), "<arg0>", "eval"), {"__builtins__": {}}, ns)
                w_val = eval(compile(ast.Expression(body.args[1]), "<arg1>", "eval"), {"__builtins__": {}}, ns)
                return f"({_format_operand(p_val)} / {_format_operand(w_val)}) * 100 = {_format_operand(result, is_result=True)}%"
            elif func_name in ("avg", "sum", "min", "max") and len(body.args) >= 1:
                arg_val = eval(compile(ast.Expression(body.args[0]), "<arg0>", "eval"), {"__builtins__": {}}, ns)
                return f"{func_name}({_format_operand(arg_val)}) = {_format_operand(result, is_result=True)}"

        elif isinstance(body, ast.Compare) and len(body.ops) == 1 and len(body.comparators) == 1:
            op_sym = _CMP_SYMBOLS.get(type(body.ops[0]), "?")
            left_val = eval(compile(ast.Expression(body.left), "<left>", "eval"), {"__builtins__": {}}, ns)
            right_val = eval(compile(ast.Expression(body.comparators[0]), "<right>", "eval"), {"__builtins__": {}}, ns)
            return f"{_format_operand(left_val)} {op_sym} {_format_operand(right_val)} = {_format_operand(result, is_result=True)}"

    except Exception as exc:
        logger.debug("Could not build calc_text for %r: %s", expr, exc)
    return None


def _entry(val: Any, calc_text: Optional[str] = None) -> dict:
    return {"value": val, "calc_text": calc_text}


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

    cost_per_unit = None
    cpu_calc = None
    cost_per_unit_charges = None
    cpuc_calc = None
    if uc and uc > 0:
        cost_per_unit = safe_eval("l1['current_bill'] / l1['units_consumed']", l1, facts)
        cpu_calc = _build_calc_text("l1['current_bill'] / l1['units_consumed']", l1, facts, cost_per_unit)
        cost_per_unit_charges = safe_eval("l1['total_charges'] / l1['units_consumed']", l1, facts)
        cpuc_calc = _build_calc_text("l1['total_charges'] / l1['units_consumed']", l1, facts, cost_per_unit_charges)

    tax_share_pct = safe_eval("pct(l1['total_taxes'], l1['current_bill'])", l1, facts) if cb else None
    tax_calc = _build_calc_text("pct(l1['total_taxes'], l1['current_bill'])", l1, facts, tax_share_pct) if cb else None

    energy_share_pct = safe_eval("pct(l1['total_charges'], l1['current_bill'])", l1, facts) if cb else None
    energy_calc = _build_calc_text("pct(l1['total_charges'], l1['current_bill'])", l1, facts, energy_share_pct) if cb else None

    late_surcharge = None
    late_calc = None
    if pwdd is not None and padd is not None:
        late_surcharge = safe_eval("l1['payable_after_due_date'] - l1['payable_within_due_date']", l1, facts)
        late_calc = _build_calc_text("l1['payable_after_due_date'] - l1['payable_within_due_date']", l1, facts, late_surcharge)

    mom_change = None
    mom_calc = None
    if len(usage) >= 2:
        mom_change = round(usage[-1] - usage[-2], 1)
        mom_calc = f"{_format_operand(usage[-1])} - {_format_operand(usage[-2])} = {_format_operand(mom_change, is_result=True)}"

    metrics = {
        "cost_per_unit_pkr": _entry(cost_per_unit, cpu_calc),
        "cost_per_unit_whole_bill_pkr": _entry(cost_per_unit, cpu_calc),
        "cost_per_unit_charges_only_pkr": _entry(cost_per_unit_charges, cpuc_calc),
        "tax_share_pct": _entry(tax_share_pct, tax_calc),
        "energy_share_pct": _entry(energy_share_pct, energy_calc),
        "usage_avg_units": _entry(round(avg(usage), 1) if usage else None),
        "usage_max_units": _entry(max(usage) if usage else None),
        "usage_min_units": _entry(min(usage) if usage else None),
        "usage_months_count": _entry(len(usage)),
        "change_vs_last_month_units": _entry(mom_change, mom_calc),
        "late_payment_surcharge_pkr": _entry(late_surcharge, late_calc),
        "arrears_is_credit": _entry(arrears is not None and arrears < 0),
        "total_charges": _entry(tc),
        "total_taxes": _entry(tt),
        "current_bill": _entry(cb),
        "units_consumed": _entry(uc),
        "arrears": _entry(arrears),
        "payable_within_due_date": _entry(pwdd),
        "payable_after_due_date": _entry(padd),
    }

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
                    val = safe_eval(expr, l1, facts)
                    calc_text = _build_calc_text(expr, l1, facts, val)
                    computed[name] = _entry(val, calc_text)
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
