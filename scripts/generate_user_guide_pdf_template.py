from __future__ import annotations

import io
import urllib.request
from datetime import date
from pathlib import Path

from docx import Document
from PIL import Image, ImageEnhance, ImageOps
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    ListFlowable,
    ListItem,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "generated"
ASSET_DIR = OUT_DIR / "user_guide_assets"
PDF_PATH = OUT_DIR / "guide_utilisateur_metrics_gp_mcr_final.pdf"
TEMPLATE_PATH = Path(r"C:\Users\chohd\Downloads\template.docx")

APP_NAME = "Performance Command Center"


AUTHOR = "Equipe Projet MicroCred"
TODAY = date.today().strftime("%d/%m/%Y")
COVER_IMAGE_URL = "https://images.unsplash.com/photo-1554224155-6726b3ff858f?auto=format&fit=crop&w=1600&q=80"

BLUE = colors.HexColor("#0B7F8C")
DARK_BLUE = colors.HexColor("#11566A")
GREEN = colors.HexColor("#36A852")
LIGHT_BLUE = colors.HexColor("#E8F3F5")
LIGHT_GRAY = colors.HexColor("#F8FAFC")
MID_GRAY = colors.HexColor("#CBD5E1")
TEXT = colors.HexColor("#18212F")
MUTED = colors.HexColor("#64748B")
WHITE = colors.white


