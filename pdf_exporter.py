import os
import math
import time
import platform
import tempfile
from datetime import date
from urllib.parse import urlparse, parse_qs

from qgis.core import (
    QgsLayoutExporter, QgsProject, QgsPrintLayout, QgsLayoutItemMap,
    QgsLayoutItemLabel, QgsLayoutItemScaleBar, QgsLayoutPoint,
    QgsLayoutSize, QgsUnitTypes, QgsRectangle, QgsTextFormat,
    QgsLayoutRenderContext, QgsRasterLayer, QgsVectorLayer,
    QgsNetworkAccessManager, Qgis
)
from qgis.PyQt.QtCore import QMarginsF, QSizeF, Qt, QSettings, QUrl
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


class NetworkMonitor:
    """Espionne QgsNetworkAccessManager pour compter requêtes/octets/erreurs.

    Permet d'identifier les goulots WMS/WMTS/XYZ : nombre de tuiles,
    volume téléchargé, latence moyenne, codes HTTP, hôtes contactés.
    """
    def __init__(self):
        self.requests = 0           # nombre de requêtes lancées
        self.finished = 0           # nombre terminées
        self.errors = 0             # erreurs réseau
        self.bytes_total = 0        # octets téléchargés
        self.from_cache = 0         # réponses servies depuis le cache
        self.hosts = {}             # hôte -> nombre de requêtes
        self.codes = {}             # code HTTP -> count
        self.latencies = []         # latences ms (échantillon)
        self._pending = {}          # id reply -> t_start
        self._nam = None
        self._connected = False

    def start(self):
        try:
            self._nam = QgsNetworkAccessManager.instance()
            self._nam.requestAboutToBeCreated.connect(self._on_request)
            self._nam.finished.connect(self._on_finished)
            self._connected = True
        except Exception:
            self._connected = False

    def stop(self):
        if not self._connected or not self._nam:
            return
        try:
            self._nam.requestAboutToBeCreated.disconnect(self._on_request)
            self._nam.finished.disconnect(self._on_finished)
        except (TypeError, RuntimeError):
            pass
        self._connected = False

    def snapshot(self):
        """Retourne un dict des compteurs courants (pour calcul delta)."""
        return {
            'requests': self.requests,
            'finished': self.finished,
            'errors': self.errors,
            'bytes': self.bytes_total,
            'cache': self.from_cache,
        }

    def delta_str(self, before):
        """Différence depuis snapshot — string lisible."""
        dr = self.requests - before['requests']
        db = self.bytes_total - before['bytes']
        dc = self.from_cache - before['cache']
        de = self.errors - before['errors']
        if dr == 0:
            return "réseau: 0 req"
        parts = [f"{dr} req"]
        if dc:
            parts.append(f"{dc} cache")
        if db:
            parts.append(_fmt_bytes(db))
        if de:
            parts.append(f"⚠ {de} erreurs")
        return "réseau: " + ", ".join(parts)

    def _on_request(self, params):
        self.requests += 1
        try:
            url = params.request().url()
            host = url.host() or '?'
            self.hosts[host] = self.hosts.get(host, 0) + 1
        except Exception:
            pass

    def _on_finished(self, reply_content):
        self.finished += 1
        try:
            # API moderne : QgsNetworkReplyContent
            err = reply_content.error()
            if err != 0:
                self.errors += 1
            # Code HTTP
            attr = reply_content.attribute(0)  # HttpStatusCodeAttribute = 0
            if attr is not None:
                code = int(attr) if not isinstance(attr, int) else attr
                self.codes[code] = self.codes.get(code, 0) + 1
            # Taille
            content = reply_content.content()
            if content:
                self.bytes_total += len(content)
            # Cache hit ?
            from_cache_attr = reply_content.attribute(3)  # SourceIsFromCacheAttribute
            if from_cache_attr:
                self.from_cache += 1
        except Exception:
            pass

    def summary(self):
        """Résumé final formaté pour log."""
        lines = []
        lines.append(f"  • Requêtes totales   : {self.requests}")
        lines.append(f"  • Réponses terminées : {self.finished}")
        if self.from_cache:
            ratio = 100 * self.from_cache / max(1, self.finished)
            lines.append(f"  • Servies par cache  : {self.from_cache} ({ratio:.0f}%)")
        lines.append(f"  • Volume téléchargé  : {_fmt_bytes(self.bytes_total)}")
        if self.errors:
            lines.append(f"  • ⚠ Erreurs réseau   : {self.errors}")
        if self.hosts:
            top = sorted(self.hosts.items(), key=lambda x: -x[1])[:5]
            lines.append("  • Hôtes contactés (top 5) :")
            for host, n in top:
                lines.append(f"      - {host} : {n} req")
        if self.codes:
            codes_str = ", ".join(f"{c}: {n}" for c, n in sorted(self.codes.items()))
            lines.append(f"  • Codes HTTP         : {codes_str}")
        return "\n".join(lines)


