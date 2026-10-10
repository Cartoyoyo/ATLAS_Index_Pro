import os
import re
import math
import time
import platform
from datetime import date
from urllib.parse import unquote, quote

from qgis.core import (
    QgsLayoutExporter, QgsProject, QgsPrintLayout, QgsLayoutItemMap,
    QgsLayoutItemLabel, QgsLayoutItemScaleBar, QgsLayoutPoint,
    QgsLayoutSize, QgsUnitTypes, QgsRectangle, QgsTextFormat,
    QgsLayoutRenderContext, QgsRasterLayer, QgsVectorLayer,
    QgsNetworkAccessManager, Qgis, QgsMapSettings, QgsMapRendererParallelJob
)
from qgis.PyQt.QtCore import QSizeF, QSize, QRect, Qt, QSettings
from qgis.PyQt.QtGui import QTextDocument, QPainter, QFont, QColor
try:
    from qgis.PyQt.QtGui import QPageSize
except ImportError:
    from qgis.PyQt.QtCore import QPageSize
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
    'cover':         {'fr': "Page de garde",       'en': "Cover page",
                      'es': "Portada",             'pt': "Capa",        'de': "Titelblatt"},
    'err_locked':    {'fr': "Le fichier {f} est ouvert dans un autre programme "
                            "(lecteur PDF ?). Fermez-le puis relancez l'export.",
                      'en': "The file {f} is open in another program (PDF viewer?). "
                            "Close it and run the export again.",
                      'es': "El archivo {f} está abierto en otro programa (¿lector PDF?). "
                            "Ciérrelo y vuelva a exportar.",
                      'pt': "O arquivo {f} está aberto noutro programa (leitor de PDF?). "
                            "Feche-o e exporte novamente.",
                      'de': "Die Datei {f} ist in einem anderen Programm geöffnet "
                            "(PDF-Viewer?). Schließen Sie sie und exportieren Sie erneut."},
}

# Préfixe des liens internes index → feuillet (réécrits en GoTo à la fusion)
_LINK_PREFIX = 'atlas://ref/'


class ExportCancelled(Exception):
    """Levée quand l'utilisateur annule pendant l'export PDF."""


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
                return unquote(part[4:])[:120]
    except Exception:
        pass
    return "(URL inconnue)"


