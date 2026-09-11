from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, pagination, require_roles
from app.db.session import get_db
from app.models.entities import Agency, Agent, ParReductionTarget, User
from app.models.enums import UserRole
from app.schemas.common import Message, Page
from app.schemas.domain import (
    ParReductionAgencySummaryRead,
    ParReductionTargetCreate,
    ParReductionTargetRead,
)
from app.services.par_reduction import _latest_snapshot_before_month_start, _volume_query

router = APIRouter(
    prefix="/par-reduction-targets",
    tags=["par-reduction-targets"],
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.ADMIN]))],
)


def _validate_agent(db: Session, payload: ParReductionTargetCreate) -> Agent:
    agent = db.get(Agent, payload.agent_id)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "agent_agency_mismatch", "message": "Le Portfolio Manager n'appartient pas a l'agence selectionnee."},
        )
    if agent.agency_id != payload.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "agent_agency_mismatch", "message": "Le Portfolio Manager n'appartient pas a l'agence selectionnee."},
        )
    return agent


def _duplicate_filter(payload: ParReductionTargetCreate):
    return and_(
        ParReductionTarget.agency_id == payload.agency_id,
        ParReductionTarget.agent_id == payload.agent_id,
        ParReductionTarget.month == payload.month,
        ParReductionTarget.year == payload.year,
    )


def _validate_target_levels(db: Session, payload: ParReductionTargetCreate) -> None:
    initial_batch = _latest_snapshot_before_month_start(db, month=payload.month, year=payload.year)
    if initial_batch is None:
        return
    initial = _volume_query(db, initial_batch.id, payload.agency_id, payload.agent_id)
    values = {
        "target_par30": (initial["par30"], payload.target_par30),
        "target_cohort_1_15": (initial["cohort_1_15"], payload.target_cohort_1_15),
        "target_cohort_16_30": (initial["cohort_16_30"], payload.target_cohort_16_30),
    }
    invalid = [name for name, (initial_value, target_value) in values.items() if target_value > initial_value]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "par_reduction_target_above_initial",
                "message": "L'objectif a atteindre doit etre inferieur ou egal au PAR initial.",
                "fields": invalid,
                "initial_snapshot_id": initial_batch.id,
            },
        )


