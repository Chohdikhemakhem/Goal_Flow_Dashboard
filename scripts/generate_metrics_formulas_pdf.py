from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "docs" / "generated"
ASSETS_DIR = OUTPUT_DIR / "user_guide_assets"
OUTPUT_PDF = OUTPUT_DIR / "formules_et_calculs_metrics_gp_mcr.pdf"


class BookmarkParagraph(Paragraph):
    def __init__(self, text: str, style: ParagraphStyle, bookmark: str | None = None):
        super().__init__(text, style)
        self.bookmark = bookmark

    def draw(self):
        if self.bookmark:
            self.canv.bookmarkPage(self.bookmark)
            self.canv.addOutlineEntry(self.getPlainText(), self.bookmark, level=0, closed=False)
        super().draw()


def build_styles():
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle(
            "cover_title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=30,
            leading=36,
            textColor=colors.white,
            alignment=TA_CENTER,
            spaceAfter=14,
        ),
        "cover_subtitle": ParagraphStyle(
            "cover_subtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=13,
            leading=18,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=22,
            textColor=colors.HexColor("#123E52"),
            spaceBefore=12,
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=17,
            textColor=colors.HexColor("#176579"),
            spaceBefore=8,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor("#20313A"),
            spaceAfter=6,
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#52636B"),
        ),
        "toc": ParagraphStyle(
            "toc",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#124F63"),
            leftIndent=8,
            spaceAfter=4,
        ),
        "cell": ParagraphStyle(
            "cell",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10.5,
            textColor=colors.HexColor("#20313A"),
        ),
        "cell_bold": ParagraphStyle(
            "cell_bold",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10.5,
            textColor=colors.white,
            alignment=TA_LEFT,
        ),
        "formula": ParagraphStyle(
            "formula",
            parent=base["BodyText"],
            fontName="Courier",
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#143642"),
        ),
    }


def p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text.replace("\n", "<br/>"), style)


def linked_toc_entry(label: str, bookmark: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(f'<link href="#{bookmark}">{label}</link>', style)


def table(data, widths, styles, repeat_rows: int = 1) -> Table:
    converted = []
    for row_index, row in enumerate(data):
        style = styles["cell_bold"] if row_index == 0 else styles["cell"]
        converted.append([p(str(cell), style) for cell in row])
    t = Table(converted, colWidths=widths, repeatRows=repeat_rows, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123E52")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
                ("TOPPADDING", (0, 0), (-1, 0), 7),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F7FAFB")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6F7")]),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C8D6DA")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 1), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
            ]
        )
    )
    return t


