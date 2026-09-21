from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
ROOT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
REPORTS_DIR = ROOT_DIR / "docs" / "reports"
BACKUP_DIR = ROOT_DIR / "backups"


@dataclass
class StepResult:
    name: str
    status: str
    message: str
    started_at: str
    finished_at: str


class DeploymentPrepError(RuntimeError):
    pass


class DeploymentPreparer:
    def __init__(
        self,
        env_name: str,
        dry_run: bool,
        skip_tests: bool,
        skip_backup: bool,
        skip_frontend_build: bool,
    ) -> None:
        self.env_name = env_name
        self.dry_run = dry_run
        self.skip_tests = skip_tests
        self.skip_backup = skip_backup
        self.skip_frontend_build = skip_frontend_build
        self.results: list[StepResult] = []
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.binaries: dict[str, str] = {}

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _record(self, name: str, status: str, message: str, started: str) -> None:
        self.results.append(
            StepResult(
                name=name,
                status=status,
                message=message,
                started_at=started,
                finished_at=self._now(),
            )
        )

    def run_step(self, name: str, fn) -> None:
        started = self._now()
        print(f"\n=== {name} ===")
        try:
            message = fn()
            self._record(name, "PASS", message, started)
            print(f"[OK] {message}")
        except Exception as exc:  # noqa: BLE001
            self._record(name, "FAIL", str(exc), started)
            print(f"[ERROR] {exc}")
            raise

    def resolve_binary(self, name: str, required: bool = True) -> str:
        cached = self.binaries.get(name)
        if cached:
            return cached

        candidates = [name]
        if os.name == "nt":
            if not name.endswith(".cmd"):
                candidates.append(f"{name}.cmd")
            if not name.endswith(".exe"):
                candidates.append(f"{name}.exe")

        for candidate in candidates:
            resolved = shutil.which(candidate)
            if resolved:
                self.binaries[name] = resolved
                return resolved

        if required:
            raise DeploymentPrepError(f"Outil introuvable: {name}")
        return name

    def run_command(
        self,
        command: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        check: bool = True,
        execute_in_dry_run: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        printable = " ".join(command)
        print(f"$ {printable}")
        if self.dry_run and not execute_in_dry_run:
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            check=check,
            text=True,
            capture_output=True,
        )

    @staticmethod
    def load_env_file(env_file: Path) -> None:
        if not env_file.exists():
            return
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)

    def check_environment(self) -> str:
        self.load_env_file(BACKEND_DIR / ".env")

        required_vars = ["DATABASE_URL", "JWT_SECRET_KEY"]
        missing_vars = [var for var in required_vars if not os.environ.get(var)]
        if missing_vars:
            raise DeploymentPrepError(
                "Variables d'environnement manquantes: " + ", ".join(missing_vars)
            )

        db_url = os.environ["DATABASE_URL"]
        if self.env_name == "prod":
            weak_secrets = {"change-me", "changeme", "secret", "admin", "password"}
            jwt_key = os.environ["JWT_SECRET_KEY"]
            if len(jwt_key) < 16 or jwt_key.lower() in weak_secrets:
                raise DeploymentPrepError(
                    "JWT_SECRET_KEY trop faible pour production (min 16 chars, non trivial)."
                )
            if db_url.startswith("sqlite"):
                raise DeploymentPrepError(
                    "DATABASE_URL sqlite détectée en mode production. Utiliser PostgreSQL."
                )

        tools = [
            ("node", [self.resolve_binary("node"), "-v"]),
            ("npm", [self.resolve_binary("npm"), "-v"]),
            ("python", [sys.executable, "--version"]),
        ]
        db_needs_pg_tools = db_url.startswith("postgresql") or db_url.startswith("postgres")
        if db_needs_pg_tools:
            tools.extend(
                [
                    ("psql", [self.resolve_binary("psql"), "--version"]),
                    ("pg_dump", [self.resolve_binary("pg_dump"), "--version"]),
                ]
            )

        checked: list[str] = []
        for tool_name, command in tools:
            try:
                result = self.run_command(command, execute_in_dry_run=True)
                output = (result.stdout or result.stderr).strip().splitlines()
                version = output[0] if output else "version inconnue"
                print(f"{tool_name}: {version}")
                checked.append(tool_name)
            except FileNotFoundError as exc:
                raise DeploymentPrepError(f"Outil introuvable: {tool_name}") from exc
            except subprocess.CalledProcessError as exc:
                raise DeploymentPrepError(
                    f"Outil non fonctionnel ({tool_name}): {exc.stderr or exc.stdout or exc}"
                ) from exc

        return f"Environnement valide ({', '.join(checked)}), variables critiques présentes."

    def prepare_database(self) -> str:
        env = os.environ.copy()
        result = self.run_command([sys.executable, "scripts/seed.py"], cwd=BACKEND_DIR, env=env)
        if not self.dry_run:
            print((result.stdout or "").strip())

        if self.dry_run:
            return "Dry-run: seed non exécuté."
        return "Base préparée (create_all/migrations/seed exécutés)."

    def verify_roles_and_security(self) -> str:
        if self.dry_run:
            return "Dry-run: vérification des rôles ignorée."

        sys.path.append(str(BACKEND_DIR))
        from sqlalchemy import select  # pylint: disable=import-outside-toplevel

        from app.db.session import SessionLocal  # pylint: disable=import-outside-toplevel
        from app.models.entities import User  # pylint: disable=import-outside-toplevel
        from app.models.enums import UserRole  # pylint: disable=import-outside-toplevel

        db = SessionLocal()
        try:
            users = db.scalars(select(User).where(User.is_active.is_(True))).all()
            super_admin_count = sum(1 for user in users if user.role == UserRole.SUPER_ADMIN)
            admin_count = sum(1 for user in users if user.role == UserRole.ADMIN)
            agency_managers = sum(1 for user in users if user.role == UserRole.AGENCY_MANAGER)
            portfolio_managers = sum(1 for user in users if user.role == UserRole.PORTFOLIO_MANAGER)
        finally:
            db.close()

        if super_admin_count == 0:
            raise DeploymentPrepError("Aucun utilisateur SUPER_ADMIN actif trouvé.")

        return (
            "Rôles validés: "
            f"SUPER_ADMIN={super_admin_count}, ADMIN={admin_count}, AGENCY_MANAGER={agency_managers}, "
            f"PORTFOLIO_MANAGER={portfolio_managers}."
        )

    def run_automated_tests(self) -> str:
        if self.skip_tests:
            return "Tests ignorés (--skip-tests)."
        if self.dry_run:
            return "Dry-run: exécution des tests simulée."

        executed: list[str] = []
        env = os.environ.copy()

        qa_script = BACKEND_DIR / "scripts" / "generate_qa_report.py"
        if qa_script.exists():
            qa = self.run_command([sys.executable, str(qa_script)], cwd=ROOT_DIR, env=env)
            if not self.dry_run:
                print((qa.stdout or "").strip())
            executed.append("QA end-to-end report")

        backend_tests_dir = BACKEND_DIR / "tests"
        if backend_tests_dir.exists():
            self.run_command([sys.executable, "-m", "pytest", str(backend_tests_dir)], cwd=BACKEND_DIR, env=env)
            executed.append("pytest backend/tests")

        if not executed:
            return "Aucun test automatisé détecté (aucun dossier tests/, script QA absent)."
        return "Tests exécutés: " + ", ".join(executed) + "."

    @staticmethod
    def _sqlite_path_from_url(database_url: str) -> Path | None:
        if not database_url.startswith("sqlite"):
            return None
        parsed = urlparse(database_url)
        if parsed.scheme != "sqlite":
            return None
        if parsed.path in ("", "/:memory:"):
            return None
        raw_path = unquote(parsed.path.lstrip("/"))
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = BACKEND_DIR / raw_path
        return candidate.resolve()

    def setup_backup_and_logs(self) -> str:
        if self.skip_backup:
            return "Backup ignoré (--skip-backup)."

        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        (BACKEND_DIR / "logs").mkdir(parents=True, exist_ok=True)
        (ROOT_DIR / "logs").mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        db_url = os.environ["DATABASE_URL"]
        backup_file = BACKUP_DIR / f"{self.env_name}_backup_{self.timestamp}"

        if db_url.startswith("postgresql") or db_url.startswith("postgres"):
            parsed = urlparse(db_url)
            db_name = parsed.path.lstrip("/") if parsed.path else ""
            if not db_name:
                raise DeploymentPrepError("DATABASE_URL PostgreSQL invalide (nom DB manquant).")
            env = os.environ.copy()
            if parsed.password:
                env["PGPASSWORD"] = parsed.password

            dump_file = backup_file.with_suffix(".dump")
            command = [
                self.resolve_binary("pg_dump"),
                "-h",
                parsed.hostname or "localhost",
                "-p",
                str(parsed.port or 5432),
                "-U",
                parsed.username or "postgres",
                "-d",
                db_name,
                "-F",
                "c",
                "-f",
                str(dump_file),
            ]
            self.run_command(command, env=env)
            if self.dry_run:
                return f"Dry-run: backup PostgreSQL simulé ({dump_file})."
            return f"Backup PostgreSQL créé: {dump_file}"

        sqlite_path = self._sqlite_path_from_url(db_url)
        if sqlite_path and sqlite_path.exists():
            dump_file = backup_file.with_suffix(".sqlite3")
            if self.dry_run:
                return f"Dry-run: backup SQLite simulé ({dump_file})."
            shutil.copy2(sqlite_path, dump_file)
            return f"Backup SQLite créé: {dump_file}"

        return "Backup ignoré: DB SQLite introuvable ou non sauvegardable."

    def build_frontend(self) -> str:
        if self.skip_frontend_build:
            return "Build frontend ignoré (--skip-frontend-build)."

        if not FRONTEND_DIR.exists():
            raise DeploymentPrepError("Dossier frontend introuvable.")

        npm_bin = self.resolve_binary("npm")
        self.run_command([npm_bin, "install"], cwd=FRONTEND_DIR)
        self.run_command([npm_bin, "run", "build"], cwd=FRONTEND_DIR)

        if self.dry_run:
            return "Dry-run: build frontend simulé."

        dist_index = FRONTEND_DIR / "dist" / "index.html"
        if not dist_index.exists():
            raise DeploymentPrepError("Build frontend incomplet: dist/index.html absent.")

        return "Build frontend validé (dist/index.html généré)."

    def write_summary_report(self) -> Path:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORTS_DIR / f"deployment_prep_{self.env_name}_{self.timestamp}.json"
        payload = {
            "generated_at": self._now(),
            "environment": self.env_name,
            "dry_run": self.dry_run,
            "results": [asdict(result) for result in self.results],
        }
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return report_path

    def run(self) -> Path:
        self.run_step("Vérification environnement", self.check_environment)
        self.run_step("Préparation base de données", self.prepare_database)
        self.run_step("Vérification rôles & sécurité", self.verify_roles_and_security)
        self.run_step("Tests automatisés", self.run_automated_tests)
        self.run_step("Backups & logs", self.setup_backup_and_logs)
        self.run_step("Build frontend", self.build_frontend)
        return self.write_summary_report()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Préparer l'application MicroCred pour pré-production/production."
    )
    parser.add_argument(
        "--env",
        choices=("preprod", "prod"),
        default="preprod",
        help="Environnement cible.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche les actions sans exécuter les commandes destructives.",
    )
    parser.add_argument("--skip-tests", action="store_true", help="Ignore les tests automatisés.")
    parser.add_argument("--skip-backup", action="store_true", help="Ignore la sauvegarde DB.")
    parser.add_argument(
        "--skip-frontend-build",
        action="store_true",
        help="Ignore npm install/build frontend.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    preparer = DeploymentPreparer(
        env_name=args.env,
        dry_run=args.dry_run,
        skip_tests=args.skip_tests,
        skip_backup=args.skip_backup,
        skip_frontend_build=args.skip_frontend_build,
    )
    try:
        summary = preparer.run()
        print(f"\nPréparation terminée. Rapport: {summary}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"\nPréparation interrompue: {exc}")
        summary = preparer.write_summary_report()
        print(f"Rapport partiel: {summary}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
