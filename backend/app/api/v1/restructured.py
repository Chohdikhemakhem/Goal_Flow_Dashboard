from __future__ import annotations

from datetime import date, datetime, timezone
import json
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, pagination, require_roles
from app.db.session import get_db
from app.models.entities import User
from app.models.enums import UserRole
from app.schemas.common import Message, Page
from app.schemas.domain import MetricsChartRead
from app.schemas.restructured import (
    RestructuredChartRead,
    RestructuredContractDetailRead,
    RestructuredDashboardKpiRead,
    RestructuredMissingMcrContractDeleteRequest,
    RestructuredMissingMcrContractDeleteResult,
    RestructuredMissingMcrContractRead,
)
from app.services.restructured_dashboard import (
    build_restructured_contracts_export,
    build_restructured_missing_from_mcr_export,
    get_restructured_consecutive_chart,
    get_restructured_dashboard_kpis,
    get_restructured_quality_chart,
    list_restructured_contracts_missing_from_mcr,
    list_restructured_contracts,
    delete_contracts_from_missing_mcr,
)

router = APIRouter(prefix="/credits-restructures", tags=["credits-restructures"])
logger = logging.getLogger(__name__)


def _family_param(family: str | None) -> str:
    if str(family or "").lower() == "all":
        return "all"
    return "consolidated" if str(family or "").lower() == "consolidated" else "restructured"


def _parse_table_filters(raw_value: str | None) -> dict:
    if not raw_value:
        return {}
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError("Filtres de la table invalides.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Filtres de la table invalides.")
    return payload


@router.get(
    "/kpis",
    response_model=RestructuredDashboardKpiRead,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.COMMITTEE_MEMBER, UserRole.AGENCY_MANAGER, UserRole.PORTFOLIO_MANAGER, UserRole.REGIONAL_MANAGER_NORD, UserRole.REGIONAL_MANAGER_SUD]))],
)
def restructured_kpis(
    family: str = Query(default="restructured"),
    agency_id: str | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    snapshot_batch_ids: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return get_restructured_dashboard_kpis(
        db,
        user,
        family=_family_param(family),
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_batch_ids=snapshot_batch_ids,
    )


@router.get(
    "/charts/quality-by-agency",
    response_model=MetricsChartRead,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.COMMITTEE_MEMBER, UserRole.AGENCY_MANAGER, UserRole.PORTFOLIO_MANAGER, UserRole.REGIONAL_MANAGER_NORD, UserRole.REGIONAL_MANAGER_SUD]))],
)
def restructured_quality_chart(
    family: str = Query(default="restructured"),
    agency_id: str | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    snapshot_batch_ids: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return get_restructured_quality_chart(
        db,
        user,
        family=_family_param(family),
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_batch_ids=snapshot_batch_ids,
    )


@router.get(
    "/charts/repartition-consecutives",
    response_model=RestructuredChartRead,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.COMMITTEE_MEMBER, UserRole.AGENCY_MANAGER, UserRole.PORTFOLIO_MANAGER, UserRole.REGIONAL_MANAGER_NORD, UserRole.REGIONAL_MANAGER_SUD]))],
)
def restructured_consecutive_chart(
    family: str = Query(default="restructured"),
    agency_id: str | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    snapshot_batch_ids: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return get_restructured_consecutive_chart(
        db,
        user,
        family=_family_param(family),
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_batch_ids=snapshot_batch_ids,
    )


@router.get(
    "/contrats",
    response_model=Page[RestructuredContractDetailRead],
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.COMMITTEE_MEMBER, UserRole.AGENCY_MANAGER, UserRole.PORTFOLIO_MANAGER, UserRole.REGIONAL_MANAGER_NORD, UserRole.REGIONAL_MANAGER_SUD]))],
)
def restructured_contracts(
    family: str = Query(default="restructured"),
    agency_id: str | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    snapshot_batch_ids: str | None = None,
    q: str | None = Query(default=None, min_length=1),
    closure_status: str | None = None,
    consecutive_bucket: str | None = None,
    anomaly: str | None = None,
    paid_last_four: str | None = None,
    sort_key: str | None = None,
    sort_direction: str | None = None,
    page: tuple[int, int] = Depends(pagination),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    limit, offset = page
    return list_restructured_contracts(
        db,
        user,
        family=_family_param(family),
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_batch_ids=snapshot_batch_ids,
        q=q,
        closure_status=closure_status,
        consecutive_bucket=consecutive_bucket,
        anomaly=anomaly,
        paid_last_four=paid_last_four,
        sort_key=sort_key,
        sort_direction=sort_direction,
        limit=limit,
        offset=offset,
    )


@router.get("/absents-mcr", response_model=Page[RestructuredMissingMcrContractRead])
def restructured_missing_from_mcr(
    family: str = Query(default="restructured"),
    agency_id: str | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    snapshot_batch_ids: str | None = None,
    q: str | None = Query(default=None, min_length=1),
    table_filters: str | None = None,
    sort_key: str | None = None,
    sort_direction: str | None = None,
    page: tuple[int, int] = Depends(pagination),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    limit, offset = page
    parsed_table_filters = _parse_table_filters(table_filters)
    return list_restructured_contracts_missing_from_mcr(
        db,
        user,
        family=_family_param(family),
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_batch_ids=snapshot_batch_ids,
        q=q,
        table_filters=parsed_table_filters,
        sort_key=sort_key,
        sort_direction=sort_direction,
        limit=limit,
        offset=offset,
    )


@router.delete(
    "/absents-mcr/contracts",
    response_model=RestructuredMissingMcrContractDeleteResult,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.SUPPORT]))],
)
def delete_missing_mcr_contracts(
    payload: RestructuredMissingMcrContractDeleteRequest,
    family: str = Query(default="all"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RestructuredMissingMcrContractDeleteResult:
    """Soft-exclude the given contracts from the
    "Contrats absents du MCR" diagnostic view.

    Restrictions enforced by the service layer:
    - Each ``contract_no`` MUST currently appear in the "missing from MCR"
      view (otherwise it is reported in ``skipped_contract_nos``).
    - The official restructured contracts list is NEVER modified: only the
      ``excluded_from_missing_mcr_at`` timestamp is set, so the action is
      fully reversible.

    Access is restricted to the same roles that operate the Importation
    module (SUPER_ADMIN, SUPPORT).
    """
    if not payload.contract_nos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "missing_mcr_no_selection",
                "message": "Aucun contrat selectionne pour la suppression.",
            },
        )
    return delete_contracts_from_missing_mcr(
        db,
        user,
        contract_nos=payload.contract_nos,
        family=_family_param(family),
    )


