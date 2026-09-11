from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    JSON,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ComplaintStatus, ImportBatchType, TargetType, UserRole


class Agency(Base):
    __tablename__ = "agencies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    agency: Mapped[Agency] = relationship()
    __table_args__ = (UniqueConstraint("name", "agency_id", name="uq_agent_agency"),)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.PORTFOLIO_MANAGER)
    agency_id: Mapped[int | None] = mapped_column(ForeignKey("agencies.id"), nullable=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    session_nonce: Mapped[int] = mapped_column(Integer, default=0)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    temporary_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    excluded_from_gp_mcr_audit_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    excluded_from_gp_mcr_audit_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    agency: Mapped[Agency | None] = relationship(foreign_keys=[agency_id])
    agent: Mapped[Agent | None] = relationship(foreign_keys=[agent_id])


class AcmLimitConfig(Base):
    __tablename__ = "acm_limit_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    par_0_limit: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    par_30_limit: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    par_120_limit: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    cohort_1_30_limit: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    cohort_31_60_limit: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    cohort_61_90_limit: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    cohort_91_120_limit: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )


class LoginAudit(Base):
    __tablename__ = "login_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    logged_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class SupportActionAudit(Base):
    __tablename__ = "support_action_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    actor_email: Mapped[str] = mapped_column(String(255), index=True)
    actor_role: Mapped[UserRole] = mapped_column(Enum(UserRole), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    target_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result: Mapped[str] = mapped_column(String(32), default="success", index=True)
    ip_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    actor_user: Mapped[User | None] = relationship(foreign_keys=[actor_user_id])


class ActivitySector(Base):
    __tablename__ = "activity_sectors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    acm_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )
    versions: Mapped[list["AcmRateVersionDetail"]] = relationship(back_populates="sector")


class CategorySectorMapping(Base):
    __tablename__ = "category_sector_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_desc: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    activity_sector_id: Mapped[int] = mapped_column(ForeignKey("activity_sectors.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )

    activity_sector: Mapped[ActivitySector] = relationship()


class AcmRateVersion(Base):
    __tablename__ = "acm_rate_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    effective_start_date: Mapped[date] = mapped_column(Date, index=True)
    effective_end_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    is_open_ended: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", index=True)
    status: Mapped[str] = mapped_column(String(20), default="historique", index=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

    created_by_user: Mapped[User | None] = relationship(foreign_keys=[created_by_user_id])
    details: Mapped[list["AcmRateVersionDetail"]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
    )
    audit_entries: Mapped[list["AcmRateVersionAudit"]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
    )


class AcmRateVersionDetail(Base):
    __tablename__ = "acm_rate_version_details"
    __table_args__ = (
        UniqueConstraint("version_id", "activity_sector_id", name="uq_acm_rate_version_details_version_sector"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("acm_rate_versions.id"), index=True)
    activity_sector_id: Mapped[int | None] = mapped_column(ForeignKey("activity_sectors.id"), nullable=True, index=True)
    sector_name: Mapped[str] = mapped_column(String(255))
    acm_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)

    version: Mapped[AcmRateVersion] = relationship(back_populates="details")
    sector: Mapped[ActivitySector | None] = relationship(back_populates="versions")


class AcmRateVersionAudit(Base):
    __tablename__ = "acm_rate_version_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("acm_rate_versions.id"), index=True)
    modified_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    modified_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    comment: Mapped[str] = mapped_column(Text)
    previous_start_date: Mapped[date] = mapped_column(Date, index=True)
    previous_end_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    previous_is_open_ended: Mapped[bool] = mapped_column(Boolean, default=False)
    new_start_date: Mapped[date] = mapped_column(Date, index=True)
    new_end_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    new_is_open_ended: Mapped[bool] = mapped_column(Boolean, default=False)
    previous_values_json: Mapped[dict] = mapped_column(JSON)
    new_values_json: Mapped[dict] = mapped_column(JSON)

    version: Mapped[AcmRateVersion] = relationship(back_populates="audit_entries")
    modified_by_user: Mapped[User | None] = relationship(foreign_keys=[modified_by_user_id])


class TaegDailySnapshot(Base):
    __tablename__ = "taeg_daily_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    period_month: Mapped[int] = mapped_column(Integer, index=True)
    period_year: Mapped[int] = mapped_column(Integer, index=True)
    agency_id: Mapped[int | None] = mapped_column(ForeignKey("agencies.id"), nullable=True, index=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True, index=True)
    sector_id: Mapped[int | None] = mapped_column(ForeignKey("activity_sectors.id"), nullable=True, index=True)
    sector_name: Mapped[str] = mapped_column(String(255), index=True)
    credits_count: Mapped[int] = mapped_column(Integer, default=0)
    disbursement_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    taeg_calculated: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    taeg_weighted_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0)
    acm_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)
    status: Mapped[str] = mapped_column(String(32), default="conforme")

    import_batch: Mapped["ImportBatch | None"] = relationship()
    agency: Mapped[Agency | None] = relationship(foreign_keys=[agency_id])
    agent: Mapped[Agent | None] = relationship(foreign_keys=[agent_id])
    sector: Mapped[ActivitySector | None] = relationship(foreign_keys=[sector_id])
    __table_args__ = (
        UniqueConstraint(
            "snapshot_date",
            "agency_id",
            "agent_id",
            "sector_name",
            name="uq_taeg_daily_snapshot_scope",
        ),
    )



