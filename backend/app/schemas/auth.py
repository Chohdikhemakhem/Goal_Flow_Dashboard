from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserRead(BaseModel):
    id: int
    email: str
    full_name: str
    role: UserRole
    agency_id: int | None = None
    agent_id: int | None = None
    is_active: bool
    must_change_password: bool = False

    model_config = {"from_attributes": True}


class UserAdminRead(UserRead):
    temporary_password: str | None = None


class UserCreate(BaseModel):
    email: str
    full_name: str
    role: UserRole
    agency_id: int | None = None
    agent_id: int | None = None
    initial_password: str | None = Field(default=None, min_length=12)


class UserUpdate(BaseModel):
    email: str | None = None
    full_name: str | None = None
    role: UserRole | None = None
    agency_id: int | None = None
    agent_id: int | None = None
    is_active: bool | None = None


class UserStatusUpdate(BaseModel):
    is_active: bool


class LoginResponse(BaseModel):
    user: UserRead
    expires_in_seconds: int


class ActivationTokenRead(BaseModel):
    activation_token: str
    expires_at: datetime
    is_reset: bool = False


class UserProvisionRead(BaseModel):
    user: UserRead
    temporary_password: str | None = None
    generated_password: bool = True


class AgentAccountProvisionRead(BaseModel):
    user_id: int
    email: str
    full_name: str
    agent_id: int
    agency_id: int
    temporary_password: str | None = None
    created: bool = True


class AgentAccountProvisionResult(BaseModel):
    accounts: list[AgentAccountProvisionRead]
    created_count: int
    provisioned_count: int


class GpAccountProvisionRequest(BaseModel):
    agent_name: str = Field(min_length=1, max_length=255)


class GpAccountProvisionResult(BaseModel):
    account: AgentAccountProvisionRead | None = None
    created: bool = False
    provisionned: bool = False
    temporary_password: str | None = None


class GpAccountBatchProvisionRequest(BaseModel):
    agent_names: list[str] = Field(default_factory=list, min_length=1, max_length=500)


class GpAccountBatchProvisionResult(BaseModel):
    accounts: list[AgentAccountProvisionRead] = Field(default_factory=list)
    created_count: int = 0
    provisioned_count: int = 0
    skipped_count: int = 0
    skipped_agent_names: list[str] = Field(default_factory=list)


class GpMcrAuditImportRead(BaseModel):
    id: int
    batch_type: str
    period: str | None = None
    snapshot_date: date
    file_name: str
    imported_at: datetime


class GpMcrAuditNewAgentRead(BaseModel):
    agent_name: str
    normalized_key: str
    agency_names: list[str]
    loan_count: int
    has_account: bool
    user_id: int | None = None
    email: str | None = None
    account_status: str
    action: str


class GpMcrAuditMissingAccountRead(BaseModel):
    user_id: int
    agent_name: str
    email: str
    agency_name: str | None = None
    agent_id: int | None = None
    is_active: bool
    must_change_password: bool
    temporary_password_available: bool
    account_status: str


class GpMcrAuditRead(BaseModel):
    import_batch: GpMcrAuditImportRead | None = None
    new_gp_without_accounts: list[GpMcrAuditNewAgentRead]
    existing_accounts_not_in_mcr: list[GpMcrAuditMissingAccountRead]


class GpMcrAuditMissingAccountDeleteRequest(BaseModel):
    account_ids: list[int] = Field(default_factory=list, min_length=1, max_length=500)


class GpMcrAuditMissingAccountDeleteResult(BaseModel):
    deleted_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    deleted_user_ids: list[int] = Field(default_factory=list)
    skipped_user_ids: list[int] = Field(default_factory=list)


class PasswordResetRequest(BaseModel):
    temporary_password: str | None = Field(default=None, min_length=12)


class PasswordResetRead(BaseModel):
    user: UserRead
    temporary_password: str | None = None
    generated_password: bool = True


class PasswordSetupRequest(BaseModel):
    token: str = Field(min_length=16)
    password: str = Field(min_length=12)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12)
