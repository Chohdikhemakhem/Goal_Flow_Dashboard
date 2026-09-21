from datetime import date
from decimal import Decimal
from io import BytesIO

from fastapi import HTTPException
from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.entities import Agency, Target, User
from app.models.enums import TargetType, UserRole
from app.services.objective_excel_import import (
    COHORT_HEADERS,
    DATA_HEADERS,
    build_objective_import_preview,
    import_objectives,
    parse_objectives_excel,
)
from app.api.v1.targets import _ensure_objective_excel_import_permission


def make_workbook(rows, headers=DATA_HEADERS, title="Objectif Septembre 2026"):
    workbook = Workbook()
    sheet = workbook.active
    # Exact workbook contract: title line, real headers line, then agencies.
    sheet.append(["Agence/Cohorte", title])
    sheet.append([None, *headers])
    for row in rows:
        sheet.append(row)
    content = BytesIO()
    workbook.save(content)
    return content.getvalue()


def values(agency, total=Decimal("1389650"), healthy=Decimal("11279158")):
    # Excel stores percentage cells as their ratio when formatted as percentages.
    return [agency, Decimal("11"), Decimal("22"), Decimal("3"), Decimal("4"), Decimal("5"), Decimal("6"), Decimal("7"), Decimal("8"), Decimal("9"), Decimal("10"), Decimal("11"), Decimal("12"), total, healthy, "=N3/(N3+O3)", Decimal("0.0617")]


def test_parser_detects_period_and_uses_required_objective_formulas():
    period, rows = parse_objectives_excel(make_workbook([values("Bizerte")]), "objectifs.xlsx")

    assert period == (9, 2026)
    assert rows[0]["target_par_1_30"] == Decimal("11")
    assert rows[0]["target_par_31_60"] == Decimal("22")
    assert rows[0]["target_par_30"] == Decimal("97")  # [1-30] is intentionally excluded
    assert rows[0]["target_outstanding"] == Decimal("12668808")
    assert rows[0]["target_healthy_outstanding"] == Decimal("11279158")
    assert rows[0]["target_par_0"] == Decimal("1389650") / Decimal("12668808")
    assert rows[0]["target_par"] == Decimal("0.0617")


def test_preview_ignores_total_and_reports_unknown_agency():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        session.add(Agency(name="BEJA"))
        session.commit()
        preview = build_objective_import_preview(
            session, make_workbook([values("BEJA "), values("TOTAL"), values("Inconnue")]), "objectifs.xlsx"
        )

    assert preview["detected_agencies"] == 2
    assert preview["valid_agencies"] == 1
    assert preview["unknown_agencies"] == 1
    assert preview["rows"][0]["agency_name"] == "BEJA"


def test_missing_required_column_is_rejected():
    headers = tuple(header for header in DATA_HEADERS if header != "Encours sain")
    try:
        parse_objectives_excel(make_workbook([], headers=headers), "objectifs.xlsx")
    except ValueError as exc:
        assert "Colonne obligatoire manquante : Encours sain" in str(exc)
    else:
        raise AssertionError("Expected the required-header validation to fail")


def test_import_creates_all_valid_agencies_in_one_transaction():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    agency_names = [f"Agence {index}" for index in range(1, 21)]
    with Session(engine) as session:
        actor = User(email="admin20@example.test", full_name="Admin", hashed_password="x", role=UserRole.SUPER_ADMIN)
        session.add_all([*(Agency(name=name) for name in agency_names), actor])
        session.commit()
        result = import_objectives(
            session, make_workbook([values(name) for name in agency_names]), "objectifs.xlsx", actor, "update", None, None
        )
        created_count = len(session.scalars(select(Target).where(Target.target_type == TargetType.AGENCY)).all())

    assert result["imported"] == 20
    assert created_count == 20


def test_update_preserves_fields_absent_from_excel_and_skip_keeps_existing_target():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    content = make_workbook([values("Bizerte")])
    with Session(engine) as session:
        agency = Agency(name="Bizerte")
        actor = User(email="admin@example.test", full_name="Admin", hashed_password="x", role=UserRole.SUPER_ADMIN)
        session.add_all([agency, actor])
        session.flush()
        target = Target(
            target_type=TargetType.AGENCY, agency_id=agency.id, month=9, year=2026,
            active_from=date(2026, 9, 1), active_until=date(2026, 9, 30),
            target_disbursement_count=25, target_nb_clients=44, target_disbursement=Decimal("500"),
            target_outstanding=Decimal("1"), target_par=Decimal("0.2"),
        )
        session.add(target)
        session.commit()

        result = import_objectives(session, content, "objectifs.xlsx", actor, "update", None, None)
        updated = session.scalar(select(Target).where(Target.id == target.id))
        assert result["updated"] == 1
        assert updated.target_disbursement_count == 25
        assert updated.target_nb_clients == 44
        assert updated.target_disbursement == Decimal("500")
        assert updated.target_outstanding == Decimal("12668808")

        import_objectives(session, make_workbook([values("Bizerte", total=Decimal("9"), healthy=Decimal("1"))]), "objectifs.xlsx", actor, "skip", None, None)
        skipped = session.scalar(select(Target).where(Target.id == target.id))
        assert skipped.target_outstanding == Decimal("12668808")


def test_only_super_admin_can_import_agency_objectives():
    try:
        _ensure_objective_excel_import_permission(User(role=UserRole.AGENCY_MANAGER))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("Expected the import permission check to reject an agency manager")