SECTIONS = [
    {
        "id": "intro",
        "title": "1. Introduction",
        "description": (
            "Metrics/GP/MCR est une application web de pilotage de performance dédiée au suivi des portefeuilles "
            "microfinance, à l’import des fichiers MCR, à l’analyse des indicateurs GP/agence, à la gestion des objectifs "
            "et aux exports opérationnels. Elle centralise l’état actuel, les mois historiques et les snapshots "
            "intermédiaires afin de fournir une vue fiable, tracée et exploitable par les différents profils métiers."
        ),
        "steps": [
            "Ouvrir l’application depuis l’URL communiquée par l’équipe interne.",
            "Identifier son profil utilisateur : GP, Chef d’agence, Admin régional ou Super Admin siège.",
            "Consulter les modules disponibles dans la barre latérale selon les droits accordés.",
        ],
        "permissions": "Tous les utilisateurs peuvent consulter cette logique générale. Les modules visibles dépendent du rôle connecté.",
    },
    {
        "id": "roles",
        "title": "2. Rôles et permissions",
        "description": (
            "L’application applique une séparation des accès par profil. Chaque utilisateur voit uniquement les modules "
            "et les données correspondant à son périmètre opérationnel."
        ),
        "steps": [
            "Se connecter avec un compte valide.",
            "Observer les entrées disponibles dans le menu latéral.",
            "Vérifier que les filtres agence et agent respectent le périmètre du profil.",
        ],
        "permissions": "GP : périmètre individuel. Chef d’agence : son agence. Admin : lecture dashboard. Super Admin : administration complète.",
    },
    {
        "id": "connexion",
        "title": "3. Première connexion et activation du compte",
        "description": (
            "La première connexion se fait avec un jeton d’activation fourni par l’administrateur. Ce jeton permet "
            "à l’utilisateur de créer son propre mot de passe puis d’activer son compte. Après activation, l’utilisateur "
            "se connecte normalement avec son email professionnel et le mot de passe qu’il vient de définir."
        ),
        "steps": [
            "Ouvrir l’URL de l’application dans le navigateur.",
            "Cliquer sur le lien ou bouton Première connexion.",
            "Coller le jeton d’activation délivré par l’administrateur.",
            "Créer un nouveau mot de passe respectant la politique de sécurité : minimum 12 caractères, une majuscule, une minuscule, au moins un chiffre et au moins un caractère spécial.",
            "Confirmer le nouveau mot de passe si le formulaire le demande.",
            "Cliquer sur Activer pour finaliser la création du compte.",
            "Revenir à l’écran de connexion, saisir l’email délivré par l’administrateur et le mot de passe créé.",
            "Valider la connexion pour accéder au dashboard correspondant au profil utilisateur.",
        ],
        "permissions": "Tous les profils activent leur compte via Première connexion lorsqu’un jeton leur est fourni. La génération du jeton est réservée à l’administrateur autorisé.",
    },
    {
        "id": "dashboard",
        "title": "4. Dashboard Metrics",
        "description": (
            "Le dashboard centralise les indicateurs de performance : Client Actif, Nombre de décaissements, Volume décaissé, "
            "Encours, Encours sain, PAR0, PAR30, PAR120 et cohortes de retard. Il contient aussi les charts Qualité Portefeuille "
            "et Volume Décaissé."
        ),
        "steps": [
            "Cliquer sur Dashboard dans la barre latérale.",
            "Lire les cartes de metrics affichées en haut de page.",
            "Survoler le chart Qualité Portefeuille pour consulter PAR0%, PAR30%, PAR120% et les cohortes.",
            "Survoler le chart Volume Décaissé pour consulter le volume et le nombre de décaissements.",
            "Utiliser les switchers disponibles selon le rôle pour basculer entre vue par agence et vue globale.",
        ],
        "permissions": "GP : périmètre individuel. Chef d’agence : agence et GP rattachés. Admin : dashboard global lecture seule. Super Admin : toutes les données.",
    },
    {
        "id": "filtres",
        "title": "5. Filtres, période, snapshots et état actuel",
        "description": (
            "La barre de filtrage combine agence, agent, dates, snapshots et recherche. L’indicateur de période filtrée "
            "affiche la plage active et la date de l’état actuel indique la référence MCR la plus récente."
        ),
        "steps": [
            "Sélectionner une agence si le profil y est autorisé.",
            "Sélectionner un agent si nécessaire.",
            "Renseigner une date de début et une date de fin appartenant au même mois.",
            "Sélectionner une ou plusieurs snapshots dans le multi-select si une comparaison est souhaitée.",
            "Cliquer sur l’icône de réinitialisation pour vider tous les filtres.",
            "Utiliser le bouton mois courant pour filtrer du premier jour du mois jusqu’au dernier snapshot actif.",
        ],
        "permissions": "Les filtres respectent le scope du rôle connecté. Un GP reste limité à ses propres crédits.",
    },
    {
        "id": "tableaux",
        "title": "6. Metrics journaliers : Metrics GP et Crédits existants",
        "description": (
            "La section Metrics journaliers propose un switch entre le tableau Metrics GP et le tableau Crédits existants MCR actuel. "
            "Les tableaux supportent recherche globale, tri, pagination et adaptation des colonnes selon le rôle."
        ),
        "steps": [
            "Descendre jusqu’à la section Metrics journaliers.",
            "Choisir Metrics GP ou Crédits existants avec le switch.",
            "Utiliser la recherche pour filtrer toutes les données disponibles.",
            "Cliquer sur les en-têtes numériques ou date pour trier en ASC/DESC.",
            "Choisir le nombre de lignes par page dans la barre de pagination.",
        ],
        "permissions": "Tous les profils peuvent consulter les tableaux dans leur périmètre. Les colonnes visibles varient selon le rôle.",
    },
    {
        "id": "exports",
        "title": "7. Exports Excel/PDF",
        "description": (
            "Les exports produisent des fichiers professionnels à partir des données visibles ou du périmètre utilisateur. "
            "Les rapports GP et Chef d’agence proposent les listes impayées, renouvellement et échéances futures."
        ),
        "steps": [
            "Depuis le dashboard, repérer la zone de téléchargement des rapports.",
            "Choisir le type de rapport dans la liste déroulante.",
            "Pour les échéances futures, saisir une période en jours entre 1 et 10.",
            "Cliquer sur Excel ou PDF selon le format attendu.",
            "Ouvrir le fichier téléchargé et vérifier le périmètre, les colonnes et les totaux.",
        ],
        "permissions": "GP et Chef d’agence disposent d’exports opérationnels. Admin et Super Admin disposent d’exports consolidés selon leurs droits.",
    },
    {
        "id": "importation",
        "title": "8. Importation MCR",
        "description": (
            "Le module Importation est réservé au Super Admin. Il permet d’importer l’état actuel quotidien et les mois historiques "
            "finalisés. Chaque import est rattaché à un batch afin de tracer son origine."
        ),
        "steps": [
            "Cliquer sur Importation dans la sidebar.",
            "Dans Importer l’état actuel, choisir le fichier MCR quotidien.",
            "Cliquer sur Importer l’état actuel et attendre la confirmation.",
            "Pour un mois passé, sélectionner le fichier final et renseigner le mois concerné.",
            "Cliquer sur Importer le mois passé ou remplacer si le mois existe déjà.",
        ],
        "permissions": "Module réservé au Super Admin. Admin, Chef d’agence et GP n’ont pas accès à l’importation.",
    },
    {
        "id": "objectifs",
        "title": "9. Gestion des objectifs",
        "description": (
            "La section Objectifs permet de définir et suivre les objectifs mensuels ou annuels. Les objectifs PAR sont des objectifs "
            "de limitation du risque : une valeur réalisée plus basse est meilleure."
        ),
        "steps": [
            "Cliquer sur Objectifs si le rôle y a accès.",
            "Sélectionner la période de l’objectif : mois et année.",
            "Pour le Super Admin, créer ou modifier les objectifs d’agence.",
            "Pour le Chef d’agence, sélectionner un GP de son agence et répartir l’objectif.",
            "Enregistrer puis vérifier l’apparition de l’objectif dans le tableau.",
        ],
        "permissions": "Super Admin : objectifs agence. Chef d’agence : objectifs GP de son agence. GP : lecture seule.",
    },
    {
        "id": "snapshots",
        "title": "10. Gestion des snapshots et imports",
        "description": (
            "Les snapshots représentent des états MCR intermédiaires datés. Ils peuvent être ajoutés aux charts pour comparaison "
            "et, si importés par erreur, supprimés par un profil autorisé."
        ),
        "steps": [
            "Ouvrir le module Importation.",
            "Consulter la table Imports et snapshots.",
            "Identifier le batch par type, date snapshot, période et nom de fichier.",
            "Pour supprimer une snapshot ou un mois passé erroné, cliquer sur Supprimer.",
            "Confirmer l’action puis retourner au dashboard pour vérifier que les données ont disparu.",
        ],
        "permissions": "Suppression réservée au Super Admin. Les autres profils sélectionnent seulement les snapshots disponibles dans leur périmètre.",
    },
    {
        "id": "utilisateurs",
        "title": "11. Gestion des utilisateurs",
        "description": (
            "Le module Utilisateurs permet au Super Admin de créer, modifier, activer, désactiver et réinitialiser les comptes "
            "des différents profils."
        ),
        "steps": [
            "Cliquer sur Utilisateurs dans la sidebar.",
            "Rechercher un utilisateur par email, nom ou rôle.",
            "Créer un nouvel utilisateur avec email, nom complet, rôle et rattachement agence/agent si nécessaire.",
            "Modifier le rôle ou le rattachement si besoin.",
            "Activer, désactiver ou réinitialiser l’accès selon le besoin opérationnel.",
        ],
        "permissions": "Module réservé au Super Admin.",
    },
    {
        "id": "bonus",
        "title": "12. Module Bonus",
        "description": (
            "Le module Bonus est actuellement visible mais inactif dans l’environnement de test. Il reste identifiable dans la navigation "
            "afin d’anticiper son activation future sans déclencher de calculs."
        ),
        "steps": [
            "Cliquer sur Bonus dans la sidebar.",
            "Lire le message Module en développement.",
            "Fermer ou changer de module pour revenir au dashboard.",
        ],
        "permissions": "Visible selon profil, mais actions désactivées tant que BONUS_MODULE_ACTIVE est false.",
    },
    {
        "id": "annexes",
        "title": "13. Annexes",
        "description": (
            "Les annexes regroupent les définitions des principaux indicateurs, les conventions graphiques et les instructions "
            "pour compléter le guide avec des captures d’écran."
        ),
        "steps": [
            "Consulter le glossaire des metrics pour comprendre la signification des indicateurs.",
            "Appliquer les conventions de couleur lors de la formation des utilisateurs.",
            "Insérer les captures d’écran aux emplacements prévus.",
        ],
        "permissions": "Annexes consultables par tous les profils.",
    },
]


