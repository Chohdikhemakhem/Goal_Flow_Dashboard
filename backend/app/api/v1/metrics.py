from calendar import monthrange
from datetime import date
from decimal import Decimal
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, case, cast, false, func, or_, select, true
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, pagination, require_roles
from app.core.config import get_settings
from app.db.session import get_db
from app.models.entities import Agency, Agent, BonusRule, ImportBatch, LoanRaw, Target, User
from app.models.enums import ImportBatchType, TargetType, UserRole
from app.schemas.common import Page
from app.schemas.domain import (
    ActiveSnapshotRead,
    ClosedMonthOptionRead,
    CurrentCreditRead,
    DailyMetricRead,
    MetricsChartRead,
    MetricsSummary,
    PortfolioCoverageRead,
    PortfolioDashboardRead,
    SnapshotOptionRead,
    ParReductionRead,
)
from app.services.agent_identity import normalized_agent_name_expression
from app.services.bonus import evaluate_bonus_expression
from app.services.data_scope import get_user_data_scope
from app.services.committee_access import (
    closed_month_key,
    is_committee_member,
    list_closed_month_batches,
    normalize_committee_historical_request,
)
from app.services.objective_metrics import compute_objective_period_realizations
from app.services.portfolio_identity import matching_agent_ids_query, user_portfolio_identity_key
from app.services.selection import normalize_agency_ids, normalize_sector_ids, sector_filter_condition
from app.services.par_reduction import (
    compute_par_reduction,
    compute_par_reduction_evolution,
    resolve_reduction_scope,
)

router = APIRouter(
    prefix="/metrics",
    tags=["metrics"],
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.COMMITTEE_MEMBER, UserRole.AGENCY_MANAGER, UserRole.PORTFOLIO_MANAGER]))],
)
logger = logging.getLogger(__name__)

RISK_CATEGORY_KEYS = {
    "cohort_1_30",
    "cohort_1_15",
    "cohort_16_30",
    "cohort_31_60",
    "cohort_61_90",
    "cohort_91_120",
    "par_0",
    "par_30",
    "par_120",
}


def _agent_join_condition():
    return (
        (normalized_agent_name_expression(Agent.name) == normalized_agent_name_expression(LoanRaw.agent_name))
        & (Agent.agency_id == Agency.id)
    )


def _latest_snapshot_date_legacy(db: Session) -> date | None:
    return db.scalar(select(func.max(LoanRaw.snapshot_date)))


def _latest_current_batch(db: Session) -> ImportBatch | None:
    return db.scalar(
        select(ImportBatch)
        .where(ImportBatch.batch_type == ImportBatchType.CURRENT_STATE)
        .order_by(ImportBatch.imported_at.desc(), ImportBatch.id.desc())
        .limit(1)
    )


def _active_snapshot_scope(db: Session) -> tuple[date | None, object | None]:
    current_batch = _latest_current_batch(db)
    if current_batch:
        return current_batch.snapshot_date, LoanRaw.import_batch_id == current_batch.id

    has_batch_metadata = (db.scalar(select(func.count(ImportBatch.id))) or 0) > 0
    if has_batch_metadata:
        return None, None

    snapshot_date = _latest_snapshot_date_legacy(db)
    if snapshot_date is None:
        return None, None
    return snapshot_date, LoanRaw.snapshot_date == snapshot_date


def _parse_risk_categories(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    normalized: list[str] = []
    for token in raw_value.split(","):
        key = token.strip().lower().replace("-", "_")
        if not key:
            continue
        if key not in RISK_CATEGORY_KEYS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "invalid_risk_category",
                    "message": f"Unknown risk category: {token.strip()}",
                },
            )
        if key not in normalized:
            normalized.append(key)
    return normalized


def _risk_category_filter(categories: list[str]):
    conditions = []
    for category in categories:
        if category == "cohort_1_30":
            conditions.append((LoanRaw.days_overdue > 0) & (LoanRaw.days_overdue <= 30))
        elif category == "cohort_1_15":
            conditions.append((LoanRaw.days_overdue > 0) & (LoanRaw.days_overdue <= 15))
        elif category == "cohort_16_30":
            conditions.append((LoanRaw.days_overdue >= 16) & (LoanRaw.days_overdue <= 30))
        elif category == "cohort_31_60":
            conditions.append((LoanRaw.days_overdue > 30) & (LoanRaw.days_overdue <= 60))
        elif category == "cohort_61_90":
            conditions.append((LoanRaw.days_overdue > 60) & (LoanRaw.days_overdue <= 90))
        elif category == "cohort_91_120":
            conditions.append((LoanRaw.days_overdue > 90) & (LoanRaw.days_overdue <= 120))
        elif category == "par_0":
            conditions.append(LoanRaw.days_overdue > 0)
        elif category == "par_30":
            conditions.append(LoanRaw.days_overdue > 30)
        elif category == "par_120":
            conditions.append(LoanRaw.days_overdue > 120)
    return or_(*conditions) if conditions else None


def _period_label_from_dates(date_from: date | None, date_to: date | None) -> str | None:
    _validate_same_month_period(date_from, date_to)
    reference_date = date_from or date_to
    if not reference_date:
        return None
    return f"{reference_date.year:04d}-{reference_date.month:02d}"


def _effective_date_bounds(
    date_from: date | None, date_to: date | None
) -> tuple[date | None, date | None]:
    return date_from, date_to


def _month_batch_not_found(period_label: str) -> HTTPException:
    year, month = _period_year_month(period_label)
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "historical_month_not_found",
            "message": f"Aucune donnee historique MCR disponible pour {month:02d}/{year}.",
        },
    )


def _batch_matches_period(batch: ImportBatch, period_label: str) -> bool:
    if batch.batch_type == ImportBatchType.HISTORICAL_MONTH and batch.period:
        return batch.period == period_label
    if batch.snapshot_date is None:
        return False
    return f"{batch.snapshot_date.year:04d}-{batch.snapshot_date.month:02d}" == period_label


def _try_monthly_mcr_batch(db: Session, period_label: str) -> ImportBatch | None:
    """Tente de trouver l'import MCR mensuel (HISTORICAL_MONTH) pour `period_label`.

    Si aucun HISTORICAL_MONTH n'existe, tente de trouver un snapshot
    (CURRENT_STATE / SNAPSHOT) dont snapshot_date est le dernier jour du mois.

    Retourne None si aucun import n'est trouvé — ne lève pas d'erreur,
    contrairement à `_selected_month_batch`.
    """
    # 1) Priorité au vrai MCR mensuel (HISTORICAL_MONTH)
    batch = db.scalar(
        select(ImportBatch)
        .where(
            ImportBatch.batch_type == ImportBatchType.HISTORICAL_MONTH,
            ImportBatch.period == period_label,
        )
        .order_by(ImportBatch.imported_at.desc(), ImportBatch.id.desc())
        .limit(1)
    )
    if batch:
        return batch

    # 2) Sinon, chercher un snapshot dont snapshot_date == dernier jour du mois
    month_start, month_end = _month_bounds_from_period(period_label)
    batch = db.scalar(
        select(ImportBatch)
        .where(
            ImportBatch.batch_type.in_(
                [ImportBatchType.CURRENT_STATE, ImportBatchType.SNAPSHOT]
            ),
            ImportBatch.snapshot_date == month_end,
        )
        .order_by(
            case((ImportBatch.batch_type == ImportBatchType.CURRENT_STATE, 0), else_=1),
            ImportBatch.snapshot_date.desc(),
            ImportBatch.imported_at.desc(),
            ImportBatch.id.desc(),
        )
        .limit(1)
    )
    return batch


def _selected_month_batch(db: Session, period_label: str) -> ImportBatch:
    batch = db.scalar(
        select(ImportBatch)
        .where(
            ImportBatch.batch_type == ImportBatchType.HISTORICAL_MONTH,
            ImportBatch.period == period_label,
        )
        .order_by(ImportBatch.imported_at.desc(), ImportBatch.id.desc())
        .limit(1)
    )
    if batch:
        return batch

    month_start, month_end = _month_bounds_from_period(period_label)
    batch = db.scalar(
        select(ImportBatch)
        .where(
            ImportBatch.batch_type.in_(
                [ImportBatchType.CURRENT_STATE, ImportBatchType.SNAPSHOT]
            ),
            ImportBatch.snapshot_date >= month_start,
            ImportBatch.snapshot_date <= month_end,
        )
        .order_by(
            case((ImportBatch.batch_type == ImportBatchType.CURRENT_STATE, 0), else_=1),
            ImportBatch.snapshot_date.desc(),
            ImportBatch.imported_at.desc(),
            ImportBatch.id.desc(),
        )
        .limit(1)
    )
    if batch:
        return batch
    raise _month_batch_not_found(period_label)


def resolve_snapshot_at_or_before(db: Session, end_date: date | None) -> ImportBatch | None:
    if end_date is None:
        return None
    return db.scalar(
        select(ImportBatch)
        .where(
            ImportBatch.batch_type.in_(
                [ImportBatchType.CURRENT_STATE, ImportBatchType.SNAPSHOT]
            ),
            ImportBatch.snapshot_date <= end_date,
        )
        .order_by(
            ImportBatch.snapshot_date.desc(),
            ImportBatch.imported_at.desc(),
            ImportBatch.id.desc(),
        )
        .limit(1)
    )


def _daily_snapshot_batch_for_date(db: Session, target_date: date) -> ImportBatch | None:
    """Retourne le snapshot journalier correspondant a `target_date`.

    Chaque import quotidien enregistre l'etat de la veille comme un
    snapshot (CURRENT_STATE ou SNAPSHOT). L'image historique correcte pour
    une date choisie est donc le snapshot le plus recent dont
    snapshot_date <= target_date (match exact prioritaire, sinon le plus
    proche avant cette date).
    """
    return resolve_snapshot_at_or_before(db, target_date)


def _is_last_day_of_month(d: date) -> bool:
    """Retourne True si `d` est le dernier jour de son mois."""
    if d is None:
        return False
    return d.day == monthrange(d.year, d.month)[1]


def _data_scope_for_period(
    db: Session,
    date_from: date | None,
    date_to: date | None,
    user: User | None = None,
) -> tuple[date | None, object | None, ImportBatch | None]:
    normalized_from = date_from
    normalized_to = date_to
    committee_batch = None
    if user is not None and is_committee_member(user):
        normalized_from, normalized_to, committee_batch = normalize_committee_historical_request(
            db,
            user,
            date_from,
            date_to,
        )

    if committee_batch is not None:
        period_label = _period_label_from_dates(normalized_from, normalized_to)
        _, month_end = _month_bounds_from_period(period_label)
        return committee_batch.snapshot_date or month_end, LoanRaw.import_batch_id == committee_batch.id, committee_batch

    if not normalized_to:
        snapshot_date, scope_filter = _active_snapshot_scope(db)
        return snapshot_date, scope_filter, None

    # Si date_to correspond au DERNIER JOUR du mois, prioriser le MCR mensuel
    # (HISTORICAL_MONTH) de ce mois ci. Cela garantit que le snapshot utilise
    # l'import MCR officiel du mois et non un snapshot journalier intermediaire.
    if _is_last_day_of_month(normalized_to):
        period_label = _period_label_from_dates(normalized_from, normalized_to)
        if period_label:
            monthly_batch = _try_monthly_mcr_batch(db, period_label)
            if monthly_batch is not None:
                logger.info(
                    "snapshot_selection date_to=%s is_month_end=true "
                    "period=%s selected_batch_id=%s snapshot_date=%s "
                    "(MCR mensuel priorise sur snapshot journalier)",
                    normalized_to,
                    period_label,
                    monthly_batch.id,
                    monthly_batch.snapshot_date,
                )
                return (
                    monthly_batch.snapshot_date
                    or normalized_to,
                    LoanRaw.import_batch_id == monthly_batch.id,
                    monthly_batch,
                )

    # 1) Priorite au snapshot journalier le plus proche (<=) de date_to :
    #    c'est l'image historique reelle demandee par l'utilisateur.
    batch = _daily_snapshot_batch_for_date(db, normalized_to)
    if batch is not None:
        logger.info(
            "snapshot_selection date_to=%s is_month_end=%s selected_batch_id=%s snapshot_date=%s",
            normalized_to,
            _is_last_day_of_month(normalized_to),
            batch.id,
            batch.snapshot_date,
        )
        return batch.snapshot_date, LoanRaw.import_batch_id == batch.id, batch

    # 2) Repli sur l'ancien mecanisme mensuel (donnees historiques
    #    importees avant la mise en place des snapshots journaliers, ou
    #    aucun snapshot journalier n'existe encore avant cette date).
    period_label = _period_label_from_dates(normalized_from, normalized_to)
    if not period_label:
        snapshot_date, scope_filter = _active_snapshot_scope(db)
        return snapshot_date, scope_filter, None

    batch = _selected_month_batch(db, period_label)
    _, month_end = _month_bounds_from_period(period_label)
    logger.info(
        "snapshot_selection date_to=%s is_month_end=%s selected_batch_id=%s snapshot_date=%s (fallback mensuel)",
        normalized_to,
        _is_last_day_of_month(normalized_to),
        batch.id,
        batch.snapshot_date,
    )
    return batch.snapshot_date or month_end, LoanRaw.import_batch_id == batch.id, batch


def _scope_filters(
    db: Session,
    user: User,
    agency_id: str | None,
    agent_id: int | None,
    sector_ids: list[int] | None = None,
):
    scope = get_user_data_scope(user)
    filters = []
    if scope.role == UserRole.AGENCY_MANAGER and scope.agency_id is not None:
        if not db.get(Agency, scope.agency_id):
            return [false()]
        filters.append(Agency.id == scope.agency_id)
    elif scope.role == UserRole.PORTFOLIO_MANAGER and scope.agent_id is not None:
        identity_key = user_portfolio_identity_key(db, user)
        if not identity_key:
            return [false()]
        filters.append(Agent.id.in_(matching_agent_ids_query(identity_key)))

    selected_agency_ids = normalize_agency_ids(agency_id=agency_id)
    if selected_agency_ids and scope.role != UserRole.PORTFOLIO_MANAGER:
        existing_agency_ids = set(
            db.scalars(select(Agency.id).where(Agency.id.in_(selected_agency_ids))).all()
        )
        if len(existing_agency_ids) != len(selected_agency_ids):
            return [false()]
        if len(selected_agency_ids) == 1:
            filters.append(Agency.id == selected_agency_ids[0])
        else:
            filters.append(Agency.id.in_(selected_agency_ids))
    if agent_id:
        selected_agent = db.get(Agent, agent_id)
        if not selected_agent:
            return [false()]
        if scope.role == UserRole.PORTFOLIO_MANAGER and scope.agent_id is not None:
            identity_key = user_portfolio_identity_key(db, user)
            selected_key = normalized_agent_name_expression(Agent.name)
            is_allowed = db.scalar(
                select(func.count(Agent.id)).where(
                    Agent.id == selected_agent.id,
                    selected_key == identity_key,
                )
            )
            if not is_allowed:
                return [false()]
        else:
            filters.append(Agent.id == agent_id)
    if sector_ids:
        sector_condition = sector_filter_condition(db, sector_ids)
        if sector_condition is not None:
            filters.append(sector_condition)
    return filters


def _loan_filters(
    db: Session,
    user: User,
    scope_filter: object,
    agency_id: str | None,
    agent_id: int | None,
    sector_ids: list[int] | None = None,
):
    return [scope_filter, *_scope_filters(db, user, agency_id, agent_id, sector_ids)]


def _flow_condition(date_from: date | None, date_to: date | None):
    condition = true()
    if date_from:
        condition = condition & (LoanRaw.disbursement_date >= date_from)
    if date_to:
        condition = condition & (LoanRaw.disbursement_date <= date_to)
    return condition


def _stock_condition(date_to: date | None):
    condition = true()
    if date_to:
        condition = condition & (LoanRaw.disbursement_date <= date_to)
    return condition


def _validate_same_month_period(date_from: date | None, date_to: date | None) -> None:
    if not date_from or not date_to:
        return
    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_date_filter", "message": "La date de debut doit etre avant la date de fin."},
        )
    if (date_from.year, date_from.month) != (date_to.year, date_to.month):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "date_filter_cross_month",
                "message": "La periode filtree doit appartenir au meme mois.",
            },
        )


def _chart_mode(user: User, agency_id: str | None, agent_id: int | None) -> str:
    scope = get_user_data_scope(user)
    if scope.agent_id is not None or agent_id:
        return "AGENT_MONTHLY_TREND"
    if scope.agency_id is not None or normalize_agency_ids(agency_id=agency_id):
        return "AGENCY_MONTHLY_TREND"
    return "GLOBAL_BY_AGENCY"


def _month_bounds_from_period(period_label: str) -> tuple[date, date]:
    year = int(period_label[:4])
    month = int(period_label[5:7])
    end_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, end_day)


def _period_year_month(period_label: str) -> tuple[int, int]:
    return int(period_label[:4]), int(period_label[5:7])


def _format_snapshot_label(snapshot_date: date) -> str:
    return f"Snapshot {snapshot_date.strftime('%d/%m/%Y')}"


def _format_closed_month_label(snapshot_date: date) -> str:
    label = snapshot_date.strftime("%B %Y")
    return label[:1].upper() + label[1:]


def _parse_snapshot_batch_ids(raw_ids: str | None) -> list[int]:
    if not raw_ids:
        return []
    parsed: list[int] = []
    for token in raw_ids.split(","):
        value = token.strip()
        if not value:
            continue
        try:
            parsed_id = int(value)
        except ValueError:
            continue
        if parsed_id > 0:
            parsed.append(parsed_id)
    return list(dict.fromkeys(parsed))


def _scoped_snapshot_batches(
    db: Session,
    user: User,
    agency_id: str | None,
    agent_id: int | None,
    snapshot_batch_ids: list[int] | None = None,
) -> list[ImportBatch]:
    query = (
        select(ImportBatch)
        .join(LoanRaw, LoanRaw.import_batch_id == ImportBatch.id)
        .join(Agency, Agency.name == LoanRaw.agency_name)
        .join(Agent, _agent_join_condition())
        .where(ImportBatch.batch_type == ImportBatchType.SNAPSHOT)
    )
    if snapshot_batch_ids is not None:
        if not snapshot_batch_ids:
            return []
        query = query.where(ImportBatch.id.in_(snapshot_batch_ids))

    scope_conditions = _scope_filters(db=db, user=user, agency_id=agency_id, agent_id=agent_id)
    if scope_conditions:
        query = query.where(*scope_conditions)

    return db.scalars(
        query.group_by(ImportBatch.id)
        .order_by(ImportBatch.snapshot_date.asc(), ImportBatch.imported_at.asc(), ImportBatch.id.asc())
    ).all()


def _safe_ratio(current_value: Decimal, target_value: Decimal) -> Decimal:
    if not target_value:
        return Decimal("0")
    return (current_value / target_value).quantize(Decimal("0.0001"))


def calculate_potentially_radiable_threshold(reference_date: date | None) -> int:
    if reference_date is None:
        return 365
    month_end = date(reference_date.year, reference_date.month, monthrange(reference_date.year, reference_date.month)[1])
    days_remaining = (month_end - reference_date).days
    return max(0, 365 - days_remaining)


def _potentially_radiable_condition(reference_date: date | None, days_overdue_expr):
    threshold = calculate_potentially_radiable_threshold(reference_date)
    return (days_overdue_expr.is_not(None)) & (days_overdue_expr >= threshold)


def client_potentially_radiable_subquery(filters: list, reference_date: date | None):
    threshold = calculate_potentially_radiable_threshold(reference_date)
    return (
        select(LoanRaw.client_id)
        .where(
            *filters,
            LoanRaw.client_id.is_not(None),
            LoanRaw.days_overdue.is_not(None),
            LoanRaw.days_overdue >= threshold,
        )
        .group_by(LoanRaw.client_id)
        .subquery()
    )


@router.get("/active-snapshot", response_model=ActiveSnapshotRead)
def active_snapshot(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if is_committee_member(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "current_state_forbidden", "message": "Le profil Membre comité n'a pas accès à l'état actuel."},
        )
    snapshot_date, scope_filter = _active_snapshot_scope(db)
    if snapshot_date is None or scope_filter is None:
        return ActiveSnapshotRead(snapshot_date=None, label=None)
    return ActiveSnapshotRead(
        snapshot_date=snapshot_date,
        label=_format_snapshot_label(snapshot_date),
    )


@router.get("/closed-months", response_model=list[ClosedMonthOptionRead])
def list_closed_months(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in {UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.COMMITTEE_MEMBER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "closed_months_forbidden", "message": "Ce profil ne peut pas consulter la liste des mois clotures."},
        )
    logger.info(
        "Closed months requested | user_id=%s | role=%s",
        user.id,
        user.role,
    )
    items: list[ClosedMonthOptionRead] = []
    for batch in list_closed_month_batches(db):
        if batch.snapshot_date is None:
            continue
        month_key = closed_month_key(batch.snapshot_date)
        items.append(
            ClosedMonthOptionRead(
                key=month_key,
                period=month_key,
                label=_format_closed_month_label(batch.snapshot_date),
                snapshot_date=batch.snapshot_date,
                batch_id=batch.id,
            )
        )
    logger.info(
        "Closed months response | user_id=%s | role=%s | count=%s | months=%s",
        user.id,
        user.role,
        len(items),
        [item.key for item in items],
    )
    return items


