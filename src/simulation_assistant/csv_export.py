"""Literal spreadsheet text for sweep comparison and ranking exports."""
from typing import Any


def safe_csv_cell(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
