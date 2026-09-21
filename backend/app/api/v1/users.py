import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, select
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, pagination, require_roles
from app.db.session import get_db
from app.models.entities import (
    Agency,
    Agent,
    BonusResult,
    Complaint,
    DailyMetric,
    PasswordSetupToken,
    RefreshToken,
    Target,
    User,
)
from app.models.enums import UserRole
from app.schemas.auth import (
    AgentAccountProvisionRead,
    AgentAccountProvisionResult,
    GpAccountBatchProvisionRequest,
    GpAccountBatchProvisionResult,
    GpAccountProvisionRequest,
    GpAccountProvisionResult,
    GpMcrAuditMissingAccountDeleteRequest,
    GpMcrAuditMissingAccountDeleteResult,
    GpMcrAuditRead,
    PasswordResetRead,
    PasswordResetRequest,
    UserAdminRead,
    UserCreate,
    UserProvisionRead,
    UserRead,
    UserStatusUpdate,
    UserUpdate,
)
from app.schemas.common import Page
from app.schemas.common import Message
from app.schemas.domain import AcmLimitConfigRead, AcmLimitConfigUpdate, LoginAuditDashboardRead
from app.services.acm_limits import get_acm_limits_payload, save_acm_limits
from app.services.agent_identity import normalized_agent_name_expression, normalized_agent_name_key
from app.services.auth_security import revoke_all_refresh_tokens
from app.services.gp_account_audit import build_gp_mcr_account_audit, delete_gp_accounts_from_mcr_audit
from app.services.login_audit import build_login_audit_dashboard
from app.services.support_audit import record_support_action
from app.services.user_accounts import _set_temporary_password, batch_provision_gp_accounts, ensure_agent_accounts, provision_single_gp_account
from app.api.v1.reports import _styled_excel_buffer, _styled_pdf_buffer

router = APIRouter(prefix="/users", tags=["users"])
logger = logging.getLogger(__name__)


def _validate_role_assignment(
    db: Session,
    role: UserRole,
    agency_id: int | None,
    agent_id: int | None,
) -> None:
    if role in {UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.SUPPORT, UserRole.COMMITTEE_MEMBER, UserRole.REGIONAL_MANAGER_NORD, UserRole.REGIONAL_MANAGER_SUD}:
        if agency_id is not None or agent_id is not None:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "invalid_role_scope",
                    "message": "agency_id and agent_id must be null for admin roles",
                },
            )
        return

    if role == UserRole.AGENCY_MANAGER:
        if agency_id is None:
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_role_scope", "message": "agency_id is required for agency manager"},
            )
        return

    if role == UserRole.PORTFOLIO_MANAGER:
        if agency_id is None or agent_id is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "invalid_role_scope",
                    "message": "agency_id and agent_id are required for portfolio manager",
                },
            )
        agent = db.get(Agent, agent_id)
        if not agent:
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_agent", "message": "Selected agent does not exist"},
            )
        if agent.agency_id != agency_id:
            raise HTTPException(
                status_code=400,
                detail={"code": "agent_agency_mismatch", "message": "Agent does not belong to selected agency"},
            )
        return

    raise HTTPException(
        status_code=400,
        detail={"code": "invalid_role_scope", "message": "Unsupported role"},
    )


def _ensure_unique_portfolio_account(
    db: Session,
    agent_id: int | None,
    *,
    exclude_user_id: int | None = None,
) -> None:
    if agent_id is None:
        return
    agent = db.get(Agent, agent_id)
    if not agent:
        return
    identity_key = normalized_agent_name_key(agent.name)
    duplicate_query = (
        select(User)
        .join(Agent, User.agent_id == Agent.id)
        .where(
            User.role == UserRole.PORTFOLIO_MANAGER,
            normalized_agent_name_expression(Agent.name) == identity_key,
        )
    )
    if exclude_user_id is not None:
        duplicate_query = duplicate_query.where(User.id != exclude_user_id)
    if db.scalar(duplicate_query.limit(1)):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "duplicate_portfolio_manager",
                "message": "Un compte Portfolio Manager existe deja pour ce GP.",
            },
        )


def _assert_support_user_target_allowed(actor: User, target: User) -> None:
    if actor.role != UserRole.SUPPORT:
        return
    if actor.id == target.id:
        raise HTTPException(
            status_code=400,
            detail={"code": "self_action_forbidden", "message": "Cette action n'est pas autorisee sur votre propre compte."},
        )
    if target.role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=403,
            detail={"code": "super_admin_protected", "message": "Le profil Support ne peut pas gerer un Super Admin."},
        )


