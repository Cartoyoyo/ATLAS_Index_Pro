import os
import math
from qgis.core import (
    QgsCoordinateTransform, QgsProject, QgsGeometry,
    QgsSpatialIndex
)

from .geocoder import UNKNOWN

# Textes de la page HTML (FR / EN / ES / PT / DE)
_HTML_TR = {
    'col':     {'fr': "Nom de rue", 'en': "Street name", 'es': "Nombre de calle",
                'pt': "Nome da rua", 'de': "Straßenname"},
    'sheets':  {'fr': "Feuillets", 'en': "Sheets", 'es': "Hojas", 'pt': "Folhas",
                'de': "Blätter"},
    'entries': {'fr': "entrée(s)", 'en': "entry(ies)", 'es': "entrada(s)",
                'pt': "entrada(s)", 'de': "Eintrag/Einträge"},
    'pages':   {'fr': "page(s)", 'en': "page(s)", 'es': "página(s)", 'pt': "página(s)",
                'de': "Seite(n)"},
    'page':    {'fr': "Page", 'en': "Page", 'es': "Página", 'pt': "Página", 'de': "Seite"},
    'search':  {'fr': "Rechercher…", 'en': "Search…", 'es': "Buscar…", 'pt': "Pesquisar…",
                'de': "Suchen…"},
    'print':   {'fr': "Imprimer / PDF", 'en': "Print / PDF", 'es': "Imprimir / PDF",
                'pt': "Imprimir / PDF", 'de': "Drucken / PDF"},
    'csv':     {'fr': "Exporter CSV", 'en': "Export CSV", 'es': "Exportar CSV",
                'pt': "Exportar CSV", 'de': "CSV exportieren"},
    'title':   {'fr': "Index des objets", 'en': "Object index", 'es': "Índice de objetos",
                'pt': "Índice de objetos", 'de': "Objektverzeichnis"},
    'orient_paysage':  {'fr': "paysage", 'en': "landscape", 'es': "horizontal",
                        'pt': "paisagem", 'de': "Querformat"},
    'orient_portrait': {'fr': "portrait", 'en': "portrait", 'es': "vertical",
                        'pt': "retrato", 'de': "Hochformat"},
}


def _esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


# Nombre de lignes par colonne selon le format/orientation
# (hauteur utile en mm / ~5.5 mm par ligne)
_ROWS_PER_COL = {
    ('A4', 'paysage'):  28,
    ('A4', 'portrait'): 44,
    ('A3', 'paysage'):  44,
    ('A3', 'portrait'): 66,
}

# Taille CSS pour @page
_PAGE_CSS_SIZE = {
    ('A4', 'paysage'):  'A4 landscape',
    ('A4', 'portrait'): 'A4 portrait',
    ('A3', 'paysage'):  'A3 landscape',
    ('A3', 'portrait'): 'A3 portrait',
}

# Dimensions en mm pour l'aperçu écran (largeur x hauteur)
_PAGE_MM = {
    ('A4', 'paysage'):  (297, 210),
    ('A4', 'portrait'): (210, 297),
    ('A3', 'paysage'):  (420, 297),
    ('A3', 'portrait'): (297, 420),
}


