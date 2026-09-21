from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from datetime import date, datetime
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, pagination, require_roles
from app.db.session import get_db
from app.models.entities import Agency, Agent, Target, User
from app.models.enums import TargetType, UserRole
from app.schemas.common import Message, Page
from app.schemas.domain import TargetCreate, TargetRead, TargetUpdate
from app.services.objective_excel_import import (
    MAX_OBJECTIVES_EXCEL_BYTES,
    build_objective_import_preview,
    import_objectives,
)
from app.services.objective_active_period import calculate_active_period
from app.services.data_scope import get_user_data_scope, region_scope_condition

router = APIRouter(
    prefix="/targets",
    tags=["targets"],
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.AGENCY_MANAGER, UserRole.PORTFOLIO_MANAGER, UserRole.REGIONAL_MANAGER_NORD, UserRole.REGIONAL_MANAGER_SUD]))],
)


def _ensure_objective_excel_import_permission(user: User) -> None:
    """Agency objectives are manually writable by Super Admin only."""
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "forbidden", "message": "Seul le Super Admin peut importer des objectifs agence"},
        )


async def _read_objectives_excel(file: UploadFile) -> tuple[bytes, str]:
    filename = file.filename or ""
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_file", "message": "Format non autorisé : utilisez un fichier Excel .xlsx"},
        )
    content = await file.read(MAX_OBJECTIVES_EXCEL_BYTES + 1)
    if len(content) > MAX_OBJECTIVES_EXCEL_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "file_too_large", "message": "Le fichier Excel dépasse la taille maximale autorisée (10 Mo)"},
        )
    return content, filename


def _apply_user_scope(user: User, filters: list):
    scope = get_user_data_scope(user)
    regional_condition = region_scope_condition(Agency.name, scope.region)
    if regional_condition is not None:
        filters.append(regional_condition)
    if scope.agency_id is not None:
        filters.append(Target.agency_id == scope.agency_id)
    if scope.agent_id is not None:
        filters.append(Target.agent_id == scope.agent_id)


def _validate_agent_scope(db: Session, payload: TargetCreate | TargetUpdate) -> None:
    if payload.target_type == TargetType.AGENT and payload.agent_id is not None:
        agent = db.get(Agent, payload.agent_id)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid_agent", "message": "Selected agent does not exist"},
            )
        if agent.agency_id != payload.agency_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "agent_agency_mismatch",
                    "message": "Selected agent does not belong to selected agency",
                },
            )


def _ensure_target_write_permission(user: User, payload: TargetCreate | TargetUpdate) -> None:
    if user.role == UserRole.SUPER_ADMIN:
        if payload.target_type == TargetType.AGENCY:
            if payload.active_from is None or payload.active_until is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "active_period_required", "message": "Active period is required for agency objectives"})
        return

    if user.role == UserRole.AGENCY_MANAGER:
        if user.agency_id is None or payload.target_type != TargetType.AGENT or payload.agency_id != user.agency_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "agency_scope_violation", "message": "Cannot manage objectives outside your agency"})
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "forbidden",
            "message": "This role has read-only access to objectives",
        },
    )


def _apply_default_active_period(
    payload: TargetCreate | TargetUpdate,
    reference_date: date | None = None,
) -> TargetCreate | TargetUpdate:
    """Set the automatic period for a new agency objective when omitted.

    Explicit values are left intact so the existing Super Admin edit capability
    remains available.  Existing objectives are never passed through this
    helper by the update route.
    """
    resolved = payload.model_copy(deep=True)
    if (
        resolved.target_type == TargetType.AGENCY
        and resolved.active_from is None
        and resolved.active_until is None
    ):
        resolved.active_from, resolved.active_until = calculate_active_period(reference_date)
    return resolved


def _ensure_target_mutation_scope(user: User, target: Target) -> None:
    if user.role == UserRole.SUPER_ADMIN:
        return

    if user.role == UserRole.AGENCY_MANAGER:
        if user.agency_id is None or target.agency_id != user.agency_id or target.target_type != TargetType.AGENT:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "agency_scope_violation", "message": "Cannot modify objectives outside your agency"})
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "forbidden",
            "message": "This role has read-only access to objectives",
        },
    )


def _ensure_target_read_permission(user: User) -> None:
    if user.role == UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "forbidden", "message": "Admin profile has no access to objectifs module"})


def _duplicate_condition(payload: TargetCreate | TargetUpdate):
    if payload.target_type == TargetType.AGENT:
        return and_(
            Target.target_type == TargetType.AGENT,
            Target.agency_id == payload.agency_id,
            Target.agent_id == payload.agent_id,
            Target.month == payload.month,
            Target.year == payload.year,
        )
    return and_(
        Target.target_type == TargetType.AGENCY,
        Target.agency_id == payload.agency_id,
        Target.month == payload.month,
        Target.year == payload.year,
    )