@router.get(
    "/contrats/export.xlsx",
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.COMMITTEE_MEMBER, UserRole.AGENCY_MANAGER, UserRole.PORTFOLIO_MANAGER, UserRole.REGIONAL_MANAGER_NORD, UserRole.REGIONAL_MANAGER_SUD]))],
)
def export_restructured_contracts_excel(
    family: str = Query(default="restructured"),
    agency_id: str | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    snapshot_batch_ids: str | None = None,
    q: str | None = Query(default=None, min_length=1),
    closure_status: str | None = None,
    consecutive_bucket: str | None = None,
    anomaly: str | None = None,
    paid_last_four: str | None = None,
    sort_key: str | None = None,
    sort_direction: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    family_value = _family_param(family)
    logger.info(
        "restructured_contracts_export_endpoint family=%s role=%s agency_id=%s agent_id=%s date_from=%s date_to=%s snapshots=%s q=%s sort_key=%s sort_direction=%s",
        family_value,
        getattr(user, "role", None),
        agency_id,
        agent_id,
        date_from,
        date_to,
        snapshot_batch_ids,
        q,
        sort_key,
        sort_direction,
    )
    buffer = build_restructured_contracts_export(
        db,
        user,
        family=family_value,
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_batch_ids=snapshot_batch_ids,
        q=q,
        closure_status=closure_status,
        consecutive_bucket=consecutive_bucket,
        anomaly=anomaly,
        paid_last_four=paid_last_four,
        sort_key=sort_key,
        sort_direction=sort_direction,
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    prefix = "detail_contrats_consolides" if family_value == "consolidated" else "detail_contrats_restructures"
    file_name = quote(f"{prefix}_{timestamp}.xlsx")
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{file_name}"},
    )


@router.get("/absents-mcr/export.xlsx")
def export_restructured_missing_from_mcr_excel(
    family: str = Query(default="restructured"),
    agency_id: str | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    snapshot_batch_ids: str | None = None,
    q: str | None = Query(default=None, min_length=1),
    table_filters: str | None = None,
    sort_key: str | None = None,
    sort_direction: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    family_value = _family_param(family)
    parsed_table_filters = _parse_table_filters(table_filters)
    buffer = build_restructured_missing_from_mcr_export(
        db,
        user,
        family=family_value,
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_batch_ids=snapshot_batch_ids,
        q=q,
        table_filters=parsed_table_filters,
        sort_key=sort_key,
        sort_direction=sort_direction,
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    prefix = (
        "contrats_absents_mcr"
        if family_value == "all"
        else
        "contrats_consolides_absents_mcr"
        if family_value == "consolidated"
        else "contrats_restructures_absents_mcr"
    )
    file_name = quote(f"{prefix}_{timestamp}.xlsx")
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{file_name}"},
    )
