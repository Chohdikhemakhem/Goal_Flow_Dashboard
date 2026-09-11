from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, select, update, delete
from sqlalchemy.orm import Session

from app.models.entities import ImportBatch, LoanRaw, User, RefreshToken, PasswordSetupToken, BonusResult, Complaint
from app.models.enums import UserRole
from app.services.agent_identity import normalized_agent_name_key


def _latest_import_batch(db: Session) -> ImportBatch | None:
    return db.scalar(
        select(ImportBatch)
        .order_by(ImportBatch.imported_at.desc(), ImportBatch.id.desc())
        .limit(1)
    )


def _portfolio_identity_key(user: User) -> str:
    if user.agent and user.agent.name:
        return normalized_agent_name_key(user.agent.name)
    return normalized_agent_name_key(user.full_name)


def _portfolio_status(user: User | None) -> str:
    if user is None:
        return "Compte absent"
    if user.temporary_password:
        return "Mot de passe provisoire disponible"
    if user.must_change_password and not user.password_changed_at:
        return "Compte cree sans mot de passe provisoire"
    if user.must_change_password:
        return "Changement de mot de passe obligatoire"
    if not user.is_active:
        return "Compte inactif"
    return "Compte actif"


def _requires_provisioning(user: User | None) -> bool:
    if user is None:
        return True
    return bool(user.must_change_password and not user.temporary_password)


def build_gp_mcr_account_audit(
    db: Session,
    *,
    import_batch: ImportBatch | None = None,
) -> dict:
    batch = import_batch or _latest_import_batch(db)
    if batch is None:
        return {
            "import_batch": None,
            "new_gp_without_accounts": [],
            "existing_accounts_not_in_mcr": [],
        }

    imported_gp_rows = db.execute(
        select(
            LoanRaw.agent_name,
            LoanRaw.agency_name,
            func.count(LoanRaw.id).label("loan_count"),
        )
        .where(LoanRaw.import_batch_id == batch.id)
        .group_by(LoanRaw.agent_name, LoanRaw.agency_name)
        .order_by(LoanRaw.agent_name.asc(), LoanRaw.agency_name.asc())
    ).all()

    imported_gps: dict[str, dict] = {}
    for agent_name, agency_name, loan_count in imported_gp_rows:
        key = normalized_agent_name_key(agent_name)
        if not key:
            continue
        entry = imported_gps.setdefault(
            key,
            {
                "agent_name": agent_name,
                "agency_names": set(),
                "loan_count": 0,
            },
        )
        if agency_name:
            entry["agency_names"].add(agency_name)
        entry["loan_count"] += int(loan_count or 0)

    users_by_key: dict[str, list[User]] = defaultdict(list)
    for user in db.scalars(
        select(User)
        .where(
            User.role == UserRole.PORTFOLIO_MANAGER,
            User.excluded_from_gp_mcr_audit_at.is_(None),
        )
        .order_by(User.id.asc())
    ).all():
        key = _portfolio_identity_key(user)
        if key:
            users_by_key[key].append(user)

    primary_user_by_key: dict[str, User] = {
        key: sorted(
            users,
            key=lambda user: (
                bool(user.must_change_password and not user.temporary_password),
                not bool(user.is_active),
                user.id,
            ),
        )[0]
        for key, users in users_by_key.items()
    }

    new_gp_without_accounts = []
    for key, imported in sorted(imported_gps.items(), key=lambda item: item[1]["agent_name"] or ""):
        user = primary_user_by_key.get(key)
        if not _requires_provisioning(user):
            continue
        new_gp_without_accounts.append(
            {
                "agent_name": imported["agent_name"],
                "normalized_key": key,
                "agency_names": sorted(imported["agency_names"]),
                "loan_count": imported["loan_count"],
                "has_account": user is not None,
                "user_id": user.id if user else None,
                "email": user.email if user else None,
                "account_status": _portfolio_status(user),
                "action": "PROVISION_PASSWORD" if user else "CREATE_ACCOUNT",
            }
        )

    existing_accounts_not_in_mcr = []
    for key, user in sorted(primary_user_by_key.items(), key=lambda item: item[1].full_name or ""):
        if key in imported_gps:
            continue
        existing_accounts_not_in_mcr.append(
            {
                "user_id": user.id,
                "agent_name": user.agent.name if user.agent else user.full_name,
                "email": user.email,
                "agency_name": user.agency.name if user.agency else None,
                "agent_id": user.agent_id,
                "is_active": bool(user.is_active),
                "must_change_password": bool(user.must_change_password),
                "temporary_password_available": bool(user.temporary_password),
                "account_status": _portfolio_status(user),
            }
        )

    return {
        "import_batch": {
            "id": batch.id,
            "batch_type": batch.batch_type,
            "period": batch.period,
            "snapshot_date": batch.snapshot_date,
            "file_name": batch.file_name,
            "imported_at": batch.imported_at,
        },
        "new_gp_without_accounts": new_gp_without_accounts,
        "existing_accounts_not_in_mcr": existing_accounts_not_in_mcr,
    }