def _assert_support_role_assignment_allowed(actor: User, role: UserRole) -> None:
    if actor.role != UserRole.SUPPORT:
        return
    if role in {UserRole.SUPER_ADMIN, UserRole.COMMITTEE_MEMBER, UserRole.REGIONAL_MANAGER_NORD, UserRole.REGIONAL_MANAGER_SUD}:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "protected_role_assignment",
                "message": "Le profil Support ne peut pas attribuer ce role.",
            },
        )


def _ensure_last_super_admin_role_preserved(db: Session, target: User, next_role: UserRole) -> None:
    if target.role != UserRole.SUPER_ADMIN or next_role == UserRole.SUPER_ADMIN:
        return
    remaining_super_admins = db.scalar(
        select(func.count(User.id)).where(
            User.role == UserRole.SUPER_ADMIN,
            User.id != target.id,
        )
    ) or 0
    if remaining_super_admins == 0:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "last_super_admin_protected",
                "message": "Le dernier Super Admin du systeme ne peut pas perdre ce role.",
            },
        )


def _ensure_last_active_super_admin_preserved(db: Session, target: User, next_is_active: bool) -> None:
    if target.role != UserRole.SUPER_ADMIN or next_is_active or not target.is_active:
        return
    remaining_active_super_admins = db.scalar(
        select(func.count(User.id)).where(
            User.role == UserRole.SUPER_ADMIN,
            User.is_active.is_(True),
            User.id != target.id,
        )
    ) or 0
    if remaining_active_super_admins == 0:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "last_active_super_admin_protected",
                "message": "Le dernier Super Admin actif du systeme ne peut pas etre desactive.",
            },
        )


def _ensure_last_super_admin_not_deleted(db: Session, target: User) -> None:
    if target.role != UserRole.SUPER_ADMIN:
        return
    remaining_super_admins = db.scalar(
        select(func.count(User.id)).where(
            User.role == UserRole.SUPER_ADMIN,
            User.id != target.id,
        )
    ) or 0
    if remaining_super_admins == 0:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "last_super_admin_protected",
                "message": "Le dernier Super Admin du systeme ne peut pas etre supprime.",
            },
        )


def _serialize_user_for_admin_view(actor: User, item: User) -> UserAdminRead:
    payload = UserAdminRead.model_validate(item)
    if actor.role == UserRole.SUPPORT:
        payload.temporary_password = None
    return payload


@router.get(
    "",
    response_model=Page[UserAdminRead],
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.SUPPORT]))],
)
def list_users(
    page: tuple[int, int] = Depends(pagination),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    limit, offset = page
    items = db.scalars(
        select(User).order_by(User.is_active.desc(), User.id.desc()).limit(limit).offset(offset)
    ).all()
    return Page(
        items=[_serialize_user_for_admin_view(actor, item) for item in items],
        total=db.scalar(select(func.count(User.id))) or 0,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/gp-mcr-audit",
    response_model=GpMcrAuditRead,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.SUPPORT]))],
)
def get_gp_mcr_audit(db: Session = Depends(get_db)):
    return build_gp_mcr_account_audit(db)


@router.delete(
    "/gp-mcr-audit/missing-accounts",
    response_model=GpMcrAuditMissingAccountDeleteResult,
    status_code=200,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.SUPPORT]))],
)
def delete_missing_gp_mcr_accounts(
    payload: GpMcrAuditMissingAccountDeleteRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    if not payload.account_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "gp_mcr_no_selection",
                "message": "Aucun compte selectionne pour la suppression.",
            },
        )
    return delete_gp_accounts_from_mcr_audit(
        db, actor, account_ids=payload.account_ids
    )