class RestructuredContract(Base):
    __tablename__ = "restructured_contracts"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_contract_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contract_no: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    normalized_contract_no: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    credit_family: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    restructure_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    delay_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    in_mcr: Mapped[str | None] = mapped_column(String(40), nullable=True)
    category_desc: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_due: Mapped[Decimal | None] = mapped_column(Numeric(18, 3), nullable=True)
    loan_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    completed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    excluded_from_missing_mcr_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    excluded_from_missing_mcr_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PendingRestructuredContract(Base):
    __tablename__ = "pending_restructured_contracts"

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_no: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized_contract_no: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    credit_family: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    category_desc: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agency_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    agent_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    disbursement_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    disbursement_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 3), nullable=True)
    shift_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_due: Mapped[Decimal | None] = mapped_column(Numeric(18, 3), nullable=True)
    loan_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    missing_fields: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    detected_from_import: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True, index=True)
    completed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    import_batch: Mapped["ImportBatch | None"] = relationship(foreign_keys=[detected_from_import])
    completed_by: Mapped[User | None] = relationship(foreign_keys=[completed_by_user_id])


class RestructuredScheduleRow(Base):
    __tablename__ = "restructured_schedule_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    agency_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    agent_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_number: Mapped[str] = mapped_column(String(100), index=True)
    t24_reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    culoanpart_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    installment_no: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    total_installment: Mapped[Decimal | None] = mapped_column(Numeric(18, 3), nullable=True)
    principal_paid: Mapped[Decimal | None] = mapped_column(Numeric(18, 3), nullable=True)
    interest_due: Mapped[Decimal | None] = mapped_column(Numeric(18, 3), nullable=True)
    interest_paid: Mapped[Decimal | None] = mapped_column(Numeric(18, 3), nullable=True)
    principal_due: Mapped[Decimal | None] = mapped_column(Numeric(18, 3), nullable=True)
    outstanding_after_payment: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 3), nullable=True
    )
    total_penalty_amt: Mapped[Decimal | None] = mapped_column(Numeric(18, 3), nullable=True)
    penalty_interest_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 3), nullable=True
    )
    unpaid_interest: Mapped[Decimal | None] = mapped_column(Numeric(18, 3), nullable=True)
    unpaid_penalty_interest: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 3), nullable=True
    )
    all_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    receipt_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    schedule_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    delay_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "account_number",
            "installment_no",
            name="uq_restructured_schedule_account_installment",
        ),
    )


class RestructuredAnalysisResult(Base):
    __tablename__ = "restructured_analysis_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_no: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    agency_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    agent_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    delay_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_due: Mapped[Decimal | None] = mapped_column(Numeric(18, 3), nullable=True)
    loan_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    consecutive_paid_count: Mapped[int] = mapped_column(Integer, default=0)
    max_series_installments: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_series_dates: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_installments_after_delay: Mapped[int] = mapped_column(Integer, default=0)
    anomaly_detected: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    anomaly_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_last_four_status: Mapped[str] = mapped_column(String(10), default="N/A", index=True)
    last_paid_installment_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_paid_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    closure_status: Mapped[str] = mapped_column(String(40), default="N/A", index=True)
    last_calculated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RestructuredGapResult(Base):
    __tablename__ = "restructured_gap_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_no: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    agency_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    agent_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    due_date_1: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date_2: Mapped[date | None] = mapped_column(Date, nullable=True)
    installment_no_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    installment_no_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gap_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_gap_count: Mapped[int] = mapped_column(Integer, default=0)
    last_calculated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RestructuredImportLog(Base):
    __tablename__ = "restructured_import_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    import_type: Mapped[str] = mapped_column(String(30), index=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inserted_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deleted_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recalculated_contracts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phase: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_rows_seen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ignored_rows_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows_per_second: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    eta_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    memory_peak_mb: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    phase_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    replaced_by_id: Mapped[int | None] = mapped_column(ForeignKey("refresh_tokens.id"), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(foreign_keys=[user_id])