METRICS = [
    ["Client Actif", "Nombre de clients actifs dans le périmètre et la période sélectionnés."],
    ["Nombre de décaissements", "Nombre de contrats dont la date de décaissement appartient à la période filtrée."],
    ["Volume décaissé", "Somme des montants décaissés dans la période sélectionnée."],
    ["Encours", "Exposition calculée sur les crédits actifs selon la formule métier courante."],
    ["Encours sain", "Part de l’encours considérée comme saine selon les règles métier."],
    ["PAR0", "Encours des crédits avec retard strictement supérieur à 0 jour selon la règle appliquée."],
    ["PAR30", "Encours des crédits avec retard supérieur à 30 jours; le pourcentage est rapporté à l’encours."],
    ["Cohorte 1-30", "Encours des crédits avec retard de 1 à 30 jours."],
    ["Cohorte 31-60", "Encours des crédits avec retard de 31 à 60 jours."],
    ["Cohorte 61-90", "Encours des crédits avec retard de 61 à 90 jours."],
    ["Cohorte 91-120", "Encours des crédits avec retard de 91 à 120 jours."],
    ["PAR120", "Encours des crédits avec retard supérieur à 120 jours et inférieur à 365 jours."],
]


class BookmarkParagraph(Paragraph):
    def __init__(self, text, style, bookmark, outline_level=0):
        super().__init__(text, style)
        self.bookmark = bookmark
        self.outline_level = outline_level

    def draw(self):
        self.canv.bookmarkPage(self.bookmark)
        self.canv.addOutlineEntry(self.getPlainText(), self.bookmark, self.outline_level, closed=False)
        super().draw()


