from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from typing import Callable, Mapping


FORMULA_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_FORMULAS = 50
MAX_EXPRESSION_LENGTH = 500
MAX_AST_NODES = 128

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: lambda left, right: left + right,
    ast.Sub: lambda left, right: left - right,
    ast.Mult: lambda left, right: left * right,
    ast.Div: lambda left, right: left / right,
    ast.Mod: lambda left, right: left % right,
    ast.Pow: lambda left, right: left**right,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: lambda value: value,
    ast.USub: lambda value: -value,
}
_FUNCTIONS: dict[str, Callable[..., float]] = {
    "abs": abs,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
}
_CONSTANTS = {"pi": math.pi, "e": math.e}


@dataclass(frozen=True)
class FormulaEvaluation:
    values: dict[str, float]
    errors: dict[str, str]


def validate_output_formulas(formulas: Mapping[str, str] | None) -> dict[str, str]:
    """Validate and normalize user-defined numeric output formulas."""
    if formulas is None:
        return {}
    if not isinstance(formulas, Mapping):
        raise ValueError("Output formulas must be a name-to-expression object")
    if len(formulas) > MAX_FORMULAS:
        raise ValueError(f"At most {MAX_FORMULAS} output formulas are allowed")

    normalized: dict[str, str] = {}
    for raw_name, raw_expression in formulas.items():
        if not isinstance(raw_name, str) or not FORMULA_NAME.fullmatch(raw_name):
            raise ValueError(
                "Formula names must start with a letter or underscore and contain "
                "only letters, digits, and underscores"
            )
        if not isinstance(raw_expression, str) or not raw_expression.strip():
            raise ValueError(f"Formula '{raw_name}' must have a non-empty expression")
        expression = raw_expression.strip()
        if len(expression) > MAX_EXPRESSION_LENGTH:
            raise ValueError(
                f"Formula '{raw_name}' exceeds {MAX_EXPRESSION_LENGTH} characters"
            )
        _parse_expression(expression, raw_name)
        normalized[raw_name] = expression
    return normalized


def evaluate_output_formulas(
    formulas: Mapping[str, str] | None,
    metrics: Mapping[str, float],
) -> FormulaEvaluation:
    """Evaluate formulas sequentially against normalized numeric metrics."""
    normalized = validate_output_formulas(formulas)
    available = {name: float(value) for name, value in metrics.items()}
    values: dict[str, float] = {}
    errors: dict[str, str] = {}

    for name, expression in normalized.items():
        if name in available:
            errors[name] = f"A metric named '{name}' already exists"
            continue
        try:
            tree = _parse_expression(expression, name)
            value = float(_evaluate_node(tree.body, available))
            if not math.isfinite(value):
                raise ValueError("result is not finite")
        except (ArithmeticError, KeyError, OverflowError, TypeError, ValueError) as exc:
            errors[name] = str(exc)
            continue
        values[name] = value
        available[name] = value
    return FormulaEvaluation(values=values, errors=errors)


def supported_formula_symbols() -> dict[str, list[str]]:
    return {
        "functions": sorted(_FUNCTIONS),
        "constants": sorted(_CONSTANTS),
    }


def _parse_expression(expression: str, formula_name: str) -> ast.Expression:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Formula '{formula_name}' has invalid syntax") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        raise ValueError(f"Formula '{formula_name}' is too complex")
    for node in nodes:
        if isinstance(
            node,
            (
                ast.Expression,
                ast.Constant,
                ast.Name,
                ast.Load,
                ast.BinOp,
                ast.UnaryOp,
                ast.Call,
                *tuple(_BINARY_OPERATORS),
                *tuple(_UNARY_OPERATORS),
            ),
        ):
            continue
        raise ValueError(
            f"Formula '{formula_name}' contains unsupported syntax: "
            f"{type(node).__name__}"
        )
    return tree


def _evaluate_node(node: ast.AST, values: Mapping[str, float]) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("Only numeric constants are allowed")
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id in values:
            return float(values[node.id])
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise KeyError(f"Metric '{node.id}' is not available")
    if isinstance(node, ast.BinOp):
        operator = _BINARY_OPERATORS.get(type(node.op))
        if operator is None:
            raise ValueError("Unsupported binary operator")
        return operator(
            _evaluate_node(node.left, values),
            _evaluate_node(node.right, values),
        )
    if isinstance(node, ast.UnaryOp):
        operator = _UNARY_OPERATORS.get(type(node.op))
        if operator is None:
            raise ValueError("Unsupported unary operator")
        return operator(_evaluate_node(node.operand, values))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise ValueError("Only supported numeric functions can be called")
        if node.keywords:
            raise ValueError("Formula functions do not accept named arguments")
        arguments = [_evaluate_node(argument, values) for argument in node.args]
        if not arguments:
            raise ValueError(f"Function '{node.func.id}' needs an argument")
        return float(_FUNCTIONS[node.func.id](*arguments))
    raise ValueError(f"Unsupported expression node: {type(node).__name__}")