def _fmt_bytes(n):
    """Octets → string lisible (KB/MB/GB)."""
    for unit in ('o', 'Ko', 'Mo', 'Go'):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}" if unit != 'o' else f"{n} {unit}"
        n /= 1024
    return f"{n:.1f} To"


def _detect_provider_type(layer):
    """Classifie une couche : WMS / WMTS / XYZ / WFS / Raster local / Vecteur / …"""
    if layer is None:
        return "?"
    try:
        provider = layer.providerType()
    except Exception:
        provider = ""
    if provider == 'wms':
        # 'wms' couvre WMS, WMTS et XYZ → inspecter l'URI
        try:
            src = layer.source()
            if 'type=xyz' in src.lower():
                return 'XYZ'
            if 'type=wmts' in src.lower() or 'wmts' in src.lower():
                return 'WMTS'
            return 'WMS'
        except Exception:
            return 'WMS'
    if provider == 'wfs':
        return 'WFS'
    if isinstance(layer, QgsRasterLayer):
        return 'Raster'
    if isinstance(layer, QgsVectorLayer):
        return f"Vecteur ({layer.featureCount()} entités)"
    return provider or "?"


def _extract_wms_url(layer):
    """Extrait l'URL serveur d'une couche WMS/WMTS/XYZ pour log."""
    try:
        src = layer.source()
        for part in src.split('&'):
            if part.lower().startswith('url='):
                from urllib.parse import unquote
                return unquote(part[4:])[:120]
    except Exception:
        pass
    return "(URL inconnue)"