class UserGuideDoc(BaseDocTemplate):
    def __init__(self, filename: str, **kwargs):
        super().__init__(filename, **kwargs)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="normal")
        cover_frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="cover")
        self.addPageTemplates(
            [
                PageTemplate(id="cover", frames=[cover_frame], onPage=draw_cover),
                PageTemplate(id="main", frames=[frame], onPage=draw_page),
            ]
        )


def extract_template_assets() -> tuple[Path, Path, Path]:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    doc = Document(TEMPLATE_PATH)
    images: list[Path] = []
    seen = set()
    for part in [doc.part, *[section.header.part for section in doc.sections], *[section.footer.part for section in doc.sections]]:
        for rel in part.rels.values():
            if "image" not in rel.reltype or id(rel.target_part) in seen:
                continue
            seen.add(id(rel.target_part))
            suffix = "." + rel.target_part.content_type.split("/")[-1].replace("jpeg", "jpg")
            path = ASSET_DIR / f"template_asset_{len(images) + 1}{suffix}"
            path.write_bytes(rel.target_part.blob)
            images.append(path)
    if len(images) < 2:
        raise RuntimeError("La template doit contenir au moins deux images: header et footer.")

    header_path, footer_path = images[0], images[1]
    logo_path = ASSET_DIR / "microcred_logo.png"
    header = Image.open(header_path).convert("RGBA")
    logo = header.crop((0, 0, min(330, header.width), header.height))
    logo.save(logo_path)
    return header_path, footer_path, logo_path


