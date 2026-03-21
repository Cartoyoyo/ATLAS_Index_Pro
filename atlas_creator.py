from qgis.core import (
    QgsProject, QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLabel,
    QgsLayoutPoint, QgsLayoutSize, QgsUnitTypes, QgsTextFormat,
    QgsCoordinateReferenceSystem
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont, QColor


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


class AtlasCreator:
    """Crée une mise en page Atlas dans le projet QGIS."""

    def __init__(self, iface, grid_layer, format_name, orientation, scale):
        self.iface = iface
        self.grid_layer = grid_layer
        self.format_name = format_name
        self.orientation = orientation
        self.scale = scale

    def create(self):
        project = QgsProject.instance()
        manager = project.layoutManager()

        # Supprimer si existe déjà
        for name in ("ATLAS Index Pro", "Atlas", "Atlas Conduites"):
            existing = manager.layoutByName(name)
            if existing:
                manager.removeLayout(existing)

        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName("ATLAS Index Pro")

        # Dimensions de la page
        w, h = FORMATS_MM[self.format_name]
        if self.orientation == 'paysage':
            w, h = h, w

        page = layout.pageCollection().page(0)
        page.setPageSize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))

        # ── Carte principale ──
        # Taille et position AVANT ajout au layout (sinon attemptResize → NaN)
        map_item = QgsLayoutItemMap(layout)
        map_item.attemptMove(QgsLayoutPoint(0, 0, QgsUnitTypes.LayoutMillimeters))
        map_item.attemptResize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))
        map_item.setKeepLayerSet(False)
        layout.addLayoutItem(map_item)

        # Emprise initiale = 1ère cellule (nécessaire pour que setScale fonctionne)
        first = next(self.grid_layer.getFeatures(), None)
        if first is None:
            raise ValueError("Grid layer is empty — cannot create atlas layout.")
        map_item.setExtent(first.geometry().boundingBox())

        # ── Étiquette référence (bas droit, semi-transparente) ──
        label = QgsLayoutItemLabel(layout)
        label.setText('[% "reference" %]')
        fmt = QgsTextFormat()
        fmt.setFont(QFont('Arial', 28, QFont.Bold))
        fmt.setColor(QColor(0, 0, 0, 120))
        label.setTextFormat(fmt)
        label.setBackgroundEnabled(True)
        label.setBackgroundColor(QColor(255, 255, 255, 80))
        label_w, label_h = 40.0, 16.0
        label.attemptMove(QgsLayoutPoint(
            w - label_w - 2, h - label_h - 2,
            QgsUnitTypes.LayoutMillimeters
        ))
        label.attemptResize(QgsLayoutSize(
            label_w, label_h, QgsUnitTypes.LayoutMillimeters
        ))
        label.setHAlign(Qt.AlignRight)
        label.setVAlign(Qt.AlignBottom)
        layout.addLayoutItem(label)

        # ── Configuration de l'Atlas ──
        atlas = layout.atlas()
        atlas.setEnabled(True)
        atlas.setCoverageLayer(self.grid_layer)
        atlas.setPageNameExpression('"reference"')

        # La carte suit l'atlas
        map_item.setAtlasDriven(True)

        # SCR géographique (degrés) : ajuster à l'emprise de la cellule
        # SCR projeté (mètres) : échelle fixe
        crs = project.crs()
        if crs.isGeographic():
            map_item.setAtlasScalingMode(QgsLayoutItemMap.Auto)
            map_item.setAtlasMargin(0.0)
        else:
            map_item.setAtlasScalingMode(QgsLayoutItemMap.Fixed)

        # Ajout au manager, rafraîchir, positionner, PUIS forcer l'échelle
        manager.addLayout(layout)
        atlas.updateFeatures()
        atlas.seekTo(0)
        if not crs.isGeographic():
            map_item.setScale(self.scale)

        return layout