def on_cover(canvas, doc):
    canvas.saveState()
    bg = ASSETS_DIR / "role_cover_background.jpg"
    if bg.exists():
        canvas.drawImage(str(bg), 0, 0, width=A4[0], height=A4[1], preserveAspectRatio=False, mask="auto")
    canvas.setFillColor(colors.Color(0.04, 0.16, 0.20, alpha=0.68))
    canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    canvas.restoreState()


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#F5F8F9"))
    canvas.rect(0, A4[1] - 1.25 * cm, A4[0], 1.25 * cm, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#123E52"))
    canvas.setFont("Helvetica-Bold", 8.5)
    canvas.drawString(1.45 * cm, A4[1] - 0.78 * cm, "Metrics/GP/MCR - Formules et calculs des metrics")
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#52636B"))
    canvas.drawRightString(A4[0] - 1.45 * cm, 0.85 * cm, f"Page {doc.page}")
    canvas.setStrokeColor(colors.HexColor("#D7E2E5"))
    canvas.line(1.45 * cm, 1.15 * cm, A4[0] - 1.45 * cm, 1.15 * cm)
    canvas.restoreState()


def cover(story, styles):
    story.append(Spacer(1, 3.0 * cm))
    logo = ASSETS_DIR / "role_guide_microcred_logo.png"
    if logo.exists():
        img = Image(str(logo), width=4.2 * cm, height=2.1 * cm)
        img.hAlign = "CENTER"
        story.append(img)
        story.append(Spacer(1, 1.0 * cm))
    story.append(p("Formules et calculs<br/>des metrics", styles["cover_title"]))
    story.append(
        p(
            "Application Metrics/GP/MCR<br/>Document de reference fonctionnelle et technique",
            styles["cover_subtitle"],
        )
    )
    story.append(Spacer(1, 5.5 * cm))
    story.append(p(f"Version document: 1.0 - Genere le {date.today().strftime('%d/%m/%Y')}", styles["cover_subtitle"]))
    story.append(NextPageTemplate("normal"))
    story.append(PageBreak())


def add_section(story, styles, number: str, title: str, bookmark: str):
    story.append(BookmarkParagraph(f"{number}. {title}", styles["h1"], bookmark))


def build_document():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    styles = build_styles()
    doc = BaseDocTemplate(
        str(OUTPUT_PDF),
        pagesize=A4,
        rightMargin=1.35 * cm,
        leftMargin=1.35 * cm,
        topMargin=1.65 * cm,
        bottomMargin=1.35 * cm,
        title="Formules et calculs des metrics - Metrics/GP/MCR",
        author="MicroCred",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    cover_frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="cover")
    doc.addPageTemplates(
        [
            PageTemplate(id="cover", frames=[cover_frame], onPage=on_cover),
            PageTemplate(id="normal", frames=[frame], onPage=on_page),
        ]
    )

    story = []
    cover(story, styles)

    story.append(BookmarkParagraph("Table des matieres", styles["h1"], "toc"))
    toc_entries = [
        ("1. Sources verifiees", "sources"),
        ("2. Regles de selection du MCR et des filtres", "scope"),
        ("3. Colonnes MCR utilisees", "columns"),
        ("4. Formules de base", "base"),
        ("5. Metrics du dashboard", "dashboard"),
        ("6. Pourcentages et ratios", "ratios"),
        ("7. Metrics par agence, agent et role", "scopes"),
        ("8. Chartes et series graphiques", "charts"),
        ("9. Tableau Credits existants", "credits"),
        ("10. Objectifs, atteinte et bonus", "targets"),
        ("11. Exports Excel/PDF et rapports GP", "exports"),
        ("12. Exemples de verification", "examples"),
    ]
    for label, bookmark in toc_entries:
        story.append(linked_toc_entry(label, bookmark, styles["toc"]))
    story.append(PageBreak())

    add_section(story, styles, "1", "Sources verifiees", "sources")
    story.append(
        p(
            "Ce document a ete prepare a partir de la version locale "
            "<b>rollback-backup-security-manual</b>. Les formules ci-dessous correspondent aux calculs backend "
            "utilises par le dashboard, les tableaux journaliers et les exports.",
            styles["body"],
        )
    )
    story.append(
        table(
            [
                ["Fichier", "Role dans les calculs"],
                ["backend/app/api/v1/metrics.py", "Endpoints dashboard, metrics journaliers, credits existants, charts, filtres et scopes utilisateur."],
                ["backend/app/schemas/domain.py", "Schemas de sortie et calculs des ratios/pourcentages avec protection division par zero."],
                ["backend/app/services/metrics.py", "Recalcul des DailyMetric a partir d'une snapshot MCR datee."],
                ["backend/app/services/objective_metrics.py", "Calcul des realisations mensuelles pour les objectifs et bonus."],
                ["backend/app/services/objective_achievement.py", "Sens de calcul d'atteinte: indicateurs classiques vs indicateurs de risque PAR."],
                ["backend/app/api/v1/reports.py", "Exports Excel/PDF Admin, Super Admin, Chef d'agence et GP."],
            ],
            [5.2 * cm, 12.6 * cm],
            styles,
        )
    )

    add_section(story, styles, "2", "Regles de selection du MCR et des filtres", "scope")
    story.append(
        p(
            "Les donnees ne sont jamais melangees entre plusieurs imports. Le backend selectionne d'abord un batch MCR "
            "puis applique les filtres date, agence, agent et role utilisateur.",
            styles["body"],
        )
    )
    story.append(
        table(
            [
                ["Situation", "MCR utilise", "Filtre de dates applique"],
                ["Aucune date", "CURRENT_STATE actif. Si ancien mode sans ImportBatch: derniere snapshot legacy.", "Aucun filtre date sur DISBURSEMENT_DATE."],
                ["date_from = x et date_to = y", "MCR du mois de x/y. x et y doivent etre dans le meme mois. Priorite: HISTORICAL_MONTH puis CURRENT_STATE/SNAPSHOT du meme mois.", "Flow: x <= DISBURSEMENT_DATE <= y. Stock: DISBURSEMENT_DATE <= y."],
                ["date_from vide et date_to = y", "MCR du mois de y.", "Flow et stock: DISBURSEMENT_DATE <= y. Il n'y a pas de borne basse automatique au 1er jour du mois."],
                ["date_from = x et date_to vide", "MCR du mois de x.", "Flow: DISBURSEMENT_DATE >= x. Stock: aucune borne haute."],
                ["MCR du mois absent", "Aucun batch disponible pour ce mois.", "Erreur affichee: Aucune donnee historique MCR disponible pour MM/YYYY."],
            ],
            [4.2 * cm, 6.2 * cm, 7.4 * cm],
            styles,
        )
    )
    story.append(
        p(
            "Exemple demande: si date_from est vide et date_to = 16/12/2025, le backend choisit le MCR du mois 12/2025 "
            "et calcule les indicateurs avec DISBURSEMENT_DATE <= 16/12/2025.",
            styles["body"],
        )
    )

    add_section(story, styles, "3", "Colonnes MCR utilisees", "columns")
    story.append(
        table(
            [
                ["Colonne / champ backend", "Origine MCR", "Utilisation"],
                ["principal_outstanding", "PRINCIPAL_OUTSTANDING", "Composant principal de l'encours."],
                ["principal_due", "TOTAL_PRINCIPAL_DUE_AMT", "Composant echeance principale due de l'encours."],
                ["disbursement_amount", "DISBURSEMENT_AMOUNT", "Volume decaisse."],
                ["disbursement_date", "DISBURSEMENT_DATE", "Filtrage periode, metrics de flux et stock."],
                ["days_overdue", "TOTAL_CUR_NO_OF_DAYS_OVERDUE", "Classification PAR et cohortes."],
                ["client_id", "CLIENT_NO", "Client Actif et rapports."],
                ["contract_no", "CONTRACT_NO", "Credits existants et rapports."],
                ["agency_name", "BRANCH", "Groupement et filtre agence."],
                ["agent_name", "DAO_NAME", "Groupement et filtre agent/GP."],
                ["maturity_date", "MATURITY_DATE", "Rapport possibilite de renouvellement."],
                ["next_schedule_date", "NEXT_SCHEDULE_DATE", "Rapport echeances futures."],
                ["client_rating", "CLIENT_RATING", "Filtre renouvellement Classe 0 / Classe 1."],
                ["total_due", "TOTAL_DUE_AMT", "Rapport impayees; conserve comme colonne separee."],
                ["total_scheduled_amount", "TOTAL_SCHEDULED_AMOUNT", "Rapport echeances futures et credits existants."],
            ],
            [4.6 * cm, 4.8 * cm, 8.4 * cm],
            styles,
        )
    )

    add_section(story, styles, "4", "Formules de base", "base")
    story.append(
        table(
            [
                ["Nom", "Formule exacte", "Commentaire"],
                ["ENCOURS / EXPOSURE", "PRINCIPAL_OUTSTANDING + TOTAL_PRINCIPAL_DUE_AMT", "Dans le code: LoanRaw.principal_outstanding + LoanRaw.principal_due."],
                ["flow_condition", "true AND DISBURSEMENT_DATE >= date_from si date_from existe AND DISBURSEMENT_DATE <= date_to si date_to existe", "Utilise pour les metrics de flux: volume et nombre de decaissements."],
                ["stock_condition", "true AND DISBURSEMENT_DATE <= date_to si date_to existe", "Utilise pour les metrics de portefeuille: encours, client actif, PAR et cohortes."],
                ["Division ratio securisee", "Si ENCOURS = 0 alors ratio = 0, sinon numerator / ENCOURS", "Evite les divisions par zero dans l'API et le frontend."],
            ],
            [4.0 * cm, 8.2 * cm, 5.6 * cm],
            styles,
        )
    )

    add_section(story, styles, "5", "Metrics du dashboard", "dashboard")
    metrics_rows = [
        ["Metric", "Formule backend", "Interpretation"],
        ["Client Actif", "COUNT(DISTINCT CLIENT_NO WHERE stock_condition)", "Nombre de clients uniques dans le portefeuille selectionne."],
        ["Nombre de decaissements / Nombre de credits", "SUM(1 WHERE flow_condition)", "Nombre de lignes de credits dont DISBURSEMENT_DATE respecte le filtre de flux."],
        ["Volume decaisse", "SUM(DISBURSEMENT_AMOUNT WHERE flow_condition)", "Montant total decaisse sur la periode filtree."],
        ["Credits count", "SUM(1 WHERE stock_condition)", "Nombre de lignes de credits presentes dans le stock selectionne."],
        ["Encours", "SUM(ENCOURS WHERE stock_condition)", "Encours total du portefeuille."],
        ["Encours sain", "SUM(ENCOURS WHERE stock_condition AND TOTAL_CUR_NO_OF_DAYS_OVERDUE = 0)", "Part du portefeuille sans retard."],
        ["PAR0", "SUM(ENCOURS WHERE stock_condition AND TOTAL_CUR_NO_OF_DAYS_OVERDUE > 0)", "Encours avec au moins un jour de retard."],
        ["Cohorte 1-30", "SUM(ENCOURS WHERE stock_condition AND TOTAL_CUR_NO_OF_DAYS_OVERDUE > 0 AND <= 30)", "Encours en retard de 1 a 30 jours."],
        ["Cohorte 31-60", "SUM(ENCOURS WHERE stock_condition AND TOTAL_CUR_NO_OF_DAYS_OVERDUE >= 31 AND <= 60)", "Encours en retard de 31 a 60 jours."],
        ["Cohorte 61-90", "SUM(ENCOURS WHERE stock_condition AND TOTAL_CUR_NO_OF_DAYS_OVERDUE > 60 AND <= 90)", "Encours en retard de 61 a 90 jours."],
        ["Cohorte 91-120", "SUM(ENCOURS WHERE stock_condition AND TOTAL_CUR_NO_OF_DAYS_OVERDUE > 90 AND <= 120)", "Encours en retard de 91 a 120 jours."],
        ["PAR120", "SUM(ENCOURS WHERE stock_condition AND TOTAL_CUR_NO_OF_DAYS_OVERDUE > 120 AND < 365)", "Encours en retard strictement superieur a 120 jours et inferieur a 365 jours."],
        ["PAR30", "SUM(ENCOURS WHERE stock_condition AND TOTAL_CUR_NO_OF_DAYS_OVERDUE > 30)", "Encours en retard de plus de 30 jours."],
    ]
    story.append(table(metrics_rows, [4.2 * cm, 9.0 * cm, 4.6 * cm], styles))

    add_section(story, styles, "6", "Pourcentages et ratios", "ratios")
    story.append(
        p(
            "Les ratios sont stockes sous forme decimale dans l'API, puis affiches en pourcentage par le frontend. "
            "Exemple: 0.0436 devient 4,36%. Tous les ratios sont arrondis/quantifies a 4 decimales cote backend.",
            styles["body"],
        )
    )
    story.append(
        table(
            [
                ["Ratio", "Formule", "Condition limite"],
                ["Encours sain %", "Encours sain / Encours", "0 si Encours = 0"],
                ["PAR0 %", "PAR0 / Encours", "0 si Encours = 0"],
                ["Cohorte 1-30 %", "Cohorte 1-30 / Encours", "0 si Encours = 0"],
                ["Cohorte 31-60 %", "Cohorte 31-60 / Encours", "0 si Encours = 0"],
                ["Cohorte 61-90 %", "Cohorte 61-90 / Encours", "0 si Encours = 0"],
                ["Cohorte 91-120 %", "Cohorte 91-120 / Encours", "0 si Encours = 0"],
                ["PAR120 %", "PAR120 / Encours", "0 si Encours = 0"],
                ["PAR30 %", "PAR30 / Encours", "0 si Encours = 0"],
            ],
            [4.3 * cm, 8.2 * cm, 5.3 * cm],
            styles,
        )
    )

    add_section(story, styles, "7", "Metrics par agence, agent et role", "scopes")
    story.append(
        p(
            "Les formules ne changent pas selon le role. Ce qui change, c'est le perimetre de donnees applique avant le calcul.",
            styles["body"],
        )
    )
    story.append(
        table(
            [
                ["Profil / filtre", "Perimetre applique", "Groupement"],
                ["Super Admin", "Toutes les agences et tous les agents, sauf filtres UI agence/agent.", "Global, par agence ou par agent selon le composant."],
                ["Admin / responsable regional", "Lecture dashboard global. Pas d'acces importation selon la regle fonctionnelle actuelle.", "Toutes agences visibles en lecture."],
                ["Chef d'agence", "Agence rattachee obligatoire; filtre agent limite aux GP de son agence.", "Par agent de l'agence ou resume agence."],
                ["Portfolio Manager (GP)", "Tous les credits du GP, meme s'il apparait dans plusieurs agences, via l'identite normalisee du nom GP.", "Vue individuelle GP."],
                ["Filtre agence", "Ajoute Agency.id = agence selectionnee, sauf GP ou le scope GP prime.", "Metrics recalcules apres filtre."],
                ["Filtre agent", "Ajoute Agent.id = agent selectionne avec verification d'autorisation.", "Metrics recalcules apres filtre."],
            ],
            [4.2 * cm, 7.6 * cm, 6.0 * cm],
            styles,
        )
    )

    add_section(story, styles, "8", "Chartes et series graphiques", "charts")
    story.append(
        table(
            [
                ["Charte", "Donnees utilisees", "Formules / ordre"],
                ["Qualite portefeuille", "Points par agence, global ou tendance mensuelle selon le mode.", "Barres empilees: 1-30, 31-60, 61-90, 91-120, PAR120. Ligne/tooltip: PAR0 %, PAR30 %, PAR120 % selon configuration frontend."],
                ["Volume decaisse", "disbursement_volume par agence ou par point de tendance.", "Volume decaisse = SUM(DISBURSEMENT_AMOUNT WHERE flow_condition). Tooltip: nombre de decaissements = SUM(1 WHERE flow_condition)."],
                ["Snapshots selectionnees", "Batchs ImportBatch de type SNAPSHOT selectionnes par l'utilisateur.", "Chaque point est calcule uniquement sur LoanRaw.import_batch_id du snapshot correspondant."],
                ["Mois passes importes", "Batchs HISTORICAL_MONTH.", "Label MM/YYYY; calcul sur le batch final du mois."],
                ["Etat actuel", "Batch CURRENT_STATE actif.", "Label remplace par la date exacte de l'etat actuel si disponible."],
            ],
            [4.3 * cm, 6.1 * cm, 7.4 * cm],
            styles,
        )
    )

    add_section(story, styles, "9", "Tableau Credits existants", "credits")
    story.append(
        p(
            "Le tableau Credits existants utilise les lignes du MCR selectionne par la logique de periode. Il applique aussi "
            "les filtres de role, agence, agent, dates et recherche.",
            styles["body"],
        )
    )
    story.append(
        table(
            [
                ["Colonne affichee", "Source / formule", "Regle"],
                ["CONTRACT_NO", "CONTRACT_NO", "Tri par defaut apres DISBURSEMENT_DATE."],
                ["CLIENT_NAME", "CLIENT_NAME", "Texte client."],
                ["CLIENT_FIRST_NAME", "CLIENT_FIRST_NAME", "Texte client."],
                ["CLIENT_NO", "CLIENT_NO", "Identifiant client."],
                ["CLIENT_NCNI", "CLIENT_NCNI", "Visible uniquement pour Super Admin."],
                ["BRANCH", "BRANCH / agency_name", "Agence."],
                ["DAO_NAME", "DAO_NAME / agent_name", "GP / agent."],
                ["CLIENT_RATING", "CLIENT_RATING", "Recherche insensible aux espaces/casse, ex: Classe 0."],
                ["DISBURSEMENT_DATE", "DISBURSEMENT_DATE", "Filtre date."],
                ["MATURITY_DATE", "MATURITY_DATE", "Date echeance finale."],
                ["DISBURSEMENT_AMOUNT", "DISBURSEMENT_AMOUNT", "Montant decaisse."],
                ["JOURS DE RETARD", "TOTAL_CUR_NO_OF_DAYS_OVERDUE", "Ancien label technique masque dans l'UI/export."],
                ["TOTAL_SCHEDULED_AMOUNT", "TOTAL_SCHEDULED_AMOUNT", "Montant programme."],
                ["ENCOURS", "PRINCIPAL_OUTSTANDING + TOTAL_PRINCIPAL_DUE_AMT", "Formule corrigee et commune avec les exports."],
            ],
            [4.2 * cm, 6.8 * cm, 6.8 * cm],
            styles,
        )
    )

    add_section(story, styles, "10", "Objectifs, atteinte et bonus", "targets")
    story.append(
        p(
            "Les objectifs sont calcules sur le mois exact de l'objectif. Les realisations prennent le batch du mois cible "
            "avec priorite au HISTORICAL_MONTH, puis CURRENT_STATE du meme mois si disponible.",
            styles["body"],
        )
    )
    story.append(
        table(
            [
                ["Element", "Formule / regle", "Commentaire"],
                ["Periode objectif", "start_date = 1er jour du mois; end_date = dernier jour du mois", "Mois et annee de l'objectif."],
                ["Flux objectif", "DISBURSEMENT_DATE >= start_date AND <= end_date", "Volume decaisse et nombre de decaissements."],
                ["Stock objectif", "DISBURSEMENT_DATE <= end_date", "Encours, encours sain et PAR."],
                ["Objectif classique", "achievementRate = actualValue / targetValue", "Volume, nombre de credits, client actif, encours, encours sain."],
                ["Objectif PAR", "achievementRate = targetValue / actualValue", "Pour par_30_rate, par_0, par_1_30, par_31_60, par_30: plus bas est meilleur."],
                ["Actual PAR = 0", "achievementRate = 1", "Objectif considere atteint a 100% minimum selon le code actuel, sans sur-score infini."],
                ["targetValue <= 0", "achievementRate = 0", "Protection contre division par zero et objectif invalide."],
                ["Bonus", "Expression configuree evaluee avec les metrics realisees et cibles", "Le module bonus peut etre desactive via flag; les calculs s'appuient sur objective_metrics."],
            ],
            [4.0 * cm, 7.4 * cm, 6.4 * cm],
            styles,
        )
    )

    add_section(story, styles, "11", "Exports Excel/PDF et rapports GP", "exports")
    story.append(
        table(
            [
                ["Export / rapport", "Critere", "Colonnes et calculs"],
                ["Admin / Super Admin metrics", "Meme perimetre dashboard/export; sections par agence puis agents.", "Client Actif, NB DE CREDITS, Volume decaisse, Encours, Encours sain, PAR0, 1-30, 31-60, 61-90, 91-120, PAR120, PAR30 et leurs %."],
                ["Liste des impayees", "TOTAL_CUR_NO_OF_DAYS_OVERDUE > 2 sur MCR actuel.", "CLIENT_NO, CLIENT_NAME, CLIENT_FIRST_NAME, TOTAL_DUE_AMT, JOURS DE RETARD, ENCOURS."],
                ["Liste possibilite de renouvellement", "MATURITY_DATE entre aujourd'hui et aujourd'hui + 90 jours ET CLIENT_RATING Classe 0 ou Classe 1.", "CLIENT_NO, CLIENT_NAME, CLIENT_FIRST_NAME, CATEGORY_DESC, DISBURSEMENT_AMOUNT, MATURITY_DATE, ENCOURS."],
                ["Liste echeances futures", "NEXT_SCHEDULE_DATE entre aujourd'hui et aujourd'hui + future_days, avec future_days entre 1 et 10.", "CLIENT_NO, CLIENT_NAME, CLIENT_FIRST_NAME, NEXT_SCHEDULE_DATE, TOTAL_SCHEDULED_AMOUNT, ENCOURS."],
                ["ENCOURS dans les rapports", "PRINCIPAL_OUTSTANDING + TOTAL_PRINCIPAL_DUE_AMT", "Meme formule que le dashboard et le tableau Credits existants."],
            ],
            [4.0 * cm, 7.0 * cm, 6.8 * cm],
            styles,
        )
    )

    add_section(story, styles, "12", "Exemples de verification", "examples")
    examples = [
        ["Cas", "Donnees fictives", "Resultat attendu"],
        ["Calcul Encours", "PRINCIPAL_OUTSTANDING = 1 000; TOTAL_PRINCIPAL_DUE_AMT = 250", "ENCOURS = 1 250"],
        ["Cohorte 61-90", "ENCOURS = 1 250; TOTAL_CUR_NO_OF_DAYS_OVERDUE = 75", "La ligne entre dans Cohorte 61-90."],
        ["Cohorte 91-120", "ENCOURS = 2 000; TOTAL_CUR_NO_OF_DAYS_OVERDUE = 100", "La ligne entre dans Cohorte 91-120."],
        ["PAR120", "ENCOURS = 3 000; TOTAL_CUR_NO_OF_DAYS_OVERDUE = 180", "La ligne entre dans PAR120."],
        ["PAR30 %", "PAR30 = 50 000; ENCOURS = 1 000 000", "PAR30 % = 50 000 / 1 000 000 = 0,05 = 5%."],
        ["date_from vide; date_to = 16/12/2025", "MCR 12/2025 existe; credits avec dates 10/12 et 20/12", "Le 10/12 est inclus; le 20/12 est exclu; aucun filtre >= 01/12 ajoute automatiquement."],
    ]
    story.append(table(examples, [4.2 * cm, 7.3 * cm, 6.3 * cm], styles))
    story.append(Spacer(1, 0.25 * cm))
    story.append(
        p(
            "Checklist: verifier les donnees MCR sources, confirmer le batch selectionne, appliquer les filtres role/agence/agent, "
            "recalculer ENCOURS ligne par ligne, puis comparer les sommes et ratios avec l'interface.",
            styles["body"],
        )
    )

    doc.build(story)
    return OUTPUT_PDF


if __name__ == "__main__":
    output = build_document()
    print(f"PDF genere: {output}")
