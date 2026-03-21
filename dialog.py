import os
import logging
from datetime import datetime
from pathlib import Path
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QComboBox, QRadioButton, QPushButton, QSpinBox, QDoubleSpinBox,
    QProgressBar, QFileDialog, QLineEdit, QButtonGroup, QMessageBox,
    QDialogButtonBox, QApplication, QFormLayout, QFrame, QWidget, QCheckBox,
    QScrollArea, QStackedWidget
)
from qgis.PyQt.QtCore import Qt, QTimer, QEventLoop
from qgis.PyQt.QtGui import QFont, QIcon
from qgis.gui import QgsMapLayerComboBox
from qgis.core import (
    QgsProject, QgsMapLayerProxyModel
)

from .grid_generator import GridGenerator
from .geocoder import Geocoder
from .index_generator import IndexGenerator
from .atlas_creator import AtlasCreator
from .rectangle_tool import RectangleMapTool
from .lasso_tool import LassoMapTool


# ═══════════════════════════════════════════════════════════════════
LANGS = ['fr', 'en', 'es', 'pt', 'de']
LANG_LABELS = {'fr': 'Français', 'en': 'English', 'es': 'Español', 'pt': 'Português', 'de': 'Deutsch'}
LANG_FLAGS = {'fr': '\U0001F1EB\U0001F1F7', 'en': '\U0001F1EC\U0001F1E7', 'es': '\U0001F1EA\U0001F1F8',
              'pt': '\U0001F1F5\U0001F1F9', 'de': '\U0001F1E9\U0001F1EA'}

