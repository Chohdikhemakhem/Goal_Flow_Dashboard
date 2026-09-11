# API Endpoints

All collection endpoints support pagination using `limit` and `offset`.

## Auth

- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`

## Imports

- `GET /api/v1/imports/batches`
- `POST /api/v1/imports/current-state`
- `POST /api/v1/imports/historical`
- `POST /api/v1/imports/loans` (legacy alias)

Uploads an Excel file containing loan-level data. Required columns:

- `CONTRACT_NO`
- `CLIENT_NO`
- `BRANCH`
- `DAO_NAME`
- `DISBURSEMENT_AMOUNT`
- `PRINCIPAL_OUTSTANDING`
- `TOTAL_PRINCIPAL_DUE_AMT`
- `TOTAL_CUR_NO_OF_DAYS_OVERDUE`
- `TOTAL_DUE_AMT`
- `DISBURSEMENT_DATE`
- `DateEOD`

Historical import requires:

- `period` in `MM/YYYY` or `YYYY-MM`
- optional `replace_existing=true` to replace an already imported month

## Metrics

- `GET /api/v1/metrics/daily?agency_id=&agent_id=&date_from=&date_to=&limit=&offset=`
- `GET /api/v1/metrics/current-credits?agency_id=&agent_id=&date_from=&date_to=&q=&limit=&offset=`
- `GET /api/v1/metrics/summary?agency_id=&agent_id=&date_from=&date_to=`
- `GET /api/v1/metrics/charts?agency_id=&agent_id=&months=&snapshot_batch_ids=`
- `GET /api/v1/metrics/snapshots?agency_id=&agent_id=`
- `GET /api/v1/metrics/portfolio-performance` (portfolio manager dashboard widget)

## Targets

- `GET /api/v1/targets?target_type=&agency_id=&agent_id=&month=&year=&limit=&offset=`
- `POST /api/v1/targets`
- `PUT /api/v1/targets/{target_id}`
- `DELETE /api/v1/targets/{target_id}`

## Bonus

- `GET /api/v1/bonus/rules`
- `POST /api/v1/bonus/rules`
- `POST /api/v1/bonus/calculate`
- `GET /api/v1/bonus/results`

## Users

- `GET /api/v1/users`
- `POST /api/v1/users`

## Complaints

- `GET /api/v1/complaints`
- `POST /api/v1/complaints`
