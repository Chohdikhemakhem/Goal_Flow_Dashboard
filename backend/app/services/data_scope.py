from dataclasses import dataclass
from enum import StrEnum

from app.models.entities import User
from app.models.enums import UserRole


# Source unique de verite pour le decoupage regional. Les donnees importees
# restent associees a une agence; la region est donc derivee, jamais acceptee
# depuis un parametre HTTP.
REGION_NORD_AGENCIES = frozenset({
    "AGENCE EZAHROUNI", "AGENCE ARIANA", "AGENCE BEN AROUS",
    "AGENCE JENDOUBA", "AGENCE KEF", "AGENCE BIZERTE", "AGENCE TCV",
    "AGENCE NABEUL", "AGENCE SILIANA", "AGENCE BEJA", "AGENCE FAHS",
})


class RegionScope(StrEnum):
    NORD = "NORD"
    SUD = "SUD"


REGIONAL_MANAGER_ROLES = frozenset({
    UserRole.REGIONAL_MANAGER_NORD,
    UserRole.REGIONAL_MANAGER_SUD,
})


def role_region_scope(role: UserRole) -> RegionScope | None:
    if role == UserRole.REGIONAL_MANAGER_NORD:
        return RegionScope.NORD
    if role == UserRole.REGIONAL_MANAGER_SUD:
        return RegionScope.SUD
    return None


def region_scope_condition(agency_name_column, region: RegionScope | None):
    """SQL condition for a regional scope; no rows are materialized in Python."""
    if region is None:
        return None
    if region == RegionScope.NORD:
        return agency_name_column.in_(REGION_NORD_AGENCIES)
    return ~agency_name_column.in_(REGION_NORD_AGENCIES)


@dataclass(frozen=True)
class UserDataScope:
    role: UserRole
    agency_id: int | None = None
    agent_id: int | None = None
    region: RegionScope | None = None

    @property
    def is_admin(self) -> bool:
        return self.role in {UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.COMMITTEE_MEMBER}

    @property
    def is_regional_scope(self) -> bool:
        return self.region is not None

    @property
    def is_agency_scope(self) -> bool:
        return self.role == UserRole.AGENCY_MANAGER and self.agency_id is not None

    @property
    def is_agent_scope(self) -> bool:
        return self.role == UserRole.PORTFOLIO_MANAGER and self.agent_id is not None


def get_user_data_scope(user: User) -> UserDataScope:
    region = role_region_scope(user.role)
    if region is not None:
        return UserDataScope(role=user.role, region=region)
    if user.role in {UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.COMMITTEE_MEMBER}:
        return UserDataScope(role=user.role)
    if user.role == UserRole.AGENCY_MANAGER:
        return UserDataScope(role=user.role, agency_id=user.agency_id)
    if user.role == UserRole.PORTFOLIO_MANAGER:
        return UserDataScope(role=user.role, agency_id=user.agency_id, agent_id=user.agent_id)
    return UserDataScope(role=user.role)
