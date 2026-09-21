from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field, model_validator

from app.models.enums import ComplaintStatus, TargetType, UserRole


class AgencyRead(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class AgentRead(BaseModel):
    id: int
    name: str
    agency_id: int

    model_config = {"from_attributes": True}


class UserMiniRead(BaseModel):
    id: int
    email: str
    full_name: str

    model_config = {"from_attributes": True}


class FeatureFlagsRead(BaseModel):
    bonus_module_active: bool


class DailyMetricRead(BaseModel):
    id: int
    agency_id: int
    agent_id: int
    date: date
    disbursement_count: int
    disbursement_volume: Decimal
    nb_clients: int
    outstanding: Decimal
    healthy_outstanding: Decimal
    par_0: Decimal
    par_1_30: Decimal
    par_1_15: Decimal = Decimal("0")
    par_16_30: Decimal = Decimal("0")
    par_31_60: Decimal
    par_61_90: Decimal
    par_91_120: Decimal
    par_120: Decimal
    par_30: Decimal
    agency: AgencyRead
    agent: AgentRead

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def par_30_rate(self) -> Decimal:
        if not self.outstanding:
            return Decimal("0")
        return (self.par_30 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def healthy_rate(self) -> Decimal:
        if not self.outstanding:
            return Decimal("0")
        return (self.healthy_outstanding / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_0_rate(self) -> Decimal:
        if not self.outstanding:
            return Decimal("0")
        return (self.par_0 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_1_30_rate(self) -> Decimal:
        if not self.outstanding:
            return Decimal("0")
        return (self.par_1_30 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_1_15_rate(self) -> Decimal:
        if not self.outstanding:
            return Decimal("0")
        return (self.par_1_15 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_16_30_rate(self) -> Decimal:
        if not self.outstanding:
            return Decimal("0")
        return (self.par_16_30 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_31_60_rate(self) -> Decimal:
        if not self.outstanding:
            return Decimal("0")
        return (self.par_31_60 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_61_90_rate(self) -> Decimal:
        if not self.outstanding:
            return Decimal("0")
        return (self.par_61_90 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_91_120_rate(self) -> Decimal:
        if not self.outstanding:
            return Decimal("0")
        return (self.par_91_120 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_120_rate(self) -> Decimal:
        if not self.outstanding:
            return Decimal("0")
        return (self.par_120 / self.outstanding).quantize(Decimal("0.0001"))


class CurrentCreditRead(BaseModel):
    contract_no: str
    client_name: str | None = None
    client_first_name: str | None = None
    client_id: str
    client_ncni: str | None = None
    agency_name: str
    agent_name: str
    client_rating: str | None = None
    disbursement_date: date | None = None
    maturity_date: date | None = None
    disbursement_amount: Decimal
    days_overdue: int
    total_scheduled_amount: Decimal
    principal_outstanding: Decimal
    total_due: Decimal
    encours: Decimal


class MetricsSummary(BaseModel):
    credits_count: int
    disbursement_count: int
    disbursements_count: int
    disbursement_volume: Decimal
    nb_clients: int
    outstanding: Decimal
    healthy_outstanding: Decimal
    healthy_count: int = 0
    healthy_client_count: int = 0
    par_0: Decimal
    par_0_count: int = 0
    par_0_client_count: int = 0
    par_1_30: Decimal
    par_1_30_count: int = 0
    par_1_30_client_count: int = 0
    par_1_15: Decimal = Decimal("0")
    par_1_15_count: int = 0
    par_1_15_client_count: int = 0
    par_16_30: Decimal = Decimal("0")
    par_16_30_count: int = 0
    par_16_30_client_count: int = 0
    par_31_60: Decimal
    par_31_60_count: int = 0
    par_31_60_client_count: int = 0
    par_61_90: Decimal
    par_61_90_count: int = 0
    par_61_90_client_count: int = 0
    par_91_120: Decimal
    par_91_120_count: int = 0
    par_91_120_client_count: int = 0
    par_120: Decimal
    par_120_count: int = 0
    par_120_client_count: int = 0
    par_30: Decimal
    par_30_count: int = 0
    par_30_client_count: int = 0
    potentially_radiable_volume: Decimal = Decimal("0")
    potentially_radiable_rate: Decimal = Decimal("0")
    requested_date_to: date | None = None
    effective_snapshot_date: date | None = None
    effective_import_batch_id: int | None = None
    potential_radiable_reference_date: date | None = None
    potential_radiable_threshold: int | None = None
    potential_radiable_client_count: int = 0
    potential_radiable_loan_count: int = 0

    @computed_field
    @property
    def healthy_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.healthy_outstanding / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_0_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.par_0 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_1_30_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.par_1_30 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_1_15_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.par_1_15 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_16_30_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.par_16_30 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_31_60_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.par_31_60 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_61_90_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.par_61_90 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_91_120_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.par_91_120 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_120_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.par_120 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_30_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.par_30 / self.outstanding).quantize(Decimal("0.0001"))


class MetricsChartPoint(BaseModel):
    label: str
    disbursement_count: int = 0
    disbursement_volume: Decimal
    outstanding: Decimal
    healthy_outstanding: Decimal
    par_0: Decimal
    par_1_30: Decimal
    par_1_15: Decimal = Decimal("0")
    par_16_30: Decimal = Decimal("0")
    par_31_60: Decimal
    par_61_90: Decimal
    par_91_120: Decimal
    par_120: Decimal
    par_30: Decimal
    micro_disbursement_volume: Decimal = Decimal("0")
    micro_disbursement_count: int = 0
    tpme_disbursement_volume: Decimal = Decimal("0")
    tpme_disbursement_count: int = 0
    afari_disbursement_volume: Decimal = Decimal("0")
    afari_disbursement_count: int = 0

    @computed_field
    @property
    def healthy_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.healthy_outstanding / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_1_30_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.par_1_30 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_1_15_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.par_1_15 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_16_30_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.par_16_30 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_31_60_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.par_31_60 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_0_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.par_0 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_61_90_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.par_61_90 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_91_120_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.par_91_120 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_120_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.par_120 / self.outstanding).quantize(Decimal("0.0001"))

    @computed_field
    @property
    def par_30_rate(self) -> Decimal:
        return Decimal("0") if not self.outstanding else (self.par_30 / self.outstanding).quantize(Decimal("0.0001"))


class MetricsChartRead(BaseModel):
    mode: Literal["GLOBAL_BY_AGENCY", "AGENCY_MONTHLY_TREND", "AGENT_MONTHLY_TREND", "GLOBAL_QUALITY_TREND"]
    points: list[MetricsChartPoint]


class SnapshotOptionRead(BaseModel):
    batch_id: int
    snapshot_date: date
    label: str


class ClosedMonthOptionRead(BaseModel):
    key: str
    period: str
    label: str
    snapshot_date: date
    batch_id: int


class ActiveSnapshotRead(BaseModel):
    snapshot_date: date | None = None
    label: str | None = None


class PortfolioCoverageRead(BaseModel):
    label: str
    current_value: Decimal
    target_value: Decimal
    ratio: Decimal
    direction: Literal["HIGHER_IS_BETTER", "LOWER_IS_BETTER"] = "HIGHER_IS_BETTER"

    @computed_field
    @property
    def achievement_percent(self) -> Decimal:
        return (self.ratio * Decimal("100")).quantize(Decimal("0.01"))


class PortfolioDashboardRead(BaseModel):
    reference_month: int | None = None
    reference_year: int | None = None
    has_target: bool
    has_bonus_rule: bool
    coverage_ratio: Decimal
    bonus_amount: Decimal
    details: list[PortfolioCoverageRead] = []
    message: str | None = None


class AcmLimitConfigBase(BaseModel):
    par_0_limit: Decimal | None = Field(default=None, ge=0)
    par_30_limit: Decimal | None = Field(default=None, ge=0)
    par_120_limit: Decimal | None = Field(default=None, ge=0)
    cohort_1_30_limit: Decimal | None = Field(default=None, ge=0)
    cohort_31_60_limit: Decimal | None = Field(default=None, ge=0)
    cohort_61_90_limit: Decimal | None = Field(default=None, ge=0)
    cohort_91_120_limit: Decimal | None = Field(default=None, ge=0)


class AcmLimitConfigUpdate(AcmLimitConfigBase):
    pass


class AcmLimitConfigRead(AcmLimitConfigBase):
    configured: bool = False
    updated_by_user_id: int | None = None
    updated_at: datetime | None = None


class LoginAuditStatRead(BaseModel):
    label: str
    count: int


class LoginAuditRowRead(BaseModel):
    user_id: int | None = None
    full_name: str
    email: str
    role: UserRole
    login_date: date
    login_hour: str
    ip_address: str | None = None
    user_agent: str | None = None
    connection_count: int


class LoginAuditDashboardRead(BaseModel):
    total_connections: int
    by_user: list[LoginAuditStatRead] = []
    by_day: list[LoginAuditStatRead] = []
    by_hour: list[LoginAuditStatRead] = []
    rows: list[LoginAuditRowRead] = []


class ActivitySectorBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    acm_rate: Decimal = Field(default=Decimal("0"), ge=0)


class ActivitySectorCreate(ActivitySectorBase):
    pass


class ActivitySectorUpdate(ActivitySectorBase):
    pass


class ActivitySectorRead(ActivitySectorBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CategorySectorMappingUpdate(BaseModel):
    category_desc: str = Field(min_length=1, max_length=255)
    activity_sector_id: int


class CategorySectorMappingRead(BaseModel):
    id: int | None = None
    category_desc: str
    occurrence_count: int = 0
    activity_sector_id: int | None = None
    activity_sector_name: str | None = None
    updated_at: datetime | None = None


class TaegPeriodRead(BaseModel):
    key: str
    label: str
    snapshot_date: date
    batch_type: str
    batch_id: int | None = None
    is_current: bool = False
    month_number: int | None = None
    year: int | None = None


class TaegSummaryRowRead(BaseModel):
    sector_id: int
    sector_name: str
    credits_count: int
    disbursement_amount: Decimal
    taeg_calculated: Decimal
    taeg_weighted_rate: Decimal
    acm_rate: Decimal | None = None
    compliant_credits_count: int = 0
    non_compliant_credits_count: int = 0
    uncovered_credits_count: int = 0
    status: Literal["conforme", "non_conforme", "non_couvert"]


class TaegAcmCoverageSegmentRead(BaseModel):
    segment_key: str
    period_key: str | None = None
    period_label: str | None = None
    range_start: date
    range_end: date
    covered: bool = True
    version_id: int | None = None
    block_label: str | None = None
    block_start_date: date | None = None
    block_end_date: date | None = None
    credits_count: int = 0
    sectors_count: int = 0
    coverage_status: str = "complete"


class TaegDashboardRead(BaseModel):
    period: TaegPeriodRead
    used_periods: list[TaegPeriodRead] = []
    acm_segments: list[TaegAcmCoverageSegmentRead] = []
    active_acm_segment: TaegAcmCoverageSegmentRead | None = None
    acm_coverage_message: str | None = None
    rows: list[TaegSummaryRowRead]


class TaegCreditDetailRead(BaseModel):
    contract_no: str
    sector_id: int
    sector_name: str
    disbursement_date: date | None = None
    disbursement_amount: Decimal
    teg_rate: Decimal
    taeg_calculated: Decimal
    taeg_weighted_rate: Decimal
    acm_rate: Decimal | None = None
    acm_block_version_id: int | None = None
    acm_block_start_date: date | None = None
    acm_block_end_date: date | None = None
    acm_block_label: str | None = None
    status: Literal["conforme", "non_conforme", "non_couvert"]


class TaegMonthlyHistoryPeriodRead(BaseModel):
    key: str
    label: str
    year: int
    month: int
    days_count: int = 0


class TaegMonthlyHistoryPointRead(BaseModel):
    snapshot_date: date
    day_label: str
    sector_id: int | None = None
    sector_name: str
    credits_count: int
    disbursement_amount: Decimal
    taeg_calculated: Decimal
    taeg_weighted_rate: Decimal
    acm_rate: Decimal
    status: Literal["conforme", "non_conforme", "non_couvert"]


class TaegMonthlyHistoryRead(BaseModel):
    period: TaegMonthlyHistoryPeriodRead
    days_count: int = 0
    sectors: list[dict[str, Any]] = []
    points: list[TaegMonthlyHistoryPointRead] = []


class AcmRateVersionSummaryRead(BaseModel):
    id: int
    effective_start_date: date
    effective_end_date: date | None = None
    is_open_ended: bool = False
    status: str
    comment: str | None = None
    created_at: datetime
    created_by_user_id: int | None = None
    created_by_name: str | None = None
    sector_count: int = 0


class AcmRateVersionDetailInput(BaseModel):
    sector_id: int
    acm_rate: Decimal = Field(ge=0)


class AcmRateVersionDetailRead(BaseModel):
    id: int
    sector_id: int | None = None
    sector_name: str
    acm_rate: Decimal


class AcmRateVersionAuditRead(BaseModel):
    id: int
    modified_by_user_id: int | None = None
    modified_by_name: str | None = None
    modified_at: datetime
    comment: str
    previous_start_date: date
    previous_end_date: date | None = None
    previous_is_open_ended: bool = False
    new_start_date: date
    new_end_date: date | None = None
    new_is_open_ended: bool = False
    previous_values_json: dict[str, Any] = Field(default_factory=dict)
    new_values_json: dict[str, Any] = Field(default_factory=dict)


class AcmRateVersionRead(BaseModel):
    id: int
    effective_start_date: date
    effective_end_date: date | None = None
    is_open_ended: bool = False
    status: str
    comment: str | None = None
    created_at: datetime
    created_by_user_id: int | None = None
    created_by_name: str | None = None
    details: list[AcmRateVersionDetailRead] = []
    sector_count: int = 0
    affected_snapshot_count: int = 0
    may_affect_existing_results: bool = False
    audit_entries: list[AcmRateVersionAuditRead] = []


class AcmRateVersionCreate(BaseModel):
    effective_start_date: date
    effective_end_date: date | None = None
    is_open_ended: bool = False
    comment: str | None = Field(default=None, max_length=1000)
    details: list[AcmRateVersionDetailInput] = []


class AcmRateVersionUpdate(BaseModel):
    effective_start_date: date
    effective_end_date: date | None = None
    is_open_ended: bool = False
    comment: str | None = Field(default=None, max_length=1000)
    modification_comment: str = Field(min_length=1, max_length=1000)
    confirm_impact: bool = False
    details: list[AcmRateVersionDetailInput] = []



class TargetCreate(BaseModel):
    target_type: TargetType
    agency_id: int
    agent_id: int | None = None
    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2000)
    active_from: date | None = None
    active_until: date | None = None
    target_disbursement_count: int = Field(default=0, ge=0)
    target_nb_clients: int = Field(default=0, ge=0)
    target_disbursement: Decimal = Field(default=Decimal("0"), ge=0)
    target_outstanding: Decimal = Field(default=Decimal("0"), ge=0)
    target_par: Decimal = Field(default=Decimal("0"), ge=0)
    target_healthy_outstanding: Decimal = Field(default=Decimal("0"), ge=0)
    target_par_0: Decimal = Field(default=Decimal("0"), ge=0)
    target_par_1_30: Decimal = Field(default=Decimal("0"), ge=0)
    target_par_31_60: Decimal = Field(default=Decimal("0"), ge=0)
    target_par_30: Decimal = Field(default=Decimal("0"), ge=0)

    @model_validator(mode="after")
    def validate_target_scope(self):
        if self.target_type == TargetType.AGENCY and self.agent_id is not None:
            raise ValueError("agent_id must be null for agency targets")
        if self.target_type == TargetType.AGENT and self.agent_id is None:
            raise ValueError("agent_id is required for agent targets")
        if (self.active_from is None) != (self.active_until is None):
            raise ValueError("active_from and active_until must be provided together")
        if self.active_from and self.active_until and self.active_until < self.active_from:
            raise ValueError("active_until must be greater than or equal to active_from")
        return self


class TargetUpdate(TargetCreate):
    pass


class TargetRead(TargetCreate):
    id: int
    agency: AgencyRead
    agent: AgentRead | None = None
    created_at: datetime | None = None
    created_by: int | None = None
    updated_by: int | None = None
    created_by_user: UserMiniRead | None = None
    updated_by_user: UserMiniRead | None = None

    model_config = {"from_attributes": True}


class ParReductionTargetCreate(BaseModel):
    agency_id: int
    agent_id: int
    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2000)
    target_par30: Decimal = Field(default=Decimal("0"), ge=0)
    target_cohort_1_15: Decimal = Field(default=Decimal("0"), ge=0)
    target_cohort_16_30: Decimal = Field(default=Decimal("0"), ge=0)


class ParReductionTargetRead(ParReductionTargetCreate):
    id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    agency: AgencyRead
    agent: AgentRead

    model_config = {"from_attributes": True}


class ParReductionAgencySummaryRead(BaseModel):
    agency_id: int
    agency_name: str
    agent_count: int = 0
    target_par30: Decimal = Decimal("0")
    target_cohort_1_15: Decimal = Decimal("0")
    target_cohort_16_30: Decimal = Decimal("0")
    initial_par30: Decimal = Decimal("0")
    initial_cohort_1_15: Decimal = Decimal("0")
    initial_cohort_16_30: Decimal = Decimal("0")
    reduction_required_par30: Decimal = Decimal("0")
    reduction_required_cohort_1_15: Decimal = Decimal("0")
    reduction_required_cohort_16_30: Decimal = Decimal("0")
    agents: list[ParReductionTargetRead] = Field(default_factory=list)


class ParReductionMetricRead(BaseModel):
    initial: Decimal = Decimal("0")
    current: Decimal = Decimal("0")
    target_to_reach: Decimal = Decimal("0")
    reduction_required: Decimal = Decimal("0")
    reduction_realized: Decimal = Decimal("0")
    achievement_rate: Decimal = Decimal("0")
    valid_target: bool = True
    message: str | None = None

    @property
    def initial_volume(self) -> Decimal:
        return self.initial

    @property
    def current_volume(self) -> Decimal:
        return self.current

    @property
    def reduction(self) -> Decimal:
        return self.reduction_realized

    @property
    def target(self) -> Decimal:
        return self.target_to_reach

    @property
    def remaining(self) -> Decimal:
        return self.target_to_reach - self.current


class ParReductionRead(BaseModel):
    period: dict[str, int]
    scope: dict[str, Any]
    metrics: dict[str, ParReductionMetricRead]
    global_achievement_rate: Decimal = Decimal("0")
    has_initial_snapshot: bool = False
    has_current_snapshot: bool = False
    initial_snapshot_date: date | None = None
    current_snapshot_date: date | None = None
    initial_snapshot_id: int | None = None
    current_snapshot_id: int | None = None
    target_par30: Decimal = Decimal("0")
    target_cohort_1_15: Decimal = Decimal("0")
    target_cohort_16_30: Decimal = Decimal("0")
    initial_par30: Decimal = Decimal("0")
    current_par30: Decimal = Decimal("0")
    reduction_par30: Decimal = Decimal("0")
    initial_cohort_1_15: Decimal = Decimal("0")
    current_cohort_1_15: Decimal = Decimal("0")
    reduction_cohort_1_15: Decimal = Decimal("0")
    initial_cohort_16_30: Decimal = Decimal("0")
    current_cohort_16_30: Decimal = Decimal("0")
    reduction_cohort_16_30: Decimal = Decimal("0")
    portfolio_comparison: list[dict[str, Any]] = Field(default_factory=list)


class BonusRuleCreate(BaseModel):
    name: str
    formula: dict[str, Any]
    is_active: bool = True


class BonusRuleRead(BonusRuleCreate):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class BonusCalculationRequest(BaseModel):
    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2000)
    bonus_rule_id: int


class BonusResultRead(BaseModel):
    id: int
    user_id: int
    bonus_rule_id: int
    month: int
    year: int
    amount: Decimal
    breakdown: dict[str, Any]
    calculated_at: datetime

    model_config = {"from_attributes": True}


class ComplaintCreate(BaseModel):
    subject: str
    message: str


class ComplaintRead(ComplaintCreate):
    id: int
    user_id: int
    status: ComplaintStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class ComplaintStatusUpdate(BaseModel):
    status: ComplaintStatus