@router.get("/daily", response_model=Page[DailyMetricRead])
def list_daily_metrics(
    agency_id: str | None = None,
    agent_id: int | None = None,
    sector_ids: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = Query(default=None, min_length=1),
    page: tuple[int, int] = Depends(pagination),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    limit, offset = page
    try:
        date_from, date_to, _committee_batch = normalize_committee_historical_request(
            db,
            user,
            date_from,
            date_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "historical_only", "message": str(exc)}) from exc
    snapshot_date, scope_filter, selected_batch = _data_scope_for_period(db, date_from, date_to, user=user)
    if snapshot_date is None or scope_filter is None:
        return Page(items=[], total=0, limit=limit, offset=offset)

    exposure = LoanRaw.principal_outstanding + LoanRaw.principal_due
    effective_date_from, effective_date_to = _effective_date_bounds(date_from, date_to)
    flow_condition = _flow_condition(effective_date_from, effective_date_to)
    stock_condition = _stock_condition(effective_date_to)
    is_healthy = LoanRaw.days_overdue == 0
    is_par_0 = LoanRaw.days_overdue > 0
    is_par_1_30 = (LoanRaw.days_overdue > 0) & (LoanRaw.days_overdue <= 30)
    is_par_1_15 = (LoanRaw.days_overdue > 0) & (LoanRaw.days_overdue <= 15)
    is_par_16_30 = (LoanRaw.days_overdue >= 16) & (LoanRaw.days_overdue <= 30)
    is_par_31_60 = (LoanRaw.days_overdue >= 31) & (LoanRaw.days_overdue <= 60)
    is_par_61_90 = (LoanRaw.days_overdue > 60) & (LoanRaw.days_overdue <= 90)
    is_par_91_120 = (LoanRaw.days_overdue > 90) & (LoanRaw.days_overdue <= 120)
    is_par_120 = LoanRaw.days_overdue > 120
    is_par_30 = LoanRaw.days_overdue > 30
    category_desc_text = func.lower(func.coalesce(LoanRaw.category_desc, ""))
    is_afari_credit = category_desc_text.contains("آفاري") | category_desc_text.contains("afari")|category_desc_text.contains("سندنا") | category_desc_text.contains("sanadna")
    is_tpme_credit = (~is_afari_credit) & (LoanRaw.disbursement_amount > 20000)
    is_micro_credit = (~is_afari_credit) & (LoanRaw.disbursement_amount <= 20000)
    is_afari_credit = func.coalesce(LoanRaw.category_desc, "").contains("آفاري")
    is_tpme_credit = (~is_afari_credit) & (LoanRaw.disbursement_amount > 20000)
    is_micro_credit = (~is_afari_credit) & (LoanRaw.disbursement_amount <= 20000)

    filters = _loan_filters(
        db=db,
        user=user,
        scope_filter=scope_filter,
        agency_id=agency_id,
        agent_id=agent_id,
        sector_ids=normalize_sector_ids(sector_ids=sector_ids),
    )
    if q:
        term = f"%{q.strip()}%"
        filters.append(
            (
                Agency.name.ilike(term)
                | Agent.name.ilike(term)
                | cast(LoanRaw.snapshot_date, String).ilike(term)
            )
        )
    scope = get_user_data_scope(user)
    grouped_ids = (
        select(Agency.id.label("agency_id"), Agent.id.label("agent_id"))
        .select_from(LoanRaw)
        .join(Agency, Agency.name == LoanRaw.agency_name)
        .join(Agent, _agent_join_condition())
        .where(*filters)
        .group_by(Agency.id, Agent.id)
        .subquery()
    )
    total = db.scalar(select(func.count()).select_from(grouped_ids)) or 0

    rows = db.execute(
        select(
            Agency.id.label("agency_id"),
            Agency.name.label("agency_name"),
            Agent.id.label("agent_id"),
            Agent.name.label("agent_name"),
            func.coalesce(func.sum(case((flow_condition, 1), else_=0)), 0).label(
                "disbursement_count"
            ),
            func.coalesce(
                func.sum(case((flow_condition, LoanRaw.disbursement_amount), else_=0)), 0
            ).label("disbursement_volume"),
            func.count(
                func.distinct(case((stock_condition, LoanRaw.client_id), else_=None))
            ).label("nb_clients"),
            func.coalesce(func.sum(case((stock_condition, exposure), else_=0)), 0).label(
                "outstanding"
            ),
            func.coalesce(
                func.sum(case((stock_condition & is_healthy, exposure), else_=0)), 0
            ).label("healthy_outstanding"),
            func.coalesce(
                func.sum(case((stock_condition & is_par_0, exposure), else_=0)), 0
            ).label("par_0"),
            func.coalesce(
                func.sum(case((stock_condition & is_par_1_30, exposure), else_=0)), 0
            ).label("par_1_30"),
            func.coalesce(func.sum(case((stock_condition & is_par_1_15, exposure), else_=0)), 0).label("par_1_15"),
            func.coalesce(func.sum(case((stock_condition & is_par_16_30, exposure), else_=0)), 0).label("par_16_30"),
            func.coalesce(
                func.sum(case((stock_condition & is_par_31_60, exposure), else_=0)), 0
            ).label("par_31_60"),
            func.coalesce(
                func.sum(case((stock_condition & is_par_61_90, exposure), else_=0)), 0
            ).label("par_61_90"),
            func.coalesce(
                func.sum(case((stock_condition & is_par_91_120, exposure), else_=0)), 0
            ).label("par_91_120"),
            func.coalesce(
                func.sum(case((stock_condition & is_par_120, exposure), else_=0)), 0
            ).label("par_120"),
            func.coalesce(
                func.sum(case((stock_condition & is_par_30, exposure), else_=0)), 0
            ).label("par_30"),
        )
        .select_from(LoanRaw)
        .join(Agency, Agency.name == LoanRaw.agency_name)
        .join(Agent, _agent_join_condition())
        .where(*filters)
        .group_by(Agency.id, Agency.name, Agent.id, Agent.name)
        .order_by(Agency.name.asc(), Agent.name.asc())
        .limit(limit)
        .offset(offset)
    ).mappings()

    items = []
    for index, row in enumerate(rows, start=1):
        items.append(
            {
                "id": offset + index,
                "agency_id": row["agency_id"],
                "agent_id": row["agent_id"],
                "date": snapshot_date,
                "disbursement_count": row["disbursement_count"],
                "disbursement_volume": row["disbursement_volume"],
                "nb_clients": row["nb_clients"],
                "outstanding": row["outstanding"],
                "healthy_outstanding": row["healthy_outstanding"],
                "par_0": row["par_0"],
                "par_1_30": row["par_1_30"],
                "par_1_15": row["par_1_15"],
                "par_16_30": row["par_16_30"],
                "par_31_60": row["par_31_60"],
                "par_61_90": row["par_61_90"],
                "par_91_120": row["par_91_120"],
                "par_120": row["par_120"],
                "par_30": row["par_30"],
                "agency": {
                    "id": row["agency_id"] or 0,
                    "name": row["agency_name"],
                },
                "agent": {
                    "id": row["agent_id"] or 0,
                    "name": row["agent_name"],
                    "agency_id": row["agency_id"] or 0,
                },
            }
        )

    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/current-credits", response_model=Page[CurrentCreditRead])
