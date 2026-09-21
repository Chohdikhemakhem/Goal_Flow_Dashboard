from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.domain import MetricsSummary


class RestructuredKpiRead(BaseModel):
    total_contracts: int
    supposed_closed: int
    in_progress: int
    anomalies_count: int
    gaps_count: int
    paid_last_four_yes: int
    total_due: Decimal
    last_recalculated_at: datetime | None = None
    last_schedule_import_at: datetime | None = None


class RestructuredChartSliceRead(BaseModel):
    label: str
    value: int
    color: str | None = None


class RestructuredChartRead(BaseModel):
    items: list[RestructuredChartSliceRead]


class RestructuredTrendPointRead(BaseModel):
    label: str
    value: int


class RestructuredTrendChartRead(BaseModel):
    items: list[RestructuredTrendPointRead]


class RestructuredContractRead(BaseModel):
    contract_no: str
    agency_name: str | None = None
    agent_name: str | None = None
    delay_date: date | None = None
    total_due: Decimal | None = None
    loan_duration: int | None = None
    schedule_status: str | None = None
    consecutive_paid_count: int
    consecutive_bucket: str
    max_series_installments: str | None = None
    max_series_dates: str | None = None
    paid_installments_after_delay: int
    anomaly_detected: bool
    anomaly_detail: str | None = None
    paid_last_four_status: str
    last_paid_installment_no: int | None = None
    last_paid_due_date: date | None = None
    closure_status: str


class RestructuredGapRead(BaseModel):
    contract_no: str
    agency_name: str | None = None
    agent_name: str | None = None
    due_date_1: date | None = None
    due_date_2: date | None = None
    installment_no_1: int | None = None
    installment_no_2: int | None = None
    gap_days: int | None = None
    total_gap_count: int


class RestructuredImportResult(BaseModel):
    rows_seen: int = Field(ge=0)
    inserted: int = Field(ge=0)
    updated: int = Field(ge=0)
    deleted: int = Field(default=0, ge=0)
    kept_count: int = Field(default=0, ge=0)
    pending_cleanup_count: int = Field(default=0, ge=0)
    recalculated_contracts: int = Field(ge=0)
    started_at: datetime
    finished_at: datetime
    import_log_id: int
    message: str


class RestructuredSyncDeletionRead(BaseModel):
    contract_no: str
    type_credit: str
    source: str | None = None
    updated_at: datetime | None = None
    reason: str
    scope: str = "official"


class RestructuredSyncPreviewRead(BaseModel):
    file_name: str
    rows_seen: int = Field(ge=0)
    existing_contracts_count: int = Field(ge=0)
    imported_list_count: int = Field(ge=0)
    detected_in_mcr_count: int = Field(ge=0)
    kept_count: int = Field(ge=0)
    add_count: int = Field(ge=0)
    update_count: int = Field(ge=0)
    delete_count: int = Field(ge=0)
    pending_cleanup_count: int = Field(default=0, ge=0)
    deletions: list[RestructuredSyncDeletionRead] = Field(default_factory=list)
    message: str


class RestructuredImportLogRead(BaseModel):
    id: int
    import_type: str
    file_name: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    duration_seconds: Decimal | None = None
    row_count: int | None = None
    inserted_count: int | None = None
    updated_count: int | None = None
    deleted_count: int | None = None
    recalculated_contracts: int | None = None
    progress_percent: int | None = None
    phase: str | None = None
    source_rows_seen: int | None = None
    ignored_rows_count: int | None = None
    rows_per_second: Decimal | None = None
    eta_seconds: Decimal | None = None
    memory_peak_mb: Decimal | None = None
    last_activity_at: datetime | None = None
    phase_details: str | None = None
    status: str | None = None
    message: str | None = None

    model_config = {"from_attributes": True}


class RestructuredDashboardKpiRead(MetricsSummary):
    family: str
    supposed_closed: int
    paid_last_four_yes: int
    last_recalculated_at: datetime | None = None
    last_schedule_import_at: datetime | None = None


class RestructuredContractDetailRead(BaseModel):
    contract_no: str
    type_credit: str
    client_name: str | None = None
    client_first_name: str | None = None
    agency_name: str | None = None
    agent_name: str | None = None
    dateeod: date | None = None
    delay_date: date | None = None
    total_due: Decimal | None = None
    total_scheduled_amount: Decimal | None = None
    loan_duration: int | None = None
    encours: Decimal = Decimal("0")
    healthy_outstanding: Decimal = Decimal("0")
    days_overdue: int | None = None
    cohort_label: str | None = None
    par_label: str | None = None
    consecutive_paid_count: int = 0
    paid_last_four_status: str = "N/A"
    last_paid_installment_no: int | None = None
    last_paid_due_date: date | None = None
    closure_status: str = "N/A"
    anomaly_detected: bool = False
    anomaly_detail: str | None = None
    max_series_installments: str | None = None
    max_series_dates: str | None = None


class RestructuredMissingMcrContractRead(BaseModel):
    contract_no: str
    type_credit: str
    category_desc: str | None = None
    delay_date: date | None = None
    total_due: Decimal | None = None
    loan_duration: int | None = None
    source: str | None = None
    detected_at: datetime | None = None


class RestructuredMissingMcrContractDeleteRequest(BaseModel):
    contract_nos: list[str] = Field(default_factory=list, min_length=1, max_length=500)


class RestructuredMissingMcrContractDeleteResult(BaseModel):
    deleted_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    deleted_contract_nos: list[str] = Field(default_factory=list)
    skipped_contract_nos: list[str] = Field(default_factory=list)


class PendingRestructuredContractRead(BaseModel):
    id: int
    contract_no: str
    type_credit: str
    category_desc: str | None = None
    client_name: str | None = None
    client_first_name: str | None = None
    agency_name: str | None = None
    agent_name: str | None = None
    disbursement_date: date | None = None
    disbursement_amount: Decimal | None = None
    shift_date: date | None = None
    total_due: Decimal | None = None
    loan_duration: int | None = None
    missing_fields: list[str] = Field(default_factory=list)
    status: str
    detected_at: datetime | None = None
    detected_from_import: int | None = None


class PendingRestructuredContractUpdate(BaseModel):
    shift_date: date | None = None
    total_due: Decimal | None = Field(default=None, ge=0)
    loan_duration: int | None = Field(default=None, gt=0)


class PendingRestructuredContractSaveResult(BaseModel):
    message: str
    saved_count: int = Field(default=0, ge=0)