@router.get(
    "/acm-limits",
    response_model=AcmLimitConfigRead,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.AGENCY_MANAGER, UserRole.PORTFOLIO_MANAGER, UserRole.SUPPORT]))],
)
def get_acm_limits(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return get_acm_limits_payload(db)


@router.put(
    "/acm-limits",
    response_model=AcmLimitConfigRead,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN]))],
)
def update_acm_limits(
    payload: AcmLimitConfigUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    result = save_acm_limits(db, payload, actor.id)
    db.commit()
    return result


@router.get(
    "/login-audit",
    response_model=LoginAuditDashboardRead,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.SUPPORT]))],
)
def get_login_audit(
    user_id: int | None = None,
    role: UserRole | None = Query(default=None),
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    return build_login_audit_dashboard(
        db,
        user_id=user_id,
        role=role,
        date_from=date_from,
        date_to=date_to,
    )


def _login_audit_export_columns():
    return [
        ("full_name", "UTILISATEUR", "text"),
        ("email", "EMAIL", "text"),
        ("role", "ROLE", "text"),
        ("login_date", "DATE", "date"),
        ("login_hour", "HEURE", "text"),
        ("ip_address", "ADRESSE IP", "text"),
        ("user_agent", "USER AGENT", "text"),
        ("connection_count", "NB CONNEXIONS", "int"),
    ]


def _login_audit_export_payload(
    db: Session,
    *,
    user_id: int | None,
    role: UserRole | None,
    date_from: date | None,
    date_to: date | None,
):
    dashboard = build_login_audit_dashboard(
        db,
        user_id=user_id,
        role=role,
        date_from=date_from,
        date_to=date_to,
    )
    rows = []
    for row in dashboard["rows"]:
        rows.append(
            {
                **row,
                "role": row["role"].value if hasattr(row["role"], "value") else str(row["role"]),
            }
        )
    subtitle_parts = [f"Total connexions: {dashboard['total_connections']}"]
    if user_id:
        subtitle_parts.append(f"Utilisateur #{user_id}")
    if role:
        subtitle_parts.append(f"Role: {role.value}")
    if date_from or date_to:
        subtitle_parts.append(f"Periode: {date_from or '-'} -> {date_to or '-'}")
    return " | ".join(subtitle_parts), rows


@router.get(
    "/login-audit.xlsx",
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.SUPPORT]))],
)
def export_login_audit_excel(
    user_id: int | None = None,
    role: UserRole | None = Query(default=None),
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    subtitle, rows = _login_audit_export_payload(
        db,
        user_id=user_id,
        role=role,
        date_from=date_from,
        date_to=date_to,
    )
    buffer = _styled_excel_buffer(
        title="MicroCred - Audit des connexions",
        subtitle=subtitle,
        columns=_login_audit_export_columns(),
        rows=rows,
    )
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=login_audit.xlsx"},
    )


@router.get(
    "/login-audit.pdf",
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.SUPPORT]))],
)
def export_login_audit_pdf(
    user_id: int | None = None,
    role: UserRole | None = Query(default=None),
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    subtitle, rows = _login_audit_export_payload(
        db,
        user_id=user_id,
        role=role,
        date_from=date_from,
        date_to=date_to,
    )
    buffer = _styled_pdf_buffer(
        title="MicroCred - Audit des connexions",
        subtitle=subtitle,
        columns=_login_audit_export_columns(),
        rows=rows,
    )
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=login_audit.pdf"},
    )


@router.post(
    "",
    response_model=UserProvisionRead,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.SUPPORT]))],
)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    request: Request = None,
):
    _assert_support_role_assignment_allowed(actor, payload.role)
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status_code=409, detail={"code": "duplicate_user", "message": "Email already exists"})
    if payload.agency_id is not None and not db.get(Agency, payload.agency_id):
        raise HTTPException(status_code=400, detail={"code": "invalid_agency", "message": "Agency not found"})
    _validate_role_assignment(db, payload.role, payload.agency_id, payload.agent_id)
    if payload.role == UserRole.PORTFOLIO_MANAGER:
        _ensure_unique_portfolio_account(db, payload.agent_id)
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        role=payload.role,
        agency_id=payload.agency_id,
        agent_id=payload.agent_id,
        hashed_password="",
        is_active=True,
        must_change_password=True,
    )
    if payload.role == UserRole.PORTFOLIO_MANAGER:
        temporary_password = _set_temporary_password(user)
        generated_password = True
    else:
        if not payload.initial_password:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "initial_password_required",
                    "message": "Le mot de passe initial est obligatoire pour ce profil.",
                },
            )
        temporary_password = _set_temporary_password(user, payload.initial_password)
        generated_password = False
    db.add(user)
    db.commit()
    db.refresh(user)
    record_support_action(
        db,
        actor=actor,
        action="user_create",
        result="success",
        request=request,
        target_type="user",
        target_id=str(user.id),
        target_label=user.email,
        details={"role": user.role.value},
    )
    db.commit()
    return UserProvisionRead(
        user=UserRead.model_validate(user),
        temporary_password=temporary_password if actor.role == UserRole.SUPER_ADMIN else None,
        generated_password=generated_password,
    )