def list_current_credits(
    agency_id: str | None = None,
    agent_id: int | None = None,
    sector_ids: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = Query(default=None, min_length=1),
    risk_categories: str | None = Query(default=None),
    page: tuple[int, int] = Depends(pagination),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    limit, offset = page
    try:
        date_from, date_to, _committee_batch = normalize_committee_historical_request(
            db,
            user,
            date_from,
            date_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "historical_only", "message": str(exc)}) from exc
    _, scope_filter, _selected_batch = _data_scope_for_period(db, date_from, date_to, user=user)
    if scope_filter is None:
        return Page(items=[], total=0, limit=limit, offset=offset)
    effective_date_from, effective_date_to = _effective_date_bounds(date_from, date_to)

    filters = _loan_filters(
        db=db,
        user=user,
        scope_filter=scope_filter,
        agency_id=agency_id,
        agent_id=agent_id,
    )
    if effective_date_from:
        filters.append(LoanRaw.disbursement_date >= effective_date_from)
    if effective_date_to:
        filters.append(LoanRaw.disbursement_date <= effective_date_to)
    risk_filter = _risk_category_filter(_parse_risk_categories(risk_categories))
    if risk_filter is not None:
        filters.append(risk_filter)
    if q:
        term_raw = q.strip()
        term = f"%{term_raw}%"
        normalized_term = "".join(term_raw.lower().split())
        normalized_rating = func.replace(func.lower(func.coalesce(LoanRaw.client_rating, "")), " ", "")
        search_condition = (
            LoanRaw.contract_no.ilike(term)
            | LoanRaw.client_id.ilike(term)
            | func.coalesce(LoanRaw.client_name, "").ilike(term)
            | func.coalesce(LoanRaw.client_first_name, "").ilike(term)
            | LoanRaw.agency_name.ilike(term)
            | LoanRaw.agent_name.ilike(term)
            | func.coalesce(LoanRaw.client_rating, "").ilike(term)
            | normalized_rating.like(f"%{normalized_term}%")
        )
        if user.role == UserRole.SUPER_ADMIN:
            search_condition = search_condition | func.coalesce(LoanRaw.client_ncni, "").ilike(term)
        filters.append(search_condition)

    base_stmt = (
        select(LoanRaw.id)
        .select_from(LoanRaw)
        .join(Agency, Agency.name == LoanRaw.agency_name)
        .join(Agent, _agent_join_condition())
        .where(*filters)
    )
    total = db.scalar(select(func.count()).select_from(base_stmt.subquery())) or 0

    encours_expr = (
        func.coalesce(LoanRaw.principal_outstanding, 0)
        + func.coalesce(LoanRaw.principal_due, 0)
    ).label("encours")
    rows = db.execute(
        select(
            LoanRaw.contract_no,
            LoanRaw.client_name,
            LoanRaw.client_first_name,
            LoanRaw.client_id,
            LoanRaw.client_ncni,
            LoanRaw.agency_name,
            LoanRaw.agent_name,
            LoanRaw.client_rating,
            LoanRaw.disbursement_date,
            LoanRaw.maturity_date,
            LoanRaw.disbursement_amount,
            LoanRaw.days_overdue,
            LoanRaw.total_scheduled_amount,
            LoanRaw.principal_outstanding,
            LoanRaw.total_due,
            encours_expr,
        )
        .select_from(LoanRaw)
        .join(Agency, Agency.name == LoanRaw.agency_name)
        .join(Agent, _agent_join_condition())
        .where(*filters)
        .order_by(LoanRaw.disbursement_date.asc(), LoanRaw.contract_no.asc())
        .limit(limit)
        .offset(offset)
    ).mappings()
    items = [dict(row) for row in rows]
    if user.role != UserRole.SUPER_ADMIN:
        for item in items:
            item["client_ncni"] = None
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/summary", response_model=MetricsSummary)
def metrics_summary(
    agency_id: str | None = None,
    agent_id: int | None = None,
    sector_ids: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        date_from, date_to, _committee_batch = normalize_committee_historical_request(
            db,
            user,
            date_from,
            date_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "historical_only", "message": str(exc)}) from exc
    snapshot_date, scope_filter, selected_batch = _data_scope_for_period(db, date_from, date_to, user=user)
    if scope_filter is None or snapshot_date is None:
        return MetricsSummary(
            credits_count=0,
            disbursement_count=0,
            disbursements_count=0,
            disbursement_volume=0,
            nb_clients=0,
            outstanding=0,
            healthy_outstanding=0,
            healthy_count=0,
            healthy_client_count=0,
            par_0=0,
            par_0_count=0,
            par_0_client_count=0,
            par_1_15=0,
            par_1_15_count=0,
            par_1_15_client_count=0,
            par_16_30=0,
            par_16_30_count=0,
            par_16_30_client_count=0,
            par_31_60=0,
            par_31_60_count=0,
            par_31_60_client_count=0,
            par_61_90=0,
            par_61_90_count=0,
            par_61_90_client_count=0,
            par_91_120=0,
            par_91_120_count=0,
            par_91_120_client_count=0,
            par_120=0,
            par_120_count=0,
            par_120_client_count=0,
            par_30=0,
            par_30_count=0,
            par_30_client_count=0,
            potentially_radiable_volume=0,
            potentially_radiable_rate=0,
        )

    reference_date = snapshot_date or date_to or date_from or date.today()
    threshold = calculate_potentially_radiable_threshold(reference_date)
    exposure = (
        func.coalesce(LoanRaw.principal_outstanding, 0)
        + func.coalesce(LoanRaw.principal_due, 0)
    )
    effective_date_from, effective_date_to = _effective_date_bounds(date_from, date_to)
    flow_condition = _flow_condition(effective_date_from, effective_date_to)
    stock_condition = _stock_condition(effective_date_to)
    is_healthy = LoanRaw.days_overdue == 0
    is_par_0 = LoanRaw.days_overdue > 0
    is_par_1_30 = (LoanRaw.days_overdue > 0) & (LoanRaw.days_overdue <= 30)
    is_par_1_15 = (LoanRaw.days_overdue > 0) & (LoanRaw.days_overdue <= 15)
    is_par_16_30 = (LoanRaw.days_overdue >= 16) & (LoanRaw.days_overdue <= 30)
    is_par_31_60 = (LoanRaw.days_overdue >= 31) & (LoanRaw.days_overdue <= 60)
    is_par_61_90 = (LoanRaw.days_overdue > 60) & (LoanRaw.days_overdue <= 90)
    is_par_91_120 = (LoanRaw.days_overdue > 90) & (LoanRaw.days_overdue <= 120)
    is_par_120 = LoanRaw.days_overdue > 120
    is_par_30 = LoanRaw.days_overdue > 30

    filters = _loan_filters(
        db=db,
        user=user,
        scope_filter=scope_filter,
        agency_id=agency_id,
        agent_id=agent_id,
        sector_ids=normalize_sector_ids(sector_ids=sector_ids),
    )

    client_radiable_ids = client_potentially_radiable_subquery(filters, reference_date)
    client_radiable_condition = LoanRaw.client_id.in_(select(client_radiable_ids.c.client_id))

    row = db.execute(
        select(
            func.coalesce(func.sum(case((stock_condition, 1), else_=0)), 0),
            func.coalesce(func.sum(case((flow_condition, 1), else_=0)), 0),
            func.count(case((stock_condition, LoanRaw.contract_no), else_=None)),
            func.coalesce(func.sum(case((flow_condition, LoanRaw.disbursement_amount), else_=0)), 0),
            func.count(
                func.distinct(case((stock_condition, LoanRaw.client_id), else_=None))
            ),
            func.coalesce(func.sum(case((stock_condition, exposure), else_=0)), 0),
            func.coalesce(
                func.sum(case((stock_condition & is_healthy, exposure), else_=0)), 0
            ),
            func.count(
                func.distinct(case((stock_condition & is_healthy, LoanRaw.contract_no), else_=None))
            ),
            func.count(
                func.distinct(case((stock_condition & is_healthy, LoanRaw.client_id), else_=None))
            ),
            func.coalesce(
                func.sum(case((stock_condition & is_par_0, exposure), else_=0)), 0
            ),
            func.count(
                func.distinct(case((stock_condition & is_par_0, LoanRaw.contract_no), else_=None))
            ),
            func.count(
                func.distinct(case((stock_condition & is_par_0, LoanRaw.client_id), else_=None))
            ),
            func.coalesce(
                func.sum(case((stock_condition & is_par_1_30, exposure), else_=0)), 0
            ),
            func.count(
                func.distinct(case((stock_condition & is_par_1_30, LoanRaw.contract_no), else_=None))
            ),
            func.count(
                func.distinct(case((stock_condition & is_par_1_30, LoanRaw.client_id), else_=None))
            ),
            func.coalesce(func.sum(case((stock_condition & is_par_1_15, exposure), else_=0)), 0),
            func.count(
                func.distinct(case((stock_condition & is_par_1_15, LoanRaw.contract_no), else_=None))
            ),
            func.count(
                func.distinct(case((stock_condition & is_par_1_15, LoanRaw.client_id), else_=None))
            ),
            func.coalesce(func.sum(case((stock_condition & is_par_16_30, exposure), else_=0)), 0),
            func.count(
                func.distinct(case((stock_condition & is_par_16_30, LoanRaw.contract_no), else_=None))
            ),
            func.count(
                func.distinct(case((stock_condition & is_par_16_30, LoanRaw.client_id), else_=None))
            ),
            func.coalesce(
                func.sum(case((stock_condition & is_par_31_60, exposure), else_=0)), 0
            ),
            func.count(
                func.distinct(case((stock_condition & is_par_31_60, LoanRaw.contract_no), else_=None))
            ),
            func.count(
                func.distinct(case((stock_condition & is_par_31_60, LoanRaw.client_id), else_=None))
            ),
            func.coalesce(
                func.sum(case((stock_condition & is_par_61_90, exposure), else_=0)), 0
            ),
            func.count(
                func.distinct(case((stock_condition & is_par_61_90, LoanRaw.contract_no), else_=None))
            ),
            func.count(
                func.distinct(case((stock_condition & is_par_61_90, LoanRaw.client_id), else_=None))
            ),
            func.coalesce(
                func.sum(case((stock_condition & is_par_91_120, exposure), else_=0)), 0
            ),
            func.count(
                func.distinct(case((stock_condition & is_par_91_120, LoanRaw.contract_no), else_=None))
            ),
            func.count(
                func.distinct(case((stock_condition & is_par_91_120, LoanRaw.client_id), else_=None))
            ),
            func.coalesce(
                func.sum(case((stock_condition & is_par_120, exposure), else_=0)), 0
            ),
            func.count(
                func.distinct(case((stock_condition & is_par_120, LoanRaw.contract_no), else_=None))
            ),
            func.count(
                func.distinct(case((stock_condition & is_par_120, LoanRaw.client_id), else_=None))
            ),
            func.coalesce(
                func.sum(case((stock_condition & is_par_30, exposure), else_=0)), 0
            ),
            func.count(
                func.distinct(case((stock_condition & is_par_30, LoanRaw.contract_no), else_=None))
            ),
            func.count(
                func.distinct(case((stock_condition & is_par_30, LoanRaw.client_id), else_=None))
            ),
            func.coalesce(
                func.sum(case((client_radiable_condition & stock_condition, exposure), else_=0)), 0
            ),
            func.count(
                func.distinct(case((client_radiable_condition & stock_condition, LoanRaw.client_id), else_=None))
            ),
            func.count(case((client_radiable_condition & stock_condition, LoanRaw.id), else_=None)),
        )
        .select_from(LoanRaw)
        .join(Agency, Agency.name == LoanRaw.agency_name)
        .join(Agent, _agent_join_condition())
        .where(*filters)
    ).one()

    total_outstanding = row[5]
    healthy_outstanding = row[6]
    healthy_count = int(row[7] or 0)
    healthy_client_count = int(row[8] or 0)
    par_0 = row[9]
    par_0_count = int(row[10] or 0)
    par_0_client_count = int(row[11] or 0)
    par_1_30 = row[12]
    par_1_30_count = int(row[13] or 0)
    par_1_30_client_count = int(row[14] or 0)
    par_1_15 = row[15]
    par_1_15_count = int(row[16] or 0)
    par_1_15_client_count = int(row[17] or 0)
    par_16_30 = row[18]
    par_16_30_count = int(row[19] or 0)
    par_16_30_client_count = int(row[20] or 0)
    par_31_60 = row[21]
    par_31_60_count = int(row[22] or 0)
    par_31_60_client_count = int(row[23] or 0)
    par_61_90 = row[24]
    par_61_90_count = int(row[25] or 0)
    par_61_90_client_count = int(row[26] or 0)
    par_91_120 = row[27]
    par_91_120_count = int(row[28] or 0)
    par_91_120_client_count = int(row[29] or 0)
    par_120 = row[30]
    par_120_count = int(row[31] or 0)
    par_120_client_count = int(row[32] or 0)
    par_30 = row[33]
    par_30_count = int(row[34] or 0)
    par_30_client_count = int(row[35] or 0)
    potentially_radiable_volume = row[36]
    potentially_radiable_client_count = row[37]
    potentially_radiable_loan_count = row[38]
    logger.info(
        "POTENTIELLE_RADIABLE_DEBUG requested_end_date=%s effective_snapshot_date=%s "
        "snapshot_batch_id=%s snapshot_filter=%s reference_date=%s threshold=%s volume=%s rate=%s",
        date_to,
        snapshot_date,
        selected_batch.id if selected_batch is not None else None,
        scope_filter,
        reference_date,
        threshold,
        potentially_radiable_volume,
        Decimal("0") if not total_outstanding else (potentially_radiable_volume / total_outstanding).quantize(Decimal("0.0001")),
    )
    return MetricsSummary(
        credits_count=row[0],
        disbursement_count=row[1],
        disbursements_count=row[2],
        disbursement_volume=row[3],
        nb_clients=row[4],
        outstanding=total_outstanding,
        healthy_outstanding=healthy_outstanding,
        healthy_count=healthy_count,
        healthy_client_count=healthy_client_count,
        par_0=par_0,
        par_0_count=par_0_count,
        par_0_client_count=par_0_client_count,
        par_1_30=par_1_30,
        par_1_30_count=par_1_30_count,
        par_1_30_client_count=par_1_30_client_count,
        par_1_15=par_1_15,
        par_1_15_count=par_1_15_count,
        par_1_15_client_count=par_1_15_client_count,
        par_16_30=par_16_30,
        par_16_30_count=par_16_30_count,
        par_16_30_client_count=par_16_30_client_count,
        par_31_60=par_31_60,
        par_31_60_count=par_31_60_count,
        par_31_60_client_count=par_31_60_client_count,
        par_61_90=par_61_90,
        par_61_90_count=par_61_90_count,
        par_61_90_client_count=par_61_90_client_count,
        par_91_120=par_91_120,
        par_91_120_count=par_91_120_count,
        par_91_120_client_count=par_91_120_client_count,
        par_120=par_120,
        par_120_count=par_120_count,
        par_120_client_count=par_120_client_count,
        par_30=par_30,
        par_30_count=par_30_count,
        par_30_client_count=par_30_client_count,
        potentially_radiable_volume=potentially_radiable_volume,
        potentially_radiable_rate=Decimal("0") if not total_outstanding else (potentially_radiable_volume / total_outstanding).quantize(Decimal("0.0001")),
        requested_date_to=date_to,
        effective_snapshot_date=snapshot_date,
        effective_import_batch_id=selected_batch.id if selected_batch is not None else None,
        potential_radiable_reference_date=reference_date,
        potential_radiable_threshold=threshold,
        potential_radiable_client_count=potentially_radiable_client_count,
        potential_radiable_loan_count=potentially_radiable_loan_count,
    )


