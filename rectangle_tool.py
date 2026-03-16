from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.core import QgsRectangle, QgsWkbTypes, QgsPointXY
from qgis.PyQt.QtCore import pyqtSignal, Qt
from qgis.PyQt.QtGui import QColor


class RectangleMapTool(QgsMapTool):
    """Outil carte pour dessiner un rectangle (clic-glisser)."""

    rectangleCreated = pyqtSignal(QgsRectangle)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.rubber_band = None
        self.start_point = None
        self.end_point = None
        self.is_drawing = False

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_point = self.toMapCoordinates(event.pos())
            self.end_point = self.start_point
            self.is_drawing = True
            self._update_rubber_band()

    def canvasMoveEvent(self, event):
        if not self.is_drawing:
            return
        self.end_point = self.toMapCoordinates(event.pos())
        self._update_rubber_band()

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_drawing:
            self.end_point = self.toMapCoordinates(event.pos())
            self.is_drawing = False

            if self.rubber_band:
                self.rubber_band.reset()
                self.rubber_band = None

            rect = QgsRectangle(self.start_point, self.end_point)
            rect.normalize()

            if rect.width() > 0 and rect.height() > 0:
                self.rectangleCreated.emit(rect)

    def _update_rubber_band(self):
        if self.rubber_band:
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        else:
            self.rubber_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
            self.rubber_band.setColor(QColor(255, 0, 0, 40))
            self.rubber_band.setStrokeColor(QColor(255, 0, 0, 200))
            self.rubber_band.setWidth(2)

        if self.start_point and self.end_point:
            p1 = self.start_point
            p2 = QgsPointXY(self.end_point.x(), self.start_point.y())
            p3 = self.end_point
            p4 = QgsPointXY(self.start_point.x(), self.end_point.y())
            self.rubber_band.addPoint(p1, False)
            self.rubber_band.addPoint(p2, False)
            self.rubber_band.addPoint(p3, False)
            self.rubber_band.addPoint(p4, True)
            self.rubber_band.show()

    def deactivate(self):
        if self.rubber_band:
            self.rubber_band.reset()
            self.rubber_band = None
        super().deactivate()