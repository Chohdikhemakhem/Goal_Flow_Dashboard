from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Image,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "docs" / "reports" / "final"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

EXCLUDE_PARTS = {"node_modules", "dist", ".venv", "__pycache__"}


@dataclass
class FSItem:
    rel: str
    is_dir: bool


def _iter_items(root: Path) -> tuple[list[FSItem], list[FSItem]]:
    dirs: list[FSItem] = []
    files: list[FSItem] = []
    for path in root.rglob("*"):
        parts = set(path.parts)
        if EXCLUDE_PARTS.intersection(parts):
            continue
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            dirs.append(FSItem(rel=rel, is_dir=True))
        else:
            files.append(FSItem(rel=rel, is_dir=False))
    dirs.sort(key=lambda x: x.rel)
    files.sort(key=lambda x: x.rel)
    return dirs, files


def _module_owner(rel: str) -> str:
    if rel.startswith("backend/app/api/"):
        return "Backend API Layer"
    if rel.startswith("backend/app/services/"):
        return "Backend Service Layer"
    if rel.startswith("backend/app/models/"):
        return "Data Model Layer"
    if rel.startswith("backend/app/schemas/"):
        return "Validation/Serialization Layer"
    if rel.startswith("backend/app/core/"):
        return "Core Infrastructure"
    if rel.startswith("backend/app/db/"):
        return "Database Infrastructure"
    if rel.startswith("backend/scripts/"):
        return "Operational Scripts"
    if rel.startswith("frontend/src/"):
        return "Frontend Application"
    if rel.startswith("docs/"):
        return "Documentation/QA Artifacts"
    return "Project Root / Runtime Artifact"


def _describe_folder(rel: str) -> tuple[str, str]:
    mapping = {
        "backend": (
            "FastAPI backend root. Contains API, services, data models and scripts.",
            "Serves business logic, import pipeline, metrics computation, security, reporting.",
        ),
        "backend/app": (
            "Application package root.",
            "Wires all backend layers and exposes main app entrypoint.",
        ),
        "backend/app/api": (
            "HTTP API namespace.",
            "Receives requests and delegates to service/model layers.",
        ),
        "backend/app/api/v1": (
            "Versioned REST endpoints.",
            "Entry point for auth, metrics, targets, imports, bonus, users, lookups, reports.",
        ),
        "backend/app/core": (
            "Core settings/security/logging modules.",
            "Provides JWT, configuration and logging consumed by all backend modules.",
        ),
        "backend/app/db": (
            "Database engine/session/bootstrap utilities.",
            "Creates SQLAlchemy engine/session and migration-like schema alignment.",
        ),
        "backend/app/models": (
            "SQLAlchemy ORM entities and enums.",
            "Defines persistent domain structure used by API/services.",
        ),
        "backend/app/schemas": (
            "Pydantic request/response contracts.",
            "Validates payloads and shapes JSON exchanged with frontend.",
        ),
        "backend/app/services": (
            "Business services.",
            "Implements import ETL, metrics, bonus, scope rules and objective calculations.",
        ),
        "backend/scripts": (
            "Operational automation scripts.",
            "Seed, backfill, sample file generation and QA/report generation.",
        ),
        "backend/sample_data": (
            "Sample MCR-like files used for testing and demonstration.",
            "Reference payloads for validating import and metrics workflows.",
        ),
        "backend/logs": (
            "Runtime logs location.",
            "Stores application logs for diagnostics and auditing.",
        ),
        "frontend": (
            "React frontend root.",
            "Hosts SPA, API client and styles used by business users.",
        ),
        "frontend/src": (
            "Frontend source code.",
            "Implements dashboard, role-based views, filters, tables, charts and forms.",
        ),
        "docs": (
            "Project documentation root.",
            "Holds setup/API/architecture docs and generated QA reports.",
        ),
        "docs/reports": (
            "Generated QA/test artifacts.",
        "Contains the unique consolidated validation outputs ready for QA sharing.",
        ),
    }
    if rel in mapping:
        return mapping[rel]
    return (
        "Supporting subdirectory for module organization.",
        f"Belongs to {_module_owner(rel)} and participates in that workflow.",
    )


