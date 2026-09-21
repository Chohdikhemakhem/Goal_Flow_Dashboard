import re
import unicodedata
from datetime import datetime, timezone
from os import getenv

from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.security import generate_temporary_password, hash_password, validate_password_policy
from app.models.entities import Agent, BonusResult, Complaint, PasswordSetupToken, RefreshToken, User
from app.models.enums import UserRole
from app.services.agent_identity import normalized_agent_name_key
from app.services.auth_security import make_unusable_password_hash

STANDARD_EMAIL_DOMAIN = "microcred.com.tn"


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return normalized.encode("ascii", "ignore").decode("ascii")


def _identity_tokens(value: str) -> list[str]:
    ascii_value = _strip_accents(value)
    return [token for token in re.findall(r"[a-z0-9]+", ascii_value.lower()) if token]


def _email_slug(value: str) -> str:
    tokens = _identity_tokens(value)
    if not tokens:
        return "user"
    if len(tokens) == 1:
        return tokens[0]
    return f"{tokens[0]}.{tokens[1]}"


def _make_email(local_part: str) -> str:
    return f"{local_part}@{STANDARD_EMAIL_DOMAIN}"


def _unique_email(base_email: str, used_emails: set[str]) -> str:
    local, _, domain = base_email.partition("@")
    candidate = f"{local}@{domain}"
    cursor = 2
    while candidate.lower() in used_emails:
        candidate = f"{local}.{cursor}@{domain}"
        cursor += 1
    used_emails.add(candidate.lower())
    return candidate


def _desired_user_local_part(user: User) -> str:
    if user.agent_id and user.agent and user.agent.name:
        return _email_slug(user.agent.name)
    if user.full_name:
        return _email_slug(user.full_name)
    email_local = (user.email or "").split("@", 1)[0]
    fallback_tokens = [token for token in _identity_tokens(email_local) if token not in {"agent", "user"}]
    if len(fallback_tokens) >= 2:
        return f"{fallback_tokens[0]}.{fallback_tokens[1]}"
    if len(fallback_tokens) == 1:
        return fallback_tokens[0]
    return f"user{user.id}"


def _set_temporary_password(user: User, password: str | None = None) -> str:
    temporary_password = password or generate_temporary_password()
    validate_password_policy(temporary_password)
    user.hashed_password = hash_password(temporary_password)
    user.is_active = True
    user.must_change_password = True
    user.password_changed_at = datetime.now(timezone.utc)
    user.temporary_password = temporary_password
    user.failed_login_attempts = 0
    user.locked_until = None
    user.session_nonce = int(user.session_nonce or 0) + 1
    return temporary_password


def _agent_identity_key(agent: Agent | None) -> str:
    return normalized_agent_name_key(agent.name if agent else None)


def _user_identity_key(user: User) -> str:
    if user.agent:
        return normalized_agent_name_key(user.agent.name)
    return normalized_agent_name_key(user.full_name)


def _delete_duplicate_user_references(db: Session, duplicate: User, survivor: User) -> None:
    db.execute(delete(RefreshToken).where(RefreshToken.user_id == duplicate.id))
    db.execute(
        delete(PasswordSetupToken).where(
            (PasswordSetupToken.user_id == duplicate.id)
            | (PasswordSetupToken.issued_by_user_id == duplicate.id)
        )
    )
    for bonus in db.scalars(select(BonusResult).where(BonusResult.user_id == duplicate.id)).all():
        existing = db.scalar(
            select(BonusResult).where(
                BonusResult.user_id == survivor.id,
                BonusResult.bonus_rule_id == bonus.bonus_rule_id,
                BonusResult.month == bonus.month,
                BonusResult.year == bonus.year,
            )
        )
        if existing:
            db.delete(bonus)
        else:
            bonus.user_id = survivor.id
    for complaint in db.scalars(select(Complaint).where(Complaint.user_id == duplicate.id)).all():
        complaint.user_id = survivor.id
    db.delete(duplicate)


def _merge_duplicate_portfolio_users(db: Session, users: list[User]) -> User:
    survivor = sorted(
        users,
        key=lambda user: (
            bool(user.must_change_password),
            not bool(user.is_active),
            user.id,
        ),
    )[0]
    for duplicate in users:
        if duplicate.id == survivor.id:
            continue
        if not survivor.temporary_password and duplicate.temporary_password and survivor.must_change_password:
            survivor.temporary_password = duplicate.temporary_password
            survivor.hashed_password = duplicate.hashed_password
            survivor.password_changed_at = duplicate.password_changed_at
        survivor.is_active = bool(survivor.is_active or duplicate.is_active)
        _delete_duplicate_user_references(db, duplicate, survivor)
    return survivor


