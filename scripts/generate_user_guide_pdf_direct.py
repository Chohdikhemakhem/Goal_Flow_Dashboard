from __future__ import annotations

from datetime import date
from pathlib import Path

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
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "generated"
PDF_PATH = OUT_DIR / "guide_utilisateur_metrics_gp_mcr.pdf"

APP_NAME = "Metrics/GP/MCR"
VERSION = "1.0.0"
AUTHOR = "Equipe Projet MicroCred"
TODAY = date.today().strftime("%d/%m/%Y")

BLUE = colors.HexColor("#2E74B5")
DARK_BLUE = colors.HexColor("#1F4D78")
LIGHT_BLUE = colors.HexColor("#E8EEF5")
LIGHT_GRAY = colors.HexColor("#F8FAFC")
MID_GRAY = colors.HexColor("#CBD5E1")
TEXT = colors.HexColor("#18212F")
MUTED = colors.HexColor("#64748B")
ORANGE = colors.HexColor("#FFF7ED")


class NumberedCanvasDoc(BaseDocTemplate):
    def __init__(self, filename: str, **kwargs):
        super().__init__(filename, **kwargs)
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="normal",
        )
        self.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=draw_footer)])


def draw_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(doc.leftMargin, 1.05 * cm, f"{APP_NAME} - Guide de l'utilisateur")
    canvas.drawRightString(A4[0] - doc.rightMargin, 1.05 * cm, f"Page {doc.page}")
    canvas.restoreState()


