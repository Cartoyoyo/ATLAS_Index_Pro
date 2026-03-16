# Changelog

All notable changes to this project are documented in this file.

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
