from enum import StrEnum


class UserRole(StrEnum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    SUPPORT = "support"
    COMMITTEE_MEMBER = "committee_member"
    PORTFOLIO_MANAGER = "portfolio_manager"
    AGENCY_MANAGER = "agency_manager"


class ComplaintStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"


class ImportBatchType(StrEnum):
    CURRENT_STATE = "CURRENT_STATE"
    HISTORICAL_MONTH = "HISTORICAL_MONTH"
    SNAPSHOT = "SNAPSHOT"


class TargetType(StrEnum):
    AGENCY = "AGENCY"
    AGENT = "AGENT"