TR = {
    'window_title': {
        'fr': "ATLAS Index Pro — Générateur de feuillets",
        'en': "ATLAS Index Pro — Sheet Generator",
        'es': "ATLAS Index Pro — Generador de hojas",
        'pt': "ATLAS Index Pro — Gerador de folhas",
        'de': "ATLAS Index Pro — Blattgenerator"},
    'grp_layer': {
        'fr': "Couche source (objets)",  'en': "Source layer (objects)",
        'es': "Capa fuente (objetos)",   'pt': "Camada fonte (objetos)",
        'de': "Quelllayer (Objekte)"},
    'grp_format': {
        'fr': "Format et échelle",  'en': "Format and scale",
        'es': "Formato y escala",   'pt': "Formato e escala",
        'de': "Format und Maßstab"},
    'lbl_format': {
        'fr': "Format :",  'en': "Format:",
        'es': "Formato:",  'pt': "Formato:",  'de': "Format:"},
    'lbl_orient': {
        'fr': "Orientation :",  'en': "Orientation:",
        'es': "Orientación:",   'pt': "Orientação:",
        'de': "Ausrichtung:"},
    'orient_0': {
        'fr': "Paysage",   'en': "Landscape",
        'es': "Horizontal", 'pt': "Paisagem",  'de': "Querformat"},
    'orient_1': {
        'fr': "Portrait",  'en': "Portrait",
        'es': "Vertical",  'pt': "Retrato",   'de': "Hochformat"},
    'lbl_scale': {
        'fr': "Échelle :",  'en': "Scale:",
        'es': "Escala:",    'pt': "Escala:",   'de': "Maßstab:"},
    'scale_custom': {
        'fr': "Personnalisé",  'en': "Custom",
        'es': "Personalizado", 'pt': "Personalizado", 'de': "Benutzerdefiniert"},
    'lbl_custom': {
        'fr': "Échelle personnalisée :",  'en': "Custom scale:",
        'es': "Escala personalizada:",    'pt': "Escala personalizada:",
        'de': "Benutzerdefinierter Maßstab:"},
    'grp_extent': {
        'fr': "Emprise",    'en': "Extent",
        'es': "Extensión",  'pt': "Extensão",  'de': "Ausdehnung"},
    'radio_all': {
        'fr': "Tous les objets",             'en': "All objects",
        'es': "Todos los objetos",           'pt': "Todos os objetos",
        'de': "Alle Objekte"},
    'radio_sel': {
        'fr': "Emprise de la carte",          'en': "Current map extent",
        'es': "Extensión del mapa actual",    'pt': "Extensão do mapa atual",
        'de': "Aktuelle Kartenausdehnung"},
    'radio_draw': {
        'fr': "Zone dessinée sur la carte",  'en': "Drawn area on map",
        'es': "Zona dibujada en el mapa",    'pt': "Zona desenhada no mapa",
        'de': "Gezeichneter Bereich auf der Karte"},
    'btn_draw': {
        'fr': "Dessiner…",  'en': "Draw…",
        'es': "Dibujar…",   'pt': "Desenhar…",  'de': "Zeichnen…"},
    'radio_lasso': {
        'fr': "Sélection interactive (lasso cumulatif)",
        'en': "Interactive selection (cumulative lasso)",
        'es': "Selección interactiva (lazo acumulativo)",
        'pt': "Seleção interativa (laço cumulativo)",
        'de': "Interaktive Auswahl (kumulatives Lasso)"},
    'btn_lasso': {
        'fr': "Sélectionner…",  'en': "Select…",
        'es': "Seleccionar…",   'pt': "Selecionar…",  'de': "Auswählen…"},
    'lasso_ok': {
        'fr': "✔ {n} objet(s) sélectionné(s)",
        'en': "✔ {n} object(s) selected",
        'es': "✔ {n} objeto(s) seleccionado(s)",
        'pt': "✔ {n} objeto(s) selecionado(s)",
        'de': "✔ {n} Objekt(e) ausgewählt"},
    'lasso_bar': {
        'fr': "{n} objet(s)  ·  Clic gauche = point  ·  Clic droit = fermer le lasso",
        'en': "{n} object(s)  ·  Left click = point  ·  Right click = close lasso",
        'es': "{n} objeto(s)  ·  Clic izq. = punto  ·  Clic der. = cerrar lazo",
        'pt': "{n} objeto(s)  ·  Clique esq. = ponto  ·  Clique dir. = fechar laço",
        'de': "{n} Objekt(e)  ·  Linksklick = Punkt  ·  Rechtsklick = Lasso schließen"},
    'lasso_finish': {
        'fr': "Terminer",  'en': "Finish",
        'es': "Terminar",  'pt': "Terminar",  'de': "Fertig"},
    'lasso_reset': {
        'fr': "Réinitialiser",  'en': "Reset",
        'es': "Reiniciar",      'pt': "Reiniciar",  'de': "Zurücksetzen"},
    'dlg_lasso_info': {
        'fr': "0 objet(s)  ·  Clic gauche = point  ·  Clic droit = fermer le lasso",
        'en': "0 object(s)  ·  Left click = point  ·  Right click = close lasso",
        'es': "0 objeto(s)  ·  Clic izq. = punto  ·  Clic der. = cerrar lazo",
        'pt': "0 objeto(s)  ·  Clique esq. = ponto  ·  Clique dir. = fechar laço",
        'de': "0 Objekt(e)  ·  Linksklick = Punkt  ·  Rechtsklick = Lasso schließen"},
    'extent_ok': {
        'fr': "✔ Zone définie",   'en': "✔ Area defined",
        'es': "✔ Zona definida",  'pt': "✔ Zona definida",
        'de': "✔ Bereich definiert"},
    'chk_index': {
        'fr': "Créer un index géographique des objets",
        'en': "Create geographic object index",
        'es': "Crear un índice geográfico de objetos",
        'pt': "Criar um índice geográfico dos objetos",
        'de': "Geographisches Objektverzeichnis erstellen"},
    'grp_field': {
        'fr': "Adresse objet",     'en': "Object address",
        'es': "Dirección del objeto", 'pt': "Endereço do objeto",
        'de': "Objektadresse"},
    'radio_field': {
        'fr': "Champ existant :",  'en': "Existing field:",
        'es': "Campo existente:",  'pt': "Campo existente:",
        'de': "Vorhandenes Feld:"},
    'radio_ban': {
        'fr': "Géocodage BAN (France)",  'en': "BAN geocoding (France)",
        'es': "Geocodificación BAN (Francia)",
        'pt': "Geocodificação BAN (França)",
        'de': "BAN-Geokodierung (Frankreich)"},
    'radio_osm': {
        'fr': "Voies OSM — 1 requête sur l'emprise",
        'en': "OSM roads — 1 query on extent",
        'es': "Vías OSM — 1 consulta sobre la extensión",
        'pt': "Vias OSM — 1 consulta na extensão",
        'de': "OSM-Straßen — 1 Abfrage auf Ausdehnung"},
    'grp_output': {
        'fr': "Répertoire de sortie",  'en': "Output directory",
        'es': "Directorio de salida",  'pt': "Diretório de saída",
        'de': "Ausgabeverzeichnis"},
    'placeholder': {
        'fr': "Choisir un répertoire…",  'en': "Choose a directory…",
        'es': "Elegir un directorio…",   'pt': "Escolher um diretório…",
        'de': "Verzeichnis wählen…"},
    'btn_browse': {
        'fr': "Parcourir…",  'en': "Browse…",
        'es': "Examinar…",   'pt': "Procurar…",  'de': "Durchsuchen…"},
    'btn_adv': {
        'fr': "⚙  Paramètres avancés",  'en': "⚙  Advanced settings",
        'es': "⚙  Ajustes avanzados",   'pt': "⚙  Configurações avançadas",
        'de': "⚙  Erweiterte Einstellungen"},
    'btn_gen': {
        'fr': "  Générer  ",   'en': "  Generate  ",
        'es': "  Generar  ",   'pt': "  Gerar  ",   'de': "  Erzeugen  "},
    'btn_cancel': {
        'fr': "Annuler",       'en': "Cancel",
        'es': "Cancelar",      'pt': "Cancelar",    'de': "Abbrechen"},
    'st_cancelled': {
        'fr': "Annulé ✘",     'en': "Cancelled ✘",
        'es': "Cancelado ✘",  'pt': "Cancelado ✘",  'de': "Abgebrochen ✘"},
    # status
    'st_grid': {
        'fr': "Génération de la grille…",  'en': "Generating grid…",
        'es': "Generando cuadrícula…",     'pt': "Gerando grade…",
        'de': "Gitter wird erzeugt…"},
    'st_streets': {
        'fr': "Récupération des adresses objets…",  'en': "Fetching object addresses…",
        'es': "Obteniendo direcciones de objetos…", 'pt': "Obtendo endereços de objetos…",
        'de': "Objektadressen werden abgerufen…"},
    'st_index': {
        'fr': "Génération de l'index…",  'en': "Generating index…",
        'es': "Generando índice…",       'pt': "Gerando índice…",
        'de': "Verzeichnis wird erzeugt…"},
    'st_layout': {
        'fr': "Création de la mise en page…",  'en': "Creating layout…",
        'es': "Creando composición…",          'pt': "Criando composição…",
        'de': "Layout wird erstellt…"},
    'st_done': {
        'fr': "Terminé ✔",    'en': "Done ✔",
        'es': "Terminado ✔",  'pt': "Concluído ✔",  'de': "Fertig ✔"},
    # errors
    'err_layer': {
        'fr': "Sélectionnez une couche.",      'en': "Please select a layer.",
        'es': "Seleccione una capa.",          'pt': "Selecione uma camada.",
        'de': "Bitte einen Layer auswählen."},
    'err_dir': {
        'fr': "Choisissez un répertoire valide.",  'en': "Please choose a valid directory.",
        'es': "Elija un directorio válido.",       'pt': "Escolha um diretório válido.",
        'de': "Bitte ein gültiges Verzeichnis wählen."},
    'err_extent': {
        'fr': "Dessinez d'abord une zone.",  'en': "Please draw an area first.",
        'es': "Dibuje primero una zona.",    'pt': "Desenhe primeiro uma zona.",
        'de': "Bitte zuerst einen Bereich zeichnen."},
    'err_field': {
        'fr': "Sélectionnez un champ.",  'en': "Please select a field.",
        'es': "Seleccione un campo.",    'pt': "Selecione um campo.",
        'de': "Bitte ein Feld auswählen."},
    'warn_empty': {
        'fr': "Aucun feuillet ne contient d'objet.",  'en': "No sheet contains any object.",
        'es': "Ninguna hoja contiene objetos.",       'pt': "Nenhuma folha contém objetos.",
        'de': "Kein Blatt enthält Objekte."},
    'dlg_pick_dir': {
        'fr': "Répertoire de sortie",  'en': "Output directory",
        'es': "Directorio de salida",  'pt': "Diretório de saída",
        'de': "Ausgabeverzeichnis"},
    'dlg_draw_info': {
        'fr': "Dessinez un rectangle sur la carte (clic + glisser).",
        'en': "Draw a rectangle on the map (click + drag).",
        'es': "Dibuje un rectángulo en el mapa (clic + arrastrar).",
        'pt': "Desenhe um retângulo no mapa (clique + arraste).",
        'de': "Zeichnen Sie ein Rechteck auf der Karte (klicken + ziehen)."},
    'title_success': {
        'fr': "Succès",   'en': "Success",
        'es': "Éxito",    'pt': "Sucesso",  'de': "Erfolg"},
    'btn_open_folder': {
        'fr': "Ouvrir le dossier",   'en': "Open folder",
        'es': "Abrir carpeta",       'pt': "Abrir pasta",  'de': "Ordner öffnen"},
    'title_error': {
        'fr': "Erreur",   'en': "Error",
        'es': "Error",    'pt': "Erro",     'de': "Fehler"},
    'title_warning': {
        'fr': "Attention",    'en': "Warning",
        'es': "Advertencia",  'pt': "Aviso",  'de': "Warnung"},
    # advanced
    'adv_title': {
        'fr': "Paramètres avancés",       'en': "Advanced settings",
        'es': "Ajustes avanzados",        'pt': "Configurações avançadas",
        'de': "Erweiterte Einstellungen"},
    'adv_overlap': {
        'fr': "Recouvrement",  'en': "Overlap",
        'es': "Solapamiento",  'pt': "Sobreposição",  'de': "Überlappung"},
    'adv_overlap_desc': {
        'fr': "Les feuillets adjacents se chevauchent de ce pourcentage.",
        'en': "Adjacent sheets overlap by this percentage.",
        'es': "Las hojas adyacentes se solapan en este porcentaje.",
        'pt': "As folhas adjacentes sobrepõem-se nesta percentagem.",
        'de': "Benachbarte Blätter überlappen sich um diesen Prozentsatz."},
    'adv_margin': {
        'fr': "Marge autour des objets",   'en': "Object border margin",
        'es': "Margen alrededor de objetos", 'pt': "Margem ao redor dos objetos",
        'de': "Rand um die Objekte"},
    'adv_margin_desc': {
        'fr': "L'emprise est agrandie de ce % d'une cellule dans chaque direction.",
        'en': "The extent is expanded by this % of a cell in each direction.",
        'es': "La extensión se amplía en este % de celda en cada dirección.",
        'pt': "A extensão é expandida nesta % de célula em cada direção.",
        'de': "Die Ausdehnung wird um diesen % einer Zelle in jede Richtung erweitert."},
    'adv_dpi': {
        'fr': "Résolution PDF",  'en': "PDF resolution",
        'es': "Resolución PDF",  'pt': "Resolução PDF",
        'de': "PDF-Auflösung"},
    'adv_dpi_desc': {
        'fr': "Résolution d'export des feuillets atlas.",
        'en': "Export resolution for atlas sheets.",
        'es': "Resolución de exportación de hojas atlas.",
        'pt': "Resolução de exportação das folhas atlas.",
        'de': "Exportauflösung für die Atlasblätter."},
    'adv_lang': {
        'fr': "Langue",  'en': "Language",
        'es': "Idioma",  'pt': "Idioma",  'de': "Sprache"},
    'adv_lang_desc': {
        'fr': "Langue de l'interface du plugin.",
        'en': "Plugin interface language.",
        'es': "Idioma de la interfaz del plugin.",
        'pt': "Idioma da interface do plugin.",
        'de': "Sprache der Plugin-Oberfläche."},
    # PDF export
    'chk_pdf': {
        'fr': "Exporter en PDF",  'en': "Export to PDF",
        'es': "Exportar a PDF",   'pt': "Exportar em PDF",
        'de': "Als PDF exportieren"},
    'lbl_pdf_title': {
        'fr': "Titre du document :",  'en': "Document title:",
        'es': "Título del documento:", 'pt': "Título do documento:",
        'de': "Dokumenttitel:"},
    'pdf_title_ph': {
        'fr': "Ex : Atlas des conduites EU",  'en': "E.g.: Water pipeline atlas",
        'es': "Ej.: Atlas de tuberías",       'pt': "Ex.: Atlas de tubulações",
        'de': "Z.B.: Leitungsatlas"},
    'st_pdf': {
        'fr': "Export PDF en cours…",   'en': "PDF export in progress…",
        'es': "Exportación PDF en curso…", 'pt': "Exportação PDF em andamento…",
        'de': "PDF-Export läuft…"},
    'st_pdf_no_merge': {
        'fr': "Fusion impossible — fichiers séparés créés.",
        'en': "Merge failed — separate files created.",
        'es': "Fusión imposible — archivos separados creados.",
        'pt': "Fusão impossível — arquivos separados criados.",
        'de': "Zusammenführung fehlgeschlagen — separate Dateien erstellt."},
    'format_custom': {
        'fr': "Personnalisé",  'en': "Custom",
        'es': "Personalizado", 'pt': "Personalizado", 'de': "Benutzerdefiniert"},
    'lbl_custom_fmt': {
        'fr': "Dimensions (mm) :",  'en': "Dimensions (mm):",
        'es': "Dimensiones (mm):",  'pt': "Dimensões (mm):",
        'de': "Abmessungen (mm):"},
    'btn_about': {
        'fr': "À propos",  'en': "About",
        'es': "Acerca de", 'pt': "Sobre",  'de': "Über"},
    'btn_next': {
        'fr': "Suivant  ▸",  'en': "Next  ▸",
        'es': "Siguiente  ▸",  'pt': "Seguinte  ▸",  'de': "Weiter  ▸"},
    'btn_prev': {
        'fr': "◂  Précédent",  'en': "◂  Previous",
        'es': "◂  Anterior",   'pt': "◂  Anterior",  'de': "◂  Zurück"},
    'step_label': {
        'fr': "Étape {cur} / {total}",  'en': "Step {cur} / {total}",
        'es': "Paso {cur} / {total}",   'pt': "Passo {cur} / {total}",
        'de': "Schritt {cur} / {total}"},
}


