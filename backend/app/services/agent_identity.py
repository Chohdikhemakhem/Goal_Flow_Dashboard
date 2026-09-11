import re

from sqlalchemy import func


_AGENT_NAME_SEPARATOR_RE = re.compile(r"[,\.\s]+")


def normalize_agent_name(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    tokens = [token for token in _AGENT_NAME_SEPARATOR_RE.split(text) if token]
    return ".".join(tokens)


def normalized_agent_name_key(value: str | None) -> str:
    return normalize_agent_name(value).upper()


def normalized_agent_name_expression(column):
    expr = func.upper(func.coalesce(column, ""))
    expr = func.replace(expr, ",", ".")
    expr = func.replace(expr, " ", ".")
    for _ in range(4):
        expr = func.replace(expr, "..", ".")
    return expr