@router.get("/snapshots", response_model=list[SnapshotOptionRead])
def list_snapshots(
    agency_id: str | None = None,
    agent_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if is_committee_member(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "daily_snapshots_forbidden", "message": "Le profil Membre comité ne peut pas consulter les snapshots journaliers."},
        )
    batches = _scoped_snapshot_batches(
        db=db,
        user=user,
        agency_id=agency_id,
        agent_id=agent_id,
    )
    return [
        SnapshotOptionRead(
            batch_id=batch.id,
            snapshot_date=batch.snapshot_date,
            label=_format_snapshot_label(batch.snapshot_date),
        )
        for batch in batches
    ]


@router.get("/charts", response_model=MetricsChartRead)
def metrics_charts(
    agency_id: str | None = None,
    agent_id: int | None = None,
    sector_ids: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    snapshot_batch_ids: str | None = Query(default=None),
    months: int = Query(default=6, ge=2, le=24),
    quality_scope: str = Query(default="agency", pattern="^(agency|global)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        date_from, date_to, _committee_batch = normalize_committee_historical_request(
            db,
            user,
            date_from,
            date_to,
            snapshot_batch_ids=snapshot_batch_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "historical_only", "message": str(exc)}) from exc
    period_label = _period_label_from_dates(date_from, date_to)
    selected_period_batch = _selected_month_batch(db, period_label) if period_label else None
    if user.role == UserRole.PORTFOLIO_MANAGER and quality_scope == "global":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Portfolio managers cannot access the global quality portfolio chart.",
        )
    mode = "GLOBAL_QUALITY_TREND" if quality_scope == "global" else _chart_mode(
        user=user, agency_id=agency_id, agent_id=agent_id
    )
    exposure = LoanRaw.principal_outstanding + LoanRaw.principal_due
    is_healthy = LoanRaw.days_overdue == 0
    is_par_0 = LoanRaw.days_overdue > 0
    is_par_1_30 = (LoanRaw.days_overdue > 0) & (LoanRaw.days_overdue <= 30)
    is_par_1_15 = (LoanRaw.days_overdue > 0) & (LoanRaw.days_overdue <= 15)
    is_par_16_30 = (LoanRaw.days_overdue >= 16) & (LoanRaw.days_overdue <= 30)
    is_par_31_60 = (LoanRaw.days_overdue >= 31) & (LoanRaw.days_overdue <= 60)
    is_par_61_90 = (LoanRaw.days_overdue > 60) & (LoanRaw.days_overdue <= 90)
    is_par_91_120 = (LoanRaw.days_overdue > 90) & (LoanRaw.days_overdue <= 120)
    is_par_120 = LoanRaw.days_overdue > 120
    is_par_30 = LoanRaw.days_overdue > 30
    category_desc_text = func.lower(func.coalesce(LoanRaw.category_desc, ""))
    is_afari_credit = category_desc_text.contains("آفاري") | category_desc_text.contains("afari")|category_desc_text.contains("سندنا") | category_desc_text.contains("sanadna")
    is_tpme_credit = (~is_afari_credit) & (LoanRaw.disbursement_amount >= 20000)
    is_micro_credit = (~is_afari_credit) & (LoanRaw.disbursement_amount < 20000)

    if mode == "GLOBAL_BY_AGENCY":
        snapshot_date, scope_filter, _selected_batch = _data_scope_for_period(db, date_from, date_to, user=user)
        if snapshot_date is None or scope_filter is None:
            return MetricsChartRead(mode=mode, points=[])
        effective_date_from, effective_date_to = _effective_date_bounds(date_from, date_to)
        stock_end_date = effective_date_to or snapshot_date
        flow_condition = _flow_condition(effective_date_from, effective_date_to)
        stock_condition = _stock_condition(stock_end_date)
        filters = _loan_filters(
            db=db,
            user=user,
            scope_filter=scope_filter,
            agency_id=agency_id,
            agent_id=agent_id,
            sector_ids=normalize_sector_ids(sector_ids=sector_ids),
        )
        valid_disbursement_date = (LoanRaw.disbursement_date >= date(2000, 1, 1)) & (
            LoanRaw.disbursement_date <= stock_end_date
        )
        rows = db.execute(
            select(
                Agency.name.label("label"),
                func.coalesce(func.sum(case((flow_condition, 1), else_=0)), 0).label(
                    "disbursement_count"
                ),
                func.coalesce(func.sum(case((flow_condition, LoanRaw.disbursement_amount), else_=0)), 0).label(
                    "disbursement_volume"
                ),
                func.coalesce(func.sum(case((flow_condition & is_micro_credit, LoanRaw.disbursement_amount), else_=0)), 0).label("micro_disbursement_volume"),
                func.coalesce(func.sum(case((flow_condition & is_micro_credit, 1), else_=0)), 0).label("micro_disbursement_count"),
                func.coalesce(func.sum(case((flow_condition & is_tpme_credit, LoanRaw.disbursement_amount), else_=0)), 0).label("tpme_disbursement_volume"),
                func.coalesce(func.sum(case((flow_condition & is_tpme_credit, 1), else_=0)), 0).label("tpme_disbursement_count"),
                func.coalesce(func.sum(case((flow_condition & is_afari_credit, LoanRaw.disbursement_amount), else_=0)), 0).label("afari_disbursement_volume"),
                func.coalesce(func.sum(case((flow_condition & is_afari_credit, 1), else_=0)), 0).label("afari_disbursement_count"),
                func.coalesce(func.sum(case((stock_condition, exposure), else_=0)), 0).label("outstanding"),
                func.coalesce(func.sum(case((stock_condition & is_healthy, exposure), else_=0)), 0).label(
                    "healthy_outstanding"
                ),
                func.coalesce(func.sum(case((stock_condition & is_par_0, exposure), else_=0)), 0).label(
                    "par_0"
                ),
                func.coalesce(func.sum(case((stock_condition & is_par_1_30, exposure), else_=0)), 0).label(
                    "par_1_30"
                ),
                func.coalesce(func.sum(case((stock_condition & is_par_1_15, exposure), else_=0)), 0).label(
                    "par_1_15"
                ),
                func.coalesce(func.sum(case((stock_condition & is_par_16_30, exposure), else_=0)), 0).label(
                    "par_16_30"
                ),
                func.coalesce(
                    func.sum(case((stock_condition & is_par_31_60, exposure), else_=0)), 0
                ).label("par_31_60"),
                func.coalesce(
                    func.sum(case((stock_condition & is_par_61_90, exposure), else_=0)), 0
                ).label("par_61_90"),
                func.coalesce(
                    func.sum(case((stock_condition & is_par_91_120, exposure), else_=0)), 0
                ).label("par_91_120"),
                func.coalesce(
                    func.sum(case((stock_condition & is_par_120, exposure), else_=0)), 0
                ).label("par_120"),
                func.coalesce(func.sum(case((stock_condition & is_par_30, exposure), else_=0)), 0).label(
                    "par_30"
                ),
            )
            .select_from(LoanRaw)
            .join(Agency, Agency.name == LoanRaw.agency_name)
            .join(Agent, _agent_join_condition())
            .where(*filters, valid_disbursement_date)
            .group_by(Agency.id, Agency.name)
        ).mappings()
        points = sorted(
            [dict(row) for row in rows],
            key=lambda point: Decimal(str(point.get("disbursement_volume") or 0)),
            reverse=True,
        )
        return MetricsChartRead(mode=mode, points=points)

    selected_snapshot_ids = _parse_snapshot_batch_ids(snapshot_batch_ids)
    selected_snapshots = _scoped_snapshot_batches(
        db=db,
        user=user,
        agency_id=agency_id,
        agent_id=agent_id,
        snapshot_batch_ids=selected_snapshot_ids,
    )

    current_batch = _latest_current_batch(db)
    historical_limit = max(0, months - (1 if current_batch else 0))
    historical_batches = db.scalars(
        select(ImportBatch)
        .where(
            ImportBatch.batch_type == ImportBatchType.HISTORICAL_MONTH,
            ImportBatch.period.is_not(None),
        )
        .order_by(ImportBatch.period.desc(), ImportBatch.imported_at.desc(), ImportBatch.id.desc())
        .limit(historical_limit)
    ).all()

    historical_period_batches = list(reversed(historical_batches))
    current_state_batches: list[ImportBatch] = [current_batch] if current_batch else []

    if selected_period_batch:
        trend_batches: list[ImportBatch] = [selected_period_batch]
    else:
        trend_batches = [
            *historical_period_batches,
            *selected_snapshots,
            *current_state_batches,
        ]

    # Legacy fallback when old data exists without import batch metadata.
    if not trend_batches:
        legacy_snapshot = _latest_snapshot_date_legacy(db)
        if legacy_snapshot:
            fallback_batch = ImportBatch(
                id=0,
                batch_type=ImportBatchType.CURRENT_STATE,
                period=None,
                snapshot_date=legacy_snapshot,
                file_name="legacy-snapshot",
            )
            trend_batches = [fallback_batch]

    points: list[dict] = []
    for batch in trend_batches:
        if period_label and not _batch_matches_period(batch, period_label):
            continue
        if batch.id == 0:
            batch_filter = LoanRaw.snapshot_date == batch.snapshot_date
        else:
            batch_filter = LoanRaw.import_batch_id == batch.id

        if batch.batch_type == ImportBatchType.HISTORICAL_MONTH and batch.period:
            month_start, month_end = _month_bounds_from_period(batch.period)
            label = batch.period
        elif batch.batch_type == ImportBatchType.SNAPSHOT:
            month_start = batch.snapshot_date.replace(day=1)
            month_end = batch.snapshot_date
            label = _format_snapshot_label(batch.snapshot_date)
        else:
            month_start = batch.snapshot_date.replace(day=1)
            month_end = batch.snapshot_date
            label = "CURRENT"

        if date_to:
            month_end = date_to
        flow_condition = _flow_condition(date_from, date_to or month_end)

        valid_disbursement_date = (LoanRaw.disbursement_date >= date(2000, 1, 1)) & (
            LoanRaw.disbursement_date <= month_end
        )
        stock_condition = LoanRaw.disbursement_date <= month_end
        filters = [batch_filter, *_scope_filters(db, user, agency_id, agent_id, normalize_sector_ids(sector_ids=sector_ids))]

        row = db.execute(
            select(
                func.coalesce(func.sum(case((flow_condition, 1), else_=0)), 0).label(
                    "disbursement_count"
                ),
                func.coalesce(
                    func.sum(case((flow_condition, LoanRaw.disbursement_amount), else_=0)),
                    0,
                ).label("disbursement_volume"),
                func.coalesce(func.sum(case((flow_condition & is_micro_credit, LoanRaw.disbursement_amount), else_=0)), 0).label("micro_disbursement_volume"),
                func.coalesce(func.sum(case((flow_condition & is_micro_credit, 1), else_=0)), 0).label("micro_disbursement_count"),
                func.coalesce(func.sum(case((flow_condition & is_tpme_credit, LoanRaw.disbursement_amount), else_=0)), 0).label("tpme_disbursement_volume"),
                func.coalesce(func.sum(case((flow_condition & is_tpme_credit, 1), else_=0)), 0).label("tpme_disbursement_count"),
                func.coalesce(func.sum(case((flow_condition & is_afari_credit, LoanRaw.disbursement_amount), else_=0)), 0).label("afari_disbursement_volume"),
                func.coalesce(func.sum(case((flow_condition & is_afari_credit, 1), else_=0)), 0).label("afari_disbursement_count"),
                func.coalesce(func.sum(case((stock_condition, exposure), else_=0)), 0).label(
                    "outstanding"
                ),
                func.coalesce(
                    func.sum(case((stock_condition & is_healthy, exposure), else_=0)), 0
                ).label("healthy_outstanding"),
                func.coalesce(
                    func.sum(case((stock_condition & is_par_0, exposure), else_=0)), 0
                ).label("par_0"),
                func.coalesce(
                    func.sum(case((stock_condition & is_par_1_30, exposure), else_=0)), 0
                ).label("par_1_30"),
                func.coalesce(func.sum(case((stock_condition & is_par_1_15, exposure), else_=0)), 0).label("par_1_15"),
                func.coalesce(func.sum(case((stock_condition & is_par_16_30, exposure), else_=0)), 0).label("par_16_30"),
                func.coalesce(
                    func.sum(case((stock_condition & is_par_31_60, exposure), else_=0)), 0
                ).label("par_31_60"),
                func.coalesce(
                    func.sum(case((stock_condition & is_par_61_90, exposure), else_=0)), 0
                ).label("par_61_90"),
                func.coalesce(
                    func.sum(case((stock_condition & is_par_91_120, exposure), else_=0)), 0
                ).label("par_91_120"),
                func.coalesce(
                    func.sum(case((stock_condition & is_par_120, exposure), else_=0)), 0
                ).label("par_120"),
                func.coalesce(
                    func.sum(case((stock_condition & is_par_30, exposure), else_=0)), 0
                ).label("par_30"),
            )
            .select_from(LoanRaw)
            .join(Agency, Agency.name == LoanRaw.agency_name)
            .join(Agent, _agent_join_condition())
            .where(*filters, valid_disbursement_date)
        ).mappings().one()
        points.append({"label": label, **dict(row)})

    return MetricsChartRead(mode=mode, points=points)


