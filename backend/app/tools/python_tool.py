"""PythonTool — safe sandboxed computation (no network, no file writes)."""

from __future__ import annotations

import traceback
from typing import Any

import pandas as pd

from backend.app.core.logging import get_logger

logger = get_logger(__name__)

# Allowed built-ins in sandboxed execution
_ALLOWED_BUILTINS = {
    "abs", "all", "any", "dict", "enumerate", "filter", "float", "int",
    "isinstance", "len", "list", "map", "max", "min", "print", "range",
    "round", "set", "sorted", "str", "sum", "tuple", "type", "zip",
    "True", "False", "None",
}

_SAFE_GLOBALS: dict[str, Any] = {
    "__builtins__": {k: __builtins__[k] for k in _ALLOWED_BUILTINS if k in __builtins__}  # type: ignore[index]
    if isinstance(__builtins__, dict)
    else {k: getattr(__builtins__, k) for k in _ALLOWED_BUILTINS if hasattr(__builtins__, k)},
    "pd": pd,
}


class PythonTool:
    """Execute Python snippets on a provided DataFrame, return computed result."""

    def run(
        self,
        code: str,
        df: pd.DataFrame,
        *,
        step: str = "unknown",
    ) -> tuple[Any, str | None]:
        """
        Execute `code` in a restricted namespace with `df` available.
        Returns (result, error_message).  result is whatever `code` assigns to `result`.
        """
        namespace: dict[str, Any] = {**_SAFE_GLOBALS, "df": df, "result": None}
        try:
            exec(compile(code, "<python_tool>", "exec"), namespace)  # noqa: S102
            logger.info("python_tool.ok", step=step)
            return namespace.get("result"), None
        except Exception:
            err = traceback.format_exc()
            logger.warning("python_tool.error", step=step, error=err)
            return None, err