logger = logging.getLogger(__name__)


def delete_gp_accounts_from_mcr_audit(
    db: Session,
    user: User,
    *,
    account_ids: list[int],
) -> dict:
    """Soft-delete the given GP accounts from the MCR audit.

    Instead of physically removing the User rows (which would cause them to be
    recreated by ``ensure_agent_accounts`` on the next startup or import), we
    set ``excluded_from_gp_mcr_audit_at`` and ``excluded_from_gp_mcr_audit_by_user_id``.

    This excludes the user from the "existing accounts not in MCR" audit view
    (the audit query filters on ``excluded_from_gp_mcr_audit_at IS NULL``),
    while keeping the user record intact so that:

    - FK integrity is preserved;
    - ``ensure_agent_accounts`` can still find the existing user (it matches by
      identity key and will not recreate it);
    - The exclusion is persistent across restarts and data refreshes.

    The given ``account_ids`` MUST currently appear in the "existing accounts
    not in MCR" audit view (otherwise they are reported as
    ``skipped_user_ids``).

    Any pending credentials (RefreshToken, PasswordSetupToken, BonusResult,
    Complaint) are still cleaned up — same pattern as the existing ``delete_user``
    endpoint — so no dangling rows remain.

    The operation is transactional: if any error occurs, the transaction is
    rolled back and no partial exclusion remains.

    Access is restricted to super_admin / support at the API layer.
    """
    normalized: list[int] = []
    seen: set[int] = set()
    for raw in account_ids or []:
        value = int(raw)
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        normalized.append(value)

    if not normalized:
        return {
            "deleted_count": 0,
            "skipped_count": 0,
            "deleted_user_ids": [],
            "skipped_user_ids": [],
        }

    audit = build_gp_mcr_account_audit(db)
    allowed_account_ids = {
        entry["user_id"]
        for entry in audit.get("existing_accounts_not_in_mcr", [])
        if entry.get("user_id") is not None
    }

    skipped = [value for value in normalized if value not in allowed_account_ids]
    candidates = [value for value in normalized if value in allowed_account_ids]

    if not candidates:
        return {
            "deleted_count": 0,
            "skipped_count": len(skipped),
            "deleted_user_ids": [],
            "skipped_user_ids": skipped,
        }

    deleted_user_ids = []
    now = datetime.now(timezone.utc)
    for account_id in candidates:
        target_user = db.get(User, account_id)
        if target_user is None:
            skipped.append(account_id)
            continue
        if user.id == target_user.id:
            skipped.append(account_id)
            continue

        db.execute(delete(RefreshToken).where(RefreshToken.user_id == target_user.id))
        db.execute(
            delete(PasswordSetupToken).where(
                (PasswordSetupToken.user_id == target_user.id)
                | (PasswordSetupToken.issued_by_user_id == target_user.id)
            )
        )
        db.execute(delete(BonusResult).where(BonusResult.user_id == target_user.id))
        db.execute(delete(Complaint).where(Complaint.user_id == target_user.id))

        target_user.excluded_from_gp_mcr_audit_at = now
        target_user.excluded_from_gp_mcr_audit_by_user_id = user.id
        deleted_user_ids.append(target_user.id)

    db.commit()

    logger.info(
        "gp_mcr_account_exclude actor_id=%s excluded=%s skipped=%s",
        getattr(user, "id", None),
        len(deleted_user_ids),
        len(skipped),
    )

    return {
        "deleted_count": len(deleted_user_ids),
        "skipped_count": len(skipped),
        "deleted_user_ids": deleted_user_ids,
        "skipped_user_ids": skipped,
    }