@router.get("", response_model=Page[ParReductionTargetRead])
def list_par_reduction_targets(
    agency_id: int | None = None,
    agent_id: int | None = None,
    month: int | None = None,
    year: int | None = None,
    page: tuple[int, int] = Depends(pagination),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    limit, offset = page
    filters = []
    if agency_id is not None:
        filters.append(ParReductionTarget.agency_id == agency_id)
    if agent_id is not None:
        filters.append(ParReductionTarget.agent_id == agent_id)
    if month is not None:
        filters.append(ParReductionTarget.month == month)
    if year is not None:
        filters.append(ParReductionTarget.year == year)

    query = select(ParReductionTarget).options(
        joinedload(ParReductionTarget.agency), joinedload(ParReductionTarget.agent)
    )
    count_query = select(func.count(ParReductionTarget.id))
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)
    items = db.scalars(
        query.order_by(ParReductionTarget.year.desc(), ParReductionTarget.month.desc(), ParReductionTarget.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return Page(items=items, total=db.scalar(count_query) or 0, limit=limit, offset=offset)


@router.post("", response_model=ParReductionTargetRead)
def create_par_reduction_target(
    payload: ParReductionTargetCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if db.scalar(select(ParReductionTarget).where(_duplicate_filter(payload))):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "par_reduction_target_duplicate", "message": "Un objectif de baisse existe deja pour ce portefeuille et cette periode."},
        )
    agent = _validate_agent(db, payload)
    _validate_target_levels(db, payload)
    target = ParReductionTarget(
        **payload.model_dump(exclude={"agency_id"}),
        agency_id=agent.agency_id,
    )
    db.add(target)
    db.commit()
    db.refresh(target)
    return db.scalar(
        select(ParReductionTarget)
        .options(joinedload(ParReductionTarget.agency), joinedload(ParReductionTarget.agent))
        .where(ParReductionTarget.id == target.id)
    )


@router.get("/agency-summary", response_model=list[ParReductionAgencySummaryRead])
def list_par_reduction_agency_summary(
    month: int,
    year: int,
    agency_id: int | None = None,
    agent_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agency_query = (
        select(Agency.id, Agency.name, func.count(Agent.id))
        .outerjoin(Agent, Agent.agency_id == Agency.id)
        .group_by(Agency.id, Agency.name)
        .order_by(Agency.name.asc())
    )
    if agency_id is not None:
        agency_query = agency_query.where(Agency.id == agency_id)
    agency_rows = db.execute(agency_query).all()

    target_query = (
        select(ParReductionTarget)
        .options(joinedload(ParReductionTarget.agency), joinedload(ParReductionTarget.agent))
        .where(ParReductionTarget.month == month, ParReductionTarget.year == year)
        .order_by(ParReductionTarget.agency_id.asc(), ParReductionTarget.agent_id.asc())
    )
    if agency_id is not None:
        target_query = target_query.where(ParReductionTarget.agency_id == agency_id)
    if agent_id is not None:
        target_query = target_query.where(ParReductionTarget.agent_id == agent_id)
    targets = db.scalars(target_query).all()
    by_agency: dict[int, list[ParReductionTarget]] = {}
    for target in targets:
        by_agency.setdefault(target.agency_id, []).append(target)

    initial_batch = _latest_snapshot_before_month_start(db, month=month, year=year)
    result = []
    for agency_id_value, agency_name, agent_count in agency_rows:
        agency_targets = by_agency.get(agency_id_value, [])
        target_values = {
            "par30": sum((target.target_par30 or 0 for target in agency_targets), 0),
            "cohort_1_15": sum((target.target_cohort_1_15 or 0 for target in agency_targets), 0),
            "cohort_16_30": sum((target.target_cohort_16_30 or 0 for target in agency_targets), 0),
        }
        initial_values = _volume_query(db, initial_batch.id, agency_id_value, None) if initial_batch else {key: 0 for key in ("par30", "cohort_1_15", "cohort_16_30")}
        result.append(
            ParReductionAgencySummaryRead(
                agency_id=agency_id_value,
                agency_name=agency_name,
                agent_count=agent_count,
                target_par30=target_values["par30"],
                target_cohort_1_15=target_values["cohort_1_15"],
                target_cohort_16_30=target_values["cohort_16_30"],
                initial_par30=initial_values["par30"],
                initial_cohort_1_15=initial_values["cohort_1_15"],
                initial_cohort_16_30=initial_values["cohort_16_30"],
                reduction_required_par30=initial_values["par30"] - target_values["par30"],
                reduction_required_cohort_1_15=initial_values["cohort_1_15"] - target_values["cohort_1_15"],
                reduction_required_cohort_16_30=initial_values["cohort_16_30"] - target_values["cohort_16_30"],
                agents=agency_targets,
            )
        )
    return result


@router.put("/{target_id}", response_model=ParReductionTargetRead)
def update_par_reduction_target(
    target_id: int,
    payload: ParReductionTargetCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    target = db.get(ParReductionTarget, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Objectif de baisse introuvable."})
    agent = _validate_agent(db, payload)
    duplicate = db.scalar(
        select(ParReductionTarget).where(_duplicate_filter(payload), ParReductionTarget.id != target_id)
    )
    if duplicate:
        raise HTTPException(status_code=409, detail={"code": "par_reduction_target_duplicate", "message": "Un objectif de baisse existe deja pour ce portefeuille et cette periode."})
    _validate_target_levels(db, payload)
    update_values = payload.model_dump(exclude={"agency_id"})
    update_values["agency_id"] = agent.agency_id
    for key, value in update_values.items():
        setattr(target, key, value)
    db.commit()
    return db.scalar(
        select(ParReductionTarget)
        .options(joinedload(ParReductionTarget.agency), joinedload(ParReductionTarget.agent))
        .where(ParReductionTarget.id == target.id)
    )


@router.delete("/{target_id}", response_model=Message)
def delete_par_reduction_target(
    target_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    target = db.get(ParReductionTarget, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Objectif de baisse introuvable."})
    db.delete(target)
    db.commit()
    return Message(message="Objectif de baisse supprime.")
