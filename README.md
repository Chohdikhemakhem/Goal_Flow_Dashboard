# MicroCred Performance Platform

Full-stack web application for MicroCred microfinance performance tracking, monthly targets, Excel loan imports, and configurable employee bonuses.

## Architecture

The system uses a daily snapshot architecture:

- Each Excel file is the end-of-day state of all loans.
- Raw rows are appended to `loans_raw`.
- Historical loan snapshots are preserved by default. A Super Admin can delete an erroneous `SNAPSHOT` batch after explicit confirmation.
- Aggregated KPIs are stored separately in `daily_metrics`.
- `UNIQUE(contract_no, snapshot_date)` prevents duplicate daily loan snapshots.

## Stack

- Backend: FastAPI, SQLAlchemy, PostgreSQL, JWT
- Frontend: React, Vite, Recharts
- Import: pandas/openpyxl
- Deployment: Docker Compose

## Quick Start

```bash
docker compose up --build
```

Services:

- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- Frontend: http://localhost:5173
- PostgreSQL: localhost:5432

Use the same hostname consistently during a session. For example, open the frontend at
`http://localhost:5173` when the API base is `http://localhost:8000`. Do not mix
`localhost` and `127.0.0.1`: authentication cookies intentionally use strict SameSite rules.

Before starting, define the required secrets in your environment or in `backend/.env`:

- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `POSTGRES_PASSWORD`

To bootstrap the very first Super Admin securely, also define:

- `BOOTSTRAP_SUPERADMIN_EMAIL`
- `BOOTSTRAP_SUPERADMIN_PASSWORD`
- `BOOTSTRAP_SUPERADMIN_FULL_NAME` (optional)

## Local Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python scripts/seed.py
uvicorn app.main:app --reload
```

## Local Frontend

```bash
cd frontend
npm install
npm run dev
```

## Production-ready containers

Two container modes are now provided:

- `docker-compose.yml` -> development stack
- `docker-compose.prod.yml` -> production-style stack

The production stack:

- serves the frontend as static assets,
- runs the backend without `--reload`,
- runs the backend as a non-root user,
- requires secrets to be injected through environment variables,
- disables FastAPI docs when `ENVIRONMENT=production`.

## Documentation

- [Architecture](docs/architecture.md)
- [API](docs/api.md)
- [Setup](docs/setup.md)

## Final local validation

Generate the consolidated QA reports from the latest code:

```bash
backend\.venv\Scripts\python.exe backend\scripts\generate_final_validation_reports.py
backend\.venv\Scripts\python.exe backend\scripts\generate_project_reports_pdf.py
backend\.venv\Scripts\python.exe backend\scripts\generate_consolidated_validation_pdf.py
```

The final shareable artifacts are written to `docs/reports/final`.

## Pre-deployment automation

Prepare the application before pre-production/production:

```bash
cd backend
.venv\Scripts\python.exe scripts/prepare_deployment.py --env preprod
```

Production mode:

```bash
cd backend
.venv\Scripts\python.exe scripts/prepare_deployment.py --env prod
```

Useful options:

- `--dry-run` to simulate execution
- `--skip-tests` to skip automated tests
- `--skip-backup` to skip backup creation
- `--skip-frontend-build` to skip frontend build

## Bonus module toggle

Use `BONUS_MODULE_ACTIVE` in `backend/.env`:

- `BONUS_MODULE_ACTIVE=false` -> disable Bonus module (test environment)
- `BONUS_MODULE_ACTIVE=true` -> enable Bonus module (preprod/production)

The default value is `false`. Keep the module disabled until the Bonus workflow has
completed its dedicated validation. Re-enable it only by explicitly setting
`BONUS_MODULE_ACTIVE=true`.

When disabled:

- `/api/v1/bonus/*` endpoints return `503 bonus_module_inactive`
- Bonus navigation stays visible with `En dev` badge; clicking opens an inactive screen and shows `Module en developpement`
- Portfolio Manager dashboard hides the "Bonus actuel" metric