@router.put(
    "/{user_id}",
    response_model=UserRead,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.SUPPORT]))],
)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    request: Request = None,
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "User not found"})
    _assert_support_user_target_allowed(actor, user)
    data = payload.model_dump(exclude_unset=True)
    if actor.role == UserRole.SUPPORT and actor.id == user.id and "role" in data and data["role"] != user.role:
        raise HTTPException(
            status_code=400,
            detail={"code": "self_role_change_forbidden", "message": "Le profil Support ne peut pas modifier son propre role."},
        )
    if "email" in data and data["email"] != user.email:
        if db.scalar(select(User).where(User.email == data["email"], User.id != user_id)):
            raise HTTPException(status_code=409, detail={"code": "duplicate_user", "message": "Email already exists"})
    next_role = data.get("role", user.role)
    next_agency_id = data.get("agency_id", user.agency_id)
    next_agent_id = data.get("agent_id", user.agent_id)
    next_is_active = data.get("is_active", user.is_active)
    _assert_support_role_assignment_allowed(actor, next_role)
    _ensure_last_super_admin_role_preserved(db, user, next_role)
    _ensure_last_active_super_admin_preserved(db, user, next_is_active)
    if next_agency_id is not None and not db.get(Agency, next_agency_id):
        raise HTTPException(status_code=400, detail={"code": "invalid_agency", "message": "Agency not found"})
    _validate_role_assignment(db, next_role, next_agency_id, next_agent_id)
    if next_role == UserRole.PORTFOLIO_MANAGER:
        _ensure_unique_portfolio_account(db, next_agent_id, exclude_user_id=user_id)
    for key, value in data.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    record_support_action(
        db,
        actor=actor,
        action="user_update",
        result="success",
        request=request,
        target_type="user",
        target_id=str(user.id),
        target_label=user.email,
        details={"updated_fields": sorted(data.keys())},
    )
    db.commit()
    return user


@router.delete(
    "/{user_id}",
    response_model=Message,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.SUPPORT]))],
)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    request: Request = None,
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "User not found"})
    _assert_support_user_target_allowed(actor, user)
    if actor.id == user.id:
        raise HTTPException(
            status_code=400,
            detail={"code": "self_delete_forbidden", "message": "Cannot delete your own account"},
        )
    _ensure_last_super_admin_not_deleted(db, user)
    agent_id_to_delete = user.agent_id if user.role == UserRole.PORTFOLIO_MANAGER else None
    db.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))
    db.execute(
        delete(PasswordSetupToken).where(
            (PasswordSetupToken.user_id == user.id)
            | (PasswordSetupToken.issued_by_user_id == user.id)
        )
    )
    db.execute(delete(BonusResult).where(BonusResult.user_id == user.id))
    db.execute(delete(Complaint).where(Complaint.user_id == user.id))
    db.delete(user)
    db.flush()

    deleted_agent_id = None
    if agent_id_to_delete is not None:
        remaining_agent_users = (
            db.scalar(select(func.count(User.id)).where(User.agent_id == agent_id_to_delete))
            or 0
        )
        if remaining_agent_users == 0:
            db.execute(delete(DailyMetric).where(DailyMetric.agent_id == agent_id_to_delete))
            db.execute(delete(Target).where(Target.agent_id == agent_id_to_delete))
            agent = db.get(Agent, agent_id_to_delete)
            if agent:
                db.delete(agent)
                deleted_agent_id = agent_id_to_delete
    record_support_action(
        db,
        actor=actor,
        action="user_delete",
        result="success",
        request=request,
        target_type="user",
        target_id=str(user_id),
        target_label=user.email,
        details={"deleted_agent_id": deleted_agent_id},
    )
    db.commit()
    logger.info(
        "User account deleted actor_id=%s actor_role=%s deleted_user_id=%s deleted_agent_id=%s",
        actor.id,
        actor.role.value,
        user_id,
        deleted_agent_id,
    )
    return Message(message="Utilisateur supprime definitivement.")


@router.patch(
    "/{user_id}/status",
    response_model=UserRead,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.SUPPORT]))],
)
def set_user_status(
    user_id: int,
    payload: UserStatusUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    request: Request = None,
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "User not found"})
    _assert_support_user_target_allowed(actor, user)
    if actor.id == user.id:
        raise HTTPException(
            status_code=400,
            detail={"code": "self_status_forbidden", "message": "Cannot change your own active status"},
        )
    _ensure_last_active_super_admin_preserved(db, user, payload.is_active)
    user.is_active = payload.is_active
    record_support_action(
        db,
        actor=actor,
        action="user_status_update",
        result="success",
        request=request,
        target_type="user",
        target_id=str(user.id),
        target_label=user.email,
        details={"is_active": payload.is_active},
    )
    db.commit()
    db.refresh(user)
    return user