def _describe_file(rel: str) -> tuple[str, str]:
    mapping = {
        "README.md": (
            "Top-level project overview and quick-start commands.",
            "Entry guide for developers/operators before running backend/frontend.",
        ),
        "docker-compose.yml": (
            "Multi-service orchestration (db, backend, frontend).",
            "Bootstraps end-to-end environment and startup commands.",
        ),
        "backend/app/main.py": (
            "FastAPI application entrypoint.",
            "Creates app, configures middleware/handlers, mounts API router.",
        ),
        "backend/app/api/deps.py": (
            "Reusable FastAPI dependencies (auth, pagination, role checks).",
            "Injected by endpoint modules to enforce access and query standards.",
        ),
        "backend/app/api/v1/router.py": (
            "Central API router registry.",
            "Controls which endpoint modules are exposed (e.g. complaints removed here).",
        ),
        "backend/app/api/v1/imports.py": (
            "Import endpoints for current state and historical month files.",
            "Delegates Excel parsing/upsert/recalculation to services/imports.py.",
        ),
        "backend/app/services/imports.py": (
            "MCR ETL core: parse/validate/upsert/import-batch logic.",
            "Feeds LoanRaw + ImportBatch then triggers metrics recalculation and account sync.",
        ),
        "backend/app/api/v1/metrics.py": (
            "Metrics, charts, snapshots and portfolio-performance endpoints.",
            "Computes dashboard values from LoanRaw/ImportBatch with role-aware scope filters.",
        ),
        "backend/app/services/metrics.py": (
            "DailyMetric recalculation service from raw loans.",
            "Maintains aggregate table used by exports and tabular views.",
        ),
        "backend/app/services/objective_metrics.py": (
            "Objective-period realization calculations.",
            "Used by targets follow-up and bonus calculations for month/year scopes.",
        ),
        "backend/app/services/objective_achievement.py": (
            "Achievement-rate direction rules (higher-better vs lower-better).",
            "Aligns PAR objective scoring with inverse achievement logic.",
        ),
        "backend/app/api/v1/targets.py": (
            "Objective CRUD with strict role permissions and anti-duplicate checks.",
            "Handles agency/agent objective workflows and validates scope integrity.",
        ),
        "backend/app/api/v1/bonus.py": (
            "Bonus rule and execution endpoints.",
            "Exposes formula tokens and runs monthly bonus computation.",
        ),
        "backend/app/services/bonus.py": (
            "Formula evaluator + bonus result persistence.",
            "Combines target values and realized metrics for payout computation.",
        ),
        "backend/app/api/v1/reports.py": (
            "Excel/PDF export endpoints.",
            "Exports DailyMetric data under role/data-scope restrictions.",
        ),
        "backend/app/api/v1/users.py": (
        "Super Admin user management endpoints.",
            "Creates/updates/disables users and triggers auto agent account creation.",
        ),
        "backend/app/api/v1/lookups.py": (
            "Agency/agent lookup endpoints.",
            "Feeds filter controls and form selectors in frontend.",
        ),
        "backend/app/api/v1/auth.py": (
            "Authentication endpoints.",
            "Validates credentials and returns JWT access tokens.",
        ),
        "backend/app/models/entities.py": (
            "ORM class definitions for all domain tables.",
            "Source of truth for data relations, constraints and persisted attributes.",
        ),
        "backend/app/models/enums.py": (
        "Enum definitions (roles, batch types and target types).",
            "Referenced by models, schemas and permission logic.",
        ),
        "backend/app/schemas/domain.py": (
            "Main API schema contracts (metrics, charts, targets, bonus payloads).",
            "Shapes frontend payloads and computed ratio fields.",
        ),
        "backend/app/schemas/imports.py": (
            "Import row and batch/result schemas.",
            "Validates ETL rows and response payloads for import endpoints.",
        ),
        "backend/app/core/security.py": (
            "Password hashing + JWT issuance/verification utilities.",
            "Used by auth endpoints and dependency guards.",
        ),
        "backend/app/core/config.py": (
            "Environment-backed settings model.",
            "Supplies DB URL, CORS, JWT config to app/session layers.",
        ),
        "backend/app/core/logging.py": (
            "Logging formatter/handler setup.",
            "Enables file + console observability.",
        ),
        "backend/app/db/session.py": (
            "SQLAlchemy engine/session factory.",
            "Every endpoint/service uses this for DB access lifecycle.",
        ),
        "backend/app/db/migrations.py": (
            "Runtime additive schema reconciler.",
            "Ensures missing columns/constraints are added on startup.",
        ),
        "backend/scripts/seed.py": (
            "Initialization script for admin + defaults + cleanup of legacy demo agencies.",
            "Invoked by docker-compose backend startup before serving API.",
        ),
        "backend/scripts/backfill_snapshot_dates.py": (
            "Backfill utility for snapshot batch dates.",
            "Repairs metadata consistency for existing snapshot batches.",
        ),
        "backend/scripts/create_sample_excel.py": (
            "Generates sample importable Excel file.",
            "Supports demonstrations and import validation drills.",
        ),
        "backend/scripts/generate_qa_report.py": (
            "Automated QA test runner + HTML/JSON report generator.",
            "Executes API/logic checks and archives evidence per run.",
        ),
        "backend/scripts/generate_project_reports_pdf.py": (
            "Documentation report generator (architecture + user guide PDFs).",
            "Produces governance-ready project documentation artifacts.",
        ),
        "frontend/src/main.jsx": (
            "Single-page React application containing all feature screens.",
            "Implements dashboard, filters, charts, import flows, bonus, targets and users.",
        ),
        "frontend/src/api.js": (
            "Frontend API client wrappers.",
            "Centralizes HTTP calls to backend endpoints and auth header logic.",
        ),
        "frontend/src/styles.css": (
            "Global UI styling and responsive rules.",
            "Controls desktop/tablet/mobile behavior, table/charts layout and touch ergonomics.",
        ),
        "frontend/package.json": (
            "Frontend package metadata and scripts.",
            "Defines build/dev entry commands for React/Vite app.",
        ),
        "frontend/vite.config.js": (
            "Vite bundler configuration.",
            "Build/dev server behavior for frontend assets.",
        ),
        "backend/requirements.txt": (
            "Python dependencies list.",
            "Defines backend runtime libraries (FastAPI, SQLAlchemy, pandas, reportlab, etc.).",
        ),
        "backend/Dockerfile": (
            "Backend container build recipe.",
            "Packages backend app and runtime for docker-compose deployment.",
        ),
        "frontend/Dockerfile": (
            "Frontend container build recipe.",
            "Packages Vite app for containerized execution.",
        ),
        "docs/architecture.md": (
            "Existing architecture notes.",
            "Reference narrative that complements generated architecture PDF.",
        ),
        "docs/api.md": (
            "API-oriented documentation.",
            "Describes endpoint contracts and usage conventions.",
        ),
        "docs/setup.md": (
            "Environment setup guide.",
            "Step-by-step local/deployment startup instructions.",
        ),
    }
    if rel in mapping:
        return mapping[rel]
    suffix = Path(rel).suffix.lower()
    if suffix in {".db"}:
        return (
            "SQLite database artifact.",
            "Local runtime storage used during development/testing scripts.",
        )
    if suffix in {".log"}:
        return (
            "Runtime log artifact.",
            "Captures server execution output for diagnostics.",
        )
    if suffix in {".json", ".html"} and rel.startswith("docs/reports/qa_report_"):
        return (
            "Generated QA report artifact.",
            "Stores executed test results, status breakdown and evidence.",
        )
    if suffix in {".xlsx", ".xls"}:
        return (
            "Spreadsheet sample/input artifact.",
            "Used by import workflows to populate LoanRaw snapshots.",
        )
    return (
        "Supporting project file.",
        f"Associated with {_module_owner(rel)}.",
    )