class PasswordSetupToken(Base):
    __tablename__ = "password_setup_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_reset: Mapped[bool] = mapped_column(Boolean, default=False)
    issued_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(foreign_keys=[user_id])


class LoanRaw(Base):
    __tablename__ = "loans_raw"

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_no: Mapped[str] = mapped_column(String(100), index=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_id: Mapped[str] = mapped_column(String(100), index=True)
    client_ncni: Mapped[str | None] = mapped_column(String(120), nullable=True)
    agency_name: Mapped[str] = mapped_column(String(255), index=True)
    agent_name: Mapped[str] = mapped_column(String(255), index=True)
    client_rating: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category_desc: Mapped[str | None] = mapped_column(String(255), nullable=True)
    teg_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)
    disbursement_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    principal_outstanding: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    principal_due: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    interest_due_amt: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    total_scheduled_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    days_overdue: Mapped[int] = mapped_column(Integer, default=0)
    total_due: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    status: Mapped[str] = mapped_column(String(100), default="active")
    disbursement_date: Mapped[date] = mapped_column(Date)
    maturity_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_schedule_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id"), nullable=True, index=True
    )
    imported_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    import_batch: Mapped[ImportBatch | None] = relationship(back_populates="loans")
    __table_args__ = (
        UniqueConstraint("contract_no", "snapshot_date", name="uq_loan_snapshot"),
    )


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_type: Mapped[ImportBatchType] = mapped_column(
        Enum(ImportBatchType), index=True
    )
    period: Mapped[str | None] = mapped_column(String(7), nullable=True, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    imported_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    loans: Mapped[list[LoanRaw]] = relationship(back_populates="import_batch")
    __table_args__ = (
        UniqueConstraint(
            "batch_type", "period", name="uq_import_batch_type_period"
        ),
    )


class DailyMetric(Base):
    __tablename__ = "daily_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    disbursement_count: Mapped[int] = mapped_column(Integer, default=0)
    disbursement_volume: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    nb_clients: Mapped[int] = mapped_column(Integer, default=0)
    outstanding: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    healthy_outstanding: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    par_0: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    par_1_30: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    par_1_15: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    par_16_30: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    par_31_60: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    par_61_90: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    par_91_120: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    par_120: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    par_30: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    agency: Mapped[Agency] = relationship()
    agent: Mapped[Agent] = relationship()
    __table_args__ = (UniqueConstraint("agency_id", "agent_id", "date", name="uq_daily_metric"),)


class Target(Base):
    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[TargetType] = mapped_column(
        Enum(TargetType, native_enum=False, length=16),
        default=TargetType.AGENCY,
        index=True,
    )
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"), index=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True, index=True)
    month: Mapped[int] = mapped_column(Integer)
    year: Mapped[int] = mapped_column(Integer)
    active_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    active_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_disbursement_count: Mapped[int] = mapped_column(Integer, default=0)
    target_nb_clients: Mapped[int] = mapped_column(Integer, default=0)
    target_disbursement: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    target_outstanding: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    target_par: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=0)
    target_healthy_outstanding: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    target_par_0: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    target_par_1_30: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    target_par_31_60: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    target_par_30: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, onupdate=func.now())
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True, default=None)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True, default=None)

    agency: Mapped[Agency] = relationship()
    agent: Mapped[Agent | None] = relationship()
    created_by_user: Mapped["User | None"] = relationship(foreign_keys=[created_by])
    updated_by_user: Mapped["User | None"] = relationship(foreign_keys=[updated_by])
    __table_args__ = (
        UniqueConstraint("target_type", "agent_id", "month", "year", name="uq_target_agent_scope"),
    )


class ParReductionTarget(Base):
    __tablename__ = "par_reduction_targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    month: Mapped[int] = mapped_column(Integer, index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    target_par30: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    target_cohort_1_15: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    target_cohort_16_30: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    agency: Mapped[Agency] = relationship()
    agent: Mapped[Agent] = relationship()
    __table_args__ = (
        UniqueConstraint("agent_id", "month", "year", name="uq_par_reduction_target_agent_period"),
    )


class BonusRule(Base):
    __tablename__ = "bonus_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    formula: Mapped[dict] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BonusResult(Base):
    __tablename__ = "bonus_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    bonus_rule_id: Mapped[int] = mapped_column(ForeignKey("bonus_rules.id"))
    month: Mapped[int] = mapped_column(Integer)
    year: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship()
    rule: Mapped[BonusRule] = relationship()
    __table_args__ = (UniqueConstraint("user_id", "bonus_rule_id", "month", "year", name="uq_bonus_result"),)


class Complaint(Base):
    __tablename__ = "complaints"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subject: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[ComplaintStatus] = mapped_column(
        Enum(ComplaintStatus), default=ComplaintStatus.OPEN
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship()