@router.post(
    "/auto-create-agents",
    response_model=AgentAccountProvisionResult,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.SUPPORT]))],
)
def auto_create_agent_users(
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    request: Request = None,
):
    accounts = ensure_agent_accounts(db, issue_credentials=True)
    if actor.role == UserRole.SUPPORT:
        accounts = [{**account, "temporary_password": None} for account in accounts]
    record_support_action(
        db,
        actor=actor,
        action="auto_create_agent_users",
        result="success",
        request=request,
        target_type="batch",
        target_label="portfolio_manager_accounts",
        details={"provisioned_count": len(accounts)},
    )
    db.commit()
    return AgentAccountProvisionResult(
        accounts=accounts,
        created_count=sum(1 for account in accounts if account.get("created")),
        provisioned_count=len(accounts),
    )


@router.post(
    "/gp-mcr-audit/provision-account",
    response_model=GpAccountProvisionResult,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.SUPPORT]))],
)
def provision_single_gp_account_endpoint(
    payload: GpAccountProvisionRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    request: Request = None,
):
    result = provision_single_gp_account(db, payload.agent_name, issue_credentials=True)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "gp_account_not_found",
                "message": f"Aucun compte GP correspondant a ete trouve pour l'agent '{payload.agent_name}'.",
            },
        )
    account = AgentAccountProvisionRead(
        user_id=result["user_id"],
        email=result["email"],
        full_name=result["full_name"],
        agent_id=result["agent_id"],
        agency_id=result["agency_id"],
        temporary_password=result["temporary_password"] if actor.role != UserRole.SUPPORT else None,
        created=result["created"],
    )
    record_support_action(
        db,
        actor=actor,
        action="provision_gp_account",
        result="success",
        request=request,
        target_type="agent",
        target_label=payload.agent_name,
        details={"user_id": result["user_id"], "created": result["created"]},
    )
    db.commit()
    return GpAccountProvisionResult(
        account=account,
        created=result["created"],
        provisionned=True,
        temporary_password=account.temporary_password,
    )


@router.post(
    "/gp-mcr-audit/provision-accounts",
    response_model=GpAccountBatchProvisionResult,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.SUPPORT]))],
)
def batch_provision_gp_accounts_endpoint(
    payload: GpAccountBatchProvisionRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    request: Request = None,
):
    result = batch_provision_gp_accounts(db, payload.agent_names, issue_credentials=True)
    accounts = []
    for account_data in result["accounts"]:
        accounts.append(
            AgentAccountProvisionRead(
                user_id=account_data["user_id"],
                email=account_data["email"],
                full_name=account_data["full_name"],
                agent_id=account_data["agent_id"],
                agency_id=account_data["agency_id"],
                temporary_password=account_data["temporary_password"] if actor.role != UserRole.SUPPORT else None,
                created=account_data["created"],
            )
        )
    record_support_action(
        db,
        actor=actor,
        action="provision_gp_accounts_batch",
        result="success",
        request=request,
        target_type="agent_batch",
        target_label=f"{len(result['accounts'])} accounts",
        details={"provisioned_count": len(accounts), "skipped_count": result["skipped_count"]},
    )
    db.commit()
    return GpAccountBatchProvisionResult(
        accounts=accounts,
        created_count=result["created_count"],
        provisioned_count=result["provisioned_count"],
        skipped_count=result["skipped_count"],
        skipped_agent_names=result["skipped_agent_names"],
    )


@router.post(
    "/{user_id}/reset-password",
    response_model=PasswordResetRead,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.SUPPORT]))],
)
def reset_user_password(
    user_id: int,
    payload: PasswordResetRequest | None = None,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    request: Request = None,
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "User not found"})
    _assert_support_user_target_allowed(actor, user)
    if actor.id == user.id:
        raise HTTPException(
            status_code=400,
            detail={"code": "self_reset_forbidden", "message": "Cannot reset your own password from this screen"},
        )
    temporary_password = _set_temporary_password(user, payload.temporary_password if payload else None)
    revoke_all_refresh_tokens(db, user.id)
    record_support_action(
        db,
        actor=actor,
        action="password_reset",
        result="success",
        request=request,
        target_type="user",
        target_id=str(user.id),
        target_label=user.email,
        details={"generated_password": not bool(payload and payload.temporary_password)},
    )
    db.commit()
    db.refresh(user)
    return PasswordResetRead(
        user=UserRead.model_validate(user),
        temporary_password=temporary_password if actor.role == UserRole.SUPER_ADMIN else None,
        generated_password=not bool(payload and payload.temporary_password),
    )
