"""
safe_calc.py – restricted expression evaluator for Level 2 plan computations.

Only arithmetic, comparisons, indexing, and whitelisted helpers allowed.
No imports, no attribute access, no arbitrary function calls.
"""
from __future__ import annotations
import ast
import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_EXPR_LEN = 400


# ── helper functions available in expressions ─────────────────────────────────

def avg(lst: list) -> float:
    """Average of a list, ignoring None values."""
    vals = [x for x in lst if x is not None]
    return sum(vals) / len(vals) if vals else 0.0


def pct(part: Any, whole: Any) -> float:
    """100 * part / whole. Returns 0 if whole is 0 or None."""
    try:
        p = float(part or 0)
        w = float(whole or 0)
        return round(100.0 * p / w, 4) if w else 0.0
    except (TypeError, ZeroDivisionError):
        return 0.0


def count_where(lst: list, key: str, op: str, value: Any) -> int:
    """Count items in lst where item[key] <op> value."""
    ops = {
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        "<":  lambda a, b: a < b,
        ">":  lambda a, b: a > b,
        "<=": lambda a, b: a <= b,
        ">=": lambda a, b: a >= b,
    }
    fn = ops.get(op, lambda a, b: False)
    return sum(1 for item in lst if isinstance(item, dict) and fn(item.get(key), value))


def pluck(lst: list, key: str) -> list:
    """Extract field 'key' from each dict in lst, skip None values."""
    return [item[key] for item in lst if isinstance(item, dict) and item.get(key) is not None]


_SAFE_BUILTINS = {
    "sum": sum,
    "len": len,
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "avg": avg,
    "pct": pct,
    "count_where": count_where,
    "pluck": pluck,
    "True": True,
    "False": False,
    "None": None,
}


# ── AST visitor to block unsafe nodes ────────────────────────────────────────

_ALLOWED_EXPR_NODES = {
    ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare,
    ast.Call, ast.IfExp, ast.Constant, ast.Name, ast.Attribute,
    ast.Subscript, ast.Index, ast.Slice, ast.List, ast.Tuple,
    ast.Load, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
    ast.Mod, ast.Pow, ast.USub, ast.UAdd, ast.Not,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.And, ast.Or,
}


def _check_ast(node: ast.AST) -> None:
    if type(node) not in _ALLOWED_EXPR_NODES:
        raise ValueError(f"Unsafe node: {type(node).__name__}")
    for child in ast.iter_child_nodes(node):
        _check_ast(child)


def safe_eval(expr: str, l1: dict, facts: dict) -> Any:
    """
    Evaluate expr in a restricted namespace.
    Returns "error" string on any failure.
    """
    if not isinstance(expr, str) or not expr.strip():
        return "error"
    if len(expr) > MAX_EXPR_LEN:
        logger.warning("safe_eval: expression too long (%d chars)", len(expr))
        return "error"
    try:
        tree = ast.parse(expr, mode="eval")
        _check_ast(tree)
        namespace = dict(_SAFE_BUILTINS)
        namespace["l1"] = l1
        namespace["facts"] = facts
        result = eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, namespace)
        return result
    except Exception as exc:
        logger.warning("safe_eval error for %r: %s", expr, exc)
        return "error"