def _success_body(lang, n, out_dir=None, with_index=False, with_pdf=False):
    _msgs = {
        'fr': ("Génération terminée !", "{n} feuillet(s) créé(s)",
               "Grille", "Index", "PDF", "Mise en page « ATLAS Index Pro » ajoutée au projet"),
        'en': ("Generation complete!", "{n} sheet(s) created",
               "Grid", "Index", "PDF", "'ATLAS Index Pro' layout added to project"),
        'es': ("¡Generación completada!", "{n} hoja(s) creada(s)",
               "Cuadrícula", "Índice", "PDF", "Composición « ATLAS Index Pro » añadida al proyecto"),
        'pt': ("Geração concluída!", "{n} folha(s) criada(s)",
               "Grade", "Índice", "PDF", "Composição « ATLAS Index Pro » adicionada ao projeto"),
        'de': ("Erzeugung abgeschlossen!", "{n} Blatt/Blätter erstellt",
               "Gitter", "Verzeichnis", "PDF", "Layout « ATLAS Index Pro » zum Projekt hinzugefügt"),
    }
    m = _msgs.get(lang, _msgs['en'])
    lines = [m[0] + "\n", f"• {m[1].format(n=n)}"]
    if out_dir:
        lines.append(f"• {m[2]} → {out_dir}/grille_feuillets.geojson")
    if with_index and out_dir:
        lines.append(f"• {m[3]}  → {out_dir}/index_objets.html")
    if with_pdf and out_dir:
        lines.append(f"• {m[4]}   → {out_dir}/atlas_complet.pdf")
    lines.append(f"• {m[5]}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
class AboutDialog(QDialog):
    """Modal dialog showing plugin info: logo, license and GitHub link."""

    _ABOUT_TR = {
        'title':  {'fr': "À propos",  'en': "About",     'es': "Acerca de",
                    'pt': "Sobre",     'de': "Über"},
        'close':  {'fr': "Fermer",    'en': "Close",     'es': "Cerrar",
                    'pt': "Fechar",    'de': "Schließen"},
    }

    def __init__(self, lang='fr', parent=None):
        super().__init__(parent)
        tr = lambda k: self._ABOUT_TR[k].get(lang, self._ABOUT_TR[k]['en'])
        self.setWindowTitle(tr('title'))
        self.setFixedWidth(420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        icon_path = os.path.join(os.path.dirname(__file__), "logo.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        # Logo (if present)
        logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
        if os.path.exists(logo_path):
            from qgis.PyQt.QtGui import QPixmap
            lbl_logo = QLabel()
            pixmap = QPixmap(logo_path).scaledToWidth(160, Qt.SmoothTransformation)
            lbl_logo.setPixmap(pixmap)
            lbl_logo.setAlignment(Qt.AlignCenter)
            layout.addWidget(lbl_logo)

        # Title
        lbl_name = QLabel("ATLAS Index Pro")
        font_title = QFont()
        font_title.setBold(True)
        font_title.setPointSize(13)
        lbl_name.setFont(font_title)
        lbl_name.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_name)

        # Version
        lbl_version = QLabel("Version 3.0.1")
        lbl_version.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_version)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        # Author
        lbl_author = QLabel(
            '<a href="mailto:y.laloux@vichy-communaute.fr">Yoan Laloux</a>'
        )
        lbl_author.setOpenExternalLinks(True)
        lbl_author.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_author)

        # License
        lbl_license = QLabel(
            '<a href="https://www.gnu.org/licenses/gpl-3.0.html">'
            'GNU General Public License v3.0</a>'
        )
        lbl_license.setOpenExternalLinks(True)
        lbl_license.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_license)

        # GitHub
        lbl_github = QLabel(
            '<a href="https://github.com/Cartoyoyo/ATLAS_Index_Pro">'
            'github.com/Cartoyoyo/ATLAS_Index_Pro</a>'
        )
        lbl_github.setOpenExternalLinks(True)
        lbl_github.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_github)

        # Close button
        btn_close = QPushButton(tr('close'))
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

        self.setLayout(layout)


