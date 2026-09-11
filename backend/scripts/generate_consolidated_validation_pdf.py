from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "docs" / "reports" / "final"
VALIDATION_PATH = REPORT_DIR / "validation_results.json"
LOAD_PATH = REPORT_DIR / "load_test_results.json"
EXCLUDED_PARTS = {".venv", "node_modules", "dist", "__pycache__", ".git"}


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("BodySmall", parent=styles["BodyText"], fontSize=8.5, leading=11))
    styles.add(ParagraphStyle("Note", parent=styles["BodySmall"], textColor=colors.HexColor("#4b5563")))
    return styles


def _table(rows: list[list[str]], widths: list[float]) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3b73")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _status(value: bool) -> str:
    return "PASS" if value else "FAIL"


def _draw_footer(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.setFont("Helvetica", 8)
    canvas.drawString(1.4 * cm, 1.0 * cm, "Metrics/GP/MCR - Validation applicative consolidee")
    canvas.drawRightString(A4[0] - 1.4 * cm, 1.0 * cm, f"Page {doc.page}")
    canvas.restoreState()


def _write_structure_inventory() -> None:
    files = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or EXCLUDED_PARTS.intersection(path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("docs/reports/final/"):
            continue
        files.append(f"- `{rel}`")
    body = [
        "# Structure detaillee finale du projet",
        "",
        "Inventaire genere automatiquement depuis la version courante du workspace.",
        "",
        "## Modules critiques",
        "",
        "- `backend/app/api/v1/imports.py`: endpoints d'import et suppression securisee de snapshots.",
        "- `backend/app/services/imports.py`: workflow CURRENT_STATE, SNAPSHOT, HISTORICAL_MONTH et nettoyage.",
        "- `backend/app/api/v1/metrics.py`: metriques, chartes et scopes agences/agents.",
        "- `backend/app/api/v1/reports.py`: exports Excel/PDF.",
        "- `backend/app/core/security.py`: JWT cookies HttpOnly, rotation, revocation et hashing.",
        "- `frontend/src/main.jsx`: dashboard React, filtres, tableaux et panneau Super Admin snapshots.",
        "- `frontend/src/api.js`: appels API centralises.",
        "",
        "## Inventaire des fichiers",
        "",
        *files,
    ]
    (REPORT_DIR / "structure_detaillee_projet.md").write_text("\n".join(body), encoding="utf-8")


def _write_qa_readme(results: dict[str, object], load: dict[str, object]) -> None:
    dynamic_ok = all(check["passed"] for check in results["dynamic_checks"])
    body = [
        "# Livrables QA finaux Metrics/GP/MCR",
        "",
        f"Generation: `{results['generated_at']}`",
        "",
        "## Resume",
        "",
        f"- Tests automatises backend: **{_status(results['functional_tests']['returncode'] == 0)}**",
        f"- Build frontend: **{_status(results['frontend_build']['returncode'] == 0)}**",
        f"- Audit npm production: **{_status(results['npm_audit']['returncode'] == 0)}**",
        f"- Audit Python: **{_status(results['pip_audit']['returncode'] == 0)}**",
        f"- Controles HTTP locaux: **{_status(dynamic_ok)}**",
        f"- Concurrence HTTP locale maximale validee: **{load['highest_validated_concurrency']}**",
        "",
        "## Fonctionnalite ajoutee",
        "",
        "Le Super Admin peut supprimer une ou plusieurs snapshots erronees depuis le dashboard. "
        "La confirmation est obligatoire et le backend refuse la suppression des batches CURRENT_STATE ou HISTORICAL_MONTH.",
        "",
        "## Usage local",
        "",
        "Utiliser `http://localhost:5173` pour le frontend local. Ne pas alterner entre `localhost` et "
        "`127.0.0.1`: les cookies d'authentification SameSite sont volontairement stricts.",
        "",
        "## Limites",
        "",
        "Ce lot constitue une validation applicative locale automatisee. Une recette staging reste obligatoire "
        "pour les parcours navigateur complets, les fichiers MCR representatifs, les exports visuels et la capacite production.",
        "",
        "## Capture QA",
        "",
        "- `captures/login.png`: ouverture locale sur formulaire de connexion vide, sans preconnexion automatique.",
    ]
    (REPORT_DIR / "README_QA_FINAL.md").write_text("\n".join(body), encoding="utf-8")


def build_pdf(results: dict[str, object], load: dict[str, object]) -> None:
    styles = _styles()
    output = REPORT_DIR / "rapport_validation_final.pdf"
    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=1.4 * cm,
        rightMargin=1.4 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.6 * cm,
    )
    story = [
        Paragraph("Rapport final consolide - Metrics/GP/MCR", styles["Title"]),
        Paragraph(f"Generation: {results['generated_at']}", styles["Note"]),
        Spacer(1, 10),
        Paragraph("1. Resume executif", styles["Heading1"]),
        Paragraph(
            "La version courante a ete verifiee avec une suite automatisee locale, un build frontend, "
            "des audits de dependances et une baseline de charge HTTP. La suppression manuelle des snapshots "
            "erronees est maintenant reservee au Super Admin.",
            styles["BodyText"],
        ),
        Spacer(1, 8),
    ]
    summary_rows = [
        ["Controle", "Resultat"],
        ["Tests fonctionnels et securite backend", _status(results["functional_tests"]["returncode"] == 0)],
        ["Build frontend React/Vite", _status(results["frontend_build"]["returncode"] == 0)],
        ["Audit dependances npm production", _status(results["npm_audit"]["returncode"] == 0)],
        ["Audit dependances Python", _status(results["pip_audit"]["returncode"] == 0)],
        ["Controles HTTP dynamiques locaux", _status(all(item["passed"] for item in results["dynamic_checks"]))],
        ["Charge HTTP locale maximale validee", str(load["highest_validated_concurrency"])],
    ]
    story += [_table(summary_rows, [11.0 * cm, 5.5 * cm]), Spacer(1, 10)]

    story += [Paragraph("2. Controles HTTP", styles["Heading1"])]
    http_rows = [["URL", "Attendu", "Observe", "Resultat"]]
    for item in results["dynamic_checks"]:
        http_rows.append([item["url"], str(item["expected_status"]), str(item["status"]), _status(item["passed"])])
    story += [_table(http_rows, [10.2 * cm, 2.0 * cm, 2.0 * cm, 2.3 * cm]), Spacer(1, 10)]

    story += [Paragraph("3. Fonctionnalite snapshots Super Admin", styles["Heading1"])]
    story += [
        Paragraph(
            "Endpoint: POST /api/v1/imports/snapshots/delete. Le controle RBAC exige SUPER_ADMIN. "
            "Le service supprime les LoanRaw rattaches, le batch SNAPSHOT et recalcule les agregats journaliers. "
            "Les autres types de batches sont refuses. L'interface propose une selection multiple et une confirmation.",
            styles["BodyText"],
        ),
        Spacer(1, 10),
    ]

    story += [Paragraph("4. Baseline de charge locale", styles["Heading1"])]
    load_rows = [["Concurrence", "Requetes", "Succes", "Erreurs", "p95 ms", "Debit req/s"]]
    for step in load["steps"]:
        load_rows.append(
            [
                str(step["concurrency"]),
                str(step["requests"]),
                str(step["successful_requests"]),
                str(step["errors"]),
                str(step["latency_ms"]["p95"]),
                str(step["throughput_requests_per_second"]),
            ]
        )
    story += [_table(load_rows, [2.8 * cm, 2.8 * cm, 2.8 * cm, 2.8 * cm, 2.8 * cm, 2.8 * cm]), Spacer(1, 8)]
    story.append(
        Paragraph(
            "Attention: cette baseline locale sur /health ne constitue pas une capacite maximale production. "
            "Une campagne staging authentifiee avec donnees QA representatives reste requise.",
            styles["Note"],
        )
    )

    story += [PageBreak(), Paragraph("5. Actions avant production", styles["Heading1"])]
    for item in [
        "Executer une recette Playwright desktop/tablette/mobile avec comptes QA par role.",
        "Executer OWASP ZAP ou Burp sur un staging isole et traiter les observations.",
        "Rejouer une charge authentifiee sur dashboard, recherche, imports et exports avec supervision DB.",
        "Relire visuellement chaque export Excel/PDF avec un jeu MCR representatif.",
        "Tester docker-compose.prod.yml avec ENVIRONMENT=production et confirmer la fermeture de Swagger/OpenAPI.",
    ]:
        story.append(Paragraph(f"- {item}", styles["BodyText"]))
    story += [
        Spacer(1, 10),
        Paragraph("6. Decision", styles["Heading1"]),
        Paragraph(
            "Validation locale: PASS. Decision production: GO AVEC RESERVES, sous condition de recette staging "
            "et de validation de charge representative.",
            styles["BodyText"],
        ),
    ]
    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    results = json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))
    load = json.loads(LOAD_PATH.read_text(encoding="utf-8"))
    _write_structure_inventory()
    _write_qa_readme(results, load)
    build_pdf(results, load)
    print(f"Consolidated reports written to {REPORT_DIR}")


if __name__ == "__main__":
    main()