@router.get("/par-reduction", response_model=ParReductionRead)
def par_reduction(
    month: int | None = Query(default=None, ge=1, le=12),
    year: int | None = Query(default=None, ge=2000),
    agency_id: str | None = None,
    agent_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    today = date.today()
    selected_month = month or today.month
    selected_year = year or today.year
    scoped_agency, scoped_agent = resolve_reduction_scope(user, agency_id, agent_id)
    return compute_par_reduction(
        db,
        month=selected_month,
        year=selected_year,
        user=user,
        agency_id=scoped_agency,
        agent_id=scoped_agent,
    )


@router.get("/par-reduction/evolution")
def par_reduction_evolution(
    month: int | None = Query(default=None, ge=1, le=12),
    year: int | None = Query(default=None, ge=2000),
    agency_id: str | None = None,
    agent_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    today = date.today()
    selected_month = month or today.month
    selected_year = year or today.year
    scoped_agency, scoped_agent = resolve_reduction_scope(user, agency_id, agent_id)
    return compute_par_reduction_evolution(
        db,
        month=selected_month,
        year=selected_year,
        user=user,
        agency_id=scoped_agency,
        agent_id=scoped_agent,
    )


@router.get("/portfolio-performance", response_model=PortfolioDashboardRead)
def portfolio_performance(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != UserRole.PORTFOLIO_MANAGER:
        return PortfolioDashboardRead(
            has_target=False,
            has_bonus_rule=False,
            coverage_ratio=Decimal("0"),
            bonus_amount=Decimal("0"),
            details=[],
            message="This dashboard widget is available for portfolio managers only.",
        )

    if user.agency_id is None or user.agent_id is None:
        return PortfolioDashboardRead(
            has_target=False,
            has_bonus_rule=False,
            coverage_ratio=Decimal("0"),
            bonus_amount=Decimal("0"),
            details=[],
            message="Portfolio manager account is missing agency or agent assignment.",
        )
    scoped_agent = db.get(Agent, user.agent_id)
    if not scoped_agent:
        return PortfolioDashboardRead(
            has_target=False,
            has_bonus_rule=False,
            coverage_ratio=Decimal("0"),
            bonus_amount=Decimal("0"),
            details=[],
            message="Portfolio manager account has an unknown agent assignment.",
        )

    snapshot_date, scope_filter = _active_snapshot_scope(db)
    if snapshot_date is None or scope_filter is None:
        return PortfolioDashboardRead(
            has_target=False,
            has_bonus_rule=False,
            coverage_ratio=Decimal("0"),
            bonus_amount=Decimal("0"),
            details=[],
            message="No imported data available yet.",
        )

    target = db.scalar(
        select(Target).where(
            Target.target_type == TargetType.AGENT,
            Target.agency_id == user.agency_id,
            Target.agent_id == user.agent_id,
            Target.month == snapshot_date.month,
            Target.year == snapshot_date.year,
        )
    )

    if not target:
        return PortfolioDashboardRead(
            reference_month=snapshot_date.month,
            reference_year=snapshot_date.year,
            has_target=False,
            has_bonus_rule=False,
            coverage_ratio=Decimal("0"),
            bonus_amount=Decimal("0"),
            details=[],
            message="No agent objective is defined for the current period.",
        )

    realized = compute_objective_period_realizations(
        db=db,
        month=target.month,
        year=target.year,
        agency_id=None,
        agent_id=user.agent_id,
    )

    current_values = {
        "disbursement_count": Decimal(str(realized["disbursement_count"] or 0)),
        "disbursement_volume": Decimal(str(realized["disbursement_volume"] or 0)),
        "nb_clients": Decimal(str(realized["nb_clients"] or 0)),
        "outstanding": Decimal(str(realized["outstanding"] or 0)),
        "healthy_outstanding": Decimal(str(realized["healthy_outstanding"] or 0)),
        "par_0": Decimal(str(realized["par_0"] or 0)),
        "par_1_30": Decimal(str(realized["par_1_30"] or 0)),
        "par_31_60": Decimal(str(realized["par_31_60"] or 0)),
        "par_30": Decimal(str(realized["par_30"] or 0)),
    }
    current_values["par_30_rate"] = _safe_ratio(current_values["par_30"], current_values["outstanding"])
    current_values["healthy_rate"] = _safe_ratio(
        current_values["healthy_outstanding"], current_values["outstanding"]
    )
    current_values["par_0_rate"] = _safe_ratio(current_values["par_0"], current_values["outstanding"])
    current_values["par_1_30_rate"] = _safe_ratio(
        current_values["par_1_30"], current_values["outstanding"]
    )
    current_values["par_31_60_rate"] = _safe_ratio(
        current_values["par_31_60"], current_values["outstanding"]
    )

    target_values = {
        "target_disbursement_count": Decimal(str(target.target_disbursement_count or 0)),
        "target_nb_clients": Decimal(str(target.target_nb_clients or 0)),
        "target_disbursement": Decimal(str(target.target_disbursement or 0)),
        "target_outstanding": Decimal(str(target.target_outstanding or 0)),
        "target_par": Decimal(str(target.target_par or 0)),
        "target_healthy_outstanding": Decimal(str(target.target_healthy_outstanding or 0)),
        "target_par_0": Decimal(str(target.target_par_0 or 0)),
        "target_par_1_30": Decimal(str(target.target_par_1_30 or 0)),
        "target_par_31_60": Decimal(str(target.target_par_31_60 or 0)),
        "target_par_30": Decimal(str(target.target_par_30 or 0)),
    }

    details: list[PortfolioCoverageRead] = []
    coverage_components: list[Decimal] = []

    def add_detail(label: str, current_key: str, target_key: str):
        target_value = target_values[target_key]
        current_value = current_values[current_key]
        if target_value <= 0:
            return
        ratio = _safe_ratio(current_value, target_value)
        details.append(
            PortfolioCoverageRead(
                label=label,
                current_value=current_value,
                target_value=target_value,
                ratio=ratio,
            )
        )
        coverage_components.append(ratio)

    add_detail("Nb decaissements", "disbursement_count", "target_disbursement_count")
    add_detail("Nb clients", "nb_clients", "target_nb_clients")
    add_detail("Volume decaisse", "disbursement_volume", "target_disbursement")
    add_detail("Encours", "outstanding", "target_outstanding")
    add_detail("Encours sain", "healthy_outstanding", "target_healthy_outstanding")

    if target_values["target_par"] > 0:
        par_ratio = max(
            Decimal("0"),
            (Decimal("1") - _safe_ratio(current_values["par_30_rate"], target_values["target_par"])),
        )
        details.append(
            PortfolioCoverageRead(
                label="Qualite PAR30",
                current_value=current_values["par_30_rate"],
                target_value=target_values["target_par"],
                ratio=par_ratio.quantize(Decimal("0.0001")),
            )
        )
        coverage_components.append(par_ratio.quantize(Decimal("0.0001")))

    coverage_ratio = (
        (sum(coverage_components) / Decimal(str(len(coverage_components)))).quantize(Decimal("0.0001"))
        if coverage_components
        else Decimal("0")
    )

    settings = get_settings()
    if not settings.bonus_module_active:
        return PortfolioDashboardRead(
            reference_month=target.month,
            reference_year=target.year,
            has_target=True,
            has_bonus_rule=False,
            coverage_ratio=coverage_ratio,
            bonus_amount=Decimal("0"),
            details=details,
            message="Module Bonus en developpement dans cet environnement de test.",
        )

    active_rule = db.scalar(
        select(BonusRule).where(BonusRule.is_active.is_(True)).order_by(BonusRule.id.desc())
    )

    bonus_amount = Decimal("0")
    has_bonus_rule = active_rule is not None
    if active_rule:
        expression = (active_rule.formula or {}).get("expression")
        if expression:
            try:
                variables = {**current_values, **target_values}
                bonus_amount = max(
                    evaluate_bonus_expression(expression, variables).quantize(Decimal("0.01")),
                    Decimal("0"),
                )
            except ValueError:
                bonus_amount = Decimal("0")

    return PortfolioDashboardRead(
        reference_month=target.month,
        reference_year=target.year,
        has_target=True,
        has_bonus_rule=has_bonus_rule,
        coverage_ratio=coverage_ratio,
        bonus_amount=bonus_amount,
        details=details,
        message=None if has_bonus_rule else "No active bonus formula configured by admin.",
    )