def _styles():
    base = getSampleStyleSheet()
    base.add(
        ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontSize=18,
            leading=22,
            spaceAfter=10,
        )
    )
    base.add(
        ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontSize=14,
            leading=18,
            spaceAfter=8,
        )
    )
    base.add(
        ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontSize=9.5,
            leading=13,
        )
    )
    base.add(
        ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#4b5563"),
        )
    )
    return base


def _draw_header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#6b7280"))
    canvas.drawString(1.5 * cm, 1.0 * cm, "MicroCred Metrics/GP/MCR - Generated Documentation")
    canvas.drawRightString(doc.pagesize[0] - 1.5 * cm, 1.0 * cm, f"Page {doc.page}")
    canvas.restoreState()


def _safe(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def _chunked(items: list[list], size: int) -> Iterable[list[list]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _table(data: list[list], col_widths: list[float]) -> Table:
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("LEADING", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return tbl


def build_architecture_pdf(output_path: Path) -> None:
    styles = _styles()
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=landscape(A4),
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.6 * cm,
    )
    story = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    dirs, files = _iter_items(ROOT)

    story.append(Paragraph("Rapport 1 - Architecture complete du projet Metrics/GP/MCR", styles["H1"]))
    story.append(Paragraph(f"Date de generation: {now}", styles["Small"]))
    story.append(Spacer(1, 8))

    toc_items = [
        "1. Table des matieres",
        "2. Vue d'ensemble du systeme",
        "3. Diagrammes (classes, modules, flux backend/frontend/DB)",
        "4. Cartographie complete des dossiers",
        "5. Cartographie complete des fichiers",
        "6. Fichiers critiques par workflow metier",
        "7. Notes sur exclusions techniques",
    ]
    story.append(Paragraph("1. Table des matieres", styles["H2"]))
    story.append(
        ListFlowable(
            [ListItem(Paragraph(item, styles["Body"])) for item in toc_items],
            bulletType="bullet",
            leftIndent=16,
        )
    )

    story.append(Spacer(1, 8))
    story.append(Paragraph("2. Vue d'ensemble du systeme", styles["H2"]))
    overview = (
        "L'application est une plateforme full-stack composee d'un backend FastAPI, d'un frontend React/Vite "
        "et d'une base SQL (PostgreSQL en cible, SQLite en developpement). Le coeur metier repose sur une "
        "architecture de snapshots quotidiens: chaque import MCR conserve l'etat brut des credits dans "
        "<b>loans_raw</b>, puis produit des indicateurs agreges exploites par le dashboard, les objectifs et les bonus."
    )
    story.append(Paragraph(_safe(overview), styles["Body"]))

    story.append(Spacer(1, 8))
    story.append(Paragraph("3. Diagrammes", styles["H2"]))
    class_diagram = """
Classes principales (ORM):
  Agency (1) ---- (N) Agent
  Agency (1) ---- (N) Target
  Agent  (1) ---- (N) Target (AGENT scope)
  User   (N) ---- (1) Agency [optionnel]
  User   (N) ---- (1) Agent  [optionnel]

  ImportBatch (1) ---- (N) LoanRaw
  LoanRaw -> alimente calculs -> DailyMetric

  BonusRule (1) ---- (N) BonusResult
  User      (1) ---- (N) BonusResult
"""
    modules_diagram = """
Flux modules:
  frontend/src/main.jsx
       -> frontend/src/api.js
          -> backend/app/api/v1/*
             -> backend/app/services/*
                -> backend/app/models/entities.py
                   -> backend/app/db/session.py (SQL)
"""
    dataflow_diagram = """
Flux MCR & analytics:
  Fichier Excel MCR
      -> api/v1/imports.py
      -> services/imports.py (parse/validate/upsert + ImportBatch)
      -> loans_raw (snapshot conserve)
      -> services/metrics.py / api/v1/metrics.py
      -> daily_metrics + dashboard KPIs/charts/tables
      -> objectifs (targets.py) & bonus (bonus.py)
"""
    story.append(Paragraph("3.1 Diagramme de classes", styles["Body"]))
    story.append(Preformatted(class_diagram.strip(), styles["Small"]))
    story.append(Paragraph("3.2 Diagramme des modules", styles["Body"]))
    story.append(Preformatted(modules_diagram.strip(), styles["Small"]))
    story.append(Paragraph("3.3 Schema backend/frontend/base de donnees", styles["Body"]))
    story.append(Preformatted(dataflow_diagram.strip(), styles["Small"]))
    story.append(PageBreak())

    story.append(Paragraph("4. Cartographie complete des dossiers", styles["H2"]))
    dir_rows = [["Dossier", "Fonction", "Role dans le workflow"]]
    for item in dirs:
        function, workflow = _describe_folder(item.rel)
        dir_rows.append([_safe(item.rel), _safe(function), _safe(workflow)])
    for chunk in _chunked(dir_rows[1:], 35):
        data = [dir_rows[0], *chunk]
        story.append(_table(data, [8.5 * cm, 9.2 * cm, 10.2 * cm]))
        story.append(Spacer(1, 6))

    story.append(PageBreak())
    story.append(Paragraph("5. Cartographie complete des fichiers", styles["H2"]))
    file_rows = [["Fichier", "Fonction", "Relations / role general"]]
    for item in files:
        function, relations = _describe_file(item.rel)
        file_rows.append([_safe(item.rel), _safe(function), _safe(relations)])
    for chunk in _chunked(file_rows[1:], 35):
        data = [file_rows[0], *chunk]
        story.append(_table(data, [8.5 * cm, 9.2 * cm, 10.2 * cm]))
        story.append(Spacer(1, 6))

    story.append(PageBreak())
    story.append(Paragraph("6. Fichiers critiques par workflow metier", styles["H2"]))
    critical_rows = [
        ["Workflow", "Fichiers responsables"],
        ["Import MCR (etat actuel / mois passe / snapshots)", "backend/app/api/v1/imports.py, backend/app/services/imports.py, backend/app/models/entities.py (ImportBatch, LoanRaw). Inclut la suppression securisee de snapshots par Super Admin."],
        ["Calcul metriques dashboard", "backend/app/api/v1/metrics.py, backend/app/services/metrics.py, backend/app/services/objective_metrics.py"],
        ["Dashboard frontend", "frontend/src/main.jsx, frontend/src/api.js, frontend/src/styles.css"],
        ["Gestion des roles & scopes", "backend/app/api/deps.py, backend/app/services/data_scope.py, backend/app/models/enums.py, frontend/src/main.jsx"],
        ["Objectifs agence/agent", "backend/app/api/v1/targets.py, backend/app/models/entities.py (Target), frontend/src/main.jsx"],
        ["Bonus", "backend/app/api/v1/bonus.py, backend/app/services/bonus.py, frontend/src/main.jsx"],
        ["Exports Excel/PDF", "backend/app/api/v1/reports.py, frontend/src/main.jsx (ReportButtons)"],
        ["Generation rapports QA", "backend/scripts/generate_qa_report.py, docs/reports/*"],
    ]
    story.append(_table(critical_rows, [8.5 * cm, 19.4 * cm]))

    story.append(Spacer(1, 10))
    story.append(Paragraph("7. Notes sur exclusions techniques", styles["H2"]))
    exclusions = (
        "Pour conserver un rapport lisible, l'inventaire detaille exclut les repertoires de dependances et de build "
        "(node_modules, dist, .venv, __pycache__). Ces repertoires ne contiennent pas de logique metier proprietaire."
    )
    story.append(Paragraph(_safe(exclusions), styles["Body"]))

    doc.build(story, onFirstPage=_draw_header_footer, onLaterPages=_draw_header_footer)


def build_user_guide_pdf(output_path: Path) -> None:
    styles = _styles()
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.8 * cm,
    )
    story = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    story.append(Paragraph("Rapport 2 - Guide d'utilisation complet Metrics/GP/MCR", styles["H1"]))
    story.append(Paragraph(f"Date de generation: {now}", styles["Small"]))
    story.append(Spacer(1, 8))

    toc = [
        "1. Table des matieres",
        "2. Navigation generale et droits par role",
        "3. Dashboard: cartes, chartes et tableaux",
        "4. Importation: etat actuel, snapshots, mois passe",
        "5. Objectifs (agence/agent) et regles d'acces",
        "6. Bonus: formules et calculs",
        "7. Origine et detail de chaque metrique",
        "8. Filtres, snapshots et interpretations",
        "9. Exports Excel/PDF",
        "10. Bonnes pratiques d'utilisation",
    ]
    story.append(Paragraph("1. Table des matieres", styles["H2"]))
    story.append(ListFlowable([ListItem(Paragraph(item, styles["Body"])) for item in toc], bulletType="bullet", leftIndent=16))

    story.append(Spacer(1, 8))
    story.append(Paragraph("2. Navigation generale et droits par role", styles["H2"]))
    role_text = (
        "Super Admin: acces global (dashboard complet, importation, objectifs agence, utilisateurs, exports et suppression de snapshots erronees).<br/>"
        "Admin: dashboard global en lecture seule; aucun acces aux modules d'administration.<br/>"
        "Chef d'agence (AGENCY_MANAGER): vue restreinte a son agence; gestion objectifs GP de son agence uniquement.<br/>"
        "Portfolio Manager: vue personnelle (agent scope), objectifs en lecture seule, aucune administration globale."
    )
    story.append(Paragraph(_safe(role_text), styles["Body"]))

    story.append(Spacer(1, 8))
    story.append(Paragraph("3. Dashboard: cartes, chartes et tableaux", styles["H2"]))
    dashboard_text = (
        "Le dashboard combine: (a) cartes KPI, (b) chartes Qualite portefeuille et Volume decaisse, "
        "(c) tableau Metrics GP / Credits existants via switch. "
        "Les chartes changent de mode selon les filtres: global par agence, tendance mensuelle agence, tendance mensuelle agent."
    )
    story.append(Paragraph(_safe(dashboard_text), styles["Body"]))

    story.append(Spacer(1, 8))
    story.append(Paragraph("4. Importation: etat actuel, snapshots, mois passe", styles["H2"]))
    import_flow = """
Workflow:
  1) Importer l'etat actuel:
     - cree/met a jour un batch CURRENT_STATE
     - l'ancien CURRENT_STATE est archive en SNAPSHOT
  2) Importer un mois passe:
     - cree un batch HISTORICAL_MONTH (period YYYY-MM)
     - detecte les doublons de periode (option remplacement)
  3) Dashboard:
     - compare mois historiques + etat actuel
     - snapshots selectionnes ajoutent des points supplementaires
  4) Correction d'une fausse importation:
     - le Super Admin peut supprimer une ou plusieurs SNAPSHOT apres confirmation
     - CURRENT_STATE et HISTORICAL_MONTH restent proteges contre la suppression
"""
    story.append(Preformatted(import_flow.strip(), styles["Small"]))

    story.append(Spacer(1, 8))
    story.append(Paragraph("5. Objectifs (agence/agent) et regles d'acces", styles["H2"]))
    objective_rows = [
        ["Role", "Peut creer/modifier", "Visibilite"],
        ["Super Admin", "Objectifs AGENCY uniquement", "Tous objectifs (AGENCY + AGENT en lecture)"],
        ["Admin", "Aucune modification", "Dashboard global en lecture seule"],
        ["Chef d'agence", "Objectifs AGENT de son agence", "Son agence + ses GP"],
        ["Portfolio Manager", "Lecture seule", "Ses propres objectifs"],
    ]
    story.append(_table(objective_rows, [4.0 * cm, 6.0 * cm, 7.4 * cm]))

    story.append(Spacer(1, 8))
    story.append(Paragraph("6. Bonus: formules et calculs", styles["H2"]))
    bonus_text = (
        "Le module Bonus reste visible mais inactif dans l'environnement de test lorsque BONUS_MODULE_ACTIVE=false. "
        "La navigation affiche alors un ecran persistant 'Module en developpement' sans lancer de calcul. "
        "La remise en service exige BONUS_MODULE_ACTIVE=true et une validation dediee en pre-production."
    )
    story.append(Paragraph(_safe(bonus_text), styles["Body"]))

    story.append(PageBreak())
    story.append(Paragraph("7. Origine et detail de chaque metrique", styles["H2"]))
    story.append(
        Paragraph(
            "Origine principale: <b>backend/app/api/v1/metrics.py</b> sur la base de <b>LoanRaw</b> "
            "(snapshot courant + filtres/date scopes).",
            styles["Body"],
        )
    )

    metric_rows = [
        ["Metrique", "Source donnees", "Formule / regle metier (implementation actuelle)"],
        ["Client Actif", "LoanRaw.client_id", "COUNT DISTINCT client_id sur condition stock (disbursement_date <= date_to si defini)."],
        ["Nombre de decaissement", "LoanRaw.contract_no", "SUM(CASE flow_condition THEN 1 ELSE 0): disbursement_date entre date_from/date_to."],
        ["Volume decaisse", "LoanRaw.disbursement_amount", "SUM(disbursement_amount) sur flow_condition."],
        ["Encours", "LoanRaw.principal_outstanding + principal_due", "SUM(exposure) sur stock_condition."],
        ["Encours sain", "LoanRaw.days_overdue", "SUM(exposure) lorsque days_overdue == 0 et stock_condition."],
        ["PAR0", "LoanRaw.days_overdue", "SUM(exposure) lorsque days_overdue > 0 et stock_condition."],
        ["PAR30", "LoanRaw.days_overdue", "SUM(exposure) lorsque days_overdue > 30 et stock_condition."],
        ["Cohorte 1-30", "LoanRaw.days_overdue", "SUM(exposure) lorsque 1 <= days_overdue <= 30."],
        ["Cohorte 31-60", "LoanRaw.days_overdue", "SUM(exposure) lorsque 31 <= days_overdue <= 60."],
        ["Cohorte 61-90", "LoanRaw.days_overdue", "SUM(exposure) lorsque 61 <= days_overdue <= 90."],
        ["PAR30 / Encours (%)", "PAR30 et Encours", "par_30_rate = par_30 / outstanding (affiche en %)."],
        ["Cohorte 1-30 (%)", "Cohorte1-30 et Encours", "par_1_30_rate = par_1_30 / outstanding."],
        ["Cohorte 31-60 (%)", "Cohorte31-60 et Encours", "par_31_60_rate = par_31_60 / outstanding."],
        ["Cohorte 61-90 (%)", "Cohorte61-90 et Encours", "par_61_90_rate = par_61_90 / outstanding."],
    ]
    story.append(_table(metric_rows, [3.6 * cm, 4.3 * cm, 9.4 * cm]))

    story.append(Spacer(1, 8))
    story.append(Paragraph("8. Filtres, snapshots et interpretations", styles["H2"]))
    filter_text = (
        "Filtres agence/agent: appliques aux requetes backend et scopes roles.<br/>"
        "Filtre date: flow metrics utilisent [date_from, date_to], stock metrics utilisent <= date_to (condition stock).<br/>"
        "Snapshots a comparer: multi-select ajoute des points supplements dans les tendances mensuelles.<br/>"
        "Bouton Mois actuel: auto date_from = premier jour du mois courant, date_to = date du CURRENT_STATE actif.<br/>"
        "Bouton Reset filtres: reinitialise agence/agent/date/snapshots (en respectant les verrous de role)."
    )
    story.append(Paragraph(_safe(filter_text), styles["Body"]))

    story.append(Spacer(1, 8))
    story.append(Paragraph("9. Exports Excel/PDF", styles["H2"]))
    export_text = (
        "Les exports sont servis par backend/app/api/v1/reports.py. "
        "Ils s'appuient sur DailyMetric (pas sur l'UI state client), avec restrictions de scope role. "
        "Le bouton frontend (ReportButtons) transmet les filtres actifs."
    )
    story.append(Paragraph(_safe(export_text), styles["Body"]))

    story.append(Spacer(1, 8))
    story.append(Paragraph("10. Conseils d'utilisation", styles["H2"]))
    tips = [
        "Toujours importer un fichier CURRENT_STATE recent avant d'analyser les KPI du jour.",
        "Utiliser HISTORICAL_MONTH pour figer les clotures officielles mensuelles.",
        "Comparer des snapshots uniquement pour des analyses ponctuelles (stress/qualite).",
        "Verifier les objectifs par role avant interpretation bonus/couverture.",
        "Croiser Dashboard et Exports pour audit et partage management.",
    ]
    story.append(
        ListFlowable([ListItem(Paragraph(_safe(item), styles["Body"])) for item in tips], bulletType="bullet", leftIndent=16)
    )

    login_capture = REPORT_DIR / "captures" / "login.png"
    if login_capture.exists():
        story.append(PageBreak())
        story.append(Paragraph("11. Capture QA - page de connexion vide", styles["H2"]))
        story.append(
            Paragraph(
                "Controle visuel local: l'ouverture de l'application affiche un formulaire de connexion vide, sans preconnexion automatique.",
                styles["Body"],
            )
        )
        story.append(Spacer(1, 8))
        story.append(Image(str(login_capture), width=17.2 * cm, height=11.9 * cm))

    doc.build(story, onFirstPage=_draw_header_footer, onLaterPages=_draw_header_footer)


def main() -> None:
    arch_pdf = REPORT_DIR / "architecture_complete_final.pdf"
    guide_pdf = REPORT_DIR / "guide_utilisation_final.pdf"

    build_architecture_pdf(arch_pdf)
    build_user_guide_pdf(guide_pdf)

    print(f"ARCH_PDF={arch_pdf}")
    print(f"GUIDE_PDF={guide_pdf}")


if __name__ == "__main__":
    main()
