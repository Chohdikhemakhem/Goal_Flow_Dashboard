from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, pagination, require_roles
from app.core.config import get_settings
from app.db.session import get_db
from app.models.entities import BonusResult, BonusRule
from app.models.enums import UserRole
from app.schemas.common import Page
from app.schemas.domain import (
    BonusCalculationRequest,
    BonusResultRead,
    BonusRuleCreate,
    BonusRuleRead,
)
from app.services.bonus import calculate_bonuses


def require_bonus_module_active():
    settings = get_settings()
    if not settings.bonus_module_active:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "bonus_module_inactive",
                "message": "Module en developpement",
            },
        )


router = APIRouter(
    prefix="/bonus",
    tags=["bonus"],
    dependencies=[Depends(get_current_user), Depends(require_bonus_module_active)],
)


@router.get("/formula-help", dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN]))])
def formula_help():
    return {
        "metrics": [
            "disbursement_count",
            "disbursement_volume",
            "nb_clients",
            "outstanding",
            "healthy_outstanding",
            "healthy_rate",
            "par_0",
            "par_0_rate",
            "par_1_30",
            "par_1_30_rate",
            "par_31_60",
            "par_31_60_rate",
            "par_30",
            "par_30_rate",
            "target_disbursement_count",
            "target_nb_clients",
            "target_disbursement",
            "target_outstanding",
            "target_par",
            "target_healthy_outstanding",
            "target_par_0",
            "target_par_1_30",
            "target_par_31_60",
            "target_par_30",
        ],
        "operators": ["+", "-", "*", "/", "**", "(", ")"],
        "functions": ["min(a, b)", "max(a, b)", "abs(a)", "round(a, n)"],
        "example": "250000 * (0.4 * min(disbursement_volume / target_disbursement, 1) + 0.4 * min(healthy_outstanding / target_healthy_outstanding, 1) + 0.2 * max(1 - par_30_rate / target_par, 0))",
    }


@router.get(
    "/rules",
    response_model=Page[BonusRuleRead],
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN]))],
)
def list_rules(page: tuple[int, int] = Depends(pagination), db: Session = Depends(get_db)):
    limit, offset = page
    return Page(
        items=db.scalars(select(BonusRule).limit(limit).offset(offset)).all(),
        total=db.scalar(select(func.count(BonusRule.id))) or 0,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/rules",
    response_model=BonusRuleRead,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN]))],
)
def create_rule(payload: BonusRuleCreate, db: Session = Depends(get_db)):
    rule = BonusRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.post(
    "/calculate",
    response_model=list[BonusResultRead],
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN]))],
)
def calculate(payload: BonusCalculationRequest, db: Session = Depends(get_db)):
    rule = db.get(BonusRule, payload.bonus_rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Bonus rule not found"})
    return calculate_bonuses(db, payload.month, payload.year, rule)


@router.get(
    "/results",
    response_model=Page[BonusResultRead],
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN]))],
)
def list_results(
    month: int | None = None,
    year: int | None = None,
    page: tuple[int, int] = Depends(pagination),
    db: Session = Depends(get_db),
):
    limit, offset = page
    query = select(BonusResult)
    count_query = select(func.count(BonusResult.id))
    filters = []
    if month:
        filters.append(BonusResult.month == month)
    if year:
        filters.append(BonusResult.year == year)
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)
    return Page(
        items=db.scalars(query.limit(limit).offset(offset)).all(),
        total=db.scalar(count_query) or 0,
        limit=limit,
        offset=offset,
    )
