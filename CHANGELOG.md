# Changelog

All notable changes to this project are documented in this file.

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
