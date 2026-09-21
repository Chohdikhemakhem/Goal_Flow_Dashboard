import ast
import operator
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.entities import BonusResult, BonusRule, Target, User
from app.models.enums import TargetType
from app.services.objective_metrics import compute_objective_period_realizations

ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}
ALLOWED_FUNCTIONS = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
}


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _pct(actual: Decimal, target: Decimal) -> Decimal:
    if not target:
        return Decimal("0")
    return actual / target


def _safe_eval(expression: str, variables: dict[str, Decimal]) -> Decimal:
    tree = ast.parse(expression, mode="eval")

    def eval_node(node):
        if isinstance(node, ast.Expression):
            return eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return Decimal(str(node.value))
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError(f"Unknown variable: {node.id}")
            return variables[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_OPERATORS:
            left = eval_node(node.left)
            right = eval_node(node.right)
            if isinstance(node.op, ast.Div) and right == 0:
                return Decimal("0")
            return _to_decimal(ALLOWED_OPERATORS[type(node.op)](left, right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_OPERATORS:
            return _to_decimal(ALLOWED_OPERATORS[type(node.op)](eval_node(node.operand)))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in ALLOWED_FUNCTIONS:
                raise ValueError(f"Unsupported function: {node.func.id}")
            args = [eval_node(arg) for arg in node.args]
            return _to_decimal(ALLOWED_FUNCTIONS[node.func.id](*args))
        raise ValueError("Unsupported formula element")

    return _to_decimal(eval_node(tree))


def evaluate_bonus_expression(expression: str, variables: dict[str, Decimal]) -> Decimal:
    return _safe_eval(expression, variables)


def _monthly_values(db: Session, user: User, month: int, year: int) -> dict[str, Decimal]:
    metrics = compute_objective_period_realizations(
        db=db,
        month=month,
        year=year,
        agency_id=user.agency_id,
        agent_id=user.agent_id,
    )

    target = None
    if user.agent_id:
        target = db.scalar(
            select(Target).where(
                Target.target_type == TargetType.AGENT,
                Target.agency_id == user.agency_id,
                Target.agent_id == user.agent_id,
                Target.month == month,
                Target.year == year,
            )
        )
    elif user.agency_id:
        target = db.scalar(
            select(Target).where(
                Target.target_type == TargetType.AGENCY,
                Target.agency_id == user.agency_id,
                Target.agent_id.is_(None),
                Target.month == month,
                Target.year == year,
            )
        )

    values = {
        "disbursement_count": _to_decimal(metrics["disbursement_count"]),
        "disbursement_volume": _to_decimal(metrics["disbursement_volume"]),
        "nb_clients": _to_decimal(metrics["nb_clients"]),
        "outstanding": _to_decimal(metrics["outstanding"]),
        "healthy_outstanding": _to_decimal(metrics["healthy_outstanding"]),
        "par_0": _to_decimal(metrics["par_0"]),
        "par_1_30": _to_decimal(metrics["par_1_30"]),
        "par_31_60": _to_decimal(metrics["par_31_60"]),
        "par_30": _to_decimal(metrics["par_30"]),
    }
    values["par_30_rate"] = _pct(values["par_30"], values["outstanding"])
    values["healthy_rate"] = _pct(values["healthy_outstanding"], values["outstanding"])
    values["par_0_rate"] = _pct(values["par_0"], values["outstanding"])
    values["par_1_30_rate"] = _pct(values["par_1_30"], values["outstanding"])
    values["par_31_60_rate"] = _pct(values["par_31_60"], values["outstanding"])

    target_values = {
        "target_disbursement_count": 0,
        "target_nb_clients": 0,
        "target_disbursement": 0,
        "target_outstanding": 0,
        "target_par": 0,
        "target_healthy_outstanding": 0,
        "target_par_0": 0,
        "target_par_1_30": 0,
        "target_par_31_60": 0,
        "target_par_30": 0,
    }
    if target:
        for key in target_values:
            target_values[key] = getattr(target, key)
    values.update({key: _to_decimal(value) for key, value in target_values.items()})
    return values


def calculate_bonuses(db: Session, month: int, year: int, rule: BonusRule) -> list[BonusResult]:
    formula: dict[str, Any] = rule.formula or {}
    expression = formula.get("expression")
    if not expression:
        expression = (
            "250000 * ("
            "0.35 * min(disbursement_volume / target_disbursement, 1) + "
            "0.25 * min(outstanding / target_outstanding, 1) + "
            "0.25 * min(healthy_outstanding / target_healthy_outstanding, 1) + "
            "0.15 * max(1 - par_30_rate / target_par, 0)"
            ")"
        )

    db.execute(
        delete(BonusResult).where(
            BonusResult.month == month,
            BonusResult.year == year,
            BonusResult.bonus_rule_id == rule.id,
        )
    )

    users = db.scalars(select(User).where(User.is_active.is_(True))).all()
    results: list[BonusResult] = []
    for user in users:
        values = _monthly_values(db, user, month, year)
        try:
            amount = _safe_eval(expression, values).quantize(Decimal("0.01"))
        except ValueError as exc:
            amount = Decimal("0")
            values["formula_error"] = Decimal("0")
            values["error"] = str(exc)

        result = BonusResult(
            user_id=user.id,
            bonus_rule_id=rule.id,
            month=month,
            year=year,
            amount=max(amount, Decimal("0")),
            breakdown={key: str(value) for key, value in values.items()},
        )
        db.add(result)
        results.append(result)
    db.commit()
    return results