# ═══════════════════════════════════════════════════════════════════
class AtlasDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.drawn_extent = None
        self.rect_tool = None
        self.previous_tool = None

        self.lang = 'fr'
        self.overlap_pct = 0.0
        self.margin_pct = 10.0
        self.dpi = 150
        self._title_user_edited = False

        self.setMinimumWidth(520)
        icon_path = os.path.join(os.path.dirname(__file__), "logo.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self._init_logger()
        self._build_ui()
        self._retranslate_ui()

    def _init_logger(self):
        """Initialise le fichier log dans le répertoire du plugin."""
        log_path = os.path.join(os.path.dirname(__file__), 'atlas_log.txt')
        self._logger = logging.getLogger('ATLAS_Index_Pro')
        self._logger.setLevel(logging.DEBUG)
        # Fermer et supprimer les handlers précédents (rechargement plugin)
        for h in self._logger.handlers[:]:
            h.close()
            self._logger.removeHandler(h)
        fh = logging.FileHandler(log_path, mode='w', encoding='utf-8')
        fh.setFormatter(logging.Formatter('%(asctime)s  %(message)s', datefmt='%H:%M:%S'))
        self._logger.addHandler(fh)

    def _log(self, msg, filepath=None):
        """Log un message + met à jour le label status avec le fichier en cours."""
        if filepath:
            full = f"{msg}  →  {filepath}"
        else:
            full = msg
        self._logger.info(full)
        # Afficher dans le status label : action + fichier
        if filepath:
            fname = os.path.basename(filepath)
            self.lbl_status.setText(f"{msg}  ·  📄 {fname}")
        else:
            self.lbl_status.setText(msg)
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

    def tr(self, key):
        entry = TR.get(key)
        if not entry:
            return key
        return entry.get(self.lang, entry.get('en', key))

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        outer = QVBoxLayout()

        # ── QStackedWidget : 3 pages ──
        self.stack = QStackedWidget()

        # ════════════════════════════════════════════════════════════
        #  PAGE 1 : Source, Format, Échelle, Emprise
        # ════════════════════════════════════════════════════════════
        page1 = QWidget()
        p1 = QVBoxLayout(page1)

        # --- Couche source ---
        self.grp_layer = QGroupBox()
        lay = QVBoxLayout()
        self.combo_layer = QgsMapLayerComboBox()
        import warnings
        _layer_filter = (
            QgsMapLayerProxyModel.LineLayer | QgsMapLayerProxyModel.PointLayer
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            self.combo_layer.setFilters(_layer_filter)
        self.combo_layer.layerChanged.connect(self._refresh_fields)
        lay.addWidget(self.combo_layer)
        self.grp_layer.setLayout(lay)
        p1.addWidget(self.grp_layer)

        # --- Format / Échelle ---
        self.grp_format = QGroupBox()
        form = QFormLayout()

        self.combo_format = QComboBox()
        self.combo_format.addItems([
            'A4', 'A3', 'A0', 'A1', 'A2', 'A5',
            'Letter', 'Legal', 'Tabloid',
            'ANSI C', 'ANSI D', 'ANSI E',
            ''  # Custom — filled by _retranslate_ui
        ])
        self.combo_format.currentIndexChanged.connect(self._on_format_changed)
        self.combo_format.currentIndexChanged.connect(lambda: self._update_default_title())
        self.lbl_format_row = QLabel()
        form.addRow(self.lbl_format_row, self.combo_format)

        # Custom format dimensions
        self.lbl_custom_fmt = QLabel()
        self.lbl_custom_fmt.setVisible(False)
        self.custom_fmt_row = QHBoxLayout()
        self.spin_custom_w = QSpinBox()
        self.spin_custom_w.setRange(50, 2000)
        self.spin_custom_w.setValue(210)
        self.spin_custom_w.setSuffix(" mm")
        self.spin_custom_w.setVisible(False)
        lbl_x = QLabel("×")
        lbl_x.setFixedWidth(12)
        self.lbl_x_fmt = lbl_x
        self.lbl_x_fmt.setVisible(False)
        self.spin_custom_h = QSpinBox()
        self.spin_custom_h.setRange(50, 2000)
        self.spin_custom_h.setValue(297)
        self.spin_custom_h.setSuffix(" mm")
        self.spin_custom_h.setVisible(False)
        custom_row = QHBoxLayout()
        custom_row.addWidget(self.spin_custom_w)
        custom_row.addWidget(self.lbl_x_fmt)
        custom_row.addWidget(self.spin_custom_h)
        self.custom_fmt_widget = QWidget()
        self.custom_fmt_widget.setLayout(custom_row)
        self.custom_fmt_widget.setVisible(False)
        form.addRow(self.lbl_custom_fmt, self.custom_fmt_widget)

        self.combo_orient = QComboBox()
        self.combo_orient.addItems(['', ''])   # rempli par _retranslate_ui
        self.combo_orient.currentIndexChanged.connect(lambda: self._update_default_title())
        self.lbl_orient_row = QLabel()
        form.addRow(self.lbl_orient_row, self.combo_orient)

        self.combo_scale = QComboBox()
        self.combo_scale.addItems(['1/200', '1/500', '1/1000', '1/2000', ''])
        self.combo_scale.setCurrentIndex(3)  # 1/2000 par défaut
        self.combo_scale.currentIndexChanged.connect(self._on_scale_changed)
        self.lbl_scale_row = QLabel()
        form.addRow(self.lbl_scale_row, self.combo_scale)

        self.spin_custom = QSpinBox()
        self.spin_custom.setRange(1, 100000)
        self.spin_custom.setValue(500)
        self.spin_custom.setPrefix("1 / ")
        self.spin_custom.setVisible(False)
        self.lbl_custom = QLabel()
        self.lbl_custom.setVisible(False)
        form.addRow(self.lbl_custom, self.spin_custom)

        self.grp_format.setLayout(form)
        p1.addWidget(self.grp_format)

        # --- Emprise ---
        self.grp_extent = QGroupBox()
        lay = QVBoxLayout()

        self.radio_all = QRadioButton()
        self.radio_all.setChecked(True)
        self.radio_sel = QRadioButton()
        self.radio_draw = QRadioButton()
        self.radio_lasso = QRadioButton()

        self.bg_extent = QButtonGroup(self)
        self.bg_extent.addButton(self.radio_all, 0)
        self.bg_extent.addButton(self.radio_sel, 1)
        self.bg_extent.addButton(self.radio_draw, 2)
        self.bg_extent.addButton(self.radio_lasso, 3)

        lay.addWidget(self.radio_all)
        lay.addWidget(self.radio_sel)

        row = QHBoxLayout()
        row.addWidget(self.radio_draw)
        self.btn_draw = QPushButton()
        self.btn_draw.setEnabled(False)
        self.btn_draw.clicked.connect(self._start_draw)
        row.addWidget(self.btn_draw)
        self.lbl_extent = QLabel("")
        row.addWidget(self.lbl_extent)
        lay.addLayout(row)

        row_lasso = QHBoxLayout()
        row_lasso.addWidget(self.radio_lasso)
        self.btn_lasso = QPushButton()
        self.btn_lasso.setEnabled(False)
        self.btn_lasso.clicked.connect(self._start_lasso)
        row_lasso.addWidget(self.btn_lasso)
        self.lbl_lasso = QLabel("")
        row_lasso.addWidget(self.lbl_lasso)
        lay.addLayout(row_lasso)

        self.radio_draw.toggled.connect(self.btn_draw.setEnabled)
        self.radio_lasso.toggled.connect(self.btn_lasso.setEnabled)

        self.grp_extent.setLayout(lay)
        p1.addWidget(self.grp_extent)

        p1.addStretch()
        self.stack.addWidget(page1)

        # ════════════════════════════════════════════════════════════
        #  PAGE 2 : Index géographique
        # ════════════════════════════════════════════════════════════
        page2 = QWidget()
        p2 = QVBoxLayout(page2)

        self.chk_index = QCheckBox()
        self.chk_index.setChecked(False)
        self.chk_index.setStyleSheet("""
            QCheckBox {
                spacing: 10px;
                font-size: 10pt;
                font-weight: bold;
                color: #2c3e50;
                padding: 8px 12px;
                background: #eaf2f8;
                border: 1px solid #aed6f1;
                border-radius: 6px;
            }
            QCheckBox:checked {
                background: #d5f5e3;
                border-color: #82e0aa;
                color: #1e8449;
            }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
            }
        """)
        p2.addWidget(self.chk_index)

        # --- Adresse objet ---
        self.grp_field = QGroupBox()
        lay = QVBoxLayout()

        row = QHBoxLayout()
        self.radio_field = QRadioButton()
        self.radio_field.setChecked(True)
        row.addWidget(self.radio_field)
        self.combo_field = QComboBox()
        self.combo_field.setMinimumWidth(180)
        row.addWidget(self.combo_field)
        lay.addLayout(row)

        self.radio_ban = QRadioButton()
        lay.addWidget(self.radio_ban)

        self.radio_osm = QRadioButton()
        lay.addWidget(self.radio_osm)

        self.bg_address = QButtonGroup(self)
        self.bg_address.addButton(self.radio_field, 0)
        self.bg_address.addButton(self.radio_ban, 1)
        self.bg_address.addButton(self.radio_osm, 2)
        self.radio_field.toggled.connect(
            lambda checked: self.combo_field.setEnabled(checked)
        )

        self.grp_field.setLayout(lay)
        self.grp_field.setEnabled(False)
        p2.addWidget(self.grp_field)

        p2.addStretch()
        self.stack.addWidget(page2)

        # ════════════════════════════════════════════════════════════
        #  PAGE 3 : Export PDF + Répertoire de sortie
        # ════════════════════════════════════════════════════════════
        page3 = QWidget()
        p3 = QVBoxLayout(page3)

        self.chk_pdf = QCheckBox()
        self.chk_pdf.setChecked(False)
        self.chk_pdf.setStyleSheet("""
            QCheckBox {
                spacing: 10px;
                font-size: 10pt;
                font-weight: bold;
                color: #2c3e50;
                padding: 8px 12px;
                background: #eaf2f8;
                border: 1px solid #aed6f1;
                border-radius: 6px;
            }
            QCheckBox:checked {
                background: #d5f5e3;
                border-color: #82e0aa;
                color: #1e8449;
            }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
            }
        """)
        p3.addWidget(self.chk_pdf)

        # Titre PDF
        self.grp_pdf_title = QGroupBox()
        row = QHBoxLayout()
        self.lbl_pdf_title = QLabel()
        row.addWidget(self.lbl_pdf_title)
        self.txt_pdf_title = QLineEdit()
        self.txt_pdf_title.textEdited.connect(self._on_title_edited)
        row.addWidget(self.txt_pdf_title)
        self.grp_pdf_title.setLayout(row)
        self.grp_pdf_title.setEnabled(False)
        p3.addWidget(self.grp_pdf_title)

        # --- Répertoire de sortie ---
        self.grp_output = QGroupBox()
        row = QHBoxLayout()
        self.txt_dir = QLineEdit()
        row.addWidget(self.txt_dir)
        self.btn_browse = QPushButton()
        self.btn_browse.clicked.connect(self._pick_dir)
        row.addWidget(self.btn_browse)
        self.grp_output.setLayout(row)
        self.grp_output.setVisible(False)
        p3.addWidget(self.grp_output)

        p3.addStretch()
        self.stack.addWidget(page3)

        # Initialiser après construction complète des 3 pages
        self._refresh_fields()
        self.chk_index.toggled.connect(self._on_index_toggled)
        self.chk_pdf.toggled.connect(self._on_pdf_toggled)
        self.stack.setCurrentIndex(0)

        # ── Ajouter le stack au layout principal ──
        outer.addWidget(self.stack, 1)

        # ── Navigation : Précédent / étape / Suivant ──
        nav_row = QHBoxLayout()

        self.btn_prev = QPushButton()
        self.btn_prev.setFixedHeight(32)
        self.btn_prev.setStyleSheet(
            "QPushButton{background:#3498db;color:#fff;padding:6px 18px;"
            "border-radius:5px;font-weight:bold}"
            "QPushButton:hover{background:#2980b9}"
            "QPushButton:disabled{background:#bdc3c7;color:#7f8c8d}"
        )
        self.btn_prev.clicked.connect(self._prev_page)
        nav_row.addWidget(self.btn_prev)

        nav_row.addStretch()

        self.lbl_step = QLabel()
        self.lbl_step.setStyleSheet(
            "font-size:9pt;font-weight:bold;color:#7f8c8d;"
        )
        nav_row.addWidget(self.lbl_step)

        nav_row.addStretch()

        self.btn_next = QPushButton()
        self.btn_next.setFixedHeight(32)
        self.btn_next.setStyleSheet(
            "QPushButton{background:#3498db;color:#fff;padding:6px 18px;"
            "border-radius:5px;font-weight:bold}"
            "QPushButton:hover{background:#2980b9}"
        )
        self.btn_next.clicked.connect(self._next_page)
        nav_row.addWidget(self.btn_next)

        outer.addLayout(nav_row)

        # ── Séparateur ──
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        outer.addWidget(sep)

        # --- Boutons bas ---
        row = QHBoxLayout()
        self.combo_lang = QComboBox()
        self.combo_lang.setFixedWidth(150)
        for code in LANGS:
            flag = LANG_FLAGS.get(code, '')
            self.combo_lang.addItem(f"{flag}  {LANG_LABELS[code]}", code)
        self.combo_lang.setCurrentIndex(LANGS.index(self.lang))
        self.combo_lang.setStyleSheet("""
            QComboBox {
                border: 1px solid #c8cdd5;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 9pt;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ffffff, stop:1 #f5f6f8);
                color: #2c3e50;
            }
            QComboBox:hover {
                border-color: #2980b9;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ffffff, stop:1 #eaf2f8);
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 6px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #c8cdd5;
                border-radius: 4px;
                background: white;
                selection-background-color: #eaf2f8;
                selection-color: #2c3e50;
                padding: 4px;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                padding: 5px 8px;
                min-height: 24px;
            }
        """)
        self.combo_lang.currentIndexChanged.connect(self._on_lang_changed)
        row.addWidget(self.combo_lang)

        self.btn_adv = QPushButton()
        self.btn_adv.clicked.connect(self._show_advanced)
        row.addWidget(self.btn_adv)

        self.btn_about = QPushButton()
        self.btn_about.setFixedWidth(90)
        self.btn_about.setFixedHeight(28)
        self.btn_about.setCursor(Qt.PointingHandCursor)
        self.btn_about.setStyleSheet(
            "QPushButton{background:#7f8c8d;color:#fff;border-radius:5px;"
            "font-weight:bold;font-size:11px}"
            "QPushButton:hover{background:#95a5a6}"
        )
        self.btn_about.clicked.connect(self._show_about)
        row.addWidget(self.btn_about)
        row.addStretch()
        self.btn_gen = QPushButton()
        self.btn_gen.setFont(QFont('Segoe UI', 10, QFont.Bold))
        self.btn_gen.setStyleSheet(
            "QPushButton{background:#27ae60;color:#fff;padding:9px 28px;"
            "border-radius:5px} QPushButton:hover{background:#219a52}"
        )
        self.btn_gen.clicked.connect(self._generate)
        row.addWidget(self.btn_gen)
        outer.addLayout(row)

        # --- Barre de progression + Annuler ---
        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        progress_row.addWidget(self.progress)
        self.btn_cancel = QPushButton()
        self.btn_cancel.setVisible(False)
        self.btn_cancel.setFixedWidth(90)
        self.btn_cancel.clicked.connect(self._cancel_generation)
        progress_row.addWidget(self.btn_cancel)
        outer.addLayout(progress_row)
        self.lbl_status = QLabel("")
        outer.addWidget(self.lbl_status)

        self.setLayout(outer)
        self._update_nav()

    def _update_nav(self):
        """Met à jour les boutons de navigation selon la page active."""
        idx = self.stack.currentIndex()
        total = self.stack.count()
        self.btn_prev.setVisible(idx > 0)
        self.btn_next.setVisible(idx < total - 1)
        self.btn_gen.setVisible(idx == total - 1)
        self.lbl_step.setText(
            self.tr('step_label').format(cur=idx + 1, total=total)
        )

    def _next_page(self):
        idx = self.stack.currentIndex()
        if idx < self.stack.count() - 1:
            self.stack.setCurrentIndex(idx + 1)
            self._update_nav()

    def _prev_page(self):
        idx = self.stack.currentIndex()
        if idx > 0:
            self.stack.setCurrentIndex(idx - 1)
            self._update_nav()

    def _retranslate_ui(self):
        self.setWindowTitle(self.tr('window_title'))
        self.grp_layer.setTitle(self.tr('grp_layer'))
        self.grp_format.setTitle(self.tr('grp_format'))
        self.lbl_format_row.setText(self.tr('lbl_format'))
        self.lbl_orient_row.setText(self.tr('lbl_orient'))
        # Orientation : conserver l'index courant
        idx = self.combo_orient.currentIndex()
        self.combo_orient.setItemText(0, self.tr('orient_0'))
        self.combo_orient.setItemText(1, self.tr('orient_1'))
        self.combo_orient.setCurrentIndex(idx)
        self.lbl_scale_row.setText(self.tr('lbl_scale'))
        self.combo_scale.setItemText(4, self.tr('scale_custom'))
        self.lbl_custom.setText(self.tr('lbl_custom'))
        self.combo_format.setItemText(12, self.tr('format_custom'))
        self.lbl_custom_fmt.setText(self.tr('lbl_custom_fmt'))
        self.grp_extent.setTitle(self.tr('grp_extent'))
        self.radio_all.setText(self.tr('radio_all'))
        self.radio_sel.setText(self.tr('radio_sel'))
        self.radio_draw.setText(self.tr('radio_draw'))
        self.btn_draw.setText(self.tr('btn_draw'))
        self.radio_lasso.setText(self.tr('radio_lasso'))
        self.btn_lasso.setText(self.tr('btn_lasso'))
        self.chk_index.setText(self.tr('chk_index'))
        self.chk_pdf.setText(self.tr('chk_pdf'))
        self.lbl_pdf_title.setText(self.tr('lbl_pdf_title'))
        self.txt_pdf_title.setPlaceholderText(self.tr('pdf_title_ph'))
        self.grp_field.setTitle(self.tr('grp_field'))
        self.radio_field.setText(self.tr('radio_field'))
        self.radio_ban.setText(self.tr('radio_ban'))
        self.radio_osm.setText(self.tr('radio_osm'))
        self.grp_output.setTitle(self.tr('grp_output'))
        self.txt_dir.setPlaceholderText(self.tr('placeholder'))
        self.btn_browse.setText(self.tr('btn_browse'))
        self.btn_adv.setText(self.tr('btn_adv'))
        self.btn_gen.setText(self.tr('btn_gen'))
        self.btn_cancel.setText(self.tr('btn_cancel'))
        self.btn_about.setText(self.tr('btn_about'))
        self.btn_next.setText(self.tr('btn_next'))
        self.btn_prev.setText(self.tr('btn_prev'))
        self._update_nav()
    # -------------------------------------------------------- slots
    def _show_about(self):
        dlg = AboutDialog(lang=self.lang, parent=self)
        dlg.exec_()

    def _on_lang_changed(self, index):
        self.lang = LANGS[index]
        self._retranslate_ui()

    def _on_format_changed(self, index):
        custom = (index == 12)
        self.lbl_custom_fmt.setVisible(custom)
        self.custom_fmt_widget.setVisible(custom)

    def _on_index_toggled(self, checked):
        self.grp_field.setEnabled(checked)
        self.grp_output.setVisible(
            self.chk_index.isChecked() or self.chk_pdf.isChecked()
        )

    def _on_pdf_toggled(self, checked):
        self.grp_pdf_title.setEnabled(checked)
        self.grp_output.setVisible(
            self.chk_index.isChecked() or self.chk_pdf.isChecked()
        )

    def _on_scale_changed(self, index):
        custom = (index == 4)
        self.spin_custom.setVisible(custom)
        self.lbl_custom.setVisible(custom)
        self._update_default_title()

    def _update_default_title(self):
        """Met à jour le titre PDF par défaut : Atlas - Couche - Format - Orientation - Echelle."""
        if self._title_user_edited:
            return
        layer = self.combo_layer.currentLayer()
        if not layer:
            return
        fmt = self.combo_format.currentText()
        orient = self.combo_orient.currentText()
        scale = self.combo_scale.currentText() if hasattr(self, 'combo_scale') else ''
        self.txt_pdf_title.setText(f"Atlas - {layer.name()} - {fmt} - {orient} - {scale}")

    def _on_title_edited(self, text):
        """Détecte si l'utilisateur a modifié manuellement le titre."""
        self._title_user_edited = bool(text.strip())

    def _refresh_fields(self):
        self.combo_field.clear()
        layer = self.combo_layer.currentLayer()
        if layer:
            for f in layer.fields():
                self.combo_field.addItem(f.name())
            self._update_default_title()

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, self.tr('dlg_pick_dir'))
        if d:
            self.txt_dir.setText(d)

    def _start_draw(self):
        self.previous_tool = self.canvas.mapTool()
        if self.rect_tool is not None:
            try:
                self.rect_tool.rectangleCreated.disconnect(self._on_rect_drawn)
            except TypeError:
                pass
        self.rect_tool = RectangleMapTool(self.canvas)
        self.rect_tool.rectangleCreated.connect(self._on_rect_drawn)
        self.canvas.setMapTool(self.rect_tool)
        self.hide()
        self.iface.messageBar().pushInfo("Atlas", self.tr('dlg_draw_info'))

    def _on_rect_drawn(self, rect):
        self.drawn_extent = rect
        self.lbl_extent.setText(self.tr('extent_ok'))
        if self.previous_tool:
            self.canvas.setMapTool(self.previous_tool)
        self.show()
        self.raise_()

    def _start_lasso(self):
        """Lance le mode sélection lasso cumulatif."""
        layer = self.combo_layer.currentLayer()
        if not layer:
            return

        # Construire l'index spatial une seule fois pour toute la session
        from qgis.core import QgsSpatialIndex
        self._lasso_layer = layer
        self._lasso_spatial_idx = QgsSpatialIndex(layer.getFeatures())

        # Vider la sélection existante au démarrage
        layer.removeSelection()

        self.previous_tool = self.canvas.mapTool()
        if hasattr(self, 'lasso_tool') and self.lasso_tool is not None:
            try:
                self.lasso_tool.lassoFinished.disconnect(self._on_lasso_finished)
            except TypeError:
                pass
            self.lasso_tool.deleteLater()
        self.lasso_tool = LassoMapTool(self.canvas)
        self.lasso_tool.lassoFinished.connect(self._on_lasso_finished)
        self.canvas.setMapTool(self.lasso_tool)
        self.hide()

        # Panneau flottant Qt au-dessus du canevas
        self._lasso_panel = QFrame(self.canvas)
        self._lasso_panel.setStyleSheet(
            "QFrame{background:#2c3e50;border-radius:8px;}"
        )
        panel_layout = QHBoxLayout(self._lasso_panel)
        panel_layout.setContentsMargins(12, 8, 12, 8)
        panel_layout.setSpacing(10)

        self._lasso_label = QLabel(self.tr('dlg_lasso_info'))
        self._lasso_label.setStyleSheet(
            "QLabel{color:#ecf0f1;font-size:10pt;font-weight:bold;}"
        )
        panel_layout.addWidget(self._lasso_label)

        btn_finish = QPushButton(self.tr('lasso_finish'))
        btn_finish.setCursor(Qt.PointingHandCursor)
        btn_finish.setStyleSheet(
            "QPushButton{background:#27ae60;color:#fff;padding:6px 16px;"
            "border-radius:4px;font-weight:bold;font-size:10pt}"
            "QPushButton:hover{background:#219a52}"
        )
        btn_finish.clicked.connect(self._finish_lasso)
        panel_layout.addWidget(btn_finish)

        btn_reset = QPushButton(self.tr('lasso_reset'))
        btn_reset.setCursor(Qt.PointingHandCursor)
        btn_reset.setStyleSheet(
            "QPushButton{background:#c0392b;color:#fff;padding:6px 16px;"
            "border-radius:4px;font-weight:bold;font-size:10pt}"
            "QPushButton:hover{background:#a93226}"
        )
        btn_reset.clicked.connect(self._reset_lasso)
        panel_layout.addWidget(btn_reset)

        self._lasso_panel.adjustSize()
        # Centrer en haut du canevas
        pw = self._lasso_panel.sizeHint().width()
        self._lasso_panel.move((self.canvas.width() - pw) // 2, 10)
        self._lasso_panel.show()
        self._lasso_panel.raise_()

    def _on_lasso_finished(self, geom):
        """Ajoute les objets intersectant le lasso à la sélection courante (cumulatif)."""
        layer = self._lasso_layer
        if not layer or not geom or geom.isEmpty():
            return

        from qgis.core import QgsCoordinateTransform, QgsProject, QgsGeometry

        # Transformer la géométrie lasso (SCR canevas) vers le SCR de la couche
        canvas_crs = QgsProject.instance().crs()
        transform = QgsCoordinateTransform(
            canvas_crs, layer.crs(), QgsProject.instance()
        )
        lasso_geom = QgsGeometry(geom)
        lasso_geom.transform(transform)

        # Trouver les objets intersectant ce lasso
        candidate_ids = self._lasso_spatial_idx.intersects(lasso_geom.boundingBox())
        new_ids = []
        for fid in candidate_ids:
            feat = layer.getFeature(fid)
            if feat.geometry().intersects(lasso_geom):
                new_ids.append(fid)

        # AJOUTER à la sélection existante (pas remplacer)
        from qgis.core import QgsVectorLayer
        current = list(layer.selectedFeatureIds())
        layer.selectByIds(current + new_ids, QgsVectorLayer.SetSelection)

        # Mettre à jour le compteur sur le panneau flottant
        n = layer.selectedFeatureCount()
        self._lasso_label.setText(
            self.tr('lasso_bar').format(n=n)
        )
        # Recentrer le panneau (la largeur a pu changer)
        self._lasso_panel.adjustSize()
        pw = self._lasso_panel.sizeHint().width()
        self._lasso_panel.move((self.canvas.width() - pw) // 2, 10)

        # L'outil lasso reste actif → prêt pour un nouveau tracé

    def _reset_lasso(self):
        """Réinitialise la sélection pendant le mode lasso."""
        if hasattr(self, '_lasso_layer') and self._lasso_layer:
            self._lasso_layer.removeSelection()
            self._lasso_label.setText(
                self.tr('lasso_bar').format(n=0)
            )
            self._lasso_panel.adjustSize()
            pw = self._lasso_panel.sizeHint().width()
            self._lasso_panel.move((self.canvas.width() - pw) // 2, 10)

    def _finish_lasso(self):
        """Valide la sélection lasso et revient au dialog."""
        layer = self._lasso_layer if hasattr(self, '_lasso_layer') else None
        n = layer.selectedFeatureCount() if layer else 0

        # Libérer l'outil lasso
        if hasattr(self, 'lasso_tool') and self.lasso_tool is not None:
            try:
                self.lasso_tool.lassoFinished.disconnect(self._on_lasso_finished)
            except TypeError:
                pass
            self.lasso_tool.deleteLater()
            self.lasso_tool = None

        # Supprimer le panneau flottant
        if hasattr(self, '_lasso_panel') and self._lasso_panel:
            self._lasso_panel.setParent(None)
            self._lasso_panel.deleteLater()
            self._lasso_panel = None

        # Restaurer l'outil carte précédent
        if self.previous_tool:
            self.canvas.setMapTool(self.previous_tool)

        # Mettre à jour le label (le lasso reste en mode 3)
        self.lbl_lasso.setText(
            self.tr('lasso_ok').format(n=n)
        )

        self.show()
        self.raise_()

    def _show_advanced(self):
        dlg = _AdvancedDialog(self.overlap_pct, self.margin_pct, self.dpi, self.lang, self)
        if dlg.exec_():
            self.overlap_pct = dlg.sp_overlap.value()
            self.margin_pct = dlg.sp_margin.value()
            self.dpi = dlg.sp_dpi.value()
            new_lang = LANGS[dlg.combo_lang.currentIndex()]
            if new_lang != self.lang:
                self.lang = new_lang
                self.combo_lang.setCurrentIndex(LANGS.index(self.lang))

    def _get_scale(self):
        if self.combo_scale.currentIndex() == 4:
            return self.spin_custom.value()
        return int(self.combo_scale.currentText().split('/')[1])

    # ------------------------------------------------------- STYLE GRILLE
    def _style_grid_layer(self, layer, scale):
        from qgis.core import (
            QgsFillSymbol, QgsPalLayerSettings,
            QgsVectorLayerSimpleLabeling, QgsTextFormat, QgsProperty
        )
        from qgis.PyQt.QtGui import QFont

        symbol = QgsFillSymbol.createSimple({
            'color': '0,0,0,0',
            'outline_color': '0,0,0,255',
            'outline_width': '0.5',
        })
        layer.renderer().setSymbol(symbol)

        pal = QgsPalLayerSettings()
        pal.fieldName = 'reference'
        pal.enabled = True
        try:
            from qgis.core import Qgis
            pal.placement = Qgis.LabelPlacement.OverPoint
            pal.quadOffset = Qgis.LabelQuadrantPosition.AboveLeft
        except (AttributeError, ImportError):
            pal.placement = QgsPalLayerSettings.OverPoint
            pal.quadOffset = QgsPalLayerSettings.QuadrantAboveLeft

        pal.dataDefinedProperties().setProperty(
            QgsPalLayerSettings.PositionX,
            QgsProperty.fromExpression('x_max($geometry)')
        )
        pal.dataDefinedProperties().setProperty(
            QgsPalLayerSettings.PositionY,
            QgsProperty.fromExpression('y_min($geometry)')
        )

        pal.scaleVisibility = True
        pal.minimumScale = scale

        fmt = QgsTextFormat()
        fmt.setFont(QFont('Arial', 8, QFont.Bold))
        fmt.setSize(8)
        pal.setFormat(fmt)

        layer.setLabeling(QgsVectorLayerSimpleLabeling(pal))
        layer.setLabelsEnabled(True)
        layer.triggerRepaint()

    # ------------------------------------------------------- GENERATION
    def _cancel_generation(self):
        """Demande l'annulation de la génération en cours."""
        self._cancelled = True
        self.btn_cancel.setEnabled(False)

    def _generation_cleanup(self):
        """Restaure l'UI après génération (succès, erreur ou annulation)."""
        self.btn_gen.setEnabled(True)
        self.btn_cancel.setVisible(False)
        self._pulse_timer.stop()

    def _start_pulse(self):
        """Lance une animation pulsante sur la barre de progression."""
        if not hasattr(self, '_pulse_timer'):
            self._pulse_timer = QTimer(self)
            self._pulse_timer.setInterval(80)
            self._pulse_dir = 1
            self._pulse_timer.timeout.connect(self._pulse_tick)
        self._pulse_timer.start()

    def _pulse_tick(self):
        """Micro-incrémentation pour montrer que le plugin travaille."""
        base = self._pulse_base
        current = self.progress.value()
        ceiling = min(base + self._pulse_range, 100)
        if current >= ceiling:
            self._pulse_dir = -1
        elif current <= base:
            self._pulse_dir = 1
        self.progress.setValue(current + self._pulse_dir)

    def _set_progress(self, value, pulse_range=0):
        """Fixe la progression et configure l'animation pulsante."""
        self.progress.setValue(value)
        self._pulse_base = value
        self._pulse_range = pulse_range
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

    def _next_step(self):
        """Planifie l'exécution de la prochaine étape (rend la main à Qt)."""
        QTimer.singleShot(0, self._run_step)

    def _generate(self):
        """Valide les paramètres puis lance la génération pas-à-pas."""
        with_index = self.chk_index.isChecked()
        with_pdf = self.chk_pdf.isChecked()

        layer = self.combo_layer.currentLayer()
        if not layer:
            QMessageBox.warning(self, self.tr('title_error'), self.tr('err_layer'))
            return

        crs = QgsProject.instance().crs()
        if not crs.isValid():
            QMessageBox.warning(self, self.tr('title_error'),
                                "Project CRS is not defined. Please set a valid CRS.")
            return

        extent_mode = self.bg_extent.checkedId()
        if extent_mode == 1:
            # Emprise de la carte : capturer l'emprise actuelle du canevas
            canvas_ext = self.canvas.extent()
            if canvas_ext.isNull() or canvas_ext.isEmpty():
                QMessageBox.warning(self, self.tr('title_error'), self.tr('err_extent'))
                return
            self.drawn_extent = canvas_ext
        if extent_mode == 2 and self.drawn_extent is None:
            QMessageBox.warning(self, self.tr('title_error'), self.tr('err_extent'))
            return

        out_dir = None
        field_name = None
        use_ban = False
        use_osm = False

        if with_index or with_pdf:
            out_dir = self.txt_dir.text().strip()
            if not out_dir or not Path(out_dir).is_dir():
                QMessageBox.warning(self, self.tr('title_error'), self.tr('err_dir'))
                return

        if with_index:
            use_ban = self.radio_ban.isChecked()
            use_osm = self.radio_osm.isChecked()
            field_name = None if (use_ban or use_osm) else self.combo_field.currentText()
            if not use_ban and not use_osm and not field_name:
                QMessageBox.warning(self, self.tr('title_error'), self.tr('err_field'))
                return

        if self.combo_format.currentIndex() == 12:  # Custom
            fmt = 'Custom'
            custom_w = self.spin_custom_w.value()
            custom_h = self.spin_custom_h.value()
            from . import grid_generator, atlas_creator, pdf_exporter
            grid_generator.FORMATS_MM['Custom'] = (custom_w, custom_h)
            atlas_creator.FORMATS_MM['Custom'] = (custom_w, custom_h)
            pdf_exporter.FORMATS_MM['Custom'] = (custom_w, custom_h)
        else:
            fmt = self.combo_format.currentText()
        orient = 'paysage' if self.combo_orient.currentIndex() == 0 else 'portrait'
        scale = self._get_scale()

        # Stocker le contexte pour les étapes
        self._ctx = {
            'layer': layer, 'crs': crs, 'fmt': fmt, 'orient': orient,
            'scale': scale, 'extent_mode': extent_mode,
            'out_dir': out_dir, 'field_name': field_name,
            'use_ban': use_ban, 'use_osm': use_osm,
            'with_index': with_index, 'with_pdf': with_pdf,
            'grid_layer': None, 'sorted_index': None, 'layout': None,
        }
        self._cancelled = False
        self._step = 0

        # UI : mode exécution
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.btn_gen.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)
        self._start_pulse()

        self._next_step()

    def _run_step(self):
        """Exécute l'étape courante puis planifie la suivante."""
        if self._cancelled:
            self._log(self.tr('st_cancelled'))
            self._generation_cleanup()
            return

        ctx = self._ctx
        try:
            # ── Étape 0 : Génération de la grille ──
            if self._step == 0:
                grid_path = os.path.join(ctx['out_dir'], 'grille_feuillets.geojson') if ctx['out_dir'] else 'grille_feuillets.geojson'
                self._log(self.tr('st_grid'), grid_path)
                self._set_progress(2, pulse_range=20)

                gen = GridGenerator(
                    layer=ctx['layer'], crs=ctx['crs'],
                    format_name=ctx['fmt'],
                    orientation=ctx['orient'], scale=ctx['scale'],
                    overlap_pct=self.overlap_pct,
                    margin_pct=self.margin_pct,
                    extent_mode=ctx['extent_mode'],
                    drawn_extent=self.drawn_extent
                )
                ctx['grid_layer'] = gen.generate(ctx['out_dir'])
                self._set_progress(25)

                if not ctx['grid_layer'] or ctx['grid_layer'].featureCount() == 0:
                    QMessageBox.warning(self, self.tr('title_warning'), self.tr('warn_empty'))
                    self._generation_cleanup()
                    return

                self._step = 1
                self._next_step()

            # ── Étape 1 : Géocodage (si index demandé) ──
            elif self._step == 1:
                if ctx['with_index']:
                    self._log(self.tr('st_streets'))
                    self._set_progress(28, pulse_range=25)

                    source = 'ban' if ctx['use_ban'] else ('osm' if ctx['use_osm'] else 'field')
                    geocoder = Geocoder(
                        layer=ctx['layer'], crs=ctx['crs'],
                        field_name=ctx['field_name'],
                        source=source,
                        grid_layer=ctx['grid_layer'] if (ctx['use_osm'] or ctx['use_ban']) else None
                    )
                    streets = geocoder.get_street_names()
                    self._set_progress(55)
                    ctx['_streets'] = streets

                self._step = 2
                self._next_step()

            # ── Étape 2 : Index HTML (si index demandé) ──
            elif self._step == 2:
                if ctx['with_index']:
                    index_path = os.path.join(ctx['out_dir'], 'index_objets.html')
                    self._log(self.tr('st_index'), index_path)
                    self._set_progress(57, pulse_range=6)

                    col_title = ctx['field_name'] if ctx['field_name'] else None
                    idx = IndexGenerator(
                        conduite_layer=ctx['layer'],
                        grid_layer=ctx['grid_layer'],
                        street_names=ctx['_streets'],
                        crs=ctx['crs'],
                        format_name=ctx['fmt'],
                        orientation=ctx['orient'],
                        column_title=col_title
                    )
                    _, ctx['sorted_index'] = idx.generate(ctx['out_dir'])

                self._set_progress(65)
                self._step = 3
                self._next_step()

            # ── Étape 3 : Mise en page + Atlas ──
            elif self._step == 3:
                self._log(self.tr('st_layout'))
                self._set_progress(66, pulse_range=3)

                project = QgsProject.instance()
                for old in project.mapLayersByName('Grille feuillets'):
                    project.removeMapLayer(old)
                project.addMapLayer(ctx['grid_layer'])
                self._style_grid_layer(ctx['grid_layer'], ctx['scale'])

                ac = AtlasCreator(
                    iface=self.iface,
                    grid_layer=ctx['grid_layer'],
                    format_name=ctx['fmt'],
                    orientation=ctx['orient'],
                    scale=ctx['scale'],
                )
                ctx['layout'] = ac.create()
                self._set_progress(70)

                self._step = 4
                self._next_step()

            # ── Étape 4 : Export PDF (si demandé) ──
            elif self._step == 4:
                if ctx['with_pdf']:
                    pdf_out = os.path.join(ctx['out_dir'], 'atlas_complet.pdf')
                    self._log(self.tr('st_pdf'), pdf_out)
                    self._set_progress(71, pulse_range=0)

                    from .pdf_exporter import PdfExporter
                    pdf_title = self.txt_pdf_title.text().strip() or self.tr('pdf_title_ph')
                    col_title = ctx['field_name'] if ctx['field_name'] else None
                    exporter = PdfExporter(
                        layout=ctx['layout'],
                        grid_layer=ctx['grid_layer'],
                        index_data=ctx['sorted_index'],
                        output_dir=ctx['out_dir'],
                        title=pdf_title,
                        format_name=ctx['fmt'],
                        orientation=ctx['orient'],
                        scale=ctx['scale'],
                        dpi=self.dpi,
                        lang=self.lang,
                        progress_callback=lambda v: self._set_progress(v),
                        log_callback=lambda msg, fp=None: self._log(msg, fp),
                        column_title=col_title,
                    )
                    exporter.export()

                self._step = 5
                self._next_step()

            # ── Étape 5 : Terminé ──
            elif self._step == 5:
                self._set_progress(100)
                self._log(self.tr('st_done'))
                self._generation_cleanup()

                out_dir = ctx['out_dir']
                msg = QMessageBox(QMessageBox.Information,
                                  self.tr('title_success'),
                                  _success_body(self.lang,
                                                ctx['grid_layer'].featureCount(),
                                                out_dir,
                                                ctx['with_index'],
                                                ctx['with_pdf']),
                                  QMessageBox.Ok, self)
                if out_dir:
                    btn_folder = msg.addButton(
                        self.tr('btn_open_folder'), QMessageBox.ActionRole)
                msg.exec_()
                if out_dir and msg.clickedButton() == btn_folder:
                    from qgis.PyQt.QtCore import QUrl
                    from qgis.PyQt.QtGui import QDesktopServices
                    QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._generation_cleanup()
            QMessageBox.critical(self, self.tr('title_error'), str(e))


# ═══════════════════════════════════════════════════════════════════
class _AdvancedDialog(QDialog):

    _CARD_STYLE = """
        QFrame {{
            background: white;
            border: 1px solid #dde1e7;
            border-radius: 8px;
        }}
    """
    _SPIN_STYLE = """
        QDoubleSpinBox {{
            border: 1px solid #c8cdd5;
            border-radius: 5px;
            padding: 5px 8px;
            font-size: 10pt;
            min-width: 80px;
        }}
        QDoubleSpinBox:focus {{
            border-color: #2980b9;
        }}
    """

    def __init__(self, overlap, margin, dpi, lang, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TR['adv_title'][lang])
        self.setFixedWidth(440)
        self.setStyleSheet("QDialog { background: #f0f2f5; }")

        main = QVBoxLayout()
        main.setSpacing(10)
        main.setContentsMargins(16, 16, 16, 16)

        # --- Cartes recouvrement / marge (QDoubleSpinBox, %) ---
        params = [
            ('adv_overlap', 'adv_overlap_desc', overlap),
            ('adv_margin',  'adv_margin_desc',  margin),
        ]
        spins = []
        for key_lbl, key_desc, val in params:
            card = QFrame()
            card.setStyleSheet(self._CARD_STYLE)
            row = QHBoxLayout(card)
            row.setContentsMargins(14, 12, 14, 12)
            row.setSpacing(12)

            text_col = QVBoxLayout()
            text_col.setSpacing(3)
            lbl = QLabel(TR[key_lbl][lang])
            lbl.setStyleSheet("font-weight: bold; font-size: 9pt; border: none; background: transparent;")
            desc = QLabel(TR[key_desc][lang])
            desc.setStyleSheet("color: #777; font-size: 8pt; border: none; background: transparent;")
            desc.setWordWrap(True)
            text_col.addWidget(lbl)
            text_col.addWidget(desc)

            spin = QDoubleSpinBox()
            spin.setRange(0, 50)
            spin.setValue(val)
            spin.setSuffix(" %")
            spin.setDecimals(1)
            spin.setStyleSheet(self._SPIN_STYLE)
            spin.setAlignment(Qt.AlignCenter)

            row.addLayout(text_col, 1)
            row.addWidget(spin, 0, Qt.AlignVCenter)
            main.addWidget(card)
            spins.append(spin)

        self.sp_overlap, self.sp_margin = spins

        # --- Carte DPI (QSpinBox, entier) ---
        card = QFrame()
        card.setStyleSheet(self._CARD_STYLE)
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        lbl = QLabel(TR['adv_dpi'][lang])
        lbl.setStyleSheet("font-weight: bold; font-size: 9pt; border: none; background: transparent;")
        desc = QLabel(TR['adv_dpi_desc'][lang])
        desc.setStyleSheet("color: #777; font-size: 8pt; border: none; background: transparent;")
        desc.setWordWrap(True)
        text_col.addWidget(lbl)
        text_col.addWidget(desc)

        self.sp_dpi = QSpinBox()
        self.sp_dpi.setRange(96, 600)
        self.sp_dpi.setValue(dpi)
        self.sp_dpi.setSuffix(" dpi")
        self.sp_dpi.setStyleSheet(
            "QSpinBox { border:1px solid #c8cdd5; border-radius:5px;"
            " padding:5px 8px; font-size:10pt; min-width:80px; }"
            "QSpinBox:focus { border-color:#2980b9; }"
        )
        self.sp_dpi.setAlignment(Qt.AlignCenter)

        row.addLayout(text_col, 1)
        row.addWidget(self.sp_dpi, 0, Qt.AlignVCenter)
        main.addWidget(card)

        # --- Carte Langue ---
        card = QFrame()
        card.setStyleSheet(self._CARD_STYLE)
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        lbl = QLabel(TR['adv_lang'][lang])
        lbl.setStyleSheet("font-weight: bold; font-size: 9pt; border: none; background: transparent;")
        desc = QLabel(TR['adv_lang_desc'][lang])
        desc.setStyleSheet("color: #777; font-size: 8pt; border: none; background: transparent;")
        desc.setWordWrap(True)
        text_col.addWidget(lbl)
        text_col.addWidget(desc)

        self.combo_lang = QComboBox()
        for code in LANGS:
            flag = LANG_FLAGS.get(code, '')
            self.combo_lang.addItem(f"{flag}  {LANG_LABELS[code]}", code)
        self.combo_lang.setCurrentIndex(LANGS.index(lang))
        self.combo_lang.setStyleSheet("""
            QComboBox {
                border: 1px solid #c8cdd5;
                border-radius: 6px;
                padding: 5px 10px;
                font-size: 10pt;
                min-width: 140px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ffffff, stop:1 #f5f6f8);
                color: #2c3e50;
            }
            QComboBox:hover {
                border-color: #2980b9;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ffffff, stop:1 #eaf2f8);
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 6px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #c8cdd5;
                border-radius: 4px;
                background: white;
                selection-background-color: #eaf2f8;
                selection-color: #2c3e50;
                padding: 4px;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                padding: 6px 10px;
                min-height: 26px;
            }
        """)

        row.addLayout(text_col, 1)
        row.addWidget(self.combo_lang, 0, Qt.AlignVCenter)
        main.addWidget(card)

        # Séparateur
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border: none; border-top: 1px solid #dde1e7;")
        main.addWidget(sep)

        # Boutons
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Ok).setStyleSheet(
            "QPushButton { background:#27ae60; color:#fff; border:none;"
            " border-radius:4px; padding:6px 22px; font-size:9pt; }"
            "QPushButton:hover { background:#219a52; }"
        )
        bb.button(QDialogButtonBox.Cancel).setStyleSheet(
            "QPushButton { border:1px solid #bbb; border-radius:4px;"
            " padding:6px 16px; font-size:9pt; }"
            "QPushButton:hover { background:#e8e8e8; }"
        )
        main.addWidget(bb)

        self.setLayout(main)


# Alias pour compatibilité avec plugin.py si nécessaire
ConduiteAtlasDialog = AtlasDialog
