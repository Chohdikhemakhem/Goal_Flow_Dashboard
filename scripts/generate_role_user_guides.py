from __future__ import annotations

import re
import urllib.request
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

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
    KeepTogether,
    ListFlowable,
    ListItem,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image as FlowableImage,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "generated" / "role_guides"
ASSET_DIR = ROOT / "docs" / "generated" / "user_guide_assets"
CAPTURE_DIR = ROOT / "docs" / "generated" / "captures"
TEMPLATE_PATH = Path(r"C:\Users\chohd\Downloads\template.docx")
COVER_IMAGE_URL = "https://images.unsplash.com/photo-1554224155-6726b3ff858f?auto=format&fit=crop&w=1600&q=80"

APP_NAME = "Performance Command Center"
APP_SUBTITLE = "Metrics/GP/MCR"
VERSION = "1.0.0"
AUTHOR = "Equipe Projet MicroCred"
TODAY = date.today().strftime("%d/%m/%Y")
ACTIVE_CAPTURE_PREFIX: str | None = None

BLUE = colors.HexColor("#0B7F8C")
DARK_BLUE = colors.HexColor("#11566A")
GREEN = colors.HexColor("#36A852")
LIGHT_BLUE = colors.HexColor("#E8F3F5")
MID_GRAY = colors.HexColor("#CBD5E1")
TEXT = colors.HexColor("#18212F")
MUTED = colors.HexColor("#64748B")
WHITE = colors.white


COMMON_LOGIN = {
    "id": "premiere_connexion",
    "title": "1. Première connexion et changement obligatoire du mot de passe",
    "description": (
        "La première connexion se fait avec l’email professionnel et le mot de passe temporaire transmis par le Super Admin. "
        "Après authentification, l’application affiche automatiquement une fenêtre de modification obligatoire du mot de passe. "
        "L’accès au dashboard et aux autres modules reste bloqué tant que le nouveau mot de passe n’a pas été enregistré."
    ),
    "steps": [
        "Ouvrir l’URL de l’application dans le navigateur.",
        "Saisir l’email professionnel transmis par l’administrateur.",
        "Saisir le mot de passe temporaire communiqué par le Super Admin.",
        "Cliquer sur Connexion.",
        "Dans la fenêtre Modification obligatoire du mot de passe, saisir le mot de passe actuel.",
        "Créer un nouveau mot de passe avec minimum 12 caractères, une majuscule, une minuscule, un chiffre et un caractère spécial.",
        "Confirmer le nouveau mot de passe puis valider.",
        "Accéder ensuite au dashboard avec le nouveau mot de passe personnel.",
    ],
}