class IndexGenerator:
    """Génère l'index HTML des objets par feuillet, formaté pour impression."""

    def __init__(self, conduite_layer, grid_layer, street_names, crs,
                 format_name='A4', orientation='paysage',
                 column_title=None, lang='fr', selected_only=False):
        self.conduite_layer = conduite_layer
        self.grid_layer = grid_layer
        self.street_names = street_names
        self.crs = crs
        self.format_name = format_name
        self.orientation = orientation
        self.lang = lang
        self.column_title = column_title or self._tr('col')
        # Mode lasso : ne traiter que les objets sélectionnés
        self.selected_only = (selected_only
                              and conduite_layer.selectedFeatureCount() > 0)

    def _tr(self, key):
        entry = _HTML_TR[key]
        return entry.get(self.lang, entry['en'])

    def generate(self, output_dir):
        index = self._build_index()
        sorted_index = self._sort_index(index)
        html = self._render_html(sorted_index)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, 'index_objets.html')
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        return output_path, sorted_index

    def _build_index(self):
        """Retourne {nom_rue: set(references)}.
        Utilise un index spatial sur la grille pour éviter le O(n×m).
        """
        transform = QgsCoordinateTransform(
            self.conduite_layer.crs(), self.crs, QgsProject.instance()
        )

        # Construire l'index spatial de la grille
        grid_index = QgsSpatialIndex()
        grid_geoms = {}
        grid_refs = {}
        has_ref_field = self.grid_layer.fields().indexOf('reference') != -1
        for gf in self.grid_layer.getFeatures():
            gid = gf.id()
            grid_geoms[gid] = QgsGeometry(gf.geometry())
            grid_refs[gid] = gf['reference'] if has_ref_field else f"F{gid}"
            grid_index.addFeature(gf)

        index = {}
        features = (self.conduite_layer.getSelectedFeatures() if self.selected_only
                    else self.conduite_layer.getFeatures())
        for feat in features:
            fid = feat.id()
            street = self.street_names.get(fid, UNKNOWN)
            geom = QgsGeometry(feat.geometry())
            geom.transform(transform)

            if street not in index:
                index[street] = set()

            # Seuls les candidats proches sont testés
            for gid in grid_index.intersects(geom.boundingBox()):
                if geom.intersects(grid_geoms[gid]):
                    index[street].add(grid_refs[gid])
        return index

    def _sort_index(self, index):
        """Trie par nom ; écarte les noms sans aucun feuillet (hors emprise)."""
        sorted_idx = {}
        for name in sorted(index.keys(), key=lambda s: s.lower()):
            if not index[name]:
                continue
            refs = sorted(
                index[name],
                key=lambda r: (
                    ''.join(c for c in r if c.isalpha()),
                    int(''.join(c for c in r if c.isdigit()) or 0)
                )
            )
            sorted_idx[name] = refs
        return sorted_idx

    def _render_html(self, index):
        key = (self.format_name, self.orientation)
        rows_per_col = _ROWS_PER_COL.get(key, 28)
        page_css_size = _PAGE_CSS_SIZE.get(key, 'A4 landscape')
        pw_mm, ph_mm = _PAGE_MM.get(key, (297, 210))

        # « Inconnue » n'est pas une entrée d'index (même règle que le PDF)
        entries = [(k, v) for k, v in index.items() if k != UNKNOWN]
        total_entries = len(entries)
        col = _esc(self.column_title)
        sheets = self._tr('sheets')
        orient_lbl = self._tr('orient_' + self.orientation) \
            if ('orient_' + self.orientation) in _HTML_TR else self.orientation

        # Nombre d'entrées par page (2 colonnes côte à côte)
        per_page = rows_per_col * 2
        total_pages = max(1, math.ceil(total_entries / per_page))

        # Générer les pages
        pages_html = ''
        for page_num in range(total_pages):
            chunk = entries[page_num * per_page: (page_num + 1) * per_page]
            mid = math.ceil(len(chunk) / 2)
            left = chunk[:mid]
            right = chunk[mid:]

            rows_html = ''
            for i in range(max(len(left), len(right))):
                l_name, l_refs = left[i] if i < len(left) else ('', [])
                r_name, r_refs = right[i] if i < len(right) else ('', [])

                rows_html += (
                    f'<tr>'
                    f'<td class="street">{_esc(l_name)}</td>'
                    f'<td class="refs">{_esc(", ".join(l_refs))}</td>'
                    f'<td class="divider"></td>'
                    f'<td class="street">{_esc(r_name)}</td>'
                    f'<td class="refs">{_esc(", ".join(r_refs))}</td>'
                    f'</tr>\n'
                )

            is_last = (page_num == total_pages - 1)
            page_break = '' if is_last else 'page-break-after:always;'

            pages_html += f'''
        <div class="page" style="{page_break}">
            <div class="page-header">
                <span class="title">Index — {col}</span>
                <span class="page-num">{self._tr('page')} {page_num + 1} / {total_pages}</span>
            </div>
            <table class="index-table">
                <thead>
                    <tr>
                        <th>{col}</th>
                        <th>{sheets}</th>
                        <th class="divider"></th>
                        <th>{col}</th>
                        <th>{sheets}</th>
                    </tr>
                </thead>
                <tbody>
{rows_html}                </tbody>
            </table>
            <div class="page-footer">{total_entries} {self._tr('entries')} &mdash; {_esc(self.format_name)} {orient_lbl}</div>
        </div>'''

        # Ratio pour l'aperçu écran (base 900px de large)
        screen_w = 900
        screen_h = round(screen_w * ph_mm / pw_mm)

        csv_header = f"{self.column_title};{sheets}".replace('\\', '\\\\').replace("'", "\\'")
        csv_header = csv_header.replace('<', '\\x3c')

        return f'''<!DOCTYPE html>
<html lang="{self.lang}">
<head>
<meta charset="UTF-8">
<title>{self._tr('title')}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}

/* ---- Écran ---- */
body {{
    background: #c8c8c8;
    font-family: Arial, Helvetica, sans-serif;
    padding: 24px;
}}
.toolbar {{
    display: flex;
    gap: 10px;
    align-items: center;
    margin-bottom: 20px;
    flex-wrap: wrap;
}}
.search {{
    padding: 8px 12px;
    border: 1px solid #bbb;
    border-radius: 4px;
    font-size: .9em;
    width: 240px;
}}
.btn {{
    padding: 8px 16px;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: .88em;
    color: #fff;
}}
.btn-print {{ background: #2980b9; }}
.btn-print:hover {{ background: #2472a4; }}
.btn-csv   {{ background: #27ae60; }}
.btn-csv:hover {{ background: #219a52; }}

.page {{
    width: {screen_w}px;
    min-height: {screen_h}px;
    background: #fff;
    box-shadow: 0 3px 14px rgba(0,0,0,.25);
    margin: 0 auto 32px;
    padding: 20px 24px 16px;
    display: flex;
    flex-direction: column;
}}
.page-header {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    border-bottom: 2px solid #2c3e50;
    padding-bottom: 6px;
    margin-bottom: 8px;
}}
.title {{
    font-size: 1.05em;
    font-weight: bold;
    color: #2c3e50;
    letter-spacing: .5px;
}}
.page-num {{
    font-size: .8em;
    color: #7f8c8d;
}}
.index-table {{
    width: 100%;
    border-collapse: collapse;
    flex: 1;
    font-size: .82em;
}}
.index-table thead th {{
    background: #2c3e50;
    color: #fff;
    padding: 5px 7px;
    text-align: left;
    font-size: .85em;
}}
.index-table tbody td {{
    padding: 2px 7px;
    border-bottom: 1px solid #f0f0f0;
    vertical-align: top;
}}
.index-table tbody tr:nth-child(even) {{ background: #f7f8fa; }}
.index-table tbody tr.hidden {{ display: none; }}
.street {{
    font-weight: 500;
    width: 36%;
    max-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.refs {{
    color: #444;
    width: 14%;
    white-space: normal;
    word-break: break-word;
}}
td.divider, th.divider {{
    width: 16px;
    min-width: 16px;
    background: transparent;
    border-left: 1px solid #ccc !important;
    border-right: 1px solid #ccc !important;
    padding: 0 !important;
}}
.page-footer {{
    text-align: right;
    font-size: .72em;
    color: #aaa;
    margin-top: 6px;
    border-top: 1px solid #eee;
    padding-top: 4px;
}}

/* ---- Impression ---- */
@page {{
    size: {page_css_size};
    margin: 12mm 14mm;
}}
@media print {{
    body {{
        background: none;
        padding: 0;
    }}
    .toolbar {{ display: none !important; }}
    .page {{
        width: 100%;
        min-height: 0;
        box-shadow: none;
        padding: 0;
        margin: 0;
    }}
    .index-table {{
        font-size: 8pt;
    }}
    .index-table thead th {{
        font-size: 8pt;
    }}
    .title {{ font-size: 10pt; }}
    .page-footer {{ font-size: 7pt; }}
}}
</style>
</head>
<body>

<div class="toolbar">
    <input class="search" id="q" type="text"
           placeholder="{self._tr('search')}"
           oninput="filterRows()">
    <button class="btn btn-print" onclick="window.print()">&#128438; {self._tr('print')}</button>
    <button class="btn btn-csv" onclick="exportCsv()">&#128190; {self._tr('csv')}</button>
    <span style="font-size:.85em;color:#555;">{total_entries} {self._tr('entries')} &mdash; {total_pages} {self._tr('pages')}</span>
</div>

{pages_html}

<script>
function filterRows() {{
    var v = document.getElementById('q').value.toLowerCase().trim();
    document.querySelectorAll('.index-table tbody tr').forEach(function(r) {{
        if (!v) {{ r.classList.remove('hidden'); return; }}
        r.classList.toggle('hidden', r.textContent.toLowerCase().indexOf(v) === -1);
    }});
}}

function exportCsv() {{
    var lines = '\\uFEFF{csv_header}\\n';
    var seen = {{}};
    document.querySelectorAll('.index-table tbody tr').forEach(function(r) {{
        var cells = r.querySelectorAll('td:not(.divider)');
        for (var i = 0; i < cells.length; i += 2) {{
            var name = cells[i].textContent.trim();
            var refs = cells[i+1] ? cells[i+1].textContent.trim() : '';
            if (name && !seen[name]) {{
                seen[name] = true;
                lines += '"' + name.replace(/"/g,'""') + '";"' + refs.replace(/"/g,'""') + '"\\n';
            }}
        }}
    }});
    var b = new Blob([lines], {{type:'text/csv;charset=utf-8;'}});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(b);
    a.download = 'index_objets.csv';
    a.click();
}}
</script>
</body>
</html>'''
