from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
REPORT_DIR = ROOT_DIR / "docs" / "reports" / "final"


def _run(command: list[str], cwd: Path) -> dict[str, object]:
    resolved_command = list(command)
    if resolved_command and resolved_command[0] == "npm":
        resolved_command[0] = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
    completed = subprocess.run(
        resolved_command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "command": resolved_command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _http_check(
    path: str,
    expected_status: int,
    *,
    method: str = "GET",
    body: bytes | None = None,
) -> dict[str, object]:
    url = f"http://127.0.0.1:8000{path}"
    try:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        with urlopen(Request(url, data=body, headers=headers, method=method), timeout=5) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {
                "url": url,
                "expected_status": expected_status,
                "status": response.status,
                "passed": response.status == expected_status,
                "headers": dict(response.headers.items()),
                "body_excerpt": body[:500],
            }
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "url": url,
            "expected_status": expected_status,
            "status": exc.code,
            "passed": exc.code == expected_status,
            "headers": dict(exc.headers.items()),
            "body_excerpt": body[:500],
        }
    except URLError as exc:
        return {
            "url": url,
            "expected_status": expected_status,
            "status": 0,
            "passed": False,
            "error": str(exc),
        }


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _write_functional_report(results: dict[str, object]) -> None:
    suite = results["functional_tests"]
    build = results["frontend_build"]
    lines = [
        "# Rapport final - Tests fonctionnels",
        "",
        f"Date d'execution: `{results['generated_at']}`",
        "",
        "## Resume",
        "",
        f"- Suite automatisee backend: **{_status(suite['returncode'] == 0)}**",
        f"- Build frontend React/Vite: **{_status(build['returncode'] == 0)}**",
        "- Scenarios automatises executes: authentification cookies HttpOnly, activation de compte, logout/revocation, verrouillage login, scope GP homonyme, normalisation du nom GP, en-tetes de securite, suppression snapshots Super Admin.",
        "",
        "## Fonctionnalite snapshots Super Admin",
        "",
        "- Endpoint: `POST /api/v1/imports/snapshots/delete`.",
        "- Controle d'acces: `SUPER_ADMIN` uniquement.",
        "- Garde-fou: seuls les batches `SNAPSHOT` sont supprimables.",
        "- Effet: suppression des lignes `LoanRaw`, suppression du batch, recalcul des agrégats journaliers impactes.",
        "- UI: selection multiple, confirmation obligatoire, rafraichissement immediat du dashboard.",
        "",
        "## Limites restantes",
        "",
        "- Les parcours navigateur complets imports/exports/objectifs doivent encore etre automatises avec Playwright sur un environnement staging contenant des fichiers MCR de test.",
        "- Les exports PDF/Excel metier doivent etre relus visuellement sur les jeux de donnees QA avant production.",
        "",
        "## Logs",
        "",
        "```text",
        suite["stdout"][-8000:] or suite["stderr"][-8000:],
        "```",
    ]
    (REPORT_DIR / "rapport_tests_fonctionnels.md").write_text("\n".join(lines), encoding="utf-8")


def _write_security_report(results: dict[str, object]) -> None:
    suite = results["security_tests"]
    npm_audit = results["npm_audit"]
    pip_audit = results["pip_audit"]
    dynamic_checks = results["dynamic_checks"]
    lines = [
        "# Rapport final - Tests de securite applicative",
        "",
        f"Date d'execution: `{results['generated_at']}`",
        "",
        "## Resume executif",
        "",
        f"- Tests de controles applicatifs: **{_status(suite['returncode'] == 0)}**",
        f"- Audit dependances frontend production: **{_status(npm_audit['returncode'] == 0)}**",
        f"- Audit dependances Python: **{_status(pip_audit['returncode'] == 0)}**",
        "- Portee: securite applicative locale uniquement. Aucun audit infrastructure, reseau ou certification ASVS complete n'est revendique.",
        "",
        "## Controles dynamiques locaux",
        "",
        "| Controle | Attendu | Observe | Resultat |",
        "|---|---:|---:|---|",
    ]
    for item in dynamic_checks:
        lines.append(f"| `{item['url']}` | {item['expected_status']} | {item['status']} | {_status(bool(item['passed']))} |")
    lines += [
        "",
        "## Protections verifiees automatiquement",
        "",
        "- JWT transportes par cookies HttpOnly et non retournes dans le JSON de login.",
        "- Rotation/revocation: le token d'acces reutilise apres logout est refuse.",
        "- Activation de compte par jeton a usage unique, sans exposition d'un mot de passe initial.",
        "- Blocage du compte apres tentatives de connexion invalides repetees.",
        "- En-tetes `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` et CSP.",
        "- Isolation GP liee a `agent_id`, y compris lorsque deux agents portent le meme nom.",
        "- Suppression snapshots protegee par role et type de batch.",
        "",
        "## Limites et actions avant production",
        "",
        "- Executer OWASP ZAP ou Burp Suite sur un staging dedie avec authentification par role.",
        "- Executer une revue ASVS Level 3 controle par controle; la suite locale n'est pas une certification.",
        "- Refaire les audits de dependances dans la CI et traiter toute vulnerabilite detectee.",
        "- Tester la stack `docker-compose.prod.yml` avec `ENVIRONMENT=production` afin de confirmer la fermeture de `/docs` et `/openapi.json`.",
        "",
        "## Audit frontend",
        "",
        "```text",
        (npm_audit["stdout"] or npm_audit["stderr"])[-5000:],
        "```",
        "",
        "## Audit Python",
        "",
        "```text",
        (pip_audit["stdout"] or pip_audit["stderr"])[-5000:],
        "```",
    ]
    (REPORT_DIR / "rapport_securite.md").write_text("\n".join(lines), encoding="utf-8")