PROFILE_GUIDES = {
    "super_admin": {
        "file": "guide_utilisateur_super_admin.pdf",
        "role_title": "Guide utilisateur - Super Admin",
        "role_label": "Super Admin / Siège",
        "cover_note": "Administration complète, import MCR, objectifs, utilisateurs, snapshots et exports consolidés.",
        "sections": [
            COMMON_LOGIN,
            {
                "id": "dashboard_global",
                "title": "2. Dashboard global des metrics",
                "description": (
                    "Le Super Admin dispose d’une vue globale sur toutes les agences, tous les GP et toutes les périodes importées. "
                    "Le dashboard affiche les cartes principales, les charts Qualité Portefeuille et Volume Décaissé, les filtres avancés et les snapshots sélectionnables."
                ),
                "steps": [
                    "Cliquer sur Dashboard dans la barre latérale.",
                    "Consulter les cartes : Client Actif, Nombre de décaissements, Volume décaissé, Encours, Encours sain, PAR et cohortes.",
                    "Basculer les charts entre vue par agence et vue globale lorsque le switcher est disponible.",
                    "Survoler les charts pour lire les tooltips détaillés.",
                    "Utiliser les filtres agence, agent, dates et snapshots pour analyser une période précise.",
                ],
            },
            {
                "id": "import_mcr",
                "title": "3. Importation MCR",
                "description": (
                    "Le Super Admin est le seul profil autorisé à importer l’état actuel quotidien et les fichiers historiques mensuels. "
                    "Chaque import crée ou remplace un batch identifié : CURRENT_STATE, HISTORICAL_MONTH ou SNAPSHOT."
                ),
                "steps": [
                    "Cliquer sur Importation.",
                    "Dans Importer l’état actuel, sélectionner le fichier MCR du jour.",
                    "Cliquer sur Importer l’état actuel et attendre la confirmation.",
                    "Dans Importer un mois passé, sélectionner le fichier final du mois et renseigner la période.",
                    "Importer ou remplacer le mois passé selon le cas.",
                    "Vérifier les résultats dans la table Imports et snapshots.",
                ],
            },
            {
                "id": "snapshots",
                "title": "4. Gestion des snapshots et imports",
                "description": (
                    "La table Imports et snapshots permet de contrôler les états MCR disponibles, les snapshots intermédiaires et les mois historiques. "
                    "Le Super Admin peut supprimer un import erroné après confirmation."
                ),
                "steps": [
                    "Ouvrir Importation puis la section Imports et snapshots.",
                    "Identifier le batch par type, période, date snapshot et nom de fichier.",
                    "Cliquer sur Supprimer pour une snapshot ou un mois passé erroné.",
                    "Confirmer la suppression.",
                    "Retourner au dashboard pour vérifier que les données supprimées ne sont plus affichées.",
                ],
            },
            {
                "id": "objectifs",
                "title": "5. Gestion des objectifs",
                "description": (
                    "Le Super Admin crée et modifie les objectifs d’agence. Les Chefs d’agence peuvent ensuite répartir les objectifs autorisés entre leurs GP."
                ),
                "steps": [
                    "Cliquer sur Objectifs.",
                    "Choisir le mois et l’année de l’objectif.",
                    "Sélectionner l’agence concernée.",
                    "Renseigner les objectifs : Client Actif, Nombre de décaissements, Volume, Encours, Encours sain, PAR et cohortes selon les champs disponibles.",
                    "Définir la période active si le champ est disponible.",
                    "Enregistrer et vérifier l’objectif dans le tableau.",
                ],
            },
            {
                "id": "utilisateurs",
                "title": "6. Gestion des utilisateurs et rôles",
                "description": (
                    "Le module Utilisateurs permet de créer, modifier, activer, désactiver et réinitialiser les comptes. "
                    "Les GP peuvent être créés automatiquement avec un mot de passe temporaire généré. Les Admins et Chefs d’agence "
                    "sont créés manuellement avec un mot de passe initial. Dans tous les cas, l’utilisateur doit changer ce mot de passe à la première connexion."
                ),
                "steps": [
                    "Cliquer sur Utilisateurs.",
                    "Rechercher un utilisateur par email, nom ou rôle.",
                    "Pour un GP, sélectionner le rôle Portfolio Manager, l’agence et l’agent, puis créer le compte : le mot de passe temporaire est généré automatiquement.",
                    "Pour un Admin ou un Chef d’agence, saisir l’email, le nom complet, le rôle, le rattachement nécessaire et le mot de passe initial.",
                    "Communiquer à l’utilisateur son email et le mot de passe temporaire affiché par l’application.",
                    "Modifier un rôle ou un rattachement existant.",
                    "Utiliser Reset MDP pour attribuer un nouveau mot de passe temporaire à un compte existant.",
                    "Activer ou désactiver un compte selon le besoin.",
                ],
            },
            {
                "id": "exports",
                "title": "7. Exports Excel/PDF consolidés",
                "description": (
                    "Les exports Super Admin regroupent toutes les agences avec une ligne globale par agence puis le détail des GP rattachés."
                ),
                "steps": [
                    "Depuis le dashboard, repérer les boutons d’export.",
                    "Choisir le format Excel ou PDF.",
                    "Générer le rapport consolidé.",
                    "Vérifier que chaque agence contient sa synthèse et les lignes GP.",
                    "Partager le rapport selon les règles internes de confidentialité.",
                ],
            },
            {
                "id": "securite",
                "title": "8. Sécurité et configuration applicative",
                "description": (
                    "Le Super Admin applique les règles d’accès, surveille l’état des comptes et vérifie que les modules sensibles restent contrôlés."
                ),
                "steps": [
                    "Vérifier régulièrement les comptes actifs et désactivés.",
                    "Contrôler les rôles affectés aux utilisateurs.",
                    "Désactiver les comptes de test ou les comptes obsolètes.",
                    "Vérifier que le module Bonus reste inactif tant que son développement n’est pas finalisé.",
                    "Limiter le partage des exports contenant des données sensibles.",
                ],
            },
        ],
    },
    "admin": {
        "file": "guide_utilisateur_admin.pdf",
        "role_title": "Guide utilisateur - Admin",
        "role_label": "Admin / Responsable régional",
        "cover_note": "Lecture globale du dashboard, analyse consolidée et exports autorisés.",
        "sections": [
            COMMON_LOGIN,
            {
                "id": "dashboard_admin",
                "title": "2. Dashboard global en lecture seule",
                "description": (
                    "Le profil Admin consulte les metrics globales pour analyser la performance sans modifier les données, les imports, les objectifs ou les utilisateurs."
                ),
                "steps": [
                    "Cliquer sur Dashboard.",
                    "Consulter les cartes de metrics consolidées.",
                    "Analyser les charts Qualité Portefeuille et Volume Décaissé.",
                    "Utiliser les filtres disponibles pour comparer agences, agents ou périodes autorisées.",
                    "Survoler les graphiques pour lire les détails des PAR, cohortes, volume et nombre de décaissements.",
                ],
            },
            {
                "id": "snapshots_admin",
                "title": "3. Consultation des snapshots et importations disponibles",
                "description": (
                    "L’Admin peut exploiter en lecture seule les snapshots et les importations disponibles dans son dashboard "
                    "pour comparer les états importés. Il ne crée pas, ne remplace pas et ne supprime pas les imports."
                ),
                "steps": [
                    "Ouvrir le dashboard.",
                    "Utiliser le sélecteur Snapshots à comparer si des snapshots sont disponibles.",
                    "Sélectionner une ou plusieurs snapshots.",
                    "Vérifier que les charts se mettent à jour avec les points sélectionnés.",
                    "Réinitialiser les filtres si nécessaire.",
                ],
            },
            {
                "id": "exports_admin",
                "title": "4. Exports Excel/PDF globaux",
                "description": (
                    "Les exports Admin sont destinés à l’analyse régionale ou globale en lecture seule. Ils ne modifient aucune donnée."
                ),
                "steps": [
                    "Depuis le dashboard, repérer les boutons d’export.",
                    "Choisir Excel ou PDF selon le besoin.",
                    "Télécharger le rapport global.",
                    "Vérifier que les agences et GP autorisés sont présents.",
                    "Partager le fichier uniquement avec les destinataires autorisés.",
                ],
            },
        ],
    },
    "gp": {
        "file": "guide_utilisateur_gp.pdf",
        "role_title": "Guide utilisateur - Portfolio Manager (GP)",
        "cover_title": "Guide utilisateur<br/>Portfolio Manager (GP)",
        "show_cover_version": False,
        "capture_prefix": "Capture GP",
        "role_label": "Portfolio Manager / GP",
        "cover_note": "Suivi individuel des metrics, crédits existants, cohortes, PAR<br/>et exports opérationnels.",
        "sections": [
            COMMON_LOGIN,
            {
                "id": "dashboard_gp",
                "title": "2. Dashboard Metrics GP",
                "description": (
                    "Le GP consulte ses propres metrics : clients actifs, nombre de décaissements, volume décaissé, encours, encours sain, PAR et cohortes."
                ),
                "steps": [
                    "Cliquer sur Dashboard.",
                    "Lire les cartes de performance individuelles.",
                    "Consulter les charts Qualité Portefeuille et Volume Décaissé.",
                    "Survoler les charts pour afficher les valeurs détaillées.",
                    "Vérifier les objectifs ou indications visibles si le compte dispose d’objectifs définis.",
                ],
            },
            {
                "id": "filtres_gp",
                "title": "3. Filtres et période",
                "description": (
                    "Le GP peut filtrer ses propres données par période et exploiter les snapshots disponibles dans son périmètre."
                ),
                "steps": [
                    "Sélectionner une date de début et une date de fin appartenant au même mois.",
                    "Utiliser le bouton mois courant si disponible.",
                    "Sélectionner une snapshot à comparer si elle est disponible.",
                    "Vérifier que les cartes, charts et tableaux se mettent à jour.",
                    "Réinitialiser les filtres pour revenir à la vue par défaut.",
                ],
            },
            {
                "id": "tableaux_gp",
                "title": "4. Metrics journaliers et Crédits existants",
                "description": (
                    "Le GP peut basculer entre le tableau Metrics GP et le tableau Crédits existants afin de rechercher un client ou un contrat."
                ),
                "steps": [
                    "Descendre à la section Metrics journaliers.",
                    "Choisir Metrics GP ou Crédits existants.",
                    "Utiliser la barre de recherche sur l’ensemble des données.",
                    "Trier les colonnes numériques ou dates si nécessaire.",
                    "Changer le nombre de lignes par page.",
                ],
            },
            {
                "id": "exports_gp",
                "title": "5. Exports GP",
                "description": (
                    "Le GP dispose d’exports opérationnels liés à ses propres crédits : impayés, possibilités de renouvellement et échéances futures."
                ),
                "steps": [
                    "Choisir le type de rapport dans la liste déroulante.",
                    "Pour les échéances futures, saisir une période de 1 à 10 jours.",
                    "Cliquer sur Excel ou PDF.",
                    "Ouvrir le fichier téléchargé.",
                    "Vérifier que seules les données du GP sont présentes.",
                ],
            },
            {
                "id": "cohortes_gp",
                "title": "6. Lecture des cohortes et PAR",
                "description": (
                    "Les cohortes et PAR permettent au GP de suivre la qualité de son portefeuille et les retards par tranche."
                ),
                "steps": [
                    "Repérer les cartes PAR0, PAR30, Cohorte 1-30, Cohorte 31-60, Cohorte 61-90, Cohorte 91-120 et PAR120 si elles sont affichées.",
                    "Lire les volumes et pourcentages associés.",
                    "Survoler le chart Qualité Portefeuille pour comparer les composantes de risque.",
                    "Utiliser les filtres de période pour analyser un mois précis.",
                ],
            },
        ],
    },
    "chef_agence": {
        "file": "guide_utilisateur_chef_agence.pdf",
        "role_title": "Guide utilisateur - Chef d’agence",
        "role_label": "Chef d’agence",
        "cover_note": "Pilotage de l’agence, suivi des GP rattachés, objectifs et exports par GP.",
        "sections": [
            COMMON_LOGIN,
            {
                "id": "dashboard_agence",
                "title": "2. Dashboard de l’agence",
                "description": (
                    "Le Chef d’agence consulte les metrics consolidées de son agence et les performances des GP rattachés."
                ),
                "steps": [
                    "Cliquer sur Dashboard.",
                    "Lire les cartes de metrics de l’agence.",
                    "Consulter les charts Qualité Portefeuille et Volume Décaissé.",
                    "Filtrer par GP si nécessaire.",
                    "Survoler les charts pour consulter les détails.",
                ],
            },
            {
                "id": "gp_agence",
                "title": "3. Visualisation des metrics des GP",
                "description": (
                    "Le tableau Metrics journaliers permet au Chef d’agence de suivre les GP de son agence, leurs clients, encours, volumes et indicateurs de risque."
                ),
                "steps": [
                    "Aller à la section Metrics journaliers.",
                    "Consulter les lignes GP disponibles.",
                    "Utiliser la recherche pour retrouver un GP ou un client.",
                    "Trier les colonnes nécessaires.",
                    "Adapter la pagination selon le volume de données.",
                ],
            },
            {
                "id": "objectifs_agence",
                "title": "4. Répartition des objectifs GP",
                "description": (
                    "Lorsque le Super Admin affecte un objectif à l’agence, le Chef d’agence peut répartir cet objectif entre les GP rattachés."
                ),
                "steps": [
                    "Cliquer sur Objectifs.",
                    "Vérifier la période active et l’objectif agence.",
                    "Sélectionner le GP concerné.",
                    "Renseigner les valeurs d’objectif du GP.",
                    "Enregistrer puis vérifier le tableau des objectifs.",
                ],
            },
            {
                "id": "exports_chef",
                "title": "5. Exports Excel/PDF par GP",
                "description": (
                    "Le Chef d’agence peut générer des rapports opérationnels pour les GP de son agence, avec des tableaux séparés par GP selon le type de rapport."
                ),
                "steps": [
                    "Choisir le type de rapport dans la zone export.",
                    "Sélectionner la période nécessaire si le rapport le demande.",
                    "Cliquer sur Excel ou PDF.",
                    "Ouvrir le fichier téléchargé.",
                    "Vérifier que les GP de l’agence sont bien présents et séparés par tableau.",
                ],
            },
            {
                "id": "snapshots_chef",
                "title": "6. Snapshots et périodes de comparaison",
                "description": (
                    "Le Chef d’agence peut utiliser les snapshots disponibles pour comparer l’état de son agence sur différentes dates."
                ),
                "steps": [
                    "Ouvrir le dashboard.",
                    "Sélectionner une ou plusieurs snapshots à comparer.",
                    "Appliquer les filtres GP ou période si nécessaire.",
                    "Vérifier les charts et tableaux mis à jour.",
                    "Réinitialiser les filtres après analyse.",
                ],
            },
        ],
    },
}


