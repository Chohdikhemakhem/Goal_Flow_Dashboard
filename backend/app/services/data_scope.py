from dataclasses import dataclass

from app.models.entities import User
from app.models.enums import UserRole


@dataclass(frozen=True)
class UserDataScope:
    role: UserRole
    agency_id: int | None = None
    agent_id: int | None = None

    @property
    def is_admin(self) -> bool:
        return self.role in {UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.COMMITTEE_MEMBER}

    @property
    def is_agency_scope(self) -> bool:
        return self.role == UserRole.AGENCY_MANAGER and self.agency_id is not None

    @property
    def is_agent_scope(self) -> bool:
        return self.role == UserRole.PORTFOLIO_MANAGER and self.agent_id is not None


def get_user_data_scope(user: User) -> UserDataScope:
    if user.role in {UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.COMMITTEE_MEMBER}:
        return UserDataScope(role=user.role)
    if user.role == UserRole.AGENCY_MANAGER:
        return UserDataScope(role=user.role, agency_id=user.agency_id)
    if user.role == UserRole.PORTFOLIO_MANAGER:
        return UserDataScope(role=user.role, agency_id=user.agency_id, agent_id=user.agent_id)
    return UserDataScope(role=user.role)
