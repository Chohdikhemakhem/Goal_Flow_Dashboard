from __future__ import annotations

from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT / "docs" / "reports"


def _latest_report_file(glob_pattern: str) -> Path:
    matches = sorted(REPORTS_DIR.glob(glob_pattern))
    if not matches:
        raise FileNotFoundError(
            f"No report files found for pattern '{glob_pattern}' in {REPORTS_DIR}"
        )
    return matches[-1]


KEY_ROLES = {
    "backend/app/services/imports.py": "ETL MCR (parse Excel, validation, import batches, snapshots).",
    "backend/app/api/v1/metrics.py": "API dashboard (summary, charts, snapshots, current credits).",
    "backend/app/services/objective_metrics.py": "Calcul réalisations des objectifs sur période DISBURSEMENT_DATE.",
    "backend/app/services/objective_achievement.py": "Calcul du taux d’atteinte (logique PAR inversée).",
    "backend/app/services/data_scope.py": "Scope sécurité par rôle (ADMIN / AGENCY_MANAGER / PORTFOLIO_MANAGER).",
    "backend/app/api/v1/targets.py": "API objectifs agence/agent + permissions.",
    "backend/app/api/v1/users.py": "Gestion comptes utilisateurs.",
    "backend/app/api/v1/imports.py": "API import état actuel / mois passé.",
    "backend/app/core/config.py": "Variables d’environnement backend et feature flags.",
    "frontend/src/main.jsx": "Application React (dashboard, filtres, pages métier).",
    "frontend/src/api.js": "Client API frontend.",
    "docker-compose.yml": "Stack Docker (PostgreSQL + backend + frontend).",
    "backend/scripts/prepare_deployment.py": "Préparation préprod/prod (checks, tests, backup, build).",
    "backend/scripts/seed.py": "Seed admin + règles initiales + recalcul métriques.",
}


def classify(path: str) -> tuple[str, str]:
    norm = path.replace("\\", "/")
    lower = norm.lower()
    if norm in KEY_ROLES:
        if norm.startswith("backend/"):
            return "backend", KEY_ROLES[norm]
        if norm.startswith("frontend/"):
            return "frontend", KEY_ROLES[norm]
        if norm.startswith("docs/"):
            return "documentation/report", KEY_ROLES[norm]
        return "root/config", KEY_ROLES[norm]

    if "/__pycache__/" in lower:
        return "artefact", "Bytecode Python généré automatiquement."
    if lower.endswith(".db"):
        return "database", "Fichier base SQLite locale/technique."
    if norm.startswith("docs/reports/"):
        return "documentation/report", "Artefact de rapport généré automatiquement."
    if lower.endswith(".log"):
        return "logs", "Fichier log d’exécution."
    if lower.endswith(".py"):
        return "backend", "Module Python (API, service, modèle ou script)."
    if lower.endswith(".jsx") or lower.endswith(".js") or lower.endswith(".css"):
        return "frontend", "Module frontend React/Vite/UI."
    if lower.endswith(".md"):
        return "documentation", "Documentation."
    if lower.endswith(".xlsx") or lower.endswith(".xls"):
        return "sample data", "Fichier Excel de test/import."
    return "root/config", "Fichier projet."


