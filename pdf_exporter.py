import os
import math
import tempfile
from datetime import date

from qgis.core import (
    QgsLayoutExporter, QgsProject, QgsPrintLayout, QgsLayoutItemMap,
    QgsLayoutItemLabel, QgsLayoutItemScaleBar, QgsLayoutPoint,
    QgsLayoutSize, QgsUnitTypes, QgsRectangle, QgsTextFormat
)
from qgis.PyQt.QtCore import QMarginsF, QSizeF, Qt
from qgis.PyQt.QtGui import QTextDocument, QPainter, QFont, QColor
try:
    from qgis.PyQt.QtGui import QPageSize, QPageLayout
except ImportError:
    from qgis.PyQt.QtCore import QPageSize, QPageLayout
from qgis.PyQt.QtPrintSupport import QPrinter
from qgis.PyQt.QtWidgets import QApplication


FORMATS_MM = {
    'A4': (210, 297),
    'A3': (297, 420),
    'A0': (841, 1189),
    'A1': (594, 841),
    'A2': (420, 594),
    'A5': (148, 210),
    'Letter': (216, 279),
    'Legal': (216, 356),
    'Tabloid': (279, 432),
    'ANSI C': (432, 559),
    'ANSI D': (559, 864),
    'ANSI E': (864, 1118),
}

_TR = {
    'cover_scale':   {'fr': "Échelle",           'en': "Scale",
                      'es': "Escala",            'pt': "Escala",        'de': "Maßstab"},
    'cover_format':  {'fr': "Format",             'en': "Format",
                      'es': "Formato",            'pt': "Formato",      'de': "Format"},
    'cover_sheets':  {'fr': "Feuillets",          'en': "Sheets",
                      'es': "Hojas",              'pt': "Folhas",       'de': "Blätter"},
    'cover_date':    {'fr': "Date",               'en': "Date",
                      'es': "Fecha",              'pt': "Data",         'de': "Datum"},
    'idx_title':     {'fr': "Index géographique",  'en': "Geographic index",
                      'es': "Índice geográfico",   'pt': "Índice geográfico",
                      'de': "Geographisches Verzeichnis"},
    'idx_street':    {'fr': "Nom de rue",          'en': "Street name",
                      'es': "Nombre de calle",     'pt': "Nome da rua",
                      'de': "Straßenname"},
    'idx_sheets':    {'fr': "Feuillets",           'en': "Sheets",
                      'es': "Hojas",               'pt': "Folhas",      'de': "Blätter"},
    'orient_p':      {'fr': "Portrait",            'en': "Portrait",
                      'es': "Vertical",            'pt': "Retrato",     'de': "Hochformat"},
    'orient_l':      {'fr': "Paysage",             'en': "Landscape",
                      'es': "Horizontal",          'pt': "Paisagem",    'de': "Querformat"},
    'overview':      {'fr': "Plan d'ensemble",     'en': "Overview map",
                      'es': "Plano general",       'pt': "Plano geral",
                      'de': "Übersichtskarte"},
}


