from __future__ import annotations

from decimal import Decimal
from typing import Literal

AchievementDirection = Literal["HIGHER_IS_BETTER", "LOWER_IS_BETTER"]


LOWER_IS_BETTER_KEYS = {
    "par_30_rate",
    "par_0",
    "par_1_30",
    "par_31_60",
    "par_30",
}


def _to_decimal(value: Decimal | int | float | str | None) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def achievement_direction(metric_key: str) -> AchievementDirection:
    if metric_key in LOWER_IS_BETTER_KEYS:
        return "LOWER_IS_BETTER"
    return "HIGHER_IS_BETTER"


def compute_achievement_ratio(
    *,
    metric_key: str,
    actual_value: Decimal | int | float | str | None,
    target_value: Decimal | int | float | str | None,
) -> Decimal:
    actual = _to_decimal(actual_value)
    target = _to_decimal(target_value)
    direction = achievement_direction(metric_key)

    if target <= 0:
        return Decimal("0")

    if direction == "LOWER_IS_BETTER":
        # Risk objectives: lower realized value is better.
        # When actual reaches 0, consider objective fully achieved (100%) without overflow.
        if actual <= 0:
            return Decimal("1")
        return target / actual

    # Growth objectives: higher realized value is better.
    if actual <= 0:
        return Decimal("0")
    return actual / target