def load_runtime_files() -> list[str]:
    runtime_list = _latest_report_file("project_structure_runtime_*.txt")
    if not runtime_list.exists():
        raise FileNotFoundError(f"Runtime list file not found: {runtime_list}")
    return sorted(
        [
            line.strip().lstrip("\ufeff").replace("\\", "/")
            for line in runtime_list.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    )


def build_report(runtime_files: list[str]) -> str:
    runtime_list = _latest_report_file("project_structure_runtime_*.txt")
    full_list = _latest_report_file("project_structure_full_*.txt")
    now = datetime.now().isoformat(timespec="seconds")
    lines: list[str] = []
    lines.append("# Rapport complet - Environnements et structure actuelle")
    lines.append("")
    lines.append(f"Date de génération: {now}")
    lines.append("")
    lines.append("## Environnements disponibles")
    lines.append("")
    lines.append("| Environnement | Accès | Ports | DB | Utilisateur par défaut (sans mot de passe) | Notes |")
    lines.append("|---|---|---|---|---|---|")
    lines.append("| Développement local | Front `http://127.0.0.1:5173`, API `http://127.0.0.1:8000`, Docs `http://127.0.0.1:8000/docs` | 5173 / 8000 | SQLite (`backend/dev_microcred.db`) | `admin@microcredapp.com` (`ADMIN`) | `BONUS_MODULE_ACTIVE=false` dans `.env` actuel |")
    lines.append("| Test local | Même endpoints que dev local | 5173 / 8000 | SQLite locale | `admin@microcredapp.com` | Login forcé vide via `VITE_FORCE_LOGIN_ON_START` |")
    lines.append("| Docker Compose | Front `http://localhost:5173`, API `http://localhost:8000`, Docs `http://localhost:8000/docs` | 5173 / 8000 / 5432 | PostgreSQL (`microcred`) | `admin@microcredapp.com` (`ADMIN`) | DB user Docker `microcred` |")
    lines.append("| Pré-production | URL non définie dans le repo | selon infra | PostgreSQL recommandé | selon IAM | Script: `backend/scripts/prepare_deployment.py --env preprod` |")
    lines.append("| Production | URL non définie dans le repo | selon infra | PostgreSQL requis | selon IAM | Script: `backend/scripts/prepare_deployment.py --env prod` (SQLite refusé) |")
    lines.append("")
    lines.append("### Variables d’environnement requises")
    lines.append("- Backend: `DATABASE_URL`, `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `CORS_ORIGINS`, `LOG_LEVEL`, `BONUS_MODULE_ACTIVE`.")
    lines.append("- Frontend: `VITE_API_BASE_URL`, `VITE_FORCE_LOGIN_ON_START`.")
    lines.append("")
    lines.append("### Scripts de démarrage")
    lines.append("```bash")
    lines.append("# Local")
    lines.append("cd backend && python scripts/seed.py && uvicorn app.main:app --host 127.0.0.1 --port 8000")
    lines.append("cd frontend && npm install && npm run dev")
    lines.append("")
    lines.append("# Docker")
    lines.append("docker compose up --build")
    lines.append("```")
    lines.append("")
    lines.append("## Architecture globale")
    lines.append("")
    lines.append("```mermaid")
    lines.append("flowchart LR")
    lines.append("  FE[\"Frontend React/Vite\\n(frontend/src)\"] --> API[\"FastAPI Backend\\n(backend/app)\"]")
    lines.append("  API --> SVC[\"Services metier\\nimports/metrics/objectifs/bonus\"]")
    lines.append("  SVC --> DB[(\"SQLite local ou PostgreSQL Docker\")]")
    lines.append("  IMPORT[\"Fichiers Excel MCR\"] --> API")
    lines.append("  API --> EXPORT[\"Exports Excel/PDF\"]")
    lines.append("  API --> LOGS[\"Logs applicatifs\"]")
    lines.append("```")
    lines.append("")
    lines.append("## Structure exacte actuelle du projet")
    lines.append("")
    lines.append(f"- Inventaire complet (incluant dépendances): `{full_list.as_posix()}`")
    lines.append(f"- Inventaire runtime (hors `node_modules`, `.venv`, `dist`): `{runtime_list.as_posix()}`")
    lines.append(f"- Total runtime listé: **{len(runtime_files)} fichiers**")
    lines.append("")
    lines.append("### Catalogue des fichiers/dossiers actuels")
    lines.append("")
    lines.append("| Chemin | Type | Fonction / rôle |")
    lines.append("|---|---|---|")
    for path in runtime_files:
        category, role = classify(path)
        safe = path.replace("|", "\\|")
        lines.append(f"| `{safe}` | {category} | {role} |")
    return "\n".join(lines)


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    runtime_files = load_runtime_files()
    body = build_report(runtime_files)
    output_path = REPORTS_DIR / f"environment_structure_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    output_path.write_text(body, encoding="utf-8")
    print(output_path.as_posix())


if __name__ == "__main__":
    main()
