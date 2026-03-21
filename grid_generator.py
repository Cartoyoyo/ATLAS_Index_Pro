import os
import math
import tempfile
import warnings
from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsRectangle,
    QgsField, QgsFields, QgsCoordinateTransform, QgsProject,
    QgsCoordinateReferenceSystem, QgsVectorFileWriter,
    QgsWkbTypes, QgsSpatialIndex
)
from qgis.PyQt.QtCore import QVariant


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

# Doit être identique à atlas_creator.LAYOUT_MARGIN_MM
LAYOUT_MARGIN_MM = 0.0


def row_to_letters(row_index):
    """
    Convertit un index de ligne (0-based) en lettres style Excel.
    0->A, 1->B, ..., 25->Z, 26->AA, 27->AB, ...
    """
    result = ""
    n = max(0, row_index) + 1
    while n > 0:
        n -= 1
        result = chr(65 + n % 26) + result
        n //= 26
    return result


class GridGenerator:
    def __init__(self, layer, crs, format_name, orientation, scale,
                 overlap_pct, margin_pct, extent_mode, drawn_extent=None):
        self.layer = layer
        self.crs = crs
        self.format_name = format_name
        self.orientation = orientation
        self.scale = scale
        self.overlap_pct = overlap_pct
        self.margin_pct = margin_pct
        if scale <= 0:
            raise ValueError(f"Scale must be > 0, got {scale}")
        self.extent_mode = extent_mode  # 0=all, 1=map_extent, 2=drawn
        self.drawn_extent = drawn_extent

    def get_printable_size_mm(self):
        """Retourne la taille du cadre carte (page - marge de mise en page)."""
        w, h = FORMATS_MM[self.format_name]
        if self.orientation == 'paysage':
            w, h = h, w
        return w - 2 * LAYOUT_MARGIN_MM, h - 2 * LAYOUT_MARGIN_MM

    def get_cell_size_crs_units(self):
        """Convertit la taille imprimable en dimensions terrain (unités du SCR).

        Si le SCR est géographique (degrés), convertit les mètres en degrés
        en utilisant le centre de l'emprise de la couche comme référence.
        """
        pw, ph = self.get_printable_size_mm()
        cell_w_m = pw * self.scale / 1000.0   # en mètres
        cell_h_m = ph * self.scale / 1000.0

        if not self.crs.isGeographic():
            return cell_w_m, cell_h_m

        # SCR géographique : convertir mètres → degrés
        # 1 degré de latitude ≈ 111 320 m (constant)
        # 1 degré de longitude ≈ 111 320 m × cos(latitude)
        extent = self.layer.extent()
        transform = QgsCoordinateTransform(
            self.layer.crs(), self.crs, QgsProject.instance()
        )
        center = transform.transform(extent.center())
        lat_rad = math.radians(center.y())

        meters_per_deg_lat = 111320.0
        meters_per_deg_lon = 111320.0 * math.cos(lat_rad)

        cell_w_deg = cell_w_m / meters_per_deg_lon
        cell_h_deg = cell_h_m / meters_per_deg_lat
        return cell_w_deg, cell_h_deg

    def get_extent(self):
        """Calcule l'emprise de travail selon le mode choisi."""
        transform_to_crs = QgsCoordinateTransform(
            self.layer.crs(), self.crs, QgsProject.instance()
        )

        if self.extent_mode == 0:  # Toutes les conduites
            extent = self.layer.extent()
            return transform_to_crs.transformBoundingBox(extent)

        elif self.extent_mode == 1:  # Emprise de la carte
            if self.drawn_extent:
                canvas_crs = QgsProject.instance().crs()
                transform = QgsCoordinateTransform(
                    canvas_crs, self.crs, QgsProject.instance()
                )
                return transform.transformBoundingBox(self.drawn_extent)
            # Fallback : emprise complète de la couche
            extent = self.layer.extent()
            return transform_to_crs.transformBoundingBox(extent)

        elif self.extent_mode == 2:  # Zone dessinée
            if self.drawn_extent:
                # L'emprise dessinée est dans le SCR du canevas (= SCR projet)
                canvas_crs = QgsProject.instance().crs()
                transform = QgsCoordinateTransform(
                    canvas_crs, self.crs, QgsProject.instance()
                )
                return transform.transformBoundingBox(self.drawn_extent)
            # Fallback
            extent = self.layer.extent()
            return transform_to_crs.transformBoundingBox(extent)

        elif self.extent_mode == 3:  # Lasso (sélection cumulative)
            if self.layer.selectedFeatureCount() > 0:
                bbox = QgsRectangle()
                bbox.setNull()
                for feat in self.layer.selectedFeatures():
                    bbox.combineExtentWith(feat.geometry().boundingBox())
                return transform_to_crs.transformBoundingBox(bbox)
            extent = self.layer.extent()
            return transform_to_crs.transformBoundingBox(extent)

    def _build_conduite_index(self):
        """
        Transforme les géométries des conduites dans le SCR de travail
        et construit un index spatial pour les tests d'intersection.
        """
        transform = QgsCoordinateTransform(
            self.layer.crs(), self.crs, QgsProject.instance()
        )

        if self.extent_mode == 3 and self.layer.selectedFeatureCount() > 0:
            features = self.layer.selectedFeatures()
        else:
            features = list(self.layer.getFeatures())

        geoms = {}
        spatial_index = QgsSpatialIndex()

        for i, feat in enumerate(features):
            geom = QgsGeometry(feat.geometry())
            geom.transform(transform)
            temp_feat = QgsFeature()
            temp_feat.setId(i)
            temp_feat.setGeometry(geom)
            spatial_index.addFeature(temp_feat)
            geoms[i] = geom

        return spatial_index, geoms

    def generate(self, output_dir):
        """Génère la grille et la sauvegarde en GeoJSON. Retourne le QgsVectorLayer."""
        extent = self.get_extent()
        if extent is None or extent.isNull() or extent.isEmpty():
            raise ValueError("Cannot generate grid: layer extent is empty or invalid.")
        cell_w, cell_h = self.get_cell_size_crs_units()

        # Agrandir l'emprise selon la marge (% de la cellule)
        if self.margin_pct > 0:
            margin_x = cell_w * self.margin_pct / 100.0
            margin_y = cell_h * self.margin_pct / 100.0
            extent = QgsRectangle(
                extent.xMinimum() - margin_x,
                extent.yMinimum() - margin_y,
                extent.xMaximum() + margin_x,
                extent.yMaximum() + margin_y,
            )

        overlap_x = cell_w * self.overlap_pct / 100.0
        overlap_y = cell_h * self.overlap_pct / 100.0

        step_x = cell_w - overlap_x
        step_y = cell_h - overlap_y

        x_min = extent.xMinimum()
        y_max = extent.yMaximum()
        x_max = extent.xMaximum()
        y_min = extent.yMinimum()

        cols = max(1, math.ceil((x_max - x_min) / step_x))
        rows = max(1, math.ceil((y_max - y_min) / step_y))

        # Index spatial des conduites
        spatial_index, conduite_geoms = self._build_conduite_index()

        # Couche mémoire de sortie
        grid_layer = QgsVectorLayer(
            f'Polygon?crs={self.crs.authid()}',
            'Grille feuillets',
            'memory'
        )
        dp = grid_layer.dataProvider()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            dp.addAttributes([
                QgsField('id', QVariant.Int),
                QgsField('reference', QVariant.String),
                QgsField('lettre', QVariant.String),
                QgsField('numero', QVariant.Int),
                QgsField('format', QVariant.String),
                QgsField('echelle', QVariant.Int),
            ])
        grid_layer.updateFields()

        features_to_add = []
        feat_id = 0

        for row in range(rows):
            letter = row_to_letters(row)
            for col in range(cols):
                x1 = x_min + col * step_x
                y1 = y_max - row * step_y
                x2 = x1 + cell_w
                y2 = y1 - cell_h

                rect = QgsRectangle(x1, y2, x2, y1)
                rect_geom = QgsGeometry.fromRect(rect)

                # Test d'intersection via l'index spatial
                candidates = spatial_index.intersects(rect)
                intersects = False
                for idx in candidates:
                    if rect_geom.intersects(conduite_geoms[idx]):
                        intersects = True
                        break

                if not intersects:
                    continue

                number = col + 1
                reference = f"{letter}{number}"

                feat = QgsFeature(grid_layer.fields())
                feat.setGeometry(rect_geom)
                feat.setAttributes([feat_id, reference, letter, number,
                                    self.format_name, self.scale])
                features_to_add.append(feat)
                feat_id += 1

        dp.addFeatures(features_to_add)
        grid_layer.updateExtents()

        # Déterminer le répertoire de sauvegarde (temp si non fourni)
        save_dir = output_dir if output_dir else tempfile.mkdtemp(prefix='atlas_')
        output_path = os.path.join(save_dir, 'grille_feuillets.geojson')

        self._save_geojson(grid_layer, output_path)

        # Recharger depuis le fichier
        saved_layer = QgsVectorLayer(output_path, 'Grille feuillets', 'ogr')
        if saved_layer.isValid():
            return saved_layer

        # Fallback : couche mémoire si la relecture échoue
        return grid_layer

    def _save_geojson(self, layer, path):
        """Sauvegarde compatible multi-versions QGIS."""
        try:
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GeoJSON"
            options.fileEncoding = "UTF-8"
            QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, path,
                QgsProject.instance().transformContext(),
                options
            )
        except AttributeError:
            QgsVectorFileWriter.writeAsVectorFormat(
                layer, path, "UTF-8", self.crs, "GeoJSON"
            )