from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import ImportBatchType


class LoanImportRow(BaseModel):
    contract_no: str = Field(min_length=1)
    client_name: str | None = None
    client_first_name: str | None = None
    client_id: str = Field(min_length=1)
    client_ncni: str | None = None
    agency_name: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    client_rating: str | None = None
    category_desc: str | None = None
    teg_rate: Decimal = Field(default=Decimal("0"), ge=0)
    disbursement_amount: Decimal = Field(ge=0)
    principal_outstanding: Decimal = Field(ge=0)
    principal_due: Decimal = Field(default=Decimal("0"))
    interest_due_amt: Decimal = Field(default=Decimal("0"))
    total_scheduled_amount: Decimal = Field(default=Decimal("0"), ge=0)
    days_overdue: int = Field(ge=0)
    total_due: Decimal 
    disbursement_date: date
    maturity_date: date | None = None
    next_schedule_date: date | None = None
    snapshot_date: date
    status: str = "active"


class ImportBatchRead(BaseModel):
    id: int
    batch_type: ImportBatchType
    period: str | None
    snapshot_date: date
    file_name: str
    imported_at: datetime

    model_config = {"from_attributes": True}


class ImportResult(BaseModel):
    snapshot_date: date
    rows_seen: int
    inserted: int
    updated: int
    duplicates: int
    metrics_recalculated: int
    import_batch: ImportBatchRead


class HistoricalImportResponse(BaseModel):
    exists: bool
    period: str
    existing_batch: ImportBatchRead | None = None


class SnapshotDeleteRequest(BaseModel):
    batch_ids: list[int] = Field(min_length=1, max_length=100)


class SnapshotDeleteResult(BaseModel):
    deleted_batch_ids: list[int]
    deleted_rows: int