def _resolve_agency_target_period(
    db: Session,
    payload: TargetCreate | TargetUpdate,
    current_target: Target | None = None,
) -> TargetCreate | TargetUpdate:
    resolved = payload.model_copy(deep=True)
    if resolved.target_type != TargetType.AGENT:
        return resolved

    agency_period_source = db.scalar(
        select(Target)
        .where(
            Target.target_type == TargetType.AGENCY,
            Target.agency_id == resolved.agency_id,
            Target.month == resolved.month,
            Target.year == resolved.year,
        )
        .order_by(Target.id.desc())
        .limit(1)
    )
    if agency_period_source is not None:
        resolved.active_from = agency_period_source.active_from
        resolved.active_until = agency_period_source.active_until
    elif current_target is not None:
        resolved.active_from = current_target.active_from
        resolved.active_until = current_target.active_until

    return resolved


@router.get("", response_model=Page[TargetRead])
def list_targets(
    target_type: TargetType | None = None,
    agency_id: int | None = None,
    agent_id: int | None = None,
    month: int | None = None,
    year: int | None = None,
    page: tuple[int, int] = Depends(pagination),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ensure_target_read_permission(user)
    limit, offset = page
    query = select(Target).join(Agency, Agency.id == Target.agency_id).options(
        joinedload(Target.agency),
        joinedload(Target.agent),
        joinedload(Target.created_by_user),
        joinedload(Target.updated_by_user),
    )
    count_query = select(func.count(Target.id)).select_from(Target).join(Agency, Agency.id == Target.agency_id)
    filters = []
    _apply_user_scope(user, filters)
    if target_type:
        filters.append(Target.target_type == target_type)
    if agency_id:
        filters.append(Target.agency_id == agency_id)
    if agent_id:
        filters.append(Target.agent_id == agent_id)
    if month:
        filters.append(Target.month == month)
    if year:
        filters.append(Target.year == year)
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)

    query = query.order_by(Target.year.desc(), Target.month.desc(), Target.id.desc())
    return Page(
        items=db.scalars(query.limit(limit).offset(offset)).all(),
        total=db.scalar(count_query) or 0,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=TargetRead)
def create_target(
    payload: TargetCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    resolved_payload = _apply_default_active_period(payload)
    _ensure_target_write_permission(user, resolved_payload)
    resolved_payload = _resolve_agency_target_period(db, resolved_payload)
    _validate_agent_scope(db, resolved_payload)

    duplicate = db.scalar(select(Target).where(_duplicate_condition(resolved_payload)))
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "target_duplicate",
                "message": "An objective already exists for this type, scope, and period",
            },
        )

    target = Target(**resolved_payload.model_dump())
    target.created_by = user.id
    target.created_at = datetime.now()
    db.add(target)
    db.commit()
    db.refresh(target)
    return target


@router.post("/import/preview")
async def preview_objectives_excel_import(
    file: UploadFile = File(...),
    month: int | None = Form(default=None),
    year: int | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ensure_objective_excel_import_permission(user)
    content, filename = await _read_objectives_excel(file)
    try:
        return build_objective_import_preview(db, content, filename, month, year)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "objectives_excel_validation_error", "message": str(exc)},
        ) from exc


@router.post("/import/confirm")
async def confirm_objectives_excel_import(
    file: UploadFile = File(...),
    mode: str = Form(...),
    month: int | None = Form(default=None),
    year: int | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ensure_objective_excel_import_permission(user)
    content, filename = await _read_objectives_excel(file)
    try:
        return import_objectives(db, content, filename, user, mode, month, year)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "objectives_excel_import_error", "message": str(exc)},
        ) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "objectives_excel_import_failed",
                "message": "L'import a échoué. Aucun objectif n'a été modifié.",
            },
        ) from exc


@router.put("/{target_id}", response_model=TargetRead)
def update_target(
    target_id: int,
    payload: TargetUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    target = db.get(Target, target_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "Target not found"},
        )

    _ensure_target_mutation_scope(user, target)
    _ensure_target_write_permission(user, payload)
    resolved_payload = _resolve_agency_target_period(db, payload, current_target=target)
    _validate_agent_scope(db, resolved_payload)
    duplicate = db.scalar(
        select(Target).where(_duplicate_condition(resolved_payload), Target.id != target_id)
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "target_duplicate",
                "message": "An objective already exists for this type, scope, and period",
            },
        )

    for key, value in resolved_payload.model_dump().items():
        setattr(target, key, value)
    target.updated_by = user.id
    target.updated_at = datetime.now()
    db.commit()
    db.refresh(target)
    return target


@router.delete("/{target_id}", response_model=Message)
def delete_target(
    target_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    target = db.get(Target, target_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "Target not found"},
        )
    _ensure_target_mutation_scope(user, target)
    db.delete(target)
    db.commit()
    return Message(message="Target deleted")
