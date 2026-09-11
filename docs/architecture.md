# Architecture

MicroCred is organized around immutable daily snapshots and import batches.

## Data Flow

1. A user uploads the Excel end-of-day loan file.
2. The import service validates required columns and row values.
3. If importing `CURRENT_STATE`:
   - previous `CURRENT_STATE` batches are archived as `SNAPSHOT` (or replaced if same `DateEOD`).
   - the new file becomes the single active `CURRENT_STATE`.
4. If importing `HISTORICAL_MONTH`:
   - snapshots from the same month are removed automatically.
   - the historical monthly closure file is saved for that period.
5. Rows are inserted into `loans_raw` using `(contract_no, snapshot_date)` as uniqueness boundary.
6. KPI aggregation runs for the imported snapshot date.
7. Aggregated rows are stored in `daily_metrics` per agency, agent, and date.
8. Dashboards, target comparisons, reports, and bonus calculations read from scoped data.

## Core Rule

Raw loan data and daily metrics are separate. Aggregates are recalculated idempotently from the imported raw batch. Dashboard comparisons use explicit batch origins (`CURRENT_STATE`, `HISTORICAL_MONTH`, selected `SNAPSHOT`) without mixing data across batches.

## Modules

- `app/api`: API routers and request handling
- `app/core`: settings, logging, security
- `app/db`: database session and base metadata
- `app/models`: SQLAlchemy models
- `app/schemas`: Pydantic schemas
- `app/services`: import, KPI, bonus, reporting business logic

## Database Class Diagram

```mermaid
classDiagram
  class Agency {
    +id: int
    +name: string
    +created_at: datetime
  }

  class Agent {
    +id: int
    +name: string
    +agency_id: int
    +created_at: datetime
  }

  class User {
    +id: int
    +email: string
    +full_name: string
    +role: enum
    +agency_id: int?
    +agent_id: int?
    +is_active: bool
    +created_at: datetime
  }

  class ImportBatch {
    +id: int
    +batch_type: CURRENT_STATE|HISTORICAL_MONTH|SNAPSHOT
    +period: string?
    +snapshot_date: date
    +file_name: string
    +imported_at: datetime
  }

  class LoanRaw {
    +id: int
    +contract_no: string
    +client_id: string
    +agency_name: string
    +agent_name: string
    +disbursement_amount: decimal
    +principal_outstanding: decimal
    +principal_due: decimal
    +days_overdue: int
    +total_due: decimal
    +status: string
    +disbursement_date: date
    +snapshot_date: date
    +import_batch_id: int?
  }

  class DailyMetric {
    +id: int
    +agency_id: int
    +agent_id: int
    +date: date
    +disbursement_count: int
    +disbursement_volume: decimal
    +nb_clients: int
    +outstanding: decimal
    +healthy_outstanding: decimal
    +par_0: decimal
    +par_1_30: decimal
    +par_31_60: decimal
    +par_30: decimal
  }

  class Target {
    +id: int
    +target_type: AGENCY|AGENT
    +agency_id: int
    +agent_id: int?
    +month: int
    +year: int
    +target_disbursement_count: int
    +target_nb_clients: int
    +target_disbursement: decimal
    +target_outstanding: decimal
    +target_par: decimal
    +target_healthy_outstanding: decimal
  }

  class BonusRule {
    +id: int
    +name: string
    +formula: json
    +is_active: bool
  }

  class BonusResult {
    +id: int
    +user_id: int
    +bonus_rule_id: int
    +month: int
    +year: int
    +amount: decimal
    +breakdown: json
  }

  class Complaint {
    +id: int
    +user_id: int
    +subject: string
    +message: text
    +status: enum
    +created_at: datetime
  }

  Agency "1" --> "many" Agent
  Agency "1" --> "many" User
  Agency "1" --> "many" DailyMetric
  Agency "1" --> "many" Target

  Agent "1" --> "many" User
  Agent "1" --> "many" DailyMetric
  Agent "1" --> "many" Target

  ImportBatch "1" --> "many" LoanRaw

  User "1" --> "many" Complaint
  User "1" --> "many" BonusResult
  BonusRule "1" --> "many" BonusResult
```