def ensure_agent_accounts(db: Session, *, issue_credentials: bool = False) -> list[dict]:
    provisioned_accounts: list[dict] = []
    agents = db.scalars(select(Agent).order_by(Agent.id)).all()
    agents_by_key: dict[str, list[Agent]] = defaultdict(list)
    for agent in agents:
        key = _agent_identity_key(agent)
        if key:
            agents_by_key[key].append(agent)

    users_by_key: dict[str, list[User]] = defaultdict(list)
    for user in db.scalars(
        select(User)
        .where(User.role == UserRole.PORTFOLIO_MANAGER)
        .order_by(User.id)
    ).all():
        key = _user_identity_key(user)
        if key:
            users_by_key[key].append(user)

    existing_portfolio_users: dict[str, User] = {}
    for key, users in users_by_key.items():
        existing_portfolio_users[key] = _merge_duplicate_portfolio_users(db, users)
    db.flush()

    existing_emails = {email.lower() for email in db.scalars(select(User.email)).all()}

    for identity_key, identity_agents in sorted(agents_by_key.items(), key=lambda item: item[1][0].id):
        primary_agent = sorted(identity_agents, key=lambda agent: agent.id)[0]
        if identity_key in existing_portfolio_users:
            existing_user = existing_portfolio_users[identity_key]
            if existing_user.excluded_from_gp_mcr_audit_at is not None:
                continue
            expected_email = _make_email(_email_slug(primary_agent.name))
            if not existing_user.email.lower().endswith(f"@{STANDARD_EMAIL_DOMAIN}"):
                existing_user.email = _unique_email(expected_email, existing_emails)
            existing_user.full_name = primary_agent.name
            existing_user.agency_id = primary_agent.agency_id
            existing_user.agent_id = primary_agent.id
            if not existing_user.hashed_password:
                existing_user.hashed_password = make_unusable_password_hash()
            if issue_credentials and existing_user.must_change_password:
                temporary_password = existing_user.temporary_password or _set_temporary_password(existing_user)
                provisioned_accounts.append(
                    {
                        "user_id": existing_user.id,
                        "email": existing_user.email,
                        "full_name": existing_user.full_name,
                        "agent_id": primary_agent.id,
                        "agency_id": primary_agent.agency_id,
                        "temporary_password": temporary_password,
                        "created": False,
                    }
                )
            continue
        base_email = _make_email(_email_slug(primary_agent.name))
        email = _unique_email(base_email, existing_emails)
        temporary_password = generate_temporary_password() if issue_credentials else None
        hashed_password = hash_password(temporary_password) if temporary_password else make_unusable_password_hash()
        user = User(
            email=email,
            full_name=primary_agent.name,
            hashed_password=hashed_password,
            role=UserRole.PORTFOLIO_MANAGER,
            agency_id=primary_agent.agency_id,
            agent_id=primary_agent.id,
            is_active=True,
            must_change_password=True,
            password_changed_at=datetime.now(timezone.utc) if temporary_password else None,
            temporary_password=temporary_password,
        )
        db.add(
            user
        )
        db.flush()
        if temporary_password:
            provisioned_accounts.append(
                {
                        "user_id": user.id,
                        "email": user.email,
                        "full_name": user.full_name,
                        "agent_id": primary_agent.id,
                        "agency_id": primary_agent.agency_id,
                        "temporary_password": temporary_password,
                        "created": True,
                    }
                )
    db.flush()
    return provisioned_accounts