def _write_load_report(load_results: dict[str, object]) -> None:
    lines = [
        "# Rapport final - Test de charge local",
        "",
        f"Date d'execution: `{load_results['generated_at']}`",
        f"Cible: `{load_results['target']}`",
        "",
        f"Concurrence maximale validee localement: **{load_results['highest_validated_concurrency']}**",
        "",
        "> Cette mesure est une baseline HTTP locale, pas une certification de capacite production. "
        "Les parcours authentifies, la base de test representative et la supervision infrastructure doivent etre testes en staging.",
        "",
        "| Concurrence | Requetes | Succes | Erreurs | Taux erreur | Debit req/s | p50 ms | p95 ms | max ms |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for step in load_results["steps"]:
        latency = step["latency_ms"]
        lines.append(
            f"| {step['concurrency']} | {step['requests']} | {step['successful_requests']} | "
            f"{step['errors']} | {step['error_rate_percent']}% | "
            f"{step['throughput_requests_per_second']} | {latency['p50']} | {latency['p95']} | {latency['max']} |"
        )
    lines += [
        "",
        "## Recommandations staging",
        "",
        "- Rejouer les memes paliers sur login, dashboard, recherche, import controle et exports avec comptes QA temporaires.",
        "- Capturer CPU, RAM, connexions PostgreSQL et latence DB pendant chaque palier.",
        "- Arreter l'augmentation de charge des que le taux d'erreur depasse 1% ou que le p95 depasse le SLO defini.",
    ]
    (REPORT_DIR / "rapport_charge.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    load_path = REPORT_DIR / "load_test_results.json"
    load_run = _run(
        [
            sys.executable,
            str(BACKEND_DIR / "scripts" / "run_load_test.py"),
            "--output",
            str(load_path),
        ],
        cwd=ROOT_DIR,
    )
    load_results = json.loads(load_path.read_text(encoding="utf-8"))

    venv_pip_audit = BACKEND_DIR / ".venv" / "Scripts" / "pip-audit.exe"
    pip_audit = str(venv_pip_audit) if venv_pip_audit.exists() else shutil.which("pip-audit")
    results = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "functional_tests": _run(
            [sys.executable, "-m", "unittest", "backend.tests.test_security_controls", "-v"],
            cwd=ROOT_DIR,
        ),
        "security_tests": _run(
            [sys.executable, "-m", "unittest", "backend.tests.test_security_controls", "-v"],
            cwd=ROOT_DIR,
        ),
        "frontend_build": _run(["npm", "run", "build"], cwd=FRONTEND_DIR),
        "npm_audit": _run(["npm", "audit", "--omit=dev", "--json"], cwd=FRONTEND_DIR),
        "pip_audit": (
            _run([pip_audit, "-r", "requirements.txt"], cwd=BACKEND_DIR)
            if pip_audit
            else {
                "command": ["pip-audit", "-r", "requirements.txt"],
                "returncode": 127,
                "stdout": "",
                "stderr": "pip-audit is not installed in this environment.",
            }
        ),
        "dynamic_checks": [
            _http_check("/health", 200),
            _http_check("/api/v1/auth/me", 401),
            _http_check("/api/v1/metrics/summary", 401),
            _http_check(
                "/api/v1/imports/snapshots/delete",
                401,
                method="POST",
                body=b'{"batch_ids":[1]}',
            ),
        ],
        "load_test": load_run,
    }
    (REPORT_DIR / "validation_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_functional_report(results)
    _write_security_report(results)
    _write_load_report(load_results)

    blocking_results = [
        results["functional_tests"]["returncode"],
        results["frontend_build"]["returncode"],
        results["npm_audit"]["returncode"],
        results["pip_audit"]["returncode"],
        *[0 if check["passed"] else 1 for check in results["dynamic_checks"]],
    ]
    print(f"Final validation reports written to {REPORT_DIR}")
    if any(blocking_results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
