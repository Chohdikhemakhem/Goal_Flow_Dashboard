# Setup

## Docker

Run the full stack:

```bash
docker compose up --build
```

The backend container creates tables and seed data on startup.

For local browser usage, keep the hostname consistent:

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`

Do not alternate between `localhost` and `127.0.0.1` during the same session. The
authentication cookies use strict SameSite rules by design.

## Production Notes

- Replace `JWT_SECRET_KEY`.
- Use managed PostgreSQL with backups.
- Run migrations with Alembic before enabling production writes.
- Store uploaded import files in object storage if audit retention is required.
- Add a reverse proxy with TLS in front of API and frontend.

## Visualiser la base avec pgAdmin

Si vous lancez l'application en local avec `backend/.env`, la base active est SQLite:

- `DATABASE_URL=sqlite:///.../backend/dev_microcred.db`

Dans ce mode, la base n'apparaitra pas dans pgAdmin (pgAdmin affiche PostgreSQL uniquement).

Pour utiliser pgAdmin:

1. Demarrer PostgreSQL via Docker:

```bash
docker compose up -d db
```

2. Connecter pgAdmin avec:

- Host: `localhost`
- Port: `5432`
- Database: `microcred`
- Username: `microcred`
- Password: the value defined by `POSTGRES_PASSWORD`

3. Faire tourner le backend sur PostgreSQL (Docker compose complet) ou modifier `backend/.env` pour pointer vers PostgreSQL.

## Backfill snapshot dates

Pour completer `snapshot_date` des anciens batches `SNAPSHOT`:

```bash
cd backend
.venv\Scripts\python.exe scripts\backfill_snapshot_dates.py
```

## Final QA report generation

From the project root:

```bash
backend\.venv\Scripts\python.exe backend\scripts\generate_final_validation_reports.py
backend\.venv\Scripts\python.exe backend\scripts\generate_project_reports_pdf.py
backend\.venv\Scripts\python.exe backend\scripts\generate_consolidated_validation_pdf.py
```

The unique final artifacts are written to `docs/reports/final`.
