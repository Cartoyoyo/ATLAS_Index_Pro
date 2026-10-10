# Changelog

All notable changes to this project are documented in this file.

---

## [3.2.0] - 2026-10-10

### Fixed
- **BAN geocoding**: the `/reverse/csv/` request sent a `type=street` form field, now read by the API as a CSV column name → HTTP 400 on every call. Field removed; street names read from `result_street` (no house numbers in the index).
- **Retry / continue without index** dialog never appeared: a failed lookup yields "Inconnue" entries, so the index was never empty. The check now requires at least one real name.
- **Index hyperlinks**: index references are now real PDF links to their atlas sheet (pypdf and built-in merge).
- **Built-in PDF merge** (no pypdf): duplicated overview page (GDAL incremental update), invalid xref entries (21 bytes) and no bookmarks — rewritten parser (stream-aware, last definition wins), valid xref, bookmarks and links.
- **WMS coverage tool**: sibling layer source rebuilt verbatim (lower-cased keys and the bare `styles` token made it invalid), scale ranges were inverted, `authcfg` now applied to GetCapabilities, XML parsed with QDomDocument (Bandit B314/B405), FR/EN messages.
- **Overview scale bar** showed only "0" (no segment size).
- Single point / aligned points layer (zero-area extent) failed with a raw error; empty layer now gets a translated message.
- Locked output PDF (open in a viewer) is detected before rendering; temporary PDFs are removed on failure or cancel.
- **Cancel** now stops the PDF export (between batches) instead of producing the full PDF.
- "Current map extent" mode no longer overwrites the drawn rectangle.
- Escape / switching map tool while drawing a rectangle or lasso brings the dialog back.
- Custom format: landscape/portrait now follow the chosen orientation whatever the W×H order.
- Field value `0` was indexed as "Inconnue"; HTML index lists only named entries with sheets; lasso mode geocodes the selection only.
- Sheets rendered after the 60 s timeout are reported (log + final message) instead of silently written incomplete.
- Grid without output directory no longer leaves an `atlas_*` temp folder per run.
- Plugin unload closes the open dialog.

### Changed
- Polygon layers accepted as source layer.
- Warning before generating in a geographic CRS or a CRS distorting distances (e.g. Web Mercator): printed scale would be wrong.
- Default PDF resolution 150 dpi; default PDF title includes the orientation; first bookmark "Cover page".
- HTML index and WMS tool translated; About: author link to LinkedIn.
- pyflakes clean (unused imports, f-string, duplicate import); Bandit clean (named exceptions).
- All Qt/QGIS enums scoped (Qt5 and Qt6 compatible).

---

## [3.1.0] - 2026-07-16

### Fixed
- **Crash on atlas export**: `QgsLayoutAtlas` has no `feature()`/`currentFeature()` method in the public PyQGIS API — sheet references are now read directly from the grid layer instead of driving the atlas.
- Geographic index generation now warns and offers **retry / continue without index / cancel** when street name lookup fails (BAN/OSM unavailable).

### Added
- **WMS orthophoto coverage tool** (Advanced settings → *Couverture WMS*): detects a scale-limited pre-cached WMS layer (e.g. a tiled orthophoto only covering coarser scales), queries `GetCapabilities` for a non-cached sibling layer, and configures scale-based visibility on both — fixes systematic tile 404s and multi-minute export slowdowns at fine scales.

### Changed
- **Atlas sheet export rewritten**: sheets are now rendered in concurrent batches (`QgsMapRendererParallelJob`, cloned layers per batch — required for thread safety, since concurrent jobs must never share the same `QgsMapLayer` instance) instead of one `QgsLayoutExporter.exportToPdf()` call per sheet in sequence. Major speedup on WMS-heavy atlases.
- Label rendering uses `Qgis.TextRenderFormat.AlwaysText` instead of vector outlines — faster and lighter output files.

---

## [3.0.2] - 2026-06-27

### Fixed
- **Security**: `geocoder.py` — new `_safe_urlopen()` helper rejects any non-HTTPS URL before opening a network connection (Bandit B310).
- **Code quality**: removed unused imports across 7 files (`QgsCoordinateReferenceSystem`, `QgsVectorLayer`, `QgsField`, `QVariant`, `QgsFields`, `QgsWkbTypes`, `QgsFeature`, `tempfile`, `QgsTextFormat`, `QMarginsF`, `QPageLayout`, `QgsPropertyDefinition`, `datetime`, `QScrollArea`).
- Fixed bare f-string without placeholder (`pdf_exporter.py`), lambda assignment replaced by `def` (`dialog.py`), alignment and line-length issues.

---

## [3.0.0] - 2026-03-21

### Added
- **Universal PDF merge**: pure Python merger with no external dependency (pypdf/PyPDF2 optional). Works on any QGIS installation.
- **Dynamic index column title**: when using an existing field instead of geocoding, the column header reflects the field name.
- **24 bug fixes**: input validation, signal management, encoding, extent checks, HTML escaping, temp file cleanup, CRS validation, and more (see CORRECTIONS.md).

### Changed
- Default DPI reduced from 300 to 150 for faster exports.
- License corrected to **GNU GPL v3** (About dialog, metadata, skill).
- About dialog simplified: author with mailto link, no organization name.
- Layout designer no longer opens automatically after export.
- Folder explorer stays in foreground when user clicks "Open folder".
- PDF export optimized: throttled UI updates, geometry simplification flags.
- Deprecated `setFilters()` replaced with `setLayerFilter()` (QGIS 3.x compat).

---

## [2.0.0] - 2026-03-16

### Added
- **Full PDF export**: single-file PDF document combining cover page, geographic index, overview map, atlas sheets, and blank filler page.
- **Hyperlinks**: each index entry links directly to the corresponding atlas sheet page in the PDF.
- **Overview map** (plan d'ensemble): summary map inserted between the index and the atlas sheets, showing all sheets in geographic context.
- **DPI setting**: configurable output resolution in the advanced parameters dialog.
- **Multilingual interface**: French, English, Spanish, Portuguese and German — switchable at runtime without restarting.
- Renamed plugin from previous working title to **ATLAS Index Pro**.

### Changed
- Advanced parameters dialog extended with DPI and overview map options.

---

## [1.1.0] - 2025

### Added
- Bilingual FR/EN interface with runtime language toggle — no restart required.
- Optional geographic index creation — paginated HTML index matching the chosen paper format.
- Grid layer auto-styled: transparent fill, black border, sheet reference label.
- Advanced settings dialog: sheet overlap and object margin parameters.

### Changed
- Plugin generalised to work with any vector object type (not limited to pipe networks).

---

## [1.0.0] - 2025

### Added
- Initial release.
- Automatic atlas sheet grid generation (A4/A3, portrait/landscape, configurable scale) from any vector layer extent.
- Sheet numbering and reference labelling.
- Basic PDF export of atlas sheets.