class PdfExporter:
    """Génère un PDF complet : page de garde + index + atlas + page blanche."""

    def __init__(self, layout, grid_layer, index_data, output_dir,
                 title, format_name, orientation, scale, dpi, lang,
                 progress_callback=None, log_callback=None,
                 column_title=None):
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
        self.column_title = column_title or self._tr('idx_street')
        self._tmp_files = []

    def _tr(self, key):
        entry = _TR.get(key)
        if not entry:
            return key
        return entry.get(self.lang, entry.get('en', key))

    # ---------------------------------------------------------------- sizes
    def _page_size_mm(self):
        w, h = FORMATS_MM[self.format_name]
        if self.orientation == 'paysage':
            w, h = h, w
        return w, h

    # Résolution d'impression pour page de garde et index.
    # QPrinter.HighResolution sur Windows = 1200 DPI par défaut :
    # une page A4 = 9 921 × 14 031 px = 139 M pixels à rastériser → lent.
    # À 96 DPI : 794 × 1 123 px = 0,9 M pixels → ~160× plus rapide.
    # Bonus : à 96 DPI les tailles en pt sont "naturelles" (1pt = 1/72")
    # sans aucune compensation nécessaire.
    _PRINTER_DPI = 96

    def _make_printer(self, path, w_mm, h_mm):
        printer = QPrinter(QPrinter.HighResolution)
        printer.setResolution(self._PRINTER_DPI)   # ← force 150 DPI au lieu de 1200
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
        # Callback UI (dialogue QGIS)
        if self.log_cb:
            self.log_cb(msg, filepath)
        # Écriture aussi dans le fichier log à côté du PDF de sortie
        self._log_to_file(msg)

    def _log_to_file(self, msg):
        """Append au fichier atlas_log.txt dans output_dir.
        Le fichier est créé/vidé au début de l'export (_open_log_file).
        """
        if not getattr(self, '_log_path', None):
            return
        try:
            with open(self._log_path, 'a', encoding='utf-8') as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        except OSError:
            pass

    def _open_log_file(self):
        """Initialise le fichier log dans output_dir."""
        try:
            self._log_path = os.path.join(self.output_dir, 'atlas_log.txt')
            with open(self._log_path, 'w', encoding='utf-8') as f:
                f.write(f"=== ATLAS Index Pro — export log ===\n")
                f.write(f"Date : {date.today().isoformat()} "
                        f"{time.strftime('%H:%M:%S')}\n")
                f.write(f"Sortie : {self.output_dir}\n\n")
        except OSError:
            self._log_path = None

    # ---------------------------------------------------------------- timing
    def _step_start(self, label):
        """Marque le début d'une étape chronométrée."""
        self._step_label = label
        self._step_t0 = time.perf_counter()
        self._log(f"▶ {label}…")

    def _step_end(self, extra=""):
        """Log la fin de l'étape précédente avec son temps écoulé."""
        if not hasattr(self, '_step_t0'):
            return
        dt = time.perf_counter() - self._step_t0
        suffix = f" — {extra}" if extra else ""
        self._log(f"✓ {self._step_label} : {self._fmt_dur(dt)}{suffix}")
        self._step_t0 = None

    @staticmethod
    def _fmt_dur(seconds):
        """Format lisible : '1m 23s' ou '4.2s' ou '230ms'."""
        if seconds < 1:
            return f"{int(seconds * 1000)}ms"
        if seconds < 60:
            return f"{seconds:.1f}s"
        m, s = divmod(seconds, 60)
        return f"{int(m)}m {int(s)}s"

    # ---------------------------------------------------------------- diagnostics
    def _log_system_info(self):
        """Inventaire système / QGIS / projet — utile pour identifier le contexte."""
        try:
            import os as _os
            try:
                qgis_ver = Qgis.QGIS_VERSION
            except Exception:
                qgis_ver = "?"
            s = QSettings()
            self._log("┌─ Contexte système ──")
            self._log(f"│  QGIS              : {qgis_ver}")
            self._log(f"│  OS                : {platform.system()} {platform.release()}")
            self._log(f"│  CPU               : {_os.cpu_count() or '?'} cœurs")
            self._log(f"│  Rendu parallèle   : {s.value('/qgis/parallel_rendering', True, bool)}")
            self._log(f"│  Threads max       : {s.value('/qgis/max_threads', -1, int)}")
            cache = s.value('/cache/size', 50 * 1024 * 1024, int)
            self._log(f"│  Cache réseau      : {_fmt_bytes(cache)}")
            self._log("└──")
        except Exception as e:
            self._log(f"(info système indisponible : {e})")

    def _log_export_params(self, w_mm, h_mm, num_sheets):
        """Paramètres d'export : format, DPI, résolution pixel, échelle."""
        try:
            # Pixels par feuillet à ce DPI
            px_w = int(w_mm / 25.4 * self.dpi)
            px_h = int(h_mm / 25.4 * self.dpi)
            megapix = (px_w * px_h) / 1_000_000
            # Couverture terrain (m × m) à l'échelle 1:N
            ground_w = (w_mm / 1000.0) * self.scale
            ground_h = (h_mm / 1000.0) * self.scale
            self._log("┌─ Paramètres export ──")
            self._log(f"│  Format            : {self.format_name} {self.orientation} "
                      f"({w_mm:.0f}×{h_mm:.0f} mm)")
            self._log(f"│  Échelle           : 1:{self.scale}")
            self._log(f"│  Couverture/page   : {ground_w:.0f}×{ground_h:.0f} m")
            self._log(f"│  DPI               : {self.dpi}")
            self._log(f"│  Pixels/page       : {px_w}×{px_h} ({megapix:.1f} Mpx)")
            self._log(f"│  Nb feuillets      : {num_sheets}")
            self._log(f"│  Total pixels      : {megapix * num_sheets:.0f} Mpx")
            self._log("└──")
        except Exception as e:
            self._log(f"(params indisponibles : {e})")

    def _log_layer_inventory(self):
        """Liste les couches visibles avec type, provider, source — repère WMS lents."""
        try:
            project = QgsProject.instance()
            root = project.layerTreeRoot()
            visible = [n.layer() for n in root.findLayers()
                       if n.isVisible() and n.layer() is not None]
            self._log(f"┌─ Couches visibles ({len(visible)}) ──")
            wms_count = 0
            for layer in visible:
                kind = _detect_provider_type(layer)
                marker = "🌐" if kind in ('WMS', 'WMTS', 'XYZ', 'WFS') else "  "
                self._log(f"│  {marker} [{kind:18s}] {layer.name()}")
                if kind in ('WMS', 'WMTS', 'XYZ'):
                    wms_count += 1
                    url = _extract_wms_url(layer)
                    self._log(f"│       ↳ {url}")
                    # Format de tuile si dispo
                    try:
                        src = layer.source()
                        for key in ('format=', 'tileMatrixSet=', 'crs='):
                            for part in src.split('&'):
                                if part.lower().startswith(key):
                                    self._log(f"│       ↳ {part}")
                    except Exception:
                        pass
            if wms_count:
                self._log(f"│  → {wms_count} couche(s) réseau (impact direct sur la vitesse)")
            self._log("└──")
        except Exception as e:
            self._log(f"(inventaire couches indisponible : {e})")

    def _log_project_info(self):
        """CRS projet + emprise grille."""
        try:
            project = QgsProject.instance()
            crs = project.crs()
            self._log(f"  CRS projet         : {crs.authid()} ({crs.description()})")
            self._log(f"  Unités carte       : {QgsUnitTypes.toString(crs.mapUnits())}")
            extent = self.grid_layer.extent()
            self._log(f"  Emprise grille     : {extent.width():.0f}×{extent.height():.0f} "
                      f"unités carte")
            self._log(f"  Couche grille      : {self.grid_layer.featureCount()} cellules")
        except Exception as e:
            self._log(f"(info projet indisponible : {e})")

    # ---------------------------------------------------------------- atlas refs in order
    def _atlas_ref_order(self):
        """Retourne la liste ordonnée des références atlas (ordre des feuillets).
        Utilise le cache si déjà calculé (évite double itération).
        """
        if hasattr(self, '_cached_refs'):
            return self._cached_refs
        atlas = self.layout.atlas()
        atlas.updateFeatures()
        refs = []
        for i in range(atlas.count()):
            atlas.seekTo(i)
            feat = atlas.coverageLayer().getFeature(atlas.currentFeatureNumber())
            ref = feat['reference'] if feat.isValid() else f"P{i+1}"
            refs.append(ref)
        self._cached_refs = refs
        return refs

    # ---------------------------------------------------------------- cover
    def _generate_cover(self, w_mm, h_mm, num_sheets):
        path = os.path.join(self.output_dir, '_cover.pdf')
        self._tmp_files.append(path)

        orient_label = self._tr('orient_l') if self.orientation == 'paysage' else self._tr('orient_p')
        today = date.today().strftime('%d/%m/%Y')

        # Tailles naturelles pour 96 DPI : pas de compensation nécessaire
        # (ratio QPrinter/screen = 1 → pt = pt réels)
        html = f'''<html><body style="margin:0; font-family:Arial, Helvetica, sans-serif;">
<table width="100%" height="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" valign="middle">
    <div style="text-align:center;">
        <div style="font-size:36pt; font-weight:bold; color:#2c3e50;
                    margin-bottom:30px; line-height:1.3;">
            {self._esc(self.title)}
        </div>
        <div style="width:200px; height:3px; background:#2980b9;
                    margin:0 auto 30px;"></div>
        <table cellpadding="6" cellspacing="0"
               style="margin:0 auto; font-size:12pt; color:#555;">
            <tr>
                <td style="text-align:right; font-weight:bold; padding-right:12px;">
                    {self._tr('cover_scale')}</td>
                <td>1 / {self.scale}</td>
            </tr>
            <tr>
                <td style="text-align:right; font-weight:bold; padding-right:12px;">
                    {self._tr('cover_format')}</td>
                <td>{self.format_name} {orient_label}</td>
            </tr>
            <tr>
                <td style="text-align:right; font-weight:bold; padding-right:12px;">
                    {self._tr('cover_sheets')}</td>
                <td>{num_sheets}</td>
            </tr>
            <tr>
                <td style="text-align:right; font-weight:bold; padding-right:12px;">
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

        # Tailles naturelles pour 96 DPI (pt réels, pas de compensation)
        body_pt = 10
        title_pt = max(24, int(min(w_mm, h_mm) * 0.11))
        head_pt = body_pt
        pad = max(2, int(body_pt * 0.25))

        # Répartir en 2 colonnes (gauche et droite), lecture verticale
        total = len(sorted_items)
        half = math.ceil(total / 2)
        col_left = sorted_items[:half]
        col_right = sorted_items[half:]

        # Construire les lignes du tableau 4 colonnes
        rows_html = ''
        sep = f'border-left:1px solid #ccc;'
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
                f'<td style="padding:{pad}px 8px; border-bottom:1px solid #eee;'
                f' font-size:{body_pt}pt;">'
                f'{self._esc(street_l)}</td>'
                f'<td style="padding:{pad}px 8px; border-bottom:1px solid #eee;'
                f' font-size:{body_pt}pt; color:#2980b9;">{refs_str_l}</td>'
                f'<td style="padding:{pad}px 8px; border-bottom:1px solid #eee;'
                f' {sep} font-size:{body_pt}pt;">'
                f'{self._esc(street_r)}</td>'
                f'<td style="padding:{pad}px 8px; border-bottom:1px solid #eee;'
                f' font-size:{body_pt}pt; color:#2980b9;">{refs_str_r}</td>'
                f'</tr>\n'
            )

        # En-tête 4 colonnes
        th_style = f'padding:{pad+2}px 8px; text-align:left; font-size:{head_pt}pt;'
        header = (
            f'<tr style="background:#2c3e50; color:#fff;">'
            f'<th style="{th_style}">{self._esc(self.column_title)}</th>'
            f'<th style="{th_style}">{self._tr("idx_sheets")}</th>'
            f'<th style="{th_style} {sep} border-color:#fff;">{self._esc(self.column_title)}</th>'
            f'<th style="{th_style}">{self._tr("idx_sheets")}</th>'
            f'</tr>'
        )

        html = f'''<html><body style="margin:0; font-family:Arial, Helvetica, sans-serif;">