class PdfExporter:
    """Génère un PDF complet : page de garde + index + atlas + page blanche."""

    def __init__(self, layout, grid_layer, index_data, output_dir,
                 title, format_name, orientation, scale, dpi, lang,
                 progress_callback=None, log_callback=None,
                 column_title=None, cancel_check=None):
        self.cancel_check = cancel_check      # callable → True si annulation demandée
        self.incomplete_sheets = []           # références rendues après délai dépassé
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

    def _check_cancel(self):
        """Interrompt l'export si l'utilisateur a demandé l'annulation."""
        QApplication.processEvents()
        if self.cancel_check and self.cancel_check():
            raise ExportCancelled()

    def _check_output_writable(self, path):
        """Vérifie AVANT le rendu que le PDF final pourra être écrit
        (fichier ouvert dans un lecteur PDF sous Windows = verrouillé)."""
        if not os.path.exists(path):
            return
        try:
            with open(path, 'ab'):
                pass
        except OSError:
            raise PermissionError(self._tr('err_locked').format(f=path))

    def _log(self, msg, filepath=None):
        # Callback UI (dialogue QGIS)
        if self.log_cb:
            self.log_cb(msg, filepath)
        # Écriture aussi dans le fichier log à côté du PDF de sortie
        self._log_to_file(msg)

    def _log_to_file(self, msg):
        """Append au fichier log (handle ouvert pendant tout l'export)."""
        fh = getattr(self, '_log_fh', None)
        if fh is None:
            return
        try:
            fh.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            fh.flush()
        except OSError:
            pass

    def _open_log_file(self):
        """Ouvre le fichier log et le garde ouvert jusqu'à _close_log_file()."""
        try:
            log_path = os.path.join(self.output_dir, 'atlas_log.txt')
            self._log_fh = open(log_path, 'w', encoding='utf-8')
            self._log_fh.write("=== ATLAS Index Pro — export log ===\n")
            self._log_fh.write(f"Date : {date.today().isoformat()} "
                               f"{time.strftime('%H:%M:%S')}\n")
            self._log_fh.write(f"Sortie : {self.output_dir}\n\n")
            self._log_fh.flush()
        except OSError:
            self._log_fh = None

    def _close_log_file(self):
        """Ferme le handle log ouvert par _open_log_file()."""
        fh = getattr(self, '_log_fh', None)
        if fh:
            try:
                fh.close()
            except OSError:
                pass
            self._log_fh = None

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
            try:
                qgis_ver = Qgis.QGIS_VERSION
            except Exception:
                qgis_ver = "?"
            s = QSettings()
            self._log("┌─ Contexte système ──")
            self._log(f"│  QGIS              : {qgis_ver}")
            self._log(f"│  OS                : {platform.system()} {platform.release()}")
            self._log(f"│  CPU               : {os.cpu_count() or '?'} cœurs")
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
                    try:
                        src = layer.source()
                        keys = ('format=', 'tilematrixset=', 'crs=')
                        for part in src.split('&'):
                            if part.lower().startswith(keys):
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

        Lit directement la couche grille plutôt que de piloter l'atlas via
        seekTo() : la carte du layout est atlas-driven, donc chaque seekTo()
        déclenche un rendu (et une requête WMS) en arrière-plan pour cette
        emprise — un balayage complet des feuillets juste pour lire un
        attribut lançait ainsi des dizaines de requêtes WMS parasites avant
        même le début de l'export réel.
        """
        if hasattr(self, '_cached_refs'):
            return self._cached_refs
        atlas = self.layout.atlas()
        atlas.updateFeatures()

        refs = [f['reference'] if f.isValid() else f"P{i+1}"
                for i, f in enumerate(self.grid_layer.getFeatures())]

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
    def _ref_link(self, ref):
        """Référence cliquable : Qt l'exporte en annotation /URI, réécrite
        en saut interne (GoTo) vers le feuillet lors de la fusion."""
        return (f'<a href="{_LINK_PREFIX}{quote(str(ref), safe="")}">'
                f'<span style="color:#2980b9; text-decoration:none;">'
                f'{self._esc(ref)}</span></a>')

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
        sep = 'border-left:10px solid #ccc;'
        for i in range(half):
            # Colonne gauche
            street_l, refs_l = col_left[i]
            refs_str_l = ', '.join(self._ref_link(r) for r in refs_l)

            # Colonne droite (peut être vide si nombre impair)
            if i < len(col_right):
                street_r, refs_r = col_right[i]
                refs_str_r = ', '.join(self._ref_link(r) for r in refs_r)
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
        overview_layers = [self.grid_layer]
        if osm_layer:
            overview_layers.append(osm_layer)

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
            QgsPalLayerSettings, QgsVectorLayerSimpleLabeling, QgsProperty
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
            layout.addLayoutItem(scalebar)
            scalebar.setLinkedMap(map_item)
            scalebar.setStyle('Single Box')
            scalebar.setHeight(scalebar_h)
            sb_fmt = QgsTextFormat()
            sb_fmt.setFont(QFont('Arial', scalebar_font))
            scalebar.setTextFormat(sb_fmt)
            # Sans taille de segment, la barre se réduit à « 0 » :
            # applyDefaultSize() choisit une longueur ronde (~1/4 de carte)
            # et les unités (m/km) adaptées à l'emprise.
            scalebar.applyDefaultSize(QgsUnitTypes.DistanceMeters)
            scalebar.setNumberOfSegments(4)
            scalebar.setNumberOfSegmentsLeft(0)
            scalebar.update()
            scalebar.attemptMove(QgsLayoutPoint(
                margin, h_mm - margin - footer_h,
                QgsUnitTypes.LayoutMillimeters
            ))

            # ── Export PDF ──
            exporter = QgsLayoutExporter(layout)
            settings = QgsLayoutExporter.PdfExportSettings()
            # Vue d'ensemble : 96 DPI suffit (limite tuiles WMS à télécharger)
            settings.dpi = min(self.dpi, 96)
            try:
                settings.flags |= QgsLayoutExporter.FlagSimplifyGeometries
            except (AttributeError, TypeError):
                pass
            try:
                settings.textRenderFormat = Qgis.TextRenderFormat.AlwaysText
            except AttributeError:
                pass
            # Pas de géoréférencement GDAL : il réécrit le PDF par mise à
            # jour incrémentale (objets /Page en double) — inutile dans un
            # PDF fusionné et source du doublon de page en fusion native.
            settings.appendGeoreference = False
            settings.exportMetadata = False
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
        cpu = os.cpu_count() or 4
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

    def _write_atlas_page_pdf(self, path, img, ref, w_mm, h_mm):
        """Écrit une page atlas (image de carte pré-rendue + étiquette
        référence) dans un PDF 1 page, en pleine page (0 marge).

        Reproduit la seule décoration du layout atlas (voir atlas_creator.py) :
        l'étiquette référence Arial 28 Bold, fond blanc translucide, 40×16mm
        en bas à droite.
        """
        printer = QPrinter(QPrinter.HighResolution)
        printer.setResolution(self.dpi)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        printer.setPageSize(QPageSize(QSizeF(w_mm, h_mm), QPageSize.Millimeter))
        printer.setFullPage(True)
        printer.setPageMargins(0, 0, 0, 0, QPrinter.Millimeter)

        w_px = max(1, int(w_mm / 25.4 * self.dpi))
        h_px = max(1, int(h_mm / 25.4 * self.dpi))

        painter = QPainter(printer)
        try:
            if img is not None and not img.isNull():
                painter.drawImage(QRect(0, 0, w_px, h_px), img)
            else:
                painter.fillRect(QRect(0, 0, w_px, h_px), QColor(255, 255, 255))

            label_w_mm, label_h_mm = 40.0, 16.0
            rect = QRect(
                int((w_mm - label_w_mm - 2) / 25.4 * self.dpi),
                int((h_mm - label_h_mm - 2) / 25.4 * self.dpi),
                int(label_w_mm / 25.4 * self.dpi),
                int(label_h_mm / 25.4 * self.dpi),
            )
            painter.fillRect(rect, QColor(255, 255, 255, 80))
            painter.setFont(QFont('Arial', 28, QFont.Bold))
            painter.setPen(QColor(0, 0, 0, 120))
            painter.drawText(rect.adjusted(4, 0, -4, 0),
                              Qt.AlignRight | Qt.AlignVCenter, str(ref))
        finally:
            painter.end()

    def _export_atlas_pages(self):
        """Exporte les feuillets atlas en rendant les cartes par lots
        concurrents (QgsMapRendererParallelJob), puis en écrivant chaque
        PDF de page à partir de l'image déjà rendue.

        Note historique : QgsLayoutExporter.exportToPdf(atlas, …) (API
        statique multi-pages) prend ~1m30 à échouer silencieusement sur
        QGIS 3.44. La boucle séquentielle manuelle (1 exportToPdf par
        feuillet) fonctionnait mais payait le rendu couche par couche à
        chaque page sans jamais recouvrir les latences réseau.

        Un premier essai de préchauffage réseau en parallèle (65 jobs
        recevant tous les MÊMES objets QgsMapLayer) a corrompu le
        fournisseur WMS (incident du 15/07/2026 : centaines d'erreurs 404
        rejouées depuis le cache disque). La règle qui en découle : deux
        QgsMapRendererParallelJob actifs en même temps ne doivent JAMAIS
        partager le même objet QgsMapLayer — chaque lot clone donc ses
        propres couches, et un clone n'est utilisé que par un seul job à
        la fois.
        """
        atlas = self.layout.atlas()
        atlas.updateFeatures()
        count = atlas.count()
        if count == 0:
            return []

        map_items = [it for it in self.layout.items() if isinstance(it, QgsLayoutItemMap)]
        if not map_items:
            return []
        map_item = map_items[0]

        nm = getattr(self, '_netmon', None)
        refs = self._atlas_ref_order()

        w_mm, h_mm = self._page_size_mm()
        w_px = max(1, int(w_mm / 25.4 * self.dpi))
        h_px = max(1, int(h_mm / 25.4 * self.dpi))

        project = QgsProject.instance()
        layers = [n.layer() for n in project.layerTreeRoot().findLayers()
                  if n.isVisible() and n.layer() is not None]

        # Emprises de toutes les pages via l'atlas lui-même (seekTo ne fait
        # que mettre à jour l'emprise du map item selon le mode Fixed/Auto
        # déjà configuré par AtlasCreator — aucun rendu déclenché ici) :
        # évite de réimplémenter à la main le calcul d'échelle de l'atlas.
        extents = []
        for i in range(count):
            atlas.seekTo(i)
            extents.append(QgsRectangle(map_item.extent()))
        atlas.seekTo(0)

        batch_size = max(2, min(4, os.cpu_count() or 4))
        pdfs = [None] * count
        sheet_times = [0.0] * count

        for start in range(0, count, batch_size):
            self._check_cancel()
            idxs = list(range(start, min(start + batch_size, count)))
            # Un jeu de clones par feuillet du lot : jamais partagé entre
            # jobs concurrents (cf. note ci-dessus).
            clone_sets = [[lyr.clone() for lyr in layers] for _ in idxs]

            net_snap = nm.snapshot() if nm else None
            t_batch = time.perf_counter()
            jobs = []
            for slot, i in enumerate(idxs):
                ms = QgsMapSettings()
                ms.setDestinationCrs(project.crs())
                ms.setTransformContext(project.transformContext())
                ms.setLayers(clone_sets[slot])
                ms.setOutputSize(QSize(w_px, h_px))
                ms.setExtent(extents[i])
                ms.setOutputDpi(self.dpi)
                ms.setBackgroundColor(QColor(255, 255, 255))
                job = QgsMapRendererParallelJob(ms)
                job.start()
                jobs.append((i, job))

            deadline = time.perf_counter() + 60.0
            while any(j.isActive() for _, j in jobs) and time.perf_counter() < deadline:
                QApplication.processEvents()
                if self.cancel_check and self.cancel_check():
                    for _, j in jobs:
                        if j.isActive():
                            j.cancel()
                    raise ExportCancelled()

            for i, job in jobs:
                if job.isActive():
                    # Délai dépassé : l'image est partielle (couches réseau
                    # non reçues) — le signaler au lieu de l'écrire en silence.
                    job.cancel()
                    ref = refs[i] if i < len(refs) else f"P{i + 1}"
                    self.incomplete_sheets.append(ref)
                    self._log(f"   ⚠ feuillet {ref} : rendu interrompu après 60 s "
                              f"(image incomplète — serveur WMS lent ?)")
                img = job.renderedImage()
                path = os.path.join(self.output_dir, f'_atlas_{i:04d}.pdf')
                self._tmp_files.append(path)
                self._write_atlas_page_pdf(path, img, refs[i] if i < len(refs) else f"P{i+1}",
                                            w_mm, h_mm)
                pdfs[i] = path

            dt_batch = time.perf_counter() - t_batch
            for i in idxs:
                sheet_times[i] = dt_batch / len(idxs)
            net_str = f" — {nm.delta_str(net_snap)}" if nm else ""
            self._log(f"   ↳ feuillets {idxs[0] + 1}-{idxs[-1] + 1}/{count} "
                      f"[{', '.join(refs[i] if i < len(refs) else f'P{i+1}' for i in idxs)}] : "
                      f"{self._fmt_dur(dt_batch)}{net_str}")
            self._progress(75 + int(20 * (idxs[-1] + 1) / count))
            QApplication.processEvents()

        if sheet_times:
            avg = sum(sheet_times) / len(sheet_times)
            mx = max(sheet_times)
            self._log(f"   ↳ stats : moy {self._fmt_dur(avg)}, "
                      f"max {self._fmt_dur(mx)}")

        self._cached_refs = refs
        return [p for p in pdfs if p]

    # ---------------------------------------------------------------- merge
    def _outline_entries(self, ref_page_map, index_pages):
        """Signets : [(titre, page 0-based, enfants)] — même structure pour
        toutes les méthodes de fusion."""
        if not ref_page_map:
            return []
        first_sheet = min(ref_page_map.values())
        entries = [(self._tr('cover'), 0, [])]
        if index_pages:
            entries.append((self._tr('idx_title'), 1, []))
        entries.append((self._tr('overview'), first_sheet - 1, []))
        sheets = [(ref, page, []) for ref, page in ref_page_map.items()]
        entries.append((self._tr('idx_sheets'), first_sheet, sheets))
        return entries

    def _merge_pdfs(self, pdf_list, output_path, ref_page_map=None, index_pages=0):
        """Fusionne les PDF. Tente pypdf, PyPDF2, puis fallback pur Python."""
        try:
            return self._merge_pypdf(pdf_list, output_path, ref_page_map, index_pages)
        except ImportError:
            pass
        except Exception as e:
            self._log(f"   ↳ pypdf : erreur merge ({e}), tentative PyPDF2…")
        try:
            return self._merge_pypdf2(pdf_list, output_path, ref_page_map, index_pages)
        except ImportError:
            pass
        except Exception as e:
            self._log(f"   ↳ PyPDF2 : erreur merge ({e}), fallback natif…")
        return self._merge_native(pdf_list, output_path, ref_page_map, index_pages)

    @staticmethod
    def _find_obj_end(data, start):
        """Position du « endobj » de l'objet commençant à `start`, en sautant
        le contenu d'un éventuel stream (qui peut contenir n'importe quels
        octets, y compris « endobj » ou « N 0 obj »)."""
        em = data.find(b'endobj', start)
        sm = re.compile(rb'stream\r?\n').search(data, start, em if em >= 0 else len(data))
        if sm is None:
            return em
        # (?!\d) : sur « /Length 1234 0 R » (longueur indirecte, écrite par
        # Qt), empêche le retour arrière qui capturerait « 123 ».
        lm = re.search(rb'/Length\s+(\d+)(?!\d)(?!\s+\d+\s+R)', data[start:sm.start()])
        skip = int(lm.group(1)) if lm else 0
        es = data.find(b'endstream', sm.end() + skip)
        if es < 0:
            return -1
        return data.find(b'endobj', es)

    @staticmethod
    def _pdf_text(s):
        """Chaîne PDF UTF-16BE (accents des signets)."""
        return '<FEFF' + str(s).encode('utf-16-be').hex().upper() + '>'

    def _merge_native(self, pdf_list, output_path, ref_page_map=None, index_pages=0):
        """Fusion PDF en pur Python — zéro dépendance externe.
        Concatène les pages en réécrivant les objets PDF avec xref valide,
        ajoute les signets et convertit les liens de l'index en sauts internes.
        Prévu pour les PDF produits par Qt (pas de flux d'objets compressés).
        """
        obj_re = re.compile(rb'(\d+)\s+(\d+)\s+obj\b')
        ref_re = re.compile(rb'(\d+)\s+0\s+R\b')

        all_objects = []   # [new_num, body_bytes]
        page_nums = []     # new_num des objets /Type /Page, dans l'ordre
        next_num = 1

        for pdf_path in pdf_list:
            if not os.path.exists(pdf_path):
                continue
            with open(pdf_path, 'rb') as f:
                data = f.read()

            # Parcours séquentiel ; en cas de mise à jour incrémentale, la
            # DERNIÈRE définition d'un numéro d'objet est la bonne.
            objects = {}
            order = []
            pos = 0
            while True:
                m = obj_re.search(data, pos)
                if not m:
                    break
                end = self._find_obj_end(data, m.end())
                if end < 0:
                    break
                num = int(m.group(1))
                if num not in objects:
                    order.append(num)
                objects[num] = data[m.end():end]
                pos = end + len(b'endobj')

            if not objects:
                continue

            obj_map = {}
            for old_num in order:
                obj_map[old_num] = next_num
                next_num += 1

            def _renum_ref(match, _map=obj_map):
                ref = int(match.group(1))
                return f'{_map.get(ref, ref)} 0 R'.encode()

            for old_num in order:
                body = objects[old_num]
                new_num = obj_map[old_num]

                # Ignorer les objets Pages, Catalog et XRef sources
                if re.search(rb'/Type\s*/(Pages|Catalog|XRef)\b', body):
                    continue

                # Renuméroter les références "N 0 R" SEULEMENT
                # dans la partie dictionnaire (avant stream)
                stream_m = re.search(rb'\bstream\r?\n', body)
                if stream_m:
                    body = (ref_re.sub(_renum_ref, body[:stream_m.start()])
                            + body[stream_m.start():])
                else:
                    body = ref_re.sub(_renum_ref, body)

                if re.search(rb'/Type\s*/Page(?![A-Za-z])', body):
                    page_nums.append(new_num)

                all_objects.append([new_num, body])

        if not page_nums:
            return None

        pages_num = next_num
        catalog_num = pages_num + 1
        next_num = catalog_num + 1

        # Liens de l'index : annotation /URI atlas://ref/X → destination interne
        if ref_page_map:
            link_re = re.compile(
                rb'/A\s*<<[^<>]*?/URI\s*\(' + re.escape(_LINK_PREFIX.encode())
                + rb'([^)]*)\)[^<>]*>>')

            def _goto(match):
                ref = unquote(match.group(1).decode('latin-1'))
                idx = ref_page_map.get(ref)
                if idx is None or idx >= len(page_nums):
                    return match.group(0)
                return f'/Dest [{page_nums[idx]} 0 R /Fit]'.encode()

            for item in all_objects:
                if b'/Subtype /Link' in item[1] or b'/Subtype/Link' in item[1]:
                    item[1] = link_re.sub(_goto, item[1])

        # Signets
        outline_objs = []
        outlines_num = None
        entries = self._outline_entries(ref_page_map, index_pages)
        if entries:
            outlines_num = next_num
            next_num += 1

            def _build(items, parent):
                nonlocal next_num
                nums = []
                for _ in items:
                    nums.append(next_num)
                    next_num += 1
                for k, (title, page, kids) in enumerate(items):
                    page = min(max(page, 0), len(page_nums) - 1)
                    d = [f'/Title {self._pdf_text(title)}', f'/Parent {parent} 0 R',
                         f'/Dest [{page_nums[page]} 0 R /Fit]']
                    if k > 0:
                        d.append(f'/Prev {nums[k - 1]} 0 R')
                    if k < len(items) - 1:
                        d.append(f'/Next {nums[k + 1]} 0 R')
                    if kids:
                        kid_nums = _build(kids, nums[k])
                        d.append(f'/First {kid_nums[0]} 0 R /Last {kid_nums[-1]} 0 R '
                                 f'/Count {len(kid_nums)}')
                    outline_objs.append((nums[k], ('<< ' + ' '.join(d) + ' >>').encode()))
                return nums

            top = _build(entries, outlines_num)
            total = len(outline_objs)
            outline_objs.append((outlines_num, (
                f'<< /Type /Outlines /First {top[0]} 0 R /Last {top[-1]} 0 R '
                f'/Count {total} >>').encode()))

        # Construire le PDF de sortie avec xref valide
        out = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
        xref_offsets = {}
        parent_repl = f'/Parent {pages_num} 0 R'.encode()
        page_set = set(page_nums)

        for num, body in all_objects:
            # Réécrire /Parent pour pointer vers notre nouvel objet Pages
            if num in page_set:
                body = re.sub(rb'/Parent\s+\d+\s+0\s+R', parent_repl, body)
            xref_offsets[num] = len(out)
            out += f'{num} 0 obj'.encode() + body + b'endobj\n'

        kids = ' '.join(f'{n} 0 R' for n in page_nums)
        xref_offsets[pages_num] = len(out)
        out += (f'{pages_num} 0 obj\n'
                f'<< /Type /Pages /Kids [{kids}] /Count {len(page_nums)} >>\n'
                f'endobj\n').encode()

        for num, body in outline_objs:
            xref_offsets[num] = len(out)
            out += f'{num} 0 obj\n'.encode() + body + b'\nendobj\n'

        catalog_extra = (f' /Outlines {outlines_num} 0 R /PageMode /UseOutlines'
                         if outlines_num else '')
        xref_offsets[catalog_num] = len(out)
        out += (f'{catalog_num} 0 obj\n'
                f'<< /Type /Catalog /Pages {pages_num} 0 R{catalog_extra} >>\n'
                f'endobj\n').encode()

        # Table xref : chaque entrée fait exactement 20 octets (fin « \r\n »)
        max_obj = max(xref_offsets)
        xref_start = len(out)
        out += f'xref\n0 {max_obj + 1}\n'.encode()
        out += b'0000000000 65535 f\r\n'
        for i in range(1, max_obj + 1):
            if i in xref_offsets:
                out += f'{xref_offsets[i]:010d} 00000 n\r\n'.encode()
            else:
                out += b'0000000000 00000 f\r\n'

        out += (f'trailer\n<< /Size {max_obj + 1} /Root {catalog_num} 0 R >>\n'
                f'startxref\n{xref_start}\n%%EOF\n').encode()

        with open(output_path, 'wb') as f:
            f.write(bytes(out))

        return output_path

    def _merge_pypdf(self, pdf_list, output_path, ref_page_map, index_pages=0):
        from pypdf import PdfWriter, PdfReader
        from pypdf.generic import NameObject, ArrayObject

        writer = PdfWriter()

        for pdf_path in pdf_list:
            reader = PdfReader(pdf_path)
            for page in reader.pages:
                writer.add_page(page)

        # Liens de l'index → destination interne vers le feuillet
        if ref_page_map:
            for page in writer.pages:
                for annot in page.get('/Annots') or []:
                    obj = annot.get_object()
                    action = obj.get('/A')
                    if action is None:
                        continue
                    uri = str(action.get_object().get('/URI', ''))
                    if not uri.startswith(_LINK_PREFIX):
                        continue
                    idx = ref_page_map.get(unquote(uri[len(_LINK_PREFIX):]))
                    if idx is None or idx >= len(writer.pages):
                        continue
                    del obj['/A']
                    obj[NameObject('/Dest')] = ArrayObject(
                        [writer.pages[idx].indirect_reference, NameObject('/Fit')])

        # Signets (bookmarks) navigables dans le panneau PDF
        def _add(items, parent=None):
            for title, page, kids in items:
                if 0 <= page < len(writer.pages):
                    node = writer.add_outline_item(title, page, parent=parent)
                    _add(kids, node)
        _add(self._outline_entries(ref_page_map, index_pages))

        with open(output_path, 'wb') as f:
            writer.write(f)
        return output_path

    def _merge_pypdf2(self, pdf_list, output_path, ref_page_map, index_pages=0):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from PyPDF2 import PdfMerger

        merger = PdfMerger()
        for pdf_path in pdf_list:
            merger.append(pdf_path)

        try:
            for title, page, kids in self._outline_entries(ref_page_map, index_pages):
                node = merger.add_outline_item(title, page)
                for ref, sheet_page, _ in kids:
                    merger.add_outline_item(ref, sheet_page, parent=node)
        except Exception as e:
            self._log(f"   ↳ PyPDF2 : signets non ajoutés ({e})")

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

        # PDF cible verrouillé (ouvert dans un lecteur) : échouer tout de
        # suite plutôt qu'après plusieurs minutes de rendu.
        self._check_output_writable(os.path.join(self.output_dir, 'atlas_complet.pdf'))

        # Initialiser le fichier log à côté du PDF de sortie
        self._open_log_file()

        # 0) Activer les optimisations vitesse (rendu parallèle, cache WMS étendu)
        self._apply_speed_optimizations()
        try:
            return self._export_impl(w_mm, h_mm)
        except BaseException as e:
            # Échec ou annulation : ne pas laisser les PDF intermédiaires
            if isinstance(e, ExportCancelled):
                self._log("Export annulé.")
            self._remove_tmp_files()
            raise
        finally:
            self._restore_settings()
            self._close_log_file()
            if hasattr(self, '_netmon') and self._netmon:
                try:
                    self._netmon.stop()
                except Exception:
                    pass

    def _remove_tmp_files(self):
        for p in self._tmp_files:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
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
        self._check_cancel()

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
        self._check_cancel()

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
        self._check_cancel()
        merged = self._merge_pdfs(all_pdfs, output_path, ref_page_map, index_pages)
        # Taille du PDF final
        size_str = ""
        if merged and os.path.exists(merged):
            size_str = f"taille : {_fmt_bytes(os.path.getsize(merged))}"
        self._step_end(size_str)

        # Nettoyage des fichiers temporaires seulement si le merge a réussi
        if merged:
            self._remove_tmp_files()
        else:
            self._log("Fusion impossible — fichiers PDF séparés conservés.")

        # ── Récapitulatif global ──
        total = time.perf_counter() - t_global
        self._log("═══════════════════════════════════════════════════════")
        self._log(f"   Export terminé en {self._fmt_dur(total)}")
        if self.incomplete_sheets:
            self._log(f"   ⚠ {len(self.incomplete_sheets)} feuillet(s) incomplet(s) "
                      f"(délai dépassé) : {', '.join(self.incomplete_sheets)}")
        if getattr(self, '_log_fh', None):
            self._log(f"   Log complet : {self._log_fh.name}")
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