def provision_single_gp_account(db: Session, agent_name: str, *, issue_credentials: bool = True) -> dict | None:
    """Provision a GP account for a single agent identified by name.

    Reuses the same matching/provisioning logic as ``ensure_agent_accounts``
    but scoped to one agent. If no matching Agent is found, returns None.
    If no matching identity key is found for the agent, returns None.
    """
    agent = db.scalars(
        select(Agent)
        .where(Agent.name == agent_name)
        .order_by(Agent.id)
    ).first()
    if agent is None:
        return None

    identity_key = _agent_identity_key(agent)
    if not identity_key:
        return None

    existing_users = db.scalars(
        select(User)
        .where(User.role == UserRole.PORTFOLIO_MANAGER)
        .order_by(User.id)
    ).all()
    users_by_key: dict[str, list[User]] = defaultdict(list)
    for user in existing_users:
        key = _user_identity_key(user)
        if key:
            users_by_key[key].append(user)

    existing_portfolio_users: dict[str, User] = {}
    for key, users in users_by_key.items():
        existing_portfolio_users[key] = _merge_duplicate_portfolio_users(db, users)
    db.flush()

    existing_emails = {email.lower() for email in db.scalars(select(User.email)).all()}

    if identity_key in existing_portfolio_users:
        existing_user = existing_portfolio_users[identity_key]
        if existing_user.excluded_from_gp_mcr_audit_at is not None:
            return None
        expected_email = _make_email(_email_slug(agent.name))
        if not existing_user.email.lower().endswith(f"@{STANDARD_EMAIL_DOMAIN}"):
            existing_user.email = _unique_email(expected_email, existing_emails)
        existing_user.full_name = agent.name
        existing_user.agency_id = agent.agency_id
        existing_user.agent_id = agent.id
        if not existing_user.hashed_password:
            existing_user.hashed_password = make_unusable_password_hash()
        temporary_password = None
        if issue_credentials and existing_user.must_change_password:
            temporary_password = existing_user.temporary_password or _set_temporary_password(existing_user)
        return {
            "user_id": existing_user.id,
            "email": existing_user.email,
            "full_name": existing_user.full_name,
            "agent_id": agent.id,
            "agency_id": agent.agency_id,
            "temporary_password": temporary_password,
            "created": False,
        }

    base_email = _make_email(_email_slug(agent.name))
    email = _unique_email(base_email, existing_emails)
    temporary_password = generate_temporary_password() if issue_credentials else None
    hashed_password = hash_password(temporary_password) if temporary_password else make_unusable_password_hash()
    user = User(
        email=email,
        full_name=agent.name,
        hashed_password=hashed_password,
        role=UserRole.PORTFOLIO_MANAGER,
        agency_id=agent.agency_id,
        agent_id=agent.id,
        is_active=True,
        must_change_password=True,
        password_changed_at=datetime.now(timezone.utc) if temporary_password else None,
        temporary_password=temporary_password,
    )
    db.add(user)
    db.flush()
    if temporary_password:
        return {
            "user_id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "agent_id": agent.id,
            "agency_id": agent.agency_id,
            "temporary_password": temporary_password,
            "created": True,
        }
    return {
        "user_id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "agent_id": agent.id,
        "agency_id": agent.agency_id,
        "temporary_password": None,
        "created": True,
    }


def batch_provision_gp_accounts(db: Session, agent_names: list[str], *, issue_credentials: bool = True) -> dict:
    """Provision multiple GP accounts in a single transaction.

    Calls ``provision_single_gp_account`` for each agent_name. If an agent
    is not found or its user is excluded from the GP/MCR audit, it is
    reported in ``skipped_agent_names`` instead of raising an error.

    Returns a dict with keys:
        accounts, created_count, provisioned_count, skipped_count, skipped_agent_names.
    """
    accounts: list[dict] = []
    skipped: list[str] = []
    for agent_name in agent_names:
        result = provision_single_gp_account(db, agent_name, issue_credentials=issue_credentials)
        if result is None:
            skipped.append(agent_name)
        else:
            accounts.append(result)
    return {
        "accounts": accounts,
        "created_count": sum(1 for account in accounts if account.get("created")),
        "provisioned_count": len(accounts),
        "skipped_count": len(skipped),
        "skipped_agent_names": skipped,
    }


def normalize_existing_accounts(db: Session) -> None:
    users = db.scalars(select(User).order_by(User.id)).all()

    for user in users:
        email = (user.email or "").lower()
        if user.role == UserRole.ADMIN and (
            email.endswith("@microcredapp.com") or email.endswith("@microcred.local")
        ):
            user.role = UserRole.SUPER_ADMIN

    users_to_normalize = [user for user in users if user.role != UserRole.SUPER_ADMIN]
    preserved_emails = {
        (user.email or "").lower()
        for user in users
        if user.role == UserRole.SUPER_ADMIN and user.email
    }

    for user in users_to_normalize:
        user.email = f"tmp.user.{user.id}@migration.local"
    db.flush()

    used_emails: set[str] = set(preserved_emails)
    for user in users_to_normalize:
        desired_local = _desired_user_local_part(user)
        desired_email = _make_email(desired_local)
        user.email = _unique_email(desired_email, used_emails)
        if not user.hashed_password:
            user.hashed_password = make_unusable_password_hash()

    db.flush()


def bootstrap_super_admin_from_env(db: Session) -> bool:
    email = (getenv("BOOTSTRAP_SUPERADMIN_EMAIL") or "").strip().lower()
    password = getenv("BOOTSTRAP_SUPERADMIN_PASSWORD") or ""
    full_name = (getenv("BOOTSTRAP_SUPERADMIN_FULL_NAME") or "Platform Super Admin").strip()
    if not email or not password:
        return False
    validate_password_policy(password)

    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        existing.role = UserRole.SUPER_ADMIN
        existing.full_name = full_name
        existing.hashed_password = hash_password(password)
        existing.is_active = True
        existing.must_change_password = False
        return False

    db.add(
        User(
            email=email,
            full_name=full_name,
            hashed_password=hash_password(password),
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            must_change_password=False,
        )
    )
    db.flush()
    return True