class PdfExporter:
    """Génère un PDF complet : page de garde + index + atlas + page blanche."""

    def __init__(self, layout, grid_layer, index_data, output_dir,
                 title, format_name, orientation, scale, dpi, lang,
                 progress_callback=None, log_callback=None):
        self.layout = layout
        self.grid_layer = grid_layer
        self.index_data = index_data          # {street: [refs]} ou None
        self.output_dir = output_dir
        self.title = title
        self.format_name = format_name
        self.orientation = orientation
        self.scale = scale
        self.dpi = dpi
        self.lang = lang
        self.progress_cb = progress_callback
        self.log_cb = log_callback
        self._tmp_files = []

    def _tr(self, key):
        return _TR[key][self.lang]

    # ---------------------------------------------------------------- sizes
    def _page_size_mm(self):
        w, h = FORMATS_MM[self.format_name]
        if self.orientation == 'paysage':
            w, h = h, w
        return w, h

    def _make_printer(self, path, w_mm, h_mm):
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        page_size = QPageSize(QSizeF(w_mm, h_mm), QPageSize.Millimeter)
        printer.setPageSize(page_size)
        printer.setPageMargins(10, 10, 10, 10, QPrinter.Millimeter)
        return printer

    def _progress(self, value):
        if self.progress_cb:
            self.progress_cb(value)

    def _log(self, msg, filepath=None):
        if self.log_cb:
            self.log_cb(msg, filepath)

    # ---------------------------------------------------------------- atlas refs in order
    def _atlas_ref_order(self):
        """Retourne la liste ordonnée des références atlas (ordre des feuillets)."""
        atlas = self.layout.atlas()
        atlas.updateFeatures()
        refs = []
        for i in range(atlas.count()):
            atlas.seekTo(i)
            feat = atlas.coverageLayer().getFeature(atlas.currentFeatureNumber())
            ref = feat['reference'] if feat.isValid() else f"P{i+1}"
            refs.append(ref)
        return refs

    # ---------------------------------------------------------------- cover
    def _generate_cover(self, w_mm, h_mm, num_sheets):
        path = os.path.join(self.output_dir, '_cover.pdf')
        self._tmp_files.append(path)

        orient_label = self._tr('orient_l') if self.orientation == 'paysage' else self._tr('orient_p')
        today = date.today().strftime('%d/%m/%Y')

        html = f'''<html><body style="margin:0; font-family:Arial, Helvetica, sans-serif;">
<table width="100%" height="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" valign="middle">
    <div style="text-align:center;">
        <div style="font-size:280pt; font-weight:bold; color:#2c3e50;
                    margin-bottom:400px; line-height:1.3;">
            {self._esc(self.title)}
        </div>
        <div style="width:2000px; height:20px; background:#2980b9;
                    margin:0 auto 400px;"></div>
        <table cellpadding="60" cellspacing="0"
               style="margin:0 auto; font-size:120pt; color:#555;">
            <tr>
                <td style="text-align:right; font-weight:bold; padding-right:120px;">
                    {self._tr('cover_scale')}</td>
                <td>1 / {self.scale}</td>
            </tr>
            <tr>
                <td style="text-align:right; font-weight:bold; padding-right:120px;">
                    {self._tr('cover_format')}</td>
                <td>{self.format_name} {orient_label}</td>
            </tr>
            <tr>
                <td style="text-align:right; font-weight:bold; padding-right:120px;">
                    {self._tr('cover_sheets')}</td>
                <td>{num_sheets}</td>
            </tr>
            <tr>
                <td style="text-align:right; font-weight:bold; padding-right:120px;">
                    {self._tr('cover_date')}</td>
                <td>{today}</td>
            </tr>
        </table>
    </div>
</td></tr>
</table>
</body></html>'''

        printer = self._make_printer(path, w_mm, h_mm)
        doc = QTextDocument()
        doc.setHtml(html)
        doc.setPageSize(QSizeF(printer.pageRect().size()))
        doc.print_(printer)
        return path

    # ---------------------------------------------------------------- index
    def _generate_index(self, w_mm, h_mm, ref_page_map=None):
        """Génère les pages d'index en 4 colonnes (Rue|Feuillets|Rue|Feuillets).

        - Filtre les rues sans feuillet (« Inconnue » ou liste vide)
        - Tri alphabétique, lecture en colonnes (col 1 puis col 3)
        """
        path = os.path.join(self.output_dir, '_index.pdf')
        self._tmp_files.append(path)

        if not self.index_data:
            return None

        # Filtrer les rues sans feuillet ou nommées "Inconnue"
        filtered = {
            street: refs for street, refs in self.index_data.items()
            if refs and street and street.strip().lower() != 'inconnue'
        }
        if not filtered:
            return None

        # Tri alphabétique
        sorted_items = sorted(filtered.items(), key=lambda x: x[0].lower())

        # Taille du texte : ×10 pour compenser le ratio QPrinter
        body_pt = 120
        title_pt = max(360, int(min(w_mm, h_mm) * 1.70))
        head_pt = body_pt
        pad = max(30, int(body_pt * 0.3))

        # Répartir en 2 colonnes (gauche et droite), lecture verticale
        total = len(sorted_items)
        half = math.ceil(total / 2)
        col_left = sorted_items[:half]
        col_right = sorted_items[half:]

        # Construire les lignes du tableau 4 colonnes
        rows_html = ''
        sep = f'border-left:10px solid #ccc;'
        for i in range(half):
            # Colonne gauche
            street_l, refs_l = col_left[i]
            refs_str_l = ', '.join(self._esc(r) for r in refs_l)

            # Colonne droite (peut être vide si nombre impair)
            if i < len(col_right):
                street_r, refs_r = col_right[i]
                refs_str_r = ', '.join(self._esc(r) for r in refs_r)
            else:
                street_r, refs_str_r = '', ''

            rows_html += (
                f'<tr>'
                f'<td style="padding:{pad}px 60px; border-bottom:8px solid #eee;'
                f' font-size:{body_pt}pt;">'
                f'{self._esc(street_l)}</td>'
                f'<td style="padding:{pad}px 60px; border-bottom:8px solid #eee;'
                f' font-size:{body_pt}pt; color:#2980b9;">{refs_str_l}</td>'
                f'<td style="padding:{pad}px 60px; border-bottom:8px solid #eee;'
                f' {sep} font-size:{body_pt}pt;">'
                f'{self._esc(street_r)}</td>'
                f'<td style="padding:{pad}px 60px; border-bottom:8px solid #eee;'
                f' font-size:{body_pt}pt; color:#2980b9;">{refs_str_r}</td>'
                f'</tr>\n'
            )

        # En-tête 4 colonnes
        th_style = f'padding:{pad+15}px 60px; text-align:left; font-size:{head_pt}pt;'
        header = (
            f'<tr style="background:#2c3e50; color:#fff;">'
            f'<th style="{th_style}">{self._tr("idx_street")}</th>'
            f'<th style="{th_style}">{self._tr("idx_sheets")}</th>'
            f'<th style="{th_style} {sep} border-color:#fff;">{self._tr("idx_street")}</th>'
            f'<th style="{th_style}">{self._tr("idx_sheets")}</th>'
            f'</tr>'
        )

        html = f'''<html><body style="margin:0; font-family:Arial, Helvetica, sans-serif;">
<div style="font-size:{title_pt}pt; font-weight:bold; color:#2c3e50;
            border-bottom:20px solid #2c3e50; padding-bottom:80px;
            margin-bottom:140px;">
    {self._tr('idx_title')}
</div>
<table width="100%" cellpadding="0" cellspacing="0">
<thead>{header}</thead>
<tbody>
{rows_html}
</tbody>
</table>
</body></html>'''

        printer = self._make_printer(path, w_mm, h_mm)
        doc = QTextDocument()
        doc.setHtml(html)
        doc.setPageSize(QSizeF(printer.pageRect().size()))
        doc.print_(printer)

        return path, doc.pageCount()

    # ---------------------------------------------------------------- overview
    def _generate_overview(self, w_mm, h_mm):
        """Crée un plan d'ensemble : carte avec toute la grille + références."""
        path = os.path.join(self.output_dir, '_overview.pdf')
        self._tmp_files.append(path)

        project = QgsProject.instance()
        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName('_overview_tmp')

        # Page au bon format
        page = layout.pageCollection().page(0)
        page.setPageSize(QgsLayoutSize(w_mm, h_mm, QgsUnitTypes.LayoutMillimeters))

        # Marges et zones proportionnelles à la page
        margin_pct = 3.0           # % de la plus petite dimension
        header_pct = 5.0           # % de la hauteur pour le titre
        footer_pct = 4.0           # % de la hauteur pour la barre d'échelle

        ref_dim = min(w_mm, h_mm)
        margin = ref_dim * margin_pct / 100.0
        header_h = h_mm * header_pct / 100.0
        footer_h = h_mm * footer_pct / 100.0

        map_x = margin
        map_y = margin + header_h
        map_w = w_mm - 2 * margin
        map_h = h_mm - 2 * margin - header_h - footer_h

        # ── Carte ──
        map_item = QgsLayoutItemMap(layout)
        map_item.attemptMove(QgsLayoutPoint(
            map_x, map_y, QgsUnitTypes.LayoutMillimeters
        ))
        map_item.attemptResize(QgsLayoutSize(
            map_w, map_h, QgsUnitTypes.LayoutMillimeters
        ))
        # Fixer explicitement les couches visibles (le layout temporaire
        # ne résout pas les couches raster/tuiles comme OSM sinon)
        map_item.setKeepLayerSet(True)
        map_item.setLayers(project.layerTreeRoot().layerOrder())

        # Emprise = grille entière, ajustée au ratio du cadre carte
        extent = self.grid_layer.extent()
        # Ratio du cadre carte sur la page
        map_ratio = map_w / map_h
        # Ratio de l'emprise géographique
        ext_ratio = extent.width() / extent.height() if extent.height() > 0 else 1.0

        if ext_ratio > map_ratio:
            # Emprise plus large que le cadre → ajuster la hauteur
            new_h = extent.width() / map_ratio
            cy = extent.center().y()
            extent = QgsRectangle(
                extent.xMinimum(), cy - new_h / 2,
                extent.xMaximum(), cy + new_h / 2)
        else:
            # Emprise plus haute que le cadre → ajuster la largeur
            new_w = extent.height() * map_ratio
            cx = extent.center().x()
            extent = QgsRectangle(
                cx - new_w / 2, extent.yMinimum(),
                cx + new_w / 2, extent.yMaximum())

        # Ajouter 5% de marge autour
        extent.grow(extent.width() * 0.05)
        map_item.setExtent(extent)

        map_item.setFrameEnabled(True)
        map_item.setFrameStrokeColor(QColor(44, 62, 80))
        from qgis.core import QgsLayoutMeasurement
        map_item.setFrameStrokeWidth(QgsLayoutMeasurement(0.3, QgsUnitTypes.LayoutMillimeters))

        layout.addLayoutItem(map_item)

        # ── Étiquettes centrées occupant 80% du cadre ──
        from qgis.core import (
            QgsPalLayerSettings, QgsVectorLayerSimpleLabeling,
            QgsTextFormat, QgsProperty, QgsPropertyDefinition
        )
        # Sauvegarder l'étiquetage actuel (clone avant remplacement)
        old_labeling = self.grid_layer.labeling().clone() if self.grid_layer.labeling() else None
        old_labels_enabled = self.grid_layer.labelsEnabled()

        # Calculer la taille de police pour que le texte occupe ~80% du cadre
        # On utilise une expression QGIS : taille en mm sur la carte,
        # convertie en points d'affichage via data-defined size.
        # Approche : taille proportionnelle à la hauteur de la cellule dans la carte
        # 80% de la cellule en unités carte → expression sur la géométrie
        pal = QgsPalLayerSettings()
        pal.fieldName = 'reference'
        pal.enabled = True
        pal.scaleVisibility = False

        # Placement centré dans le polygone
        try:
            from qgis.core import Qgis
            pal.placement = Qgis.LabelPlacement.OverPoint
            pal.quadOffset = Qgis.LabelQuadrantPosition.Over
        except (AttributeError, ImportError):
            pal.placement = QgsPalLayerSettings.OverPoint
            pal.quadOffset = QgsPalLayerSettings.QuadrantOver

        fmt = QgsTextFormat()
        fmt.setFont(QFont('Arial', 10, QFont.Bold))
        fmt.setColor(QColor(44, 62, 80, 180))
        # Taille en unités carte (mm sur la carte) pour s'adapter au zoom
        fmt.setSizeUnit(QgsUnitTypes.RenderMapUnits)
        # Taille = 80% de la hauteur de la cellule / nb caractères ajusté
        # Expression : bounds_height * 0.8 / max(length("reference"), 1) * 0.6
        # Simplifié : on utilise 40% de la hauteur du bbox (bon ratio pour 2-3 chars)
        fmt.setSize(10)  # valeur par défaut, surchargée par data-defined
        pal.setFormat(fmt)

        # Data-defined size : 80% de la hauteur de la bbox de chaque cellule
        # divisé par un facteur pour que le texte rentre en largeur aussi
        pal.dataDefinedProperties().setProperty(
            QgsPalLayerSettings.Size,
            QgsProperty.fromExpression(
                'bounds_height($geometry) * 0.8 / max(1.2, length("reference") * 0.55)'
            )
        )

        self.grid_layer.setLabeling(QgsVectorLayerSimpleLabeling(pal))
        self.grid_layer.setLabelsEnabled(True)
        self.grid_layer.triggerRepaint()

        # ── Titre (taille proportionnelle à la page) ──
        # ~4.7% de la hauteur de page → ~14pt pour A4 portrait, ~20pt pour A3
        title_pt = max(8, int(h_mm * 0.047))
        title_label = QgsLayoutItemLabel(layout)
        title_label.setText(self._tr('overview'))
        title_fmt = QgsTextFormat()
        title_fmt.setFont(QFont('Arial', title_pt, QFont.Bold))
        title_fmt.setColor(QColor(44, 62, 80))
        title_label.setTextFormat(title_fmt)
        title_label.attemptMove(QgsLayoutPoint(
            margin, margin, QgsUnitTypes.LayoutMillimeters
        ))
        title_label.attemptResize(QgsLayoutSize(
            map_w, header_h, QgsUnitTypes.LayoutMillimeters
        ))
        title_label.setHAlign(Qt.AlignCenter)
        title_label.setVAlign(Qt.AlignVCenter)
        layout.addLayoutItem(title_label)

        # ── Barre d'échelle (taille proportionnelle) ──
        scalebar_h = max(2, ref_dim * 0.012)
        scalebar_font = max(5, int(ref_dim * 0.033))
        scalebar = QgsLayoutItemScaleBar(layout)
        scalebar.setLinkedMap(map_item)
        scalebar.setStyle('Single Box')
        scalebar.setUnits(QgsUnitTypes.DistanceMeters)
        scalebar.setNumberOfSegments(4)
        scalebar.setNumberOfSegmentsLeft(0)
        scalebar.setHeight(scalebar_h)
        sb_fmt = QgsTextFormat()
        sb_fmt.setFont(QFont('Arial', scalebar_font))
        scalebar.setTextFormat(sb_fmt)
        scalebar.attemptMove(QgsLayoutPoint(
            margin, h_mm - margin - footer_h,
            QgsUnitTypes.LayoutMillimeters
        ))
        layout.addLayoutItem(scalebar)

        # ── Export PDF ──
        exporter = QgsLayoutExporter(layout)
        settings = QgsLayoutExporter.PdfExportSettings()
        settings.dpi = self.dpi
        exporter.exportToPdf(path, settings)

        # Restaurer l'étiquetage original
        if old_labeling:
            self.grid_layer.setLabeling(old_labeling)
        else:
            self.grid_layer.setLabelsEnabled(old_labels_enabled)
        self.grid_layer.triggerRepaint()

        del layout
        return path

    # ---------------------------------------------------------------- blank
    def _generate_blank(self, w_mm, h_mm):
        path = os.path.join(self.output_dir, '_blank.pdf')
        self._tmp_files.append(path)
        printer = self._make_printer(path, w_mm, h_mm)
        painter = QPainter(printer)
        painter.end()
        return path

    # ---------------------------------------------------------------- atlas
    def _export_atlas_pages(self):
        atlas = self.layout.atlas()
        atlas.updateFeatures()
        count = atlas.count()
        pdfs = []

        exporter = QgsLayoutExporter(self.layout)
        settings = QgsLayoutExporter.PdfExportSettings()
        settings.dpi = self.dpi

        for i in range(count):
            atlas.seekTo(i)
            path = os.path.join(self.output_dir, f'_atlas_{i:04d}.pdf')
            self._tmp_files.append(path)
            self._log(f"Feuillet {i+1}/{count}", path)

            result = exporter.exportToPdf(path, settings)
            if result == QgsLayoutExporter.Success:
                pdfs.append(path)

            self._progress(75 + int(20 * (i + 1) / count))
            QApplication.processEvents()

        return pdfs

    # ---------------------------------------------------------------- merge
    def _merge_pdfs(self, pdf_list, output_path, ref_page_map=None):
        """Fusionne les PDF. Tente pypdf puis PyPDF2."""
        try:
            return self._merge_pypdf(pdf_list, output_path, ref_page_map)
        except ImportError:
            pass
        try:
            return self._merge_pypdf2(pdf_list, output_path, ref_page_map)
        except ImportError:
            pass
        # Fallback : pas de fusion possible
        return None

    def _merge_pypdf(self, pdf_list, output_path, ref_page_map):
        from pypdf import PdfWriter, PdfReader

        writer = PdfWriter()

        for pdf_path in pdf_list:
            reader = PdfReader(pdf_path)
            for page in reader.pages:
                writer.add_page(page)

        # Ajouter des signets (bookmarks) navigables dans le panneau PDF
        if ref_page_map:
            # Sections principales
            cover_bm = writer.add_outline_item(
                self._tr('cover_format'), 0)  # page de garde

            idx_start = 1
            if self.index_data:
                writer.add_outline_item(
                    self._tr('idx_title'), idx_start)

            # Plan d'ensemble : juste avant les feuillets atlas
            overview_page = min(ref_page_map.values()) - 1 if ref_page_map else 1
            if overview_page >= 0 and overview_page < len(writer.pages):
                writer.add_outline_item(
                    self._tr('overview'), overview_page)

            # Signets pour chaque feuillet atlas
            atlas_parent = writer.add_outline_item(
                self._tr('idx_sheets'), min(ref_page_map.values()))
            for ref, page_idx in ref_page_map.items():
                if page_idx < len(writer.pages):
                    writer.add_outline_item(
                        ref, page_idx, parent=atlas_parent)

        with open(output_path, 'wb') as f:
            writer.write(f)
        return output_path

    def _merge_pypdf2(self, pdf_list, output_path, ref_page_map):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from PyPDF2 import PdfMerger

        merger = PdfMerger()
        for pdf_path in pdf_list:
            merger.append(pdf_path)

        # Signets navigables
        if ref_page_map:
            try:
                merger.add_outline_item(self._tr('cover_format'), 0)
                if self.index_data:
                    merger.add_outline_item(self._tr('idx_title'), 1)
                overview_page = min(ref_page_map.values()) - 1
                if overview_page >= 0:
                    merger.add_outline_item(self._tr('overview'), overview_page)
                for ref, page_idx in ref_page_map.items():
                    merger.add_outline_item(ref, page_idx)
            except Exception:
                pass

        merger.write(output_path)
        merger.close()
        return output_path

    # ---------------------------------------------------------------- main
    def export(self):
        """Point d'entrée. Retourne le chemin du PDF final.

        Structure du PDF :
          1. Page de garde
          2. Pages d'index (si données)
          3. Plan d'ensemble (1 page)
          4. Feuillets atlas
          5. Page blanche
        """
        w_mm, h_mm = self._page_size_mm()

        # 1) Références atlas dans l'ordre
        self._progress(70)
        atlas_refs = self._atlas_ref_order()
        num_sheets = len(atlas_refs)

        # 2) Page de garde
        self._progress(72)
        self._log("Page de garde", os.path.join(self.output_dir, '_cover.pdf'))
        cover_pdf = self._generate_cover(w_mm, h_mm, num_sheets)

        # 3) Index (si données disponibles)
        index_pdf = None
        index_pages = 0

        if self.index_data:
            self._log("Index géographique", os.path.join(self.output_dir, '_index.pdf'))
            result = self._generate_index(w_mm, h_mm, {})
            if result:
                index_pdf, index_pages = result

        # Calculer ref_page_map pour les signets PDF
        offset = 1 + index_pages + 1  # couverture + index + plan d'ensemble
        ref_page_map = {}
        for i, ref in enumerate(atlas_refs):
            ref_page_map[ref] = offset + i

        self._progress(74)

        # 4) Plan d'ensemble
        self._log("Plan d'ensemble", os.path.join(self.output_dir, '_overview.pdf'))
        overview_pdf = self._generate_overview(w_mm, h_mm)
        self._progress(76)

        # 5) Pages atlas
        atlas_pdfs = self._export_atlas_pages()

        # 6) Page blanche
        self._progress(96)
        blank_pdf = self._generate_blank(w_mm, h_mm)

        # 7) Fusionner
        self._progress(97)
        self._log("Fusion PDF", os.path.join(self.output_dir, 'atlas_complet.pdf'))
        all_pdfs = [cover_pdf]
        if index_pdf:
            all_pdfs.append(index_pdf)
        all_pdfs.append(overview_pdf)
        all_pdfs.extend(atlas_pdfs)
        all_pdfs.append(blank_pdf)

        output_path = os.path.join(self.output_dir, 'atlas_complet.pdf')
        merged = self._merge_pdfs(all_pdfs, output_path, ref_page_map)

        # Nettoyage des fichiers temporaires
        if merged:
            for p in self._tmp_files:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass

        self._progress(100)
        return merged or self.output_dir

    # ---------------------------------------------------------------- utils
    @staticmethod
    def _esc(s):
        return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