PROFILE_GUIDES["gp"]["sections"][5] = {
    "id": "glossaire_metrics_gp",
    "title": "6. Glossaire des metrics et conventions graphiques",
    "description": (
        "Cette section regroupe les definitions des principaux metrics visibles dans le dashboard GP "
        "ainsi que les conventions graphiques utilisees dans les cartes, chartes et tableaux."
    ),
    "tables": [
        {
            "title": "Glossaire des metrics",
            "columns": ["Metric", "Definition", "Interpretation"],
            "rows": [
                ["Client Actif", "Nombre de clients ayant un credit en cours dans le perimetre du GP.", "Mesure la taille du portefeuille actif suivi par le GP."],
                ["Nombre de decaissements", "Nombre de contrats dont la date de decaissement appartient a la periode filtree.", "Indique l'activite commerciale realisee sur la periode."],
                ["Volume decaisse", "Somme des montants decaisses sur la periode selectionnee.", "Permet d'evaluer le volume financier produit par le GP."],
                ["Encours", "Exposition totale du portefeuille, calculee a partir du principal restant et du principal en retard.", "Mesure le stock de portefeuille actuellement porte par le GP."],
                ["Encours sain", "Partie de l'encours sans retard de paiement.", "Indique la part du portefeuille consideree comme saine."],
                ["PAR0", "Volume de portefeuille avec au moins un jour de retard.", "Signale le risque des le premier jour de retard."],
                ["PAR30", "Volume de portefeuille dont le retard est strictement superieur a 30 jours.", "Repere le risque consolide au-dela de 30 jours."],
                ["Cohorte 1-30", "Encours des credits avec un retard compris entre 1 et 30 jours.", "Met en evidence les retards recents a suivre rapidement."],
                ["Cohorte 31-60", "Encours des credits avec un retard compris entre 31 et 60 jours.", "Montre les retards installes necessitant un suivi renforce."],
                ["Cohorte 61-90", "Encours des credits avec un retard compris entre 61 et 90 jours.", "Identifie les dossiers a risque eleve."],
                ["Cohorte 91-120", "Encours des credits avec un retard compris entre 91 et 120 jours.", "Indique une degradation avancee du portefeuille."],
                ["PAR120", "Encours des credits avec un retard superieur a 120 jours et inferieur a 365 jours.", "Isole les dossiers tres critiques avant sortie du perimetre suivi."],
            ],
        },
        {
            "title": "Conventions graphiques",
            "columns": ["Element graphique", "Signification", "Utilisation dans le dashboard"],
            "rows": [
                ["Cartes de metrics", "Blocs synthetiques affichant une valeur principale et parfois un pourcentage secondaire.", "Lire rapidement l'etat global du portefeuille GP."],
                ["Couleurs PAR et cohortes", "Couleurs distinctes pour chaque tranche de retard.", "Comparer visuellement les niveaux de risque."],
                ["Barres empilees", "Segments empiles par tranche de retard, de la cohorte la plus courte vers la plus longue.", "Comprendre la composition du risque dans la qualite portefeuille."],
                ["Tooltips", "Cartes d'information affichees au survol ou au tap.", "Consulter les valeurs detaillees d'une barre ou d'un point de chart."],
                ["Filtres", "Champs periode et snapshots qui modifient les donnees affichees.", "Recalculer cartes, chartes et tableaux selon le contexte choisi."],
                ["Messages d'erreur", "Messages rouges signalant une periode invalide ou une absence de donnees.", "Corriger rapidement l'action ou le filtre applique."],
                ["Messages de confirmation", "Messages positifs indiquant qu'une action a reussi.", "Confirmer l'application d'un filtre ou la reussite d'une operation."],
            ],
        },
    ],
}


