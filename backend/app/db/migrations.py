from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


TARGET_COLUMNS = {
    "target_disbursement_count": "INTEGER DEFAULT 0 NOT NULL",
    "target_nb_clients": "INTEGER DEFAULT 0 NOT NULL",
    "target_par_0": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
    "target_par_1_30": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
    "target_par_31_60": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
    "target_par_30": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
    "target_type": "VARCHAR(16) DEFAULT 'AGENCY' NOT NULL",
    "agent_id": "INTEGER",
    "active_from": "DATE",
    "active_until": "DATE",
    "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL",
    "updated_at": "TIMESTAMP",
    "created_by": "INTEGER",
    "updated_by": "INTEGER",
}

PAR_REDUCTION_TARGET_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS par_reduction_targets (
    id INTEGER NOT NULL PRIMARY KEY,
    agency_id INTEGER NOT NULL REFERENCES agencies(id),
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    month INTEGER NOT NULL,
    year INTEGER NOT NULL,
    target_par30 NUMERIC(18, 2) NOT NULL DEFAULT 0,
    target_cohort_1_15 NUMERIC(18, 2) NOT NULL DEFAULT 0,
    target_cohort_16_30 NUMERIC(18, 2) NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_par_reduction_target_agent_period UNIQUE (agent_id, month, year)
)
"""

LOANS_RAW_COLUMNS = {
    "client_name": "VARCHAR(255)",
    "client_first_name": "VARCHAR(255)",
    "client_ncni": "VARCHAR(120)",
    "client_rating": "VARCHAR(100)",
    "category_desc": "VARCHAR(255)",
    "teg_rate": "NUMERIC(10, 4) DEFAULT 0 NOT NULL",
    "principal_due": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
    "interest_due_amt": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
    "total_scheduled_amount": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
    "maturity_date": "DATE",
    "next_schedule_date": "DATE",
    "import_batch_id": "INTEGER",
}

DAILY_METRIC_COLUMNS = {
    "nb_clients": "INTEGER DEFAULT 0 NOT NULL",
    "par_1_15": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
    "par_16_30": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
    "par_61_90": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
    "par_91_120": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
    "par_120": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
}

USER_COLUMNS = {
    "session_nonce": "INTEGER DEFAULT 0 NOT NULL",
    "failed_login_attempts": "INTEGER DEFAULT 0 NOT NULL",
    "locked_until": "TIMESTAMP",
    "password_changed_at": "TIMESTAMP",
    "temporary_password": "VARCHAR(255)",
    "excluded_from_gp_mcr_audit_at": "TIMESTAMP",
    "excluded_from_gp_mcr_audit_by_user_id": "INTEGER",
}

IMPORT_BATCH_COLUMNS = {
    "period": "VARCHAR(7)",
    "snapshot_date": "DATE",
    "file_name": "VARCHAR(255)",
}

RESTRUCTURED_CONTRACT_COLUMNS = {
    "normalized_contract_no": "VARCHAR(100)",
    "credit_family": "VARCHAR(24)",
    "source": "VARCHAR(40)",
    "completed_by_user_id": "INTEGER",
    "completed_at": "TIMESTAMP",
    "excluded_from_missing_mcr_at": "TIMESTAMP",
    "excluded_from_missing_mcr_by_user_id": "INTEGER",
}

RESTRUCTURED_IMPORT_LOG_COLUMNS = {
    "inserted_count": "INTEGER",
    "updated_count": "INTEGER",
    "deleted_count": "INTEGER",
    "recalculated_contracts": "INTEGER",
    "progress_percent": "INTEGER",
    "phase": "VARCHAR(40)",
    "source_rows_seen": "INTEGER",
    "ignored_rows_count": "INTEGER",
    "rows_per_second": "NUMERIC(12, 2)",
    "eta_seconds": "NUMERIC(12, 2)",
    "memory_peak_mb": "NUMERIC(12, 2)",
    "last_activity_at": "TIMESTAMP",
    "phase_details": "TEXT",
}

PENDING_RESTRUCTURED_CONTRACT_INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS ix_pending_restructured_contracts_credit_family ON pending_restructured_contracts (credit_family)",
    "CREATE INDEX IF NOT EXISTS ix_pending_restructured_contracts_status ON pending_restructured_contracts (status)",
    "CREATE INDEX IF NOT EXISTS ix_pending_restructured_contracts_detected_from_import ON pending_restructured_contracts (detected_from_import)",
    "CREATE INDEX IF NOT EXISTS ix_pending_restructured_contracts_agency_name ON pending_restructured_contracts (agency_name)",
    "CREATE INDEX IF NOT EXISTS ix_pending_restructured_contracts_agent_name ON pending_restructured_contracts (agent_name)",
]

ACM_RATE_VERSION_COLUMNS = {
    "effective_start_date": "DATE",
    "effective_end_date": "DATE",
    "is_open_ended": "BOOLEAN DEFAULT FALSE NOT NULL",
    "status": "VARCHAR(20) DEFAULT 'historique' NOT NULL",
    "comment": "TEXT",
}

RESTRUCTURED_INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS ix_restructured_contracts_normalized_contract_no ON restructured_contracts (normalized_contract_no)",
    "CREATE INDEX IF NOT EXISTS ix_restructured_contracts_credit_family ON restructured_contracts (credit_family)",
    "CREATE INDEX IF NOT EXISTS ix_restructured_contracts_excluded_from_missing_mcr_at ON restructured_contracts (excluded_from_missing_mcr_at)",
    "CREATE INDEX IF NOT EXISTS ix_restructured_schedule_rows_account_number ON restructured_schedule_rows (account_number)",
    "CREATE INDEX IF NOT EXISTS ix_restructured_schedule_rows_due_date ON restructured_schedule_rows (due_date)",
    "CREATE INDEX IF NOT EXISTS ix_restructured_schedule_rows_account_due_date ON restructured_schedule_rows (account_number, due_date)",
    "CREATE INDEX IF NOT EXISTS ix_restructured_schedule_rows_agency_name ON restructured_schedule_rows (agency_name)",
    "CREATE INDEX IF NOT EXISTS ix_restructured_schedule_rows_agent_name ON restructured_schedule_rows (agent_name)",
]


def _add_columns_if_missing(connection, table_name: str, columns: dict[str, str]) -> None:
    inspector = inspect(connection)
    if table_name not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    for name, definition in columns.items():
        if name not in existing:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}"))


def _migrate_par_reduction_targets(connection) -> None:
    inspector = inspect(connection)
    if "par_reduction_targets" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("par_reduction_targets")}
    legacy_columns = {
        "target_par30_reduction": "legacy_target_par30_reduction",
        "target_cohort_1_15_reduction": "legacy_target_cohort_1_15_reduction",
        "target_cohort_16_30_reduction": "legacy_target_cohort_16_30_reduction",
    }
    for old_name, legacy_name in legacy_columns.items():
        if old_name in columns and legacy_name not in columns:
            connection.execute(text(f"ALTER TABLE par_reduction_targets RENAME COLUMN {old_name} TO {legacy_name}"))
            columns.remove(old_name)
            columns.add(legacy_name)

    # Legacy reduction values are retained for historical compatibility only.
    # New records deliberately leave them NULL because target_* now means the
    # level to reach, not the reduction volume.
    if connection.dialect.name == "postgresql":
        for legacy_name in legacy_columns.values():
            if legacy_name in columns:
                connection.execute(
                    text(
                        f"ALTER TABLE par_reduction_targets "
                        f"ALTER COLUMN {legacy_name} DROP NOT NULL"
                    )
                )
    _add_columns_if_missing(
        connection,
        "par_reduction_targets",
        {
            "target_par30": "NUMERIC(18, 2) NOT NULL DEFAULT 0",
            "target_cohort_1_15": "NUMERIC(18, 2) NOT NULL DEFAULT 0",
            "target_cohort_16_30": "NUMERIC(18, 2) NOT NULL DEFAULT 0",
            "target_levels_migrated": "BOOLEAN NOT NULL DEFAULT FALSE",
        },
    )
    if not all(name in columns for name in legacy_columns.values()):
        return
    rows = connection.execute(
        text(
            "SELECT id, agency_id, agent_id, month, year, "
            "legacy_target_par30_reduction, legacy_target_cohort_1_15_reduction, "
            "legacy_target_cohort_16_30_reduction FROM par_reduction_targets "
            "WHERE target_levels_migrated = FALSE "
            "AND legacy_target_par30_reduction IS NOT NULL "
            "AND legacy_target_cohort_1_15_reduction IS NOT NULL "
            "AND legacy_target_cohort_16_30_reduction IS NOT NULL"
        )
    ).mappings().all()
    for row in rows:
        period_start = f"{int(row['year']):04d}-{int(row['month']):02d}-01"
        batch_id = connection.execute(
            text(
                "SELECT id FROM import_batches "
                "WHERE batch_type IN ('HISTORICAL_MONTH', 'SNAPSHOT', 'CURRENT_STATE') "
                "AND snapshot_date < :period_start "
                "ORDER BY snapshot_date DESC, imported_at DESC, id DESC LIMIT 1"
            ),
            {"period_start": period_start},
        ).scalar()
        if batch_id is None:
            continue
        initial_row = connection.execute(
            text(
                "SELECT "
                "COALESCE(SUM(CASE WHEN lr.days_overdue > 30 THEN COALESCE(lr.principal_outstanding, 0) + COALESCE(lr.principal_due, 0) ELSE 0 END), 0) AS par30, "
                "COALESCE(SUM(CASE WHEN lr.days_overdue > 0 AND lr.days_overdue <= 15 THEN COALESCE(lr.principal_outstanding, 0) + COALESCE(lr.principal_due, 0) ELSE 0 END), 0) AS cohort_1_15, "
                "COALESCE(SUM(CASE WHEN lr.days_overdue >= 16 AND lr.days_overdue <= 30 THEN COALESCE(lr.principal_outstanding, 0) + COALESCE(lr.principal_due, 0) ELSE 0 END), 0) AS cohort_16_30 "
                "FROM loans_raw lr "
                "JOIN agencies a ON a.name = lr.agency_name "
                "JOIN agents ag ON ag.agency_id = a.id AND LOWER(TRIM(ag.name)) = LOWER(TRIM(lr.agent_name)) "
                "WHERE lr.import_batch_id = :batch_id AND a.id = :agency_id AND ag.id = :agent_id"
            ),
            {"batch_id": batch_id, "agency_id": row["agency_id"], "agent_id": row["agent_id"]},
        ).mappings().one()
        converted = {
            "target_par30": max(initial_row["par30"] - (row["legacy_target_par30_reduction"] or 0), 0),
            "target_cohort_1_15": max(initial_row["cohort_1_15"] - (row["legacy_target_cohort_1_15_reduction"] or 0), 0),
            "target_cohort_16_30": max(initial_row["cohort_16_30"] - (row["legacy_target_cohort_16_30_reduction"] or 0), 0),
        }
        connection.execute(
            text(
                "UPDATE par_reduction_targets SET target_par30 = :target_par30, "
                "target_cohort_1_15 = :target_cohort_1_15, "
                "target_cohort_16_30 = :target_cohort_16_30, "
                "target_levels_migrated = TRUE "
                "WHERE id = :id"
            ),
            {**converted, "id": row["id"]},
        )


def _rebuild_targets_sqlite(connection) -> None:
    inspector = inspect(connection)
    existing_cols = {column["name"] for column in inspector.get_columns("targets")}

    # Ensure optional legacy columns exist before copy expression generation.
    connection.execute(text("PRAGMA foreign_keys=OFF"))
    connection.execute(text("ALTER TABLE targets RENAME TO targets_old"))
    connection.execute(
        text(
            """
            CREATE TABLE targets (
                id INTEGER NOT NULL,
                target_type VARCHAR(16) NOT NULL DEFAULT 'AGENCY',
                agency_id INTEGER NOT NULL,
                agent_id INTEGER,
                month INTEGER NOT NULL,
                year INTEGER NOT NULL,
                active_from DATE,
                active_until DATE,
                target_disbursement_count INTEGER NOT NULL DEFAULT 0,
                target_nb_clients INTEGER NOT NULL DEFAULT 0,
                target_disbursement NUMERIC(18, 2) NOT NULL DEFAULT 0,
                target_outstanding NUMERIC(18, 2) NOT NULL DEFAULT 0,
                target_par NUMERIC(8, 4) NOT NULL DEFAULT 0,
                target_healthy_outstanding NUMERIC(18, 2) NOT NULL DEFAULT 0,
                target_par_0 NUMERIC(18, 2) NOT NULL DEFAULT 0,
                target_par_1_30 NUMERIC(18, 2) NOT NULL DEFAULT 0,
                target_par_31_60 NUMERIC(18, 2) NOT NULL DEFAULT 0,
                target_par_30 NUMERIC(18, 2) NOT NULL DEFAULT 0,
                PRIMARY KEY (id),
                CONSTRAINT uq_target_agent_scope UNIQUE (target_type, agent_id, month, year),
                FOREIGN KEY(agency_id) REFERENCES agencies (id),
                FOREIGN KEY(agent_id) REFERENCES agents (id)
            )
            """
        )
    )

    def column_expr(name: str, fallback: str) -> str:
        return name if name in existing_cols else fallback

    connection.execute(
        text(
            f"""
            INSERT INTO targets (
                id, target_type, agency_id, agent_id, month, year,
                active_from, active_until,
                target_disbursement_count, target_nb_clients, target_disbursement,
                target_outstanding, target_par, target_healthy_outstanding,
                target_par_0, target_par_1_30, target_par_31_60, target_par_30
            )
            SELECT
                {column_expr("id", "NULL")},
                {column_expr("target_type", "'AGENCY'")},
                {column_expr("agency_id", "NULL")},
                {column_expr("agent_id", "NULL")},
                {column_expr("month", "1")},
                {column_expr("year", "2000")},
                {column_expr("active_from", "NULL")},
                {column_expr("active_until", "NULL")},
                {column_expr("target_disbursement_count", "0")},
                {column_expr("target_nb_clients", "0")},
                {column_expr("target_disbursement", "0")},
                {column_expr("target_outstanding", "0")},
                {column_expr("target_par", "0")},
                {column_expr("target_healthy_outstanding", "0")},
                {column_expr("target_par_0", "0")},
                {column_expr("target_par_1_30", "0")},
                {column_expr("target_par_31_60", "0")},
                {column_expr("target_par_30", "0")}
            FROM targets_old
            """
        )
    )
    connection.execute(text("DROP TABLE targets_old"))
    connection.execute(text("PRAGMA foreign_keys=ON"))


def _migrate_targets(connection, engine: Engine) -> None:
    inspector = inspect(connection)
    if "targets" not in inspector.get_table_names():
        return

    if engine.dialect.name == "sqlite":
        table_sql = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='targets'")
        ).scalar() or ""
        schema_ok = (
            "target_type" in table_sql
            and "agent_id" in table_sql
            and "uq_target_agent_scope" in table_sql
        )
        if not schema_ok:
            _rebuild_targets_sqlite(connection)
            return
        _add_columns_if_missing(connection, "targets", TARGET_COLUMNS)
        return

    _add_columns_if_missing(connection, "targets", TARGET_COLUMNS)
    constraint_names = {c["name"] for c in inspect(connection).get_unique_constraints("targets")}
    if "uq_target_month" in constraint_names:
        connection.execute(text("ALTER TABLE targets DROP CONSTRAINT uq_target_month"))
    if "uq_target_agency_scope" in constraint_names:
        connection.execute(text("ALTER TABLE targets DROP CONSTRAINT uq_target_agency_scope"))
    if "uq_target_agent_scope" not in constraint_names:
        connection.execute(
            text(
                "ALTER TABLE targets ADD CONSTRAINT uq_target_agent_scope "
                "UNIQUE (target_type, agent_id, month, year)"
            )
        )


def _migrate_import_batches(connection, engine: Engine) -> None:
    inspector = inspect(connection)
    if "import_batches" not in inspector.get_table_names():
        return

    _add_columns_if_missing(connection, "import_batches", IMPORT_BATCH_COLUMNS)
    if engine.dialect.name != "postgresql":
        return

    enum_names = {item.get("name") for item in inspector.get_enums() if item.get("name")}
    for enum_type in ("importbatchtype", "import_batch_type", "importbatchtype_enum"):
        if enum_type not in enum_names:
            continue
        connection.execute(text(f"ALTER TYPE {enum_type} ADD VALUE IF NOT EXISTS 'SNAPSHOT'"))
        return


def _migrate_user_roles(connection, engine: Engine) -> None:
    inspector = inspect(connection)
    if "users" not in inspector.get_table_names():
        return

    if engine.dialect.name == "postgresql":
        enum_names = {item.get("name") for item in inspector.get_enums() if item.get("name")}
        for enum_type in ("userrole", "user_role", "userrole_enum"):
            if enum_type not in enum_names:
                continue
            connection.execute(text(f"ALTER TYPE {enum_type} ADD VALUE IF NOT EXISTS 'SUPER_ADMIN'"))
            connection.execute(text(f"ALTER TYPE {enum_type} ADD VALUE IF NOT EXISTS 'SUPPORT'"))
            connection.execute(text(f"ALTER TYPE {enum_type} ADD VALUE IF NOT EXISTS 'COMMITTEE_MEMBER'"))
            break
        # Do not update rows to SUPER_ADMIN in the same transaction as ALTER TYPE.
        # PostgreSQL requires a commit boundary before the new enum value can be used.
        return

    # Promote legacy full-access admins (old microcredapp/local accounts) to SUPER_ADMIN.
    connection.execute(
        text(
            """
            UPDATE users
            SET role = 'SUPER_ADMIN'
            WHERE LOWER(role) = 'admin'
              AND (
                    LOWER(email) LIKE '%@microcredapp.com'
                 OR LOWER(email) LIKE '%@microcred.local'
              )
            """
        )
    )


def _rebuild_users_sqlite(connection) -> None:
    inspector = inspect(connection)
    existing_cols = {column["name"] for column in inspector.get_columns("users")}

    connection.execute(text("PRAGMA foreign_keys=OFF"))
    connection.execute(text("ALTER TABLE users RENAME TO users_old"))
    connection.execute(
        text(
            """
            CREATE TABLE users (
                id INTEGER NOT NULL,
                email VARCHAR(255) NOT NULL,
                full_name VARCHAR(255) NOT NULL,
                hashed_password VARCHAR(255) NOT NULL,
                role VARCHAR(32) NOT NULL,
                agency_id INTEGER,
                agent_id INTEGER,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                session_nonce INTEGER NOT NULL DEFAULT 0,
                failed_login_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TIMESTAMP,
                password_changed_at TIMESTAMP,
                must_change_password BOOLEAN NOT NULL DEFAULT 1,
                temporary_password VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                UNIQUE (email),
                FOREIGN KEY(agency_id) REFERENCES agencies (id),
                FOREIGN KEY(agent_id) REFERENCES agents (id)
            )
            """
        )
    )

    def column_expr(name: str, fallback: str) -> str:
        return name if name in existing_cols else fallback

    connection.execute(
        text(
            f"""
            INSERT INTO users (
                id, email, full_name, hashed_password, role, agency_id, agent_id,
                is_active, session_nonce, failed_login_attempts, locked_until, password_changed_at,
                must_change_password, temporary_password, created_at
            )
            SELECT
                {column_expr("id", "NULL")},
                {column_expr("email", "''")},
                {column_expr("full_name", "''")},
                {column_expr("hashed_password", "''")},
                {column_expr("role", "'portfolio_manager'")},
                {column_expr("agency_id", "NULL")},
                {column_expr("agent_id", "NULL")},
                {column_expr("is_active", "1")},
                {column_expr("session_nonce", "0")},
                {column_expr("failed_login_attempts", "0")},
                {column_expr("locked_until", "NULL")},
                {column_expr("password_changed_at", "NULL")},
                {column_expr("must_change_password", "CASE WHEN UPPER(CAST(role AS VARCHAR)) = 'SUPER_ADMIN' THEN 0 ELSE 1 END")},
                {column_expr("temporary_password", "NULL")},
                {column_expr("created_at", "CURRENT_TIMESTAMP")}
            FROM users_old
            """
        )
    )
    connection.execute(text("DROP TABLE users_old"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_users_email ON users (email)"))
    connection.execute(text("PRAGMA foreign_keys=ON"))


def _migrate_users(connection, engine: Engine) -> None:
    inspector = inspect(connection)
    if "users" not in inspector.get_table_names():
        return

    if engine.dialect.name == "sqlite":
        table_sql = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'")
        ).scalar() or ""
        needs_rebuild = (
            "initial_password" in table_sql
            or "failed_login_attempts" not in table_sql
            or "session_nonce" not in table_sql
        )
        if needs_rebuild:
            _rebuild_users_sqlite(connection)
            return

    _add_columns_if_missing(connection, "users", USER_COLUMNS)
    existing_columns = {column["name"] for column in inspect(connection).get_columns("users")}
    if "must_change_password" not in existing_columns:
        connection.execute(
            text("ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT TRUE NOT NULL")
        )
        connection.execute(
            text(
                """
                UPDATE users
                SET must_change_password = CASE
                    WHEN UPPER(CAST(role AS VARCHAR)) = 'SUPER_ADMIN' THEN FALSE
                    ELSE TRUE
                END
                """
            )
        )

    if engine.dialect.name == "postgresql":
        connection.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS initial_password"))


def _ensure_restructured_indexes(connection) -> None:
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    if "restructured_contracts" not in existing_tables or "restructured_schedule_rows" not in existing_tables:
        return
    for statement in RESTRUCTURED_INDEX_STATEMENTS:
        connection.execute(text(statement))
    if "pending_restructured_contracts" in existing_tables:
        for statement in PENDING_RESTRUCTURED_CONTRACT_INDEX_STATEMENTS:
            connection.execute(text(statement))


def _migrate_acm_rate_versions(connection) -> None:
    inspector = inspect(connection)
    if "acm_rate_versions" not in inspector.get_table_names():
        return

    _add_columns_if_missing(connection, "acm_rate_versions", ACM_RATE_VERSION_COLUMNS)
    existing_columns = {column["name"] for column in inspector.get_columns("acm_rate_versions")}

    created_at_expr = "DATE(created_at)" if "created_at" in existing_columns else "CURRENT_DATE"
    if "effective_start_date" in {column["name"] for column in inspect(connection).get_columns("acm_rate_versions")}:
        connection.execute(
            text(
                f"""
                UPDATE acm_rate_versions
                SET effective_start_date = COALESCE(effective_start_date, {created_at_expr})
                WHERE effective_start_date IS NULL
                """
            )
        )

    connection.execute(
        text(
            """
            UPDATE acm_rate_versions
            SET is_open_ended = CASE
                WHEN effective_end_date IS NULL THEN TRUE
                ELSE COALESCE(is_open_ended, FALSE)
            END
            WHERE is_open_ended IS NULL
            """
        )
    )

    connection.execute(
        text(
            """
            UPDATE acm_rate_versions
            SET status = CASE
                WHEN effective_end_date IS NOT NULL AND effective_end_date < CURRENT_DATE THEN 'historique'
                WHEN effective_end_date IS NULL THEN COALESCE(status, 'actif')
                WHEN effective_start_date IS NOT NULL AND effective_start_date > CURRENT_DATE THEN 'actif'
                ELSE status
            END
            WHERE status IS NULL OR TRIM(status) = ''
            """
        )
    )


def add_missing_columns(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(PAR_REDUCTION_TARGET_TABLE_SQL))
        _migrate_par_reduction_targets(connection)
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_par_reduction_target_agent_period_idx "
                "ON par_reduction_targets (agent_id, month, year)"
            )
        )
        for table_name, columns in {
            "loans_raw": LOANS_RAW_COLUMNS,
            "daily_metrics": DAILY_METRIC_COLUMNS,
            "restructured_contracts": RESTRUCTURED_CONTRACT_COLUMNS,
            "restructured_import_logs": RESTRUCTURED_IMPORT_LOG_COLUMNS,
        }.items():
            _add_columns_if_missing(connection, table_name, columns)
        _migrate_import_batches(connection, engine)
        _migrate_targets(connection, engine)
        _migrate_user_roles(connection, engine)
        _migrate_users(connection, engine)
        _migrate_acm_rate_versions(connection)
        _ensure_restructured_indexes(connection)