def make_styles():
    base = getSampleStyleSheet()
    styles = {
        "Title": ParagraphStyle(
            "TitleCustom",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=26,
            leading=31,
            textColor=BLUE,
            alignment=TA_CENTER,
            spaceAfter=14,
        ),
        "Subtitle": ParagraphStyle(
            "SubtitleCustom",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=22,
            textColor=DARK_BLUE,
            alignment=TA_CENTER,
            spaceAfter=24,
        ),
        "H1": ParagraphStyle(
            "H1Custom",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=BLUE,
            spaceBefore=14,
            spaceAfter=8,
        ),
        "H2": ParagraphStyle(
            "H2Custom",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=17,
            textColor=BLUE,
            spaceBefore=10,
            spaceAfter=6,
        ),
        "H3": ParagraphStyle(
            "H3Custom",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11.5,
            leading=15,
            textColor=DARK_BLUE,
            spaceBefore=8,
            spaceAfter=5,
        ),
        "Body": ParagraphStyle(
            "BodyCustom",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.6,
            leading=13.4,
            textColor=TEXT,
            alignment=TA_LEFT,
            spaceAfter=6,
        ),
        "Small": ParagraphStyle(
            "SmallCustom",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.2,
            leading=10.5,
            textColor=MUTED,
            spaceAfter=4,
        ),
        "Caption": ParagraphStyle(
            "CaptionCustom",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=10,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "Box": ParagraphStyle(
            "BoxCustom",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
    }
    return styles


S = make_styles()


def p(text: str, style: str = "Body") -> Paragraph:
    return Paragraph(text, S[style])


def bullet_list(items: list[str]) -> ListFlowable:
    return ListFlowable(
        [ListItem(p(item), leftIndent=12) for item in items],
        bulletType="bullet",
        start="circle",
        leftIndent=18,
        bulletFontName="Helvetica",
        bulletFontSize=7,
    )


def numbered_steps(items: list[str], prefix: str) -> list:
    flowables = []
    for index, item in enumerate(items, 1):
        flowables.append(p(f"<b>Etape {index} :</b> {item}"))
        flowables.extend(screenshot_box(f"Capture {prefix}.{index} - {item[:78]}"))
    return flowables


def screenshot_box(caption: str):
    box = Table(
        [[p("[INSERER CAPTURE ICI]", "Box")]],
        colWidths=[16.2 * cm],
        rowHeights=[3.0 * cm],
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


def note_box(title: str, text: str, fill=LIGHT_GRAY):
    table = Table(
        [[p(f"<b>{title} :</b> {text}")]],
        colWidths=[16.2 * cm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), fill),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#D7DDE8")),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def data_table(headers: list[str], rows: list[list[str]], widths: list[float]):
    table_data = [[p(f"<b>{h}</b>", "Small") for h in headers]]
    for row in rows:
        table_data.append([p(str(cell), "Small") for cell in row])
    table = Table(table_data, colWidths=[w * cm for w in widths], repeatRows=1)
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
    for row_index in range(1, len(table_data)):
        if row_index % 2 == 0:
            table.setStyle(TableStyle([("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#FBFCFE"))]))
    return table


def add_section(story, title: str, description: str, steps: list[str], notes: list[str], roles: str, prefix: str):
    story.append(p(title, "H1"))
    story.append(p("Description generale", "H2"))
    story.append(p(description))
    story.append(p("Etapes detaillees", "H2"))
    story.extend(numbered_steps(steps, prefix))
    story.append(p("Notes et conseils pratiques", "H2"))
    story.append(bullet_list(notes))
    story.append(note_box("Roles et permissions", roles))
    story.append(Spacer(1, 0.25 * cm))


def build_story() -> list:
    story = []
    story.append(Spacer(1, 3.0 * cm))
    story.append(p("Guide de l'utilisateur", "Title"))
    story.append(p(APP_NAME, "Subtitle"))
    story.append(
        data_table(
            ["Champ", "Valeur"],
            [
                ["Version", VERSION],
                ["Auteur / equipe", AUTHOR],
                ["Date", TODAY],
                ["Public cible", "GP, Chefs d'agence, Responsables regionaux, Super Admin siege"],
            ],
            [4.0, 11.8],
        )
    )
    story.append(Spacer(1, 0.8 * cm))
    story.append(note_box("Objectif du document", "Guide de formation pret a completer avec captures d'ecran.", ORANGE))
    story.append(PageBreak())

    story.append(p("Table des matieres", "H1"))
    toc = [
        "1. Introduction",
        "2. Roles et permissions",
        "3. Connexion et changement de mot de passe",
        "4. Dashboard Metrics",
        "5. Filtres, periode, snapshots et etat actuel",
        "6. Metrics journaliers : Metrics GP et Credits existants",
        "7. Exports Excel/PDF",
        "8. Importation MCR",
        "9. Gestion des objectifs",
        "10. Gestion des snapshots et imports",
        "11. Gestion des utilisateurs",
        "12. Module Bonus",
        "13. Workflows complets par profil",
        "14. Annexes",
    ]
    story.append(bullet_list(toc))
    story.append(note_box("Note", "La table des matieres liste les sections principales pour lecture PDF et formation."))
    story.append(PageBreak())

    story.append(p("1. Introduction", "H1"))
    story.append(
        p(
            "Metrics/GP/MCR est une application web de pilotage de performance dediee au suivi des portefeuilles "
            "microfinance, a l'import des fichiers MCR, a l'analyse des indicateurs GP/agence, a la gestion des objectifs "
            "et aux exports operationnels. Elle centralise l'etat actuel, les mois historiques et les snapshots "
            "intermediaires afin de fournir une vue fiable, tracee et exploitable par les profils metiers."
        )
    )
    story.append(
        p(
            "Ce guide explique comment acceder aux fonctionnalites, comment utiliser les filtres et tableaux, comment "
            "importer les donnees, comment gerer les objectifs et comment produire les rapports Excel/PDF."
        )
    )
    story.append(note_box("Portee", "Document oriente utilisateur. Il ne remplace pas la documentation technique d'installation, de securite ou de maintenance."))
    story.extend(screenshot_box("Capture 1.1 - Page de connexion ou ecran d'accueil de l'application"))

    story.append(p("2. Roles et permissions", "H1"))
    story.append(
        p(
            "L'application applique une separation des acces par profil. Chaque utilisateur voit uniquement les modules "
            "et donnees correspondant a son perimetre operationnel."
        )
    )
    story.append(
        data_table(
            ["Profil", "Perimetre visible", "Actions principales", "Restrictions"],
            [
                ["Portfolio Manager / GP", "Ses credits et metrics, y compris credits multi-agences rattaches a lui.", "Consulter dashboard, filtrer, exporter ses listes.", "Lecture seule sur objectifs; pas d'import ni gestion utilisateurs."],
                ["Chef d'agence", "Son agence et les GP rattaches.", "Suivre performance, diviser objectifs, exporter rapports agence.", "Pas d'acces aux autres agences."],
                ["Admin / Responsable regional", "Dashboard global en lecture seule selon parametrage.", "Analyser metrics et exports autorises.", "Pas d'importation ni gestion utilisateurs."],
                ["Super Admin / Siege", "Toutes les agences, tous les agents, toutes les donnees importees.", "Importer MCR, gerer snapshots, objectifs, utilisateurs, exports complets.", "Actions sensibles avec confirmation."],
            ],
            [3.2, 4.8, 4.8, 3.2],
        )
    )

    sections = [
        (
            "3. Connexion et changement de mot de passe",
            "La premiere connexion se fait avec un jeton d'activation fourni par l'administrateur. Ce jeton permet a l'utilisateur de creer son propre mot de passe, puis d'activer son compte. Apres activation, l'utilisateur se connecte normalement avec son email professionnel et le mot de passe qu'il vient de definir.",
            [
                "Ouvrir l'URL de l'application dans le navigateur.",
                "Cliquer sur le lien ou bouton Premiere connexion.",
                "Coller le jeton d'activation delivre par l'administrateur.",
                "Creer un nouveau mot de passe respectant la politique de securite : minimum 12 caracteres, une majuscule, une minuscule, au moins un chiffre et au moins un caractere special.",
                "Confirmer le nouveau mot de passe si le formulaire le demande.",
                "Cliquer sur Activer pour finaliser la creation du compte.",
                "Revenir a l'ecran de connexion, saisir l'email delivre par l'administrateur et le mot de passe cree.",
                "Valider la connexion pour acceder au dashboard correspondant au profil utilisateur.",
            ],
            [
                "Le jeton est personnel et ne doit pas etre partage.",
                "Le mot de passe doit respecter strictement les criteres affiches dans le formulaire.",
                "Apres activation, le jeton ne sert plus a se connecter : l'utilisateur utilise uniquement son email et son mot de passe.",
                "En cas de jeton invalide, expire ou perdu, contacter l'administrateur pour generer un nouveau jeton.",
            ],
            "Tous les profils activent leur compte via Premiere connexion lorsqu'un jeton leur est fourni. La generation et la transmission du jeton sont reservees a l'administrateur autorise.",
            "3",
        ),
        (
            "4. Dashboard Metrics",
            "Le dashboard centralise les indicateurs de performance : Client Actif, Nombre de decaissements, Volume decaisse, Encours, Encours sain, PAR0, PAR30 et cohortes de retard. Il contient aussi les charts Qualite Portefeuille et Volume Decaisse.",
            [
                "Cliquer sur Dashboard dans la barre laterale.",
                "Lire les cartes de metrics en haut de page.",
                "Survoler le chart Qualite Portefeuille pour consulter PAR0%, PAR30%, PAR120% et les cohortes.",
                "Survoler le chart Volume Decaisse pour consulter le volume et le nombre de decaissements.",
                "Utiliser les switchers disponibles selon le role pour basculer entre vue par agence et vue globale.",
            ],
            ["Les valeurs changent selon le role, les filtres, la periode et les snapshots selectionnes.", "Le profil GP ne voit pas les vues globales non autorisees."],
            "GP : perimetre individuel. Chef d'agence : agence et GP rattaches. Admin : dashboard global lecture seule. Super Admin : toutes donnees.",
            "4",
        ),
        (
            "5. Filtres, periode, snapshots et etat actuel",
            "La barre de filtrage combine agence, agent, dates, snapshots et recherche. L'indicateur de periode filtree affiche la plage active et la date de l'etat actuel indique la reference MCR la plus recente.",
            [
                "Selectionner une agence si le profil y est autorise.",
                "Selectionner un agent si necessaire.",
                "Renseigner une date de debut et une date de fin du meme mois.",
                "Selectionner une ou plusieurs snapshots dans le multi-select si une comparaison est souhaitee.",
                "Cliquer sur l'icone de reinitialisation pour vider tous les filtres.",
                "Utiliser le bouton mois courant pour filtrer du premier jour du mois jusqu'au dernier snapshot actif.",
            ],
            ["Si le MCR historique du mois selectionne n'existe pas, un message d'erreur apparait.", "Les snapshots selectionnees s'ajoutent aux charts sans remplacer l'etat actuel."],
            "Les filtres respectent le scope du role connecte. Un GP reste limite a ses propres credits.",
            "5",
        ),
        (
            "6. Metrics journaliers : Metrics GP et Credits existants",
            "La section Metrics journaliers propose un switch entre le tableau Metrics GP et le tableau Credits existants MCR actuel. Les tableaux supportent recherche globale, tri, pagination et adaptation des colonnes selon le role.",
            [
                "Descendre jusqu'a Metrics journaliers.",
                "Choisir Metrics GP ou Credits existants avec le switch.",
                "Utiliser la recherche pour filtrer toutes les donnees disponibles.",
                "Cliquer sur les en-tetes numeriques ou date pour trier en ASC/DESC.",
                "Choisir le nombre de lignes par page dans la barre de pagination.",
            ],
            ["La colonne CLIENT_NCNI est visible uniquement pour le Super Admin.", "La colonne ENCOURS du tableau Credits existants suit la formule metier configuree."],
            "Tous les profils peuvent consulter les tableaux dans leur perimetre. Les colonnes visibles varient selon le role.",
            "6",
        ),
        (
            "7. Exports Excel/PDF",
            "Les exports produisent des fichiers professionnels a partir des donnees visibles ou du perimetre utilisateur. Les rapports GP et Chef d'agence proposent les listes impayees, renouvellement et echeances futures.",
            [
                "Depuis le dashboard, reperer la zone de telechargement des rapports.",
                "Choisir le type de rapport dans la liste deroulante.",
                "Pour les echeances futures, saisir une periode en jours entre 1 et 10.",
                "Cliquer sur Excel ou PDF.",
                "Ouvrir le fichier telecharge et verifier le perimetre, les colonnes et les totaux.",
            ],
            ["Les rapports Admin et Super Admin sont organises par agence.", "Les rapports Chef d'agence regroupent les GP de son agence.", "Les exports respectent les filtres applicables."],
            "GP et Chef d'agence disposent d'exports operationnels. Admin et Super Admin disposent d'exports consolides selon leurs droits.",
            "7",
        ),
        (
            "8. Importation MCR",
            "Le module Importation est reserve au Super Admin. Il permet d'importer l'etat actuel quotidien et les mois historiques finalises. Chaque import est rattache a un batch afin de tracer son origine.",
            [
                "Cliquer sur Importation dans la sidebar.",
                "Dans Importer l'etat actuel, choisir le fichier MCR quotidien.",
                "Cliquer sur Importer l'etat actuel et attendre la confirmation.",
                "Pour un mois passe, selectionner le fichier final et renseigner le mois concerne.",
                "Cliquer sur Importer le mois passe ou remplacer si le mois existe deja.",
            ],
            ["Lorsqu'un nouvel etat actuel est importe, l'ancien etat peut devenir snapshot.", "Lorsqu'un mois historique final est importe, les snapshots du meme mois sont supprimees automatiquement.", "Ne pas fermer la page pendant un import volumineux."],
            "Module reserve au Super Admin. Admin, Chef d'agence et GP n'ont pas acces a l'importation.",
            "8",
        ),
        (
            "9. Gestion des objectifs",
            "La section Objectifs permet de definir et suivre les objectifs mensuels ou annuels. Les objectifs PAR sont des objectifs de limitation du risque : une valeur realisee plus basse est meilleure.",
            [
                "Cliquer sur Objectifs si le role y a acces.",
                "Selectionner la periode de l'objectif : mois et annee.",
                "Pour le Super Admin, creer ou modifier les objectifs d'agence.",
                "Pour le Chef d'agence, selectionner un GP de son agence et repartir l'objectif.",
                "Enregistrer puis verifier l'apparition de l'objectif dans le tableau.",
            ],
            ["Les indicateurs classiques utilisent realise / objectif.", "Les indicateurs PAR utilisent objectif / realise lorsque la valeur faible est meilleure.", "Le GP consulte ses objectifs en lecture seule."],
            "Super Admin : objectifs agence. Chef d'agence : objectifs GP de son agence. GP : lecture seule.",
            "9",
        ),
        (
            "10. Gestion des snapshots et imports",
            "Les snapshots representent des etats MCR intermediaires dates. Ils peuvent etre ajoutes aux charts pour comparaison et, si importes par erreur, supprimes par un profil autorise.",
            [
                "Ouvrir le module Importation.",
                "Consulter la table Imports et snapshots.",
                "Identifier le batch par type, date snapshot, periode et nom de fichier.",
                "Pour supprimer une snapshot ou un mois passe errone, cliquer sur Supprimer.",
                "Confirmer l'action puis retourner au dashboard pour verifier que les donnees ont disparu.",
            ],
            ["La suppression d'un import est definitive.", "Ne supprimer qu'une snapshot clairement identifiee comme erronee."],
            "Suppression reservee au Super Admin. Les autres profils selectionnent seulement les snapshots disponibles dans leur perimetre.",
            "10",
        ),
        (
            "11. Gestion des utilisateurs",
            "Le module Utilisateurs permet au Super Admin de creer, modifier, activer, desactiver et reinitialiser les comptes.",
            [
                "Cliquer sur Utilisateurs dans la sidebar.",
                "Rechercher un utilisateur par email, nom ou role.",
                "Creer un nouvel utilisateur avec email, nom complet, role et rattachement agence/agent si necessaire.",
                "Modifier le role ou le rattachement si besoin.",
                "Activer, desactiver ou reinitialiser l'acces selon le besoin operationnel.",
            ],
            ["Un GP doit etre rattache a un agent.", "Un Chef d'agence doit etre rattache a une agence.", "Les comptes Admin/Super Admin ne sont pas rattaches a un agent."],
            "Module reserve au Super Admin.",
            "11",
        ),
        (
            "12. Module Bonus",
            "Le module Bonus est actuellement visible mais inactif dans l'environnement de test. Il reste identifiable dans la navigation afin d'anticiper son activation future sans declencher de calculs.",
            [
                "Cliquer sur Bonus dans la sidebar.",
                "Lire le message Module en developpement.",
                "Fermer ou changer de module pour revenir au dashboard.",
            ],
            ["Aucun calcul Bonus n'est execute lorsque le module est inactif.", "La carte Prime peut rester visible mais inactive pour les GP selon configuration."],
            "Visible selon profil, mais actions desactivees tant que BONUS_MODULE_ACTIVE est false.",
            "12",
        ),
    ]
    for section in sections:
        add_section(story, *section)

    story.append(p("13. Workflows complets par profil", "H1"))
    workflows = {
        "Portfolio Manager / GP": [
            "Activer son compte via Premiere connexion avec le jeton fourni par l'administrateur.",
            "Se connecter avec l'email fourni et le mot de passe cree.",
            "Lire ses cartes de performance.",
            "Filtrer par periode du mois courant.",
            "Basculer vers Credits existants pour rechercher un client.",
            "Exporter une liste d'impayees ou d'echeances futures.",
        ],
        "Chef d'agence": [
            "Se connecter au dashboard agence.",
            "Filtrer ou rechercher les GP rattaches.",
            "Analyser les cohortes et le volume par agent.",
            "Repartir les objectifs entre GP.",
            "Exporter les rapports par GP de l'agence.",
        ],
        "Admin / Responsable regional": [
            "Se connecter en lecture seule.",
            "Consulter les metrics consolidees.",
            "Comparer agences, periodes et snapshots disponibles.",
            "Exporter les rapports autorises pour analyse regionale.",
        ],
        "Super Admin / Siege": [
            "Importer l'etat actuel ou un mois passe.",
            "Verifier la date de l'etat actuel et les snapshots.",
            "Gerer utilisateurs et objectifs agence.",
            "Supprimer un import errone si necessaire.",
            "Exporter les rapports consolides toutes agences.",
        ],
    }
    for role, steps in workflows.items():
        story.append(p(role, "H2"))
        story.extend(numbered_steps(steps, role.split()[0]))

    story.append(p("14. Annexes", "H1"))
    story.append(p("Annexe A - Glossaire des metrics", "H2"))
    metrics = [
        ["Client Actif", "Nombre de clients actifs dans le perimetre et la periode selectionnes."],
        ["Nombre de decaissements", "Nombre de contrats dont la date de decaissement appartient a la periode filtree."],
        ["Volume decaisse", "Somme des montants decaisses dans la periode selectionnee."],
        ["Encours", "Exposition calculee sur les credits actifs selon la formule metier courante."],
        ["Encours sain", "Part de l'encours consideree comme saine selon les regles metier."],
        ["PAR0", "Encours des credits avec retard strictement superieur a 0 jour selon la regle appliquee."],
        ["PAR30", "Encours des credits avec retard superieur a 30 jours; le pourcentage est rapporte a l'encours."],
        ["Cohorte 1-30", "Encours des credits avec retard de 1 a 30 jours."],
        ["Cohorte 31-60", "Encours des credits avec retard de 31 a 60 jours."],
        ["Cohorte 61-90", "Encours des credits avec retard de 61 a 90 jours."],
        ["Cohorte 91-120", "Encours des credits avec retard de 91 a 120 jours."],
        ["PAR120", "Encours des credits avec retard superieur a 120 jours et inferieur a 365 jours."],
    ]
    story.append(data_table(["Metric", "Definition utilisateur"], metrics, [4.2, 11.8]))

    story.append(p("Annexe B - Conventions graphiques", "H2"))
    story.append(
        data_table(
            ["Couleur / convention", "Signification"],
            [
                ["Vert", "Succes, validation, indicateur favorable."],
                ["Rouge", "Erreur, alerte, risque ou indicateur defavorable."],
                ["Orange", "Attention, module en developpement, point a surveiller."],
                ["Bleu", "Information, navigation, axes de charts et elements structurants."],
            ],
            [4.5, 11.5],
        )
    )
    story.append(p("Annexe C - Instructions pour insertion des captures", "H2"))
    story.append(
        bullet_list(
            [
                "Format recommande : PNG pour les captures de dashboard; JPEG uniquement si l'image doit rester legere.",
                "Largeur conseillee : 1200 a 1600 px pour desktop; 768 a 1024 px pour tablette.",
                "Masquer les donnees sensibles inutiles avant insertion.",
                "Inserer la capture dans le bloc [INSERER CAPTURE ICI] puis conserver une legende courte.",
                "Conserver un zoom navigateur de 100% pour eviter les captures deformees.",
            ]
        )
    )
    return story


def build_pdf(path: Path) -> None:
    doc = NumberedCanvasDoc(
        str(path),
        pagesize=A4,
        leftMargin=1.7 * cm,
        rightMargin=1.7 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.8 * cm,
        title=f"Guide utilisateur {APP_NAME}",
        author=AUTHOR,
    )
    doc.build(build_story())


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        build_pdf(PDF_PATH)
        output_path = PDF_PATH
    except PermissionError:
        output_path = PDF_PATH.with_name(f"{PDF_PATH.stem}_corrige.pdf")
        build_pdf(output_path)
        print(f"Fichier principal verrouille, version corrigee generee: {output_path}")
        return
    print(PDF_PATH)


if __name__ == "__main__":
    main()
