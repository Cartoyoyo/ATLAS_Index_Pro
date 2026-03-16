from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.core import QgsWkbTypes, QgsPointXY, QgsGeometry
from qgis.PyQt.QtCore import pyqtSignal, Qt
from qgis.PyQt.QtGui import QColor


class LassoMapTool(QgsMapTool):
    """Outil carte pour dessiner un polygone libre (lasso).
    Clic gauche = ajouter un point, clic droit = fermer le polygone.
    Le signal lassoFinished émet la géométrie polygonale résultante.
    """

    lassoFinished = pyqtSignal(QgsGeometry)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.rubber_band = None
        self.points = []

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pt = self.toMapCoordinates(event.pos())
            self.points.append(pt)
            self._update_rubber_band()

        elif event.button() == Qt.RightButton:
            self._finish()

    def canvasMoveEvent(self, event):
        if not self.points:
            return
        # Aperçu dynamique : polygone courant + curseur
        pt = self.toMapCoordinates(event.pos())
        self._update_rubber_band(preview_point=pt)

    def _update_rubber_band(self, preview_point=None):
        if self.rubber_band:
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        else:
            self.rubber_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
            self.rubber_band.setColor(QColor(0, 120, 255, 40))
            self.rubber_band.setStrokeColor(QColor(0, 120, 255, 200))
            self.rubber_band.setWidth(2)

        for pt in self.points:
            self.rubber_band.addPoint(pt, False)

        if preview_point:
            self.rubber_band.addPoint(preview_point, False)

        # Fermer visuellement le polygone
        if self.points:
            self.rubber_band.addPoint(self.points[0], True)

        self.rubber_band.show()

    def _finish(self):
        if self.rubber_band:
            self.rubber_band.reset()
            self.rubber_band = None

        if len(self.points) >= 3:
            # Fermer le polygone
            ring = [QgsPointXY(p) for p in self.points]
            ring.append(ring[0])
            geom = QgsGeometry.fromPolygonXY([ring])
            self.lassoFinished.emit(geom)

        self.points = []

    def deactivate(self):
        if self.rubber_band:
            self.rubber_band.reset()
            self.rubber_band = None
        self.points = []
        super().deactivate()