class BookmarkParagraph(Paragraph):
    def __init__(self, text, style, bookmark, outline_level=0):
        super().__init__(text, style)
        self.bookmark = bookmark
        self.outline_level = outline_level

    def draw(self):
        self.canv.bookmarkPage(self.bookmark)
        self.canv.addOutlineEntry(self.getPlainText(), self.bookmark, self.outline_level, closed=False)
        super().draw()


class CatalogParagraph(Paragraph):
    def __init__(self, text, style, bookmark, catalog_type, catalog_number, catalog_title):
        super().__init__(text, style)
        self.bookmark = bookmark
        self.catalog_type = catalog_type
        self.catalog_number = catalog_number
        self.catalog_title = catalog_title

    def draw(self):
        self.canv.bookmarkPage(self.bookmark)
        super().draw()


class RoleGuideDoc(BaseDocTemplate):
    def __init__(self, filename: str, **kwargs):
        super().__init__(filename, **kwargs)
        self.catalog_entries = {"figure": [], "table": []}
        self._catalog_seen = set()
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="normal")
        cover_frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="cover")
        self.addPageTemplates(
            [
                PageTemplate(id="cover", frames=[cover_frame], onPage=draw_cover),
                PageTemplate(id="main", frames=[frame], onPage=draw_page),
            ]
        )

    def afterFlowable(self, flowable):
        if not hasattr(flowable, "catalog_type"):
            return
        key = (flowable.catalog_type, flowable.bookmark)
        if key in self._catalog_seen:
            return
        self._catalog_seen.add(key)
        self.catalog_entries[flowable.catalog_type].append(
            {
                "number": flowable.catalog_number,
                "title": flowable.catalog_title,
                "page": self.page,
                "bookmark": flowable.bookmark,
            }
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
            path = ASSET_DIR / f"role_guide_template_asset_{len(images) + 1}{suffix}"
            path.write_bytes(rel.target_part.blob)
            images.append(path)
    if len(images) < 2:
        raise RuntimeError("La template doit contenir au moins deux images: header et footer.")
    header_path, footer_path = images[0], images[1]
    logo_path = ASSET_DIR / "role_guide_microcred_logo.png"
    header = Image.open(header_path).convert("RGBA")
    logo = header.crop((0, 0, min(330, header.width), header.height))
    logo.save(logo_path)
    return header_path, footer_path, logo_path


def download_cover_image() -> Path:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = ASSET_DIR / "role_cover_raw.jpg"
    final_path = ASSET_DIR / "role_cover_background.jpg"
    if not final_path.exists():
        with urllib.request.urlopen(COVER_IMAGE_URL, timeout=30) as response:
            raw_path.write_bytes(response.read())
        image = Image.open(raw_path).convert("RGB")
        image = ImageOps.fit(image, (1600, 2263), method=Image.Resampling.LANCZOS)
        image = ImageEnhance.Brightness(image).enhance(0.62)
        image.save(final_path, quality=92)
    return final_path


HEADER_IMG, FOOTER_IMG, LOGO_IMG = extract_template_assets()
COVER_IMG = download_cover_image()


def make_styles():
    base = getSampleStyleSheet()
    return {
        "CoverTitle": ParagraphStyle("CoverTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=27, leading=33, textColor=WHITE, alignment=TA_LEFT, spaceAfter=10),
        "CoverSub": ParagraphStyle("CoverSub", parent=base["BodyText"], fontName="Helvetica", fontSize=13, leading=18, textColor=colors.HexColor("#EAF7FA"), alignment=TA_LEFT, spaceAfter=7),
        "H1": ParagraphStyle("H1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=15.5, leading=20, textColor=DARK_BLUE, spaceBefore=13, spaceAfter=8),
        "H2": ParagraphStyle("H2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=BLUE, spaceBefore=9, spaceAfter=5),
        "Body": ParagraphStyle("Body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13.2, textColor=TEXT, alignment=TA_LEFT, spaceAfter=6),
        "Small": ParagraphStyle("Small", parent=base["BodyText"], fontName="Helvetica", fontSize=8.0, leading=10.2, textColor=MUTED, spaceAfter=4),
        "Caption": ParagraphStyle("Caption", parent=base["BodyText"], fontName="Helvetica-Oblique", fontSize=8, leading=10, textColor=MUTED, alignment=TA_CENTER, spaceAfter=8),
        "Box": ParagraphStyle("Box", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=MUTED, alignment=TA_CENTER),
        "TOC": ParagraphStyle("TOC", parent=base["BodyText"], fontName="Helvetica", fontSize=10.3, leading=15, textColor=DARK_BLUE, spaceAfter=5, leftIndent=12),
    }


S = make_styles()


def p(text: str, style: str = "Body") -> Paragraph:
    return Paragraph(text, S[style])


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
    canvas.setFillColor(colors.Color(1, 1, 1, alpha=0.96))
    canvas.roundRect(1.82 * cm, 21.08 * cm, 6.35 * cm, 2.62 * cm, 12, stroke=0, fill=1)
    canvas.drawImage(str(LOGO_IMG), 2.22 * cm, 21.43 * cm, width=5.55 * cm, height=1.92 * cm, preserveAspectRatio=True, mask="auto")
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


def screenshot_box(caption: str) -> list:
    box = Table([[p("[INSÉRER CAPTURE ICI]", "Box")]], colWidths=[16.1 * cm], rowHeights=[2.75 * cm])
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


def capture_path_for_caption(caption: str) -> Path | None:
    if not ACTIVE_CAPTURE_PREFIX:
        return None
    match = re.search(r"Capture\s+(\d+\.\d+)", caption)
    if not match:
        return None
    base_name = f"{ACTIVE_CAPTURE_PREFIX} {match.group(1)}"
    for extension in (".png", ".jpg", ".jpeg"):
        candidate = CAPTURE_DIR / f"{base_name}{extension}"
        if candidate.exists():
            return candidate
    matches = sorted(CAPTURE_DIR.glob(f"{base_name}.*"))
    return matches[0] if matches else None


def screenshot_box(caption: str, bookmark: str | None = None, catalog_number: str | None = None) -> list:
    capture_path = capture_path_for_caption(caption)
    caption_flowable = (
        CatalogParagraph(caption, S["Caption"], bookmark, "figure", catalog_number or caption.split(" - ")[0], caption)
        if bookmark
        else p(caption, "Caption")
    )
    if capture_path:
        max_width = 16.1 * cm
        max_height = 7.9 * cm
        with Image.open(capture_path) as img:
            ratio = min(max_width / img.width, max_height / img.height)
            width = img.width * ratio
            height = img.height * ratio
        image = FlowableImage(str(capture_path), width=width, height=height)
        box = Table([[image]], colWidths=[16.1 * cm])
        box.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#94A3B8")),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        return [box, caption_flowable]

    box = Table([[p("[INSERER CAPTURE ICI]", "Box")]], colWidths=[16.1 * cm], rowHeights=[2.75 * cm])
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
    return [box, caption_flowable]


def numbered_steps(items: list[str], prefix: str) -> list:
    flowables = []
    for index, item in enumerate(items, 1):
        flowables.append(p(f"<b>Étape {index} :</b> {item}"))
        flowables.extend(screenshot_box(f"Capture {prefix}.{index} - {item[:76]}"))
    return flowables


def numbered_steps(items: list[str], prefix: str) -> list:
    flowables = []
    for index, item in enumerate(items, 1):
        caption = f"Capture {prefix}.{index} - {item[:76]}"
        step_flowables = [
            p(f"<b>Etape {index} :</b> {item}"),
            Spacer(1, 0.12 * cm),
            *screenshot_box(
                caption,
                bookmark=f"figure_{prefix}_{index}",
                catalog_number=f"Figure {prefix}.{index}",
            ),
            Spacer(1, 0.22 * cm),
        ]
        flowables.append(KeepTogether(step_flowables))
    return flowables


def bullet_list(items: list[str]) -> ListFlowable:
    return ListFlowable(
        [ListItem(p(item), leftIndent=8) for item in items],
        bulletType="bullet",
        start="circle",
        leftIndent=16,
        bulletFontName="Helvetica",
        bulletFontSize=7,
    )


def section_table(columns: list[str], rows: list[list[str]]) -> Table:
    table_rows = [[p(f"<b>{column}</b>", "Small") for column in columns]]
    table_rows.extend([[p(str(cell), "Small") for cell in row] for row in rows])
    table = Table(
        table_rows,
        colWidths=[3.7 * cm, 6.0 * cm, 6.4 * cm],
        repeatRows=1,
        hAlign="LEFT",
    )
    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#9FB8C2")),
        ("INNERGRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#D5E3E7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for row_index in range(1, len(table_rows)):
        if row_index % 2 == 0:
            style_commands.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#F7FAFB")))
    table.setStyle(TableStyle(style_commands))
    return table


def section_number(section: dict) -> str:
    return section["title"].split(".")[0]


def figure_entry(section_no: str, index: int, label: str, page: int | None = None) -> dict:
    return {
        "number": f"Figure {section_no}.{index}",
        "title": f"Capture {section_no}.{index} - {label[:76]}",
        "page": page,
        "bookmark": f"figure_{section_no}_{index}",
    }


def table_entry(section_no: str, index: int, title: str, page: int | None = None) -> dict:
    return {
        "number": f"Tableau {section_no}.{index}",
        "title": title,
        "page": page,
        "bookmark": f"table_{section_no}_{index}",
    }


def build_catalog_seed(guide: dict) -> dict:
    figures = []
    tables = []
    for section in guide["sections"]:
        section_no = section_number(section)
        if section.get("tables"):
            for index, table_spec in enumerate(section["tables"], 1):
                tables.append(table_entry(section_no, index, table_spec["title"]))
            continue
        if section.get("subsections"):
            for index, caption in enumerate(section.get("captures", []), 1):
                figures.append(figure_entry(section_no, index, caption))
            continue
        for index, item in enumerate(section.get("steps", []), 1):
            figures.append(figure_entry(section_no, index, item))
    return {"figure": figures, "table": tables}


def catalog_link(entry: dict, value: str) -> Paragraph:
    text = escape(str(value))
    return Paragraph(f'<link href="#{entry["bookmark"]}"><font color="#0B7F8C"><u>{text}</u></font></link>', S["Small"])


def catalog_table(entries: list[dict], empty_text: str) -> Table | Paragraph:
    if not entries:
        return p(empty_text)
    rows = [[p("<b>Numero</b>", "Small"), p("<b>Titre</b>", "Small"), p("<b>Page</b>", "Small")]]
    for entry in entries:
        page = entry.get("page") if entry.get("page") is not None else "..."
        rows.append(
            [
                catalog_link(entry, entry["number"]),
                catalog_link(entry, entry["title"]),
                catalog_link(entry, page),
            ]
        )
    table = Table(rows, colWidths=[3.0 * cm, 10.8 * cm, 2.3 * cm], repeatRows=1, hAlign="LEFT")
    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#9FB8C2")),
        ("INNERGRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#D5E3E7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for row_index in range(1, len(rows)):
        if row_index % 2 == 0:
            style_commands.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#F7FAFB")))
    table.setStyle(TableStyle(style_commands))
    return table


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


def build_cover(story: list, guide: dict):
    story.append(Spacer(1, 7.55 * cm))
    story.append(p(guide.get("cover_title", guide["role_title"]), "CoverTitle"))
    story.append(p(APP_NAME, "CoverSub"))
    story.append(p(f"{APP_SUBTITLE} · Version {VERSION} · {TODAY}", "CoverSub"))
    if not guide.get("show_cover_version", True):
        story.pop()
    story.append(p(guide["cover_note"], "CoverSub"))
    story.append(NextPageTemplate("main"))
    story.append(PageBreak())


def build_toc(story: list, guide: dict):
    story.append(BookmarkParagraph("Table des matières", S["H1"], "toc", 0))
    for section in guide["sections"]:
        story.append(Paragraph(f'<link href="#{section["id"]}">{section["title"]}</link>', S["TOC"]))
    story.append(Paragraph('<link href="#list_figures">Liste des figures</link>', S["TOC"]))
    story.append(Paragraph('<link href="#list_tables">Liste des tableaux</link>', S["TOC"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(info_box("Navigation PDF", "Chaque entrée est cliquable et redirige vers la section correspondante."))
    story.append(PageBreak())


def build_catalog_lists(story: list, catalog_data: dict):
    story.append(BookmarkParagraph("Liste des figures", S["H1"], "list_figures", 0))
    story.append(catalog_table(catalog_data.get("figure", []), "Aucune figure dans ce guide."))
    story.append(Spacer(1, 0.55 * cm))
    story.append(BookmarkParagraph("Liste des tableaux", S["H1"], "list_tables", 0))
    story.append(catalog_table(catalog_data.get("table", []), "Aucun tableau dans ce guide."))
    story.append(PageBreak())


def add_section(story: list, section: dict):
    story.append(BookmarkParagraph(section["title"], S["H1"], section["id"], 0))
    story.append(p("Description de la fonctionnalité", "H2"))
    story.append(p(section["description"]))
    story.append(p("Étapes d’utilisation", "H2"))
    story.extend(numbered_steps(section["steps"], section["title"].split(".")[0]))


def add_section(story: list, section: dict):
    story.append(BookmarkParagraph(section["title"], S["H1"], section["id"], 0))
    story.append(p("Description de la fonctionnalite", "H2"))
    story.append(p(section["description"]))
    section_no = section_number(section)
    if section.get("tables"):
        for table_index, table_spec in enumerate(section["tables"], 1):
            story.append(
                CatalogParagraph(
                    table_spec["title"],
                    S["H2"],
                    f"table_{section_no}_{table_index}",
                    "table",
                    f"Tableau {section_no}.{table_index}",
                    table_spec["title"],
                )
            )
            story.append(section_table(table_spec["columns"], table_spec["rows"]))
            story.append(Spacer(1, 0.35 * cm))
        return
    if section.get("subsections"):
        for subsection in section["subsections"]:
            story.append(p(subsection["title"], "H2"))
            story.append(bullet_list(subsection["items"]))
            story.append(Spacer(1, 0.12 * cm))
        for index, caption in enumerate(section.get("captures", []), 1):
            story.extend(
                screenshot_box(
                    f"Capture {section_no}.{index} - {caption}",
                    bookmark=f"figure_{section_no}_{index}",
                    catalog_number=f"Figure {section_no}.{index}",
                )
            )
        return
    story.append(p("Etapes d'utilisation", "H2"))
    story.extend(numbered_steps(section["steps"], section_no))


def build_story(guide: dict, catalog_data: dict | None = None) -> list:
    global ACTIVE_CAPTURE_PREFIX
    ACTIVE_CAPTURE_PREFIX = guide.get("capture_prefix")
    if catalog_data is None:
        catalog_data = build_catalog_seed(guide)
    story: list = []
    build_cover(story, guide)
    build_toc(story, guide)
    build_catalog_lists(story, catalog_data)
    story.append(info_box("Profil concerné", guide["role_label"]))
    for section in guide["sections"]:
        add_section(story, section)
    return story


def build_pdf(path: Path, guide: dict):
    catalog_data = build_catalog_seed(guide)
    previous_catalog = None
    for _ in range(4):
        doc = RoleGuideDoc(
            str(path),
            pagesize=A4,
            leftMargin=1.75 * cm,
            rightMargin=1.75 * cm,
            topMargin=2.65 * cm,
            bottomMargin=1.55 * cm,
            title=f"{guide['role_title']} - {APP_SUBTITLE}",
            author=AUTHOR,
        )
        doc.build(build_story(guide, catalog_data))
        current_catalog = doc.catalog_entries
        if current_catalog == previous_catalog:
            break
        previous_catalog = current_catalog
        catalog_data = current_catalog


def available_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 50):
        candidate = path.with_name(f"{path.stem}_v{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem}_{date.today().strftime('%Y%m%d')}{path.suffix}")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for guide in PROFILE_GUIDES.values():
        output = OUT_DIR / guide["file"]
        try:
            build_pdf(output, guide)
        except PermissionError:
            output = available_path(output)
            build_pdf(output, guide)
        print(output)


if __name__ == "__main__":
    main()