def download_cover_image() -> Path:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = ASSET_DIR / "cover_raw.jpg"
    final_path = ASSET_DIR / "cover_background.jpg"
    if not final_path.exists():
        with urllib.request.urlopen(COVER_IMAGE_URL, timeout=30) as response:
            raw_path.write_bytes(response.read())
        image = Image.open(raw_path).convert("RGB")
        target_size = (1600, 2263)
        image = ImageOps.fit(image, target_size, method=Image.Resampling.LANCZOS)
        image = ImageEnhance.Brightness(image).enhance(0.62)
        image.save(final_path, quality=92)
    return final_path


HEADER_IMG, FOOTER_IMG, LOGO_IMG = extract_template_assets()
COVER_IMG = download_cover_image()


def make_styles():
    base = getSampleStyleSheet()
    return {
        "CoverTitle": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=32,
            leading=38,
            textColor=WHITE,
            alignment=TA_LEFT,
            spaceAfter=14,
        ),
        "CoverSub": ParagraphStyle(
            "CoverSub",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=14,
            leading=19,
            textColor=colors.HexColor("#EAF7FA"),
            alignment=TA_LEFT,
            spaceAfter=8,
        ),
        "H1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=15.5,
            leading=20,
            textColor=DARK_BLUE,
            spaceBefore=13,
            spaceAfter=8,
        ),
        "H2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=16,
            textColor=BLUE,
            spaceBefore=9,
            spaceAfter=5,
        ),
        "Body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13.2,
            textColor=TEXT,
            alignment=TA_LEFT,
            spaceAfter=6,
        ),
        "Small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.0,
            leading=10.2,
            textColor=MUTED,
            spaceAfter=4,
        ),
        "Caption": ParagraphStyle(
            "Caption",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=10,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "Box": ParagraphStyle(
            "Box",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
        "TOC": ParagraphStyle(
            "TOC",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10.3,
            leading=15,
            textColor=DARK_BLUE,
            spaceAfter=5,
            leftIndent=12,
        ),
    }


S = make_styles()


def p(text: str, style: str = "Body") -> Paragraph:
    return Paragraph(text, S[style])


def h(section: dict) -> BookmarkParagraph:
    return BookmarkParagraph(section["title"], S["H1"], section["id"], 0)


def draw_template_bands(canvas, doc, include_page_number: bool = True):
    width, height = A4
    canvas.drawImage(str(HEADER_IMG), 0, height - 2.28 * cm, width=width, height=2.28 * cm, preserveAspectRatio=False, mask="auto")
    canvas.drawImage(str(FOOTER_IMG), 0, 0, width=width, height=1.08 * cm, preserveAspectRatio=False, mask="auto")
    if include_page_number:
        canvas.saveState()
        canvas.setFillColor(WHITE)
        canvas.setFont("Helvetica-Bold", 8.2)
        canvas.drawRightString(width - 1.0 * cm, 0.34 * cm, f"Page {doc.page}")
        canvas.restoreState()


def draw_cover(canvas, doc):
    width, height = A4
    canvas.drawImage(str(COVER_IMG), 0, 0, width=width, height=height, preserveAspectRatio=False, mask="auto")
    canvas.saveState()
    canvas.setFillColor(colors.Color(0.02, 0.22, 0.27, alpha=0.78))
    canvas.rect(0, 0, width, height, stroke=0, fill=1)
    canvas.setFillColor(colors.Color(1, 1, 1, alpha=0.13))
    canvas.roundRect(1.15 * cm, 5.85 * cm, 14.4 * cm, 16.65 * cm, 18, stroke=0, fill=1)
    canvas.setFillColor(colors.Color(0.04, 0.50, 0.55, alpha=0.88))
    canvas.roundRect(1.15 * cm, 5.85 * cm, 0.16 * cm, 16.65 * cm, 5, stroke=0, fill=1)
    canvas.setFillColor(colors.Color(0, 0, 0, alpha=0.16))
    canvas.roundRect(1.95 * cm, 20.95 * cm, 6.35 * cm, 2.62 * cm, 12, stroke=0, fill=1)
    canvas.setFillColor(colors.Color(1, 1, 1, alpha=0.96))
    canvas.roundRect(1.82 * cm, 21.08 * cm, 6.35 * cm, 2.62 * cm, 12, stroke=0, fill=1)
    canvas.drawImage(
        str(LOGO_IMG),
        2.22 * cm,
        21.43 * cm,
        width=5.55 * cm,
        height=1.92 * cm,
        preserveAspectRatio=True,
        mask="auto",
    )
    canvas.setFillColor(colors.Color(0.22, 0.66, 0.32, alpha=0.92))
    canvas.circle(17.4 * cm, 23.5 * cm, 0.18 * cm, stroke=0, fill=1)
    canvas.circle(18.05 * cm, 22.95 * cm, 0.11 * cm, stroke=0, fill=1)
    canvas.setStrokeColor(colors.Color(1, 1, 1, alpha=0.34))
    canvas.setLineWidth(0.8)
    canvas.line(1.9 * cm, 7.55 * cm, 14.2 * cm, 7.55 * cm)
    canvas.setStrokeColor(colors.Color(0.22, 0.66, 0.32, alpha=0.76))
    canvas.setLineWidth(3.0)
    canvas.line(1.9 * cm, 7.25 * cm, 7.4 * cm, 7.25 * cm)
    canvas.restoreState()


def draw_page(canvas, doc):
    draw_template_bands(canvas, doc, include_page_number=True)


def bullet_list(items: list[str]) -> ListFlowable:
    return ListFlowable(
        [ListItem(p(item), leftIndent=12) for item in items],
        bulletType="bullet",
        leftIndent=18,
        bulletFontName="Helvetica",
        bulletFontSize=7,
    )


def screenshot_box(caption: str) -> list:
    box = Table(
        [[p("[INSÉRER CAPTURE ICI]", "Box")]],
        colWidths=[16.1 * cm],
        rowHeights=[2.75 * cm],
    )
    box.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1.0, colors.HexColor("#94A3B8")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    return [box, p(caption, "Caption")]


def numbered_steps(items: list[str], prefix: str) -> list:
    flowables = []
    for index, item in enumerate(items, 1):
        flowables.append(p(f"<b>Étape {index} :</b> {item}"))
        flowables.extend(screenshot_box(f"Capture {prefix}.{index} - {item[:76]}"))
    return flowables


def info_box(title: str, text: str):
    table = Table([[p(f"<b>{title} :</b> {text}")]], colWidths=[16.1 * cm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BLUE),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#CFE8ED")),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def data_table(headers: list[str], rows: list[list[str]], widths: list[float]) -> Table:
    data = [[p(f"<b>{header}</b>", "Small") for header in headers]]
    data.extend([[p(str(cell), "Small") for cell in row] for row in rows])
    table = Table(data, colWidths=[w * cm for w in widths], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), DARK_BLUE),
                ("GRID", (0, 0), (-1, -1), 0.45, MID_GRAY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    for row_index in range(1, len(data)):
        if row_index % 2 == 0:
            table.setStyle(TableStyle([("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#FBFCFE"))]))
    return table


def add_section(story: list, section: dict):
    story.append(h(section))
    story.append(p("Description de la fonctionnalité", "H2"))
    story.append(p(section["description"]))
    story.append(p("Étapes d’utilisation", "H2"))
    story.extend(numbered_steps(section["steps"], section["title"].split(".")[0]))
    story.append(info_box("Permissions nécessaires", section["permissions"]))
    story.append(Spacer(1, 0.2 * cm))


def build_cover(story: list):
    story.append(Spacer(1, 7.55 * cm))
    story.append(p("Guide de l’utilisateur", "CoverTitle"))
    story.append(p(APP_NAME, "CoverSub"))
   
    story.append(p("Document de formation.", "CoverSub"))
    story.append(NextPageTemplate("main"))
    story.append(PageBreak())


def build_toc(story: list):
    story.append(BookmarkParagraph("Table des matières", S["H1"], "toc", 0))
    for section in SECTIONS:
        story.append(Paragraph(f'<link href="#{section["id"]}">{section["title"]}</link>', S["TOC"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(info_box("Navigation PDF", "Chaque entrée de cette table des matières est cliquable et redirige vers la section correspondante."))
    story.append(PageBreak())


def build_roles_table(story: list):
    rows = [
        ["Portfolio Manager / GP", "Ses crédits et metrics, y compris crédits multi-agences rattachés à lui.", "Consulter dashboard, filtrer, exporter ses listes.", "Lecture seule sur objectifs; pas d’import ni gestion utilisateurs."],
        ["Chef d’agence", "Son agence et les GP rattachés.", "Suivre performance, répartir objectifs, exporter rapports agence.", "Pas d’accès aux autres agences."],
        ["Admin / Responsable régional", "Dashboard global en lecture seule selon paramétrage.", "Analyser metrics et exports autorisés.", "Pas d’importation ni gestion utilisateurs."],
        ["Super Admin / Siège", "Toutes les agences, tous les agents, toutes les données importées.", "Importer MCR, gérer snapshots, objectifs, utilisateurs, exports complets.", "Actions sensibles avec confirmation."],
    ]
    story.append(data_table(["Profil", "Périmètre visible", "Actions principales", "Restrictions"], rows, [3.2, 4.8, 4.8, 3.2]))


def build_annexes(story: list):
    story.append(p("Glossaire des metrics", "H2"))
    story.append(data_table(["Metric", "Définition utilisateur"], METRICS, [4.2, 11.8]))
    story.append(p("Conventions graphiques", "H2"))
    story.append(
        data_table(
            ["Couleur / convention", "Signification"],
            [
                ["Vert", "Succès, validation, indicateur favorable."],
                ["Rouge", "Erreur, alerte, risque ou indicateur défavorable."],
                ["Orange", "Attention, module en développement, point à surveiller."],
                ["Bleu / Turquoise", "Information, navigation, axes de charts et éléments structurants."],
            ],
            [4.5, 11.5],
        )
    )
    return
    story.append(p("Instructions pour insertion des captures", "H2"))
    story.append(
        bullet_list(
            [
                "Format recommandé : PNG pour les captures de dashboard; JPEG uniquement si l’image doit rester légère.",
                "Largeur conseillée : 1200 à 1600 px pour desktop; 768 à 1024 px pour tablette.",
                "Masquer les données sensibles inutiles avant insertion.",
                "Insérer la capture dans le bloc [INSÉRER CAPTURE ICI] puis conserver une légende courte.",
                "Conserver un zoom navigateur de 100% pour éviter les captures déformées.",
            ]
        )
    )


def build_story() -> list:
    story: list = []
    build_cover(story)
    build_toc(story)
    for section in SECTIONS:
        add_section(story, section)
        if section["id"] == "roles":
            build_roles_table(story)
        if section["id"] == "annexes":
            build_annexes(story)
    return story


def build_pdf(path: Path):
    doc = UserGuideDoc(
        str(path),
        pagesize=A4,
        leftMargin=1.75 * cm,
        rightMargin=1.75 * cm,
        topMargin=2.65 * cm,
        bottomMargin=1.55 * cm,
        title=f"Guide utilisateur ",
        author=AUTHOR,
    )
    doc.build(build_story())


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    candidates = [PDF_PATH, PDF_PATH.with_name(f"{PDF_PATH.stem}_logo_reorganise.pdf")]
    candidates.extend(PDF_PATH.with_name(f"{PDF_PATH.stem}_version_{index}.pdf") for index in range(2, 20))
    last_error = None
    for candidate in candidates:
        try:
            build_pdf(candidate)
            print(candidate)
            return
        except PermissionError as exc:
            last_error = exc
    raise last_error


if __name__ == "__main__":
    main()