<div style="font-size:{title_pt}pt; font-weight:bold; color:#2c3e50;
            border-bottom:3px solid #2c3e50; padding-bottom:10px;
            margin-bottom:18px;">
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
        # Plan d'ensemble : fond OSM + grille uniquement
        osm_layer = next(
            (l for l in project.mapLayers().values()
             if isinstance(l, QgsRasterLayer) and l.isValid()
             and ('osm' in l.name().lower() or 'openstreetmap' in l.name().lower())),
            None
        )
        if osm_layer is None:
            osm_uri = ("type=xyz"
                       "&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png"
                       "&zmax=19&zmin=0&crs=EPSG:3857")
            osm_layer = QgsRasterLayer(osm_uri, "OpenStreetMap", "wms")
            if not osm_layer.isValid():
                osm_layer = None
        overview_layers = []
        if osm_layer:
            overview_layers.append(osm_layer)
        overview_layers.append(self.grid_layer)

        map_item.setKeepLayerSet(True)
        map_item.setLayers(overview_layers)

        # Emprise = grille entière, ajustée au ratio du cadre carte
        extent = self.grid_layer.extent()
        if extent.isNull() or extent.isEmpty():
            del layout
            return path
        # Ratio du cadre carte sur la page
        map_ratio = map_w / map_h if map_h > 0 else 1.0
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
        # Pas de triggerRepaint() ici : inutile avant l'export PDF
        # (évite un rendu complet du canvas QGIS principal)

        try:
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
            # Vue d'ensemble : 96 DPI suffit (limite tuiles WMS à télécharger)
            settings.dpi = min(self.dpi, 96)
            try:
                settings.flags |= QgsLayoutExporter.FlagSimplifyGeometries
            except (AttributeError, TypeError):
                pass
            # NE PAS activer rasterizeWholeImage : bloque le rendu WMS.
            exporter.exportToPdf(path, settings)
        finally:
            # Restaurer l'étiquetage original (même en cas d'erreur)
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
    def _apply_speed_optimizations(self):
        """Active rendu parallèle + cache réseau étendu pour accélérer WMS.

        Sauvegarde les valeurs d'origine dans self._saved_settings pour
        restauration via _restore_settings() en fin d'export.
        """
        s = QSettings()
        self._saved_settings = {
            'parallel_rendering': s.value("/qgis/parallel_rendering", True, bool),
            'max_threads': s.value("/qgis/max_threads", -1, int),
            'wms_capabilities_expiry': s.value("/qgis/defaultCapabilitiesExpiry", 24, int),
            'network_cache_size': s.value("/cache/size", 50 * 1024 * 1024, int),
        }
        # Rendu parallèle activé (téléchargement WMS multi-thread)
        s.setValue("/qgis/parallel_rendering", True)
        # Plafonner à 8 threads max (au-delà : saturation serveur WMS)
        import os as _os
        cpu = _os.cpu_count() or 4
        s.setValue("/qgis/max_threads", min(8, cpu))
        # Cache réseau 500 Mo (vs 50 Mo par défaut) → réutilise les tuiles
        # WMS entre l'overview et les feuillets atlas
        s.setValue("/cache/size", 500 * 1024 * 1024)

        # Configurer le layout : antialiasing désactivé pour les exports atlas
        ctx = self.layout.renderContext()
        self._saved_aa = ctx.flags()
        try:
            ctx.setFlag(QgsLayoutRenderContext.FlagAntialiasing, False)
        except AttributeError:
            pass

    def _restore_settings(self):
        """Restaure les paramètres modifiés par _apply_speed_optimizations()."""
        if not hasattr(self, '_saved_settings'):
            return
        s = QSettings()
        s.setValue("/qgis/parallel_rendering", self._saved_settings['parallel_rendering'])
        s.setValue("/qgis/max_threads", self._saved_settings['max_threads'])
        s.setValue("/cache/size", self._saved_settings['network_cache_size'])
        if hasattr(self, '_saved_aa'):
            try:
                ctx = self.layout.renderContext()
                ctx.setFlag(QgsLayoutRenderContext.FlagAntialiasing,
                            bool(self._saved_aa & QgsLayoutRenderContext.FlagAntialiasing))
            except AttributeError:
                pass

    def _make_atlas_settings(self):
        """Crée les PdfExportSettings communes atlas + overview."""
        settings = QgsLayoutExporter.PdfExportSettings()
        settings.dpi = self.dpi
        try:
            settings.flags |= QgsLayoutExporter.FlagSimplifyGeometries
        except (AttributeError, TypeError):
            pass
        # Laisser QGIS rasteriser les WMS en images embedded (vs vecteur forcé)
        # → JPEG embedded plus rapide et plus compact que vecteur pour rasters
        try:
            settings.forceVectorOutput = False
        except AttributeError:
            pass
        return settings

    def _export_atlas_pages(self):
        """Exporte les feuillets atlas en boucle (1 PDF par feuillet).

        Note historique : on a essayé QgsLayoutExporter.exportToPdf(atlas, …)
        (API statique multi-pages) mais sur QGIS 3.44 elle prend ~1m30 à
        échouer silencieusement avant de tomber en fallback. On reste donc
        sur la boucle manuelle, qui est prévisible et instrumentable.
        """
        atlas = self.layout.atlas()
        atlas.updateFeatures()
        count = atlas.count()
        settings = self._make_atlas_settings()

        pdfs = []
        refs = []
        exporter = QgsLayoutExporter(self.layout)
        log_every = max(1, count // 20) if count > 10 else 1
        sheet_times = []

        nm = getattr(self, '_netmon', None)
        for i in range(count):
            atlas.seekTo(i)
            path = os.path.join(self.output_dir, f'_atlas_{i:04d}.pdf')
            self._tmp_files.append(path)

            feat = atlas.coverageLayer().getFeature(atlas.currentFeatureNumber())
            ref = feat['reference'] if feat.isValid() else f"P{i+1}"
            refs.append(ref)

            net_snap = nm.snapshot() if nm else None
            t0 = time.perf_counter()
            result = exporter.exportToPdf(path, settings)
            dt = time.perf_counter() - t0
            sheet_times.append(dt)
            if result == QgsLayoutExporter.Success:
                pdfs.append(path)

            if i % log_every == 0 or i == count - 1:
                net_str = f" — {nm.delta_str(net_snap)}" if nm else ""
                self._log(f"   ↳ feuillet {i+1}/{count} [{ref}] : "
                          f"{self._fmt_dur(dt)}{net_str}", path)
                self._progress(75 + int(20 * (i + 1) / count))
                QApplication.processEvents()

        # Stats récap (utile pour diagnostiquer WMS lent)
        if sheet_times:
            avg = sum(sheet_times) / len(sheet_times)
            mx = max(sheet_times)
            self._log(f"   ↳ stats : moy {self._fmt_dur(avg)}, "
                      f"max {self._fmt_dur(mx)}")

        self._cached_refs = refs
        return pdfs

    # ---------------------------------------------------------------- merge
    def _merge_pdfs(self, pdf_list, output_path, ref_page_map=None):
        """Fusionne les PDF. Tente pypdf, PyPDF2, puis fallback pur Python."""
        try:
            return self._merge_pypdf(pdf_list, output_path, ref_page_map)
        except (ImportError, Exception):
            pass
        try:
            return self._merge_pypdf2(pdf_list, output_path, ref_page_map)
        except (ImportError, Exception):
            pass
        # Fallback pur Python — zéro dépendance, fonctionne partout
        return self._merge_native(pdf_list, output_path)

    def _merge_native(self, pdf_list, output_path):
        """Fusion PDF en pur Python — zéro dépendance externe.
        Concatène les pages en réécrivant les objets PDF avec xref valide.
        Pas de signets, mais produit un PDF lisible par tout lecteur.
        """
        import re

        all_objects = []   # (new_num, body_bytes)
        page_nums = []     # new_num des objets /Type /Page
        next_num = 1

        for pdf_path in pdf_list:
            if not os.path.exists(pdf_path):
                continue
            with open(pdf_path, 'rb') as f:
                data = f.read()

            # Extraire chaque objet : "N 0 obj ... endobj"
            objects = []
            for m in re.finditer(rb'(\d+)\s+0\s+obj\b', data):
                obj_num = int(m.group(1))
                body_start = m.end()
                end_m = re.search(rb'\bendobj\b', data[body_start:])
                if not end_m:
                    continue
                body = data[body_start:body_start + end_m.start()]
                objects.append((obj_num, body))

            if not objects:
                continue

            # Table de renumérotation
            obj_map = {}
            for old_num, _ in objects:
                obj_map[old_num] = next_num
                next_num += 1

            def _renum_ref(match, _map=obj_map):
                ref = int(match.group(1))
                return f'{_map.get(ref, ref)} 0 R'.encode()

            for old_num, body in objects:
                new_num = obj_map[old_num]

                # Ignorer les objets Pages, Catalog et XRef sources
                if re.search(rb'/Type\s*/Pages\b', body):
                    continue
                if re.search(rb'/Type\s*/Catalog\b', body):
                    continue
                if re.search(rb'/Type\s*/XRef\b', body):
                    continue

                # Renuméroter les références "N 0 R" SEULEMENT
                # dans la partie dictionnaire (avant stream)
                stream_m = re.search(rb'\bstream\r?\n', body)
                if stream_m:
                    dict_part = body[:stream_m.start()]
                    stream_part = body[stream_m.start():]
                    dict_part = re.sub(rb'(\d+)\s+0\s+R\b', _renum_ref, dict_part)
                    body = dict_part + stream_part
                else:
                    body = re.sub(rb'(\d+)\s+0\s+R\b', _renum_ref, body)

                # Détecter les pages
                is_page = bool(re.search(rb'/Type\s*/Page\b(?!s)', body))
                if is_page:
                    page_nums.append(new_num)

                all_objects.append((new_num, body))

        if not page_nums:
            return None

        # Construire le PDF de sortie avec xref valide
        out = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
        xref_offsets = {}

        # Écrire tous les objets (avec /Parent corrigé vers notre Pages)
        pages_num = next_num
        parent_repl = f'/Parent {pages_num} 0 R'.encode()

        for num, body in all_objects:
            # Réécrire /Parent pour pointer vers notre nouvel objet Pages
            if num in page_nums:
                body = re.sub(rb'/Parent\s+\d+\s+0\s+R', parent_repl, body)
            xref_offsets[num] = len(out)
            out += f'{num} 0 obj'.encode() + body + b'endobj\n'

        # Objet Pages (arbre de pages unique)
        kids = ' '.join(f'{n} 0 R' for n in page_nums)
        xref_offsets[pages_num] = len(out)
        out += (f'{pages_num} 0 obj\n'
                f'<< /Type /Pages /Kids [{kids}] /Count {len(page_nums)} >>\n'
                f'endobj\n').encode()

        # Objet Catalog
        catalog_num = pages_num + 1
        xref_offsets[catalog_num] = len(out)
        out += (f'{catalog_num} 0 obj\n'
                f'<< /Type /Catalog /Pages {pages_num} 0 R >>\n'
                f'endobj\n').encode()

        # Table xref complète
        max_obj = catalog_num
        xref_start = len(out)
        out += f'xref\n0 {max_obj + 1}\n'.encode()
        out += b'0000000000 65535 f \r\n'
        for i in range(1, max_obj + 1):
            if i in xref_offsets:
                out += f'{xref_offsets[i]:010d} 00000 n \r\n'.encode()
            else:
                out += b'0000000000 00000 f \r\n'

        # Trailer
        out += (f'trailer\n<< /Size {max_obj + 1} /Root {catalog_num} 0 R >>\n'
                f'startxref\n{xref_start}\n%%EOF\n').encode()

        with open(output_path, 'wb') as f:
            f.write(bytes(out))

        return output_path

    def _merge_pypdf(self, pdf_list, output_path, ref_page_map):
        from pypdf import PdfWriter, PdfReader

        writer = PdfWriter()

        for pdf_path in pdf_list:
            reader = PdfReader(pdf_path)
            for page in reader.pages:
                writer.add_page(page)

        # Ajouter des signets (bookmarks) navigables dans le panneau PDF
        if ref_page_map:
            writer.add_outline_item(
                self._tr('cover_format'), 0)

            idx_start = 1
            if self.index_data:
                writer.add_outline_item(
                    self._tr('idx_title'), idx_start)

            overview_page = min(ref_page_map.values()) - 1 if ref_page_map else 1
            if overview_page >= 0 and overview_page < len(writer.pages):
                writer.add_outline_item(
                    self._tr('overview'), overview_page)

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
        # Vérifier que le répertoire de sortie existe
        if not os.path.isdir(self.output_dir):
            raise FileNotFoundError(f"Output directory does not exist: {self.output_dir}")
        w_mm, h_mm = self._page_size_mm()

        # Initialiser le fichier log à côté du PDF de sortie
        self._open_log_file()

        # 0) Activer les optimisations vitesse (rendu parallèle, cache WMS étendu)
        self._apply_speed_optimizations()
        try:
            return self._export_impl(w_mm, h_mm)
        finally:
            self._restore_settings()
            # Sécurité : couper le NetworkMonitor même en cas d'exception
            if hasattr(self, '_netmon') and self._netmon:
                try:
                    self._netmon.stop()
                except Exception:
                    pass

    def _export_impl(self, w_mm, h_mm):
        """Implémentation interne de l'export (séparée pour try/finally propre)."""
        t_global = time.perf_counter()

        # ── Démarrer la surveillance réseau ──
        self._netmon = NetworkMonitor()
        self._netmon.start()

        self._log("═══════════════════════════════════════════════════════")
        self._log(f"   Export PDF — démarré à {time.strftime('%H:%M:%S')}")
        self._log("═══════════════════════════════════════════════════════")
        self._log_system_info()

        # 1) Nombre de feuillets
        self._progress(70)
        self._step_start("Indexation atlas")
        atlas = self.layout.atlas()
        atlas.updateFeatures()
        num_sheets = atlas.count()
        self._step_end(f"{num_sheets} feuillet(s)")

        # Logs détaillés une fois num_sheets connu
        self._log_export_params(w_mm, h_mm, num_sheets)
        self._log_project_info()
        self._log_layer_inventory()

        # 2) Page de garde
        self._progress(72)
        self._step_start("Page de garde")
        snap = self._netmon.snapshot()
        cover_pdf = self._generate_cover(w_mm, h_mm, num_sheets)
        self._step_end(self._netmon.delta_str(snap))

        # 3) Index (si données disponibles)
        index_pdf = None
        index_pages = 0

        if self.index_data:
            self._step_start("Index géographique")
            snap = self._netmon.snapshot()
            result = self._generate_index(w_mm, h_mm, {})
            if result:
                index_pdf, index_pages = result
            self._step_end(f"{index_pages} page(s) — {self._netmon.delta_str(snap)}")

        self._progress(74)

        # 4) Plan d'ensemble
        self._step_start("Plan d'ensemble")
        snap = self._netmon.snapshot()
        overview_pdf = self._generate_overview(w_mm, h_mm)
        self._step_end(self._netmon.delta_str(snap))
        self._progress(76)

        # 5) Pages atlas (le plus long)
        self._step_start(f"Feuillets atlas ({num_sheets} pages)")
        snap = self._netmon.snapshot()
        t_atlas = time.perf_counter()
        atlas_pdfs = self._export_atlas_pages()
        per_sheet = (time.perf_counter() - t_atlas) / max(1, num_sheets)
        self._step_end(f"moy {self._fmt_dur(per_sheet)}/feuillet — "
                       f"{self._netmon.delta_str(snap)}")

        # Calculer ref_page_map APRÈS l'export (refs collectées ou cachées)
        atlas_refs = self._atlas_ref_order()
        offset = 1 + index_pages + 1
        ref_page_map = {ref: offset + i for i, ref in enumerate(atlas_refs)}

        # 6) Page blanche
        self._progress(96)
        blank_pdf = self._generate_blank(w_mm, h_mm)

        # 7) Fusionner
        self._progress(97)
        n_files = len(atlas_pdfs) + 2 + (1 if index_pdf else 0) + 1
        self._step_start(f"Fusion PDF ({n_files} fichiers)")
        all_pdfs = [cover_pdf]
        if index_pdf:
            all_pdfs.append(index_pdf)
        all_pdfs.append(overview_pdf)
        all_pdfs.extend(atlas_pdfs)
        all_pdfs.append(blank_pdf)

        output_path = os.path.join(self.output_dir, 'atlas_complet.pdf')
        merged = self._merge_pdfs(all_pdfs, output_path, ref_page_map)
        # Taille du PDF final
        size_str = ""
        if merged and os.path.exists(merged):
            size_str = f"taille : {_fmt_bytes(os.path.getsize(merged))}"
        self._step_end(size_str)

        # Nettoyage des fichiers temporaires seulement si le merge a réussi
        if merged:
            for p in self._tmp_files:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass
        else:
            self._log("Fusion impossible — fichiers PDF séparés conservés.")

        # ── Récapitulatif global ──
        total = time.perf_counter() - t_global
        self._log("═══════════════════════════════════════════════════════")
        self._log(f"   Export terminé en {self._fmt_dur(total)}")
        if getattr(self, '_log_path', None):
            self._log(f"   Log complet : {self._log_path}")
        self._log("═══════════════════════════════════════════════════════")
        self._log("┌─ Statistiques réseau (total) ──")
        for line in self._netmon.summary().splitlines():
            self._log(f"│ {line[2:] if line.startswith('  ') else line}")
        self._log("└──")
        # Conseils auto selon les stats
        self._log_perf_hints(total, num_sheets)

        self._netmon.stop()
        self._progress(100)
        return merged or self.output_dir

    def _log_perf_hints(self, total_seconds, num_sheets):
        """Conseils auto basés sur les stats observées."""
        hints = []
        per_sheet = total_seconds / max(1, num_sheets)
        nm = self._netmon

        if per_sheet > 30:
            hints.append("⚠ +30s/feuillet : envisager DPI plus bas ou cache WMS persistant")
        if nm.errors > 0:
            hints.append(f"⚠ {nm.errors} erreurs réseau : serveur WMS instable ou timeout")
        if nm.from_cache == 0 and nm.requests > 50:
            hints.append("⚠ Aucune réponse en cache : QGIS retélécharge tout — "
                         "vérifier /cache/size dans Préférences > Réseau")
        if nm.bytes_total > 100 * 1024 * 1024:
            hints.append(f"⚠ {_fmt_bytes(nm.bytes_total)} téléchargés : "
                         "DPI probablement trop élevé pour les couches WMS")
        # Hôtes les plus utilisés
        if nm.hosts:
            slow_hosts = [h for h, n in nm.hosts.items() if n > 20]
            if slow_hosts:
                hints.append(f"ℹ Hôte le plus sollicité : {slow_hosts[0]} — "
                             f"vérifier sa latence ping")
        if hints:
            self._log("┌─ Conseils d'optimisation ──")
            for h in hints:
                self._log(f"│ {h}")
            self._log("└──")

    # ---------------------------------------------------------------- utils
    @staticmethod
    def _esc(s):
        return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
