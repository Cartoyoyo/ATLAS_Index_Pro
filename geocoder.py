import csv
import io
import json
from urllib.request import urlopen, Request
from qgis.core import (
    QgsCoordinateTransform, QgsProject, QgsCoordinateReferenceSystem,
    QgsSpatialIndex, QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
    QgsField
)
from qgis.PyQt.QtCore import QVariant

# L'API BAN /reverse/csv/ accepte max ~10 000 lignes par requête.
# On découpe en lots pour rester sous la limite et éviter les timeouts.
BAN_BATCH_SIZE = 5000


class Geocoder:
    """Récupère les noms d'adresses associés aux objets.
    Sources :
      - 'field'  : champ existant
      - 'ban'    : BAN (France), avec fallback OSM sur les "Inconnue"
      - 'osm'    : voies OSM — 1 requête Overpass sur l'emprise de la grille
    """

    def __init__(self, layer, crs, field_name=None, source='field',
                 grid_layer=None, progress_callback=None):
        self.layer = layer
        self.crs = crs
        self.field_name = field_name
        self.source = source
        self.grid_layer = grid_layer  # requis pour 'osm' et fallback BAN
        self.progress_callback = progress_callback

    def get_street_names(self):
        """Retourne un dict {feature_id: adresse}."""
        if self.source == 'ban':
            return self._from_ban()
        if self.source == 'osm':
            return self._from_osm()
        return self._from_field()

    # ---------------------------------------------------------------- utils
    def _to_wgs84(self, layer):
        return QgsCoordinateTransform(
            layer.crs(),
            QgsCoordinateReferenceSystem('EPSG:4326'),
            QgsProject.instance()
        )

    def _centroid_wgs84(self, feat, transform):
        pt = transform.transform(feat.geometry().centroid().asPoint())
        return pt.y(), pt.x()

    # ---------------------------------------------------------------- field
    def _from_field(self):
        result = {}
        for feat in self.layer.getFeatures():
            val = feat[self.field_name] if self.field_name else None
            result[feat.id()] = str(val).strip() if val and str(val).strip() else "Inconnue"
        return result

    # ---------------------------------------------------------------- OSM
    def _fetch_osm_roads(self):
        """
        1 requête Overpass sur l'emprise de la grille.
        Retourne une liste de (nom, lat_centre, lon_centre).
        """
        if not self.grid_layer:
            return []

        t_grid = self._to_wgs84(self.grid_layer)
        bbox = t_grid.transformBoundingBox(self.grid_layer.extent())

        query = (
            f'[out:json][timeout:30];'
            f'(way["highway"]["name"]'
            f'({bbox.yMinimum():.6f},{bbox.xMinimum():.6f}'
            f',{bbox.yMaximum():.6f},{bbox.xMaximum():.6f}););'
            f'out center tags;'
        )
        try:
            req = Request(
                'https://overpass-api.de/api/interpreter',
                data=query.encode('utf-8'),
                headers={
                    'User-Agent': 'QGIS-Atlas/1.0',
                    'Content-Type': 'application/x-www-form-urlencoded',
                }
            )
            data = json.loads(urlopen(req, timeout=35).read().decode('utf-8'))
        except Exception:
            return []

        roads = []
        for elem in data.get('elements', []):
            name   = elem.get('tags', {}).get('name')
            center = elem.get('center')
            if name and center:
                roads.append((name, center['lat'], center['lon']))
        return roads

    def _match_osm(self, feature_ids, roads):
        """Associe chaque feature_id à la voie OSM la plus proche via index spatial."""
        # Construire un index spatial des routes OSM
        road_names = {}
        road_index = QgsSpatialIndex()
        for i, (name, lat, lon) in enumerate(roads):
            feat = QgsFeature()
            feat.setId(i)
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
            road_index.addFeature(feat)
            road_names[i] = name

        result = {}
        t_obj = self._to_wgs84(self.layer)
        id_set = set(feature_ids)

        for feat in self.layer.getFeatures():
            if feat.id() not in id_set:
                continue
            lat, lon = self._centroid_wgs84(feat, t_obj)
            pt = QgsGeometry.fromPointXY(QgsPointXY(lon, lat))
            nearest_ids = road_index.nearestNeighbor(pt.asPoint(), 1)
            if nearest_ids:
                result[feat.id()] = road_names[nearest_ids[0]]
            else:
                result[feat.id()] = "Inconnue"
        return result

    def _from_osm(self):
        """Géocodage pur OSM pour tous les objets."""
        roads = self._fetch_osm_roads()
        if not roads:
            return {feat.id(): "Inconnue" for feat in self.layer.getFeatures()}
        return self._match_osm(
            [feat.id() for feat in self.layer.getFeatures()],
            roads
        )

    # ---------------------------------------------------------------- BAN
    def _ban_reverse_csv(self, rows):
        """
        Envoie un lot de (fid, lat, lon) à l'API BAN /reverse/csv/.
        Retourne un dict {fid: adresse}.
        """
        # Construction du CSV à envoyer
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['fid', 'latitude', 'longitude'])
        for fid, lat, lon in rows:
            writer.writerow([fid, f'{lat:.7f}', f'{lon:.7f}'])
        csv_bytes = buf.getvalue().encode('utf-8')

        # Requête multipart/form-data
        boundary = '----BAN_BATCH_BOUNDARY'
        body = (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="data"; filename="batch.csv"\r\n'
            f'Content-Type: text/csv\r\n\r\n'
        ).encode('utf-8') + csv_bytes + (
            f'\r\n--{boundary}\r\n'
            f'Content-Disposition: form-data; name="type"\r\n\r\nstreet\r\n'
            f'--{boundary}--\r\n'
        ).encode('utf-8')

        req = Request(
            'https://api-adresse.data.gouv.fr/reverse/csv/',
            data=body,
            headers={
                'User-Agent': 'QGIS-ATLAS_Index_Pro/2.0',
                'Content-Type': f'multipart/form-data; boundary={boundary}',
            }
        )

        result = {}
        try:
            resp = urlopen(req, timeout=60).read().decode('utf-8')
            reader = csv.DictReader(io.StringIO(resp))
            for row in reader:
                fid = int(row['fid'])
                name = (row.get('result_name') or row.get('result_label') or '').strip()
                result[fid] = name if name else "Inconnue"
        except Exception:
            # Si le batch échoue, tout est "Inconnue" → le fallback OSM prendra le relais
            for fid, _, _ in rows:
                result[fid] = "Inconnue"

        return result

    def _from_ban(self):
        """
        Géocodage BAN batch via /reverse/csv/ (1 requête par lot de 5000).
        Les objets restés "Inconnue" sont ensuite traités par
        la méthode OSM (1 requête Overpass pour tous les inconnus).
        """
        features = list(self.layer.getFeatures())
        transform = self._to_wgs84(self.layer)
        total = len(features)

        # Préparer les coordonnées WGS84 de chaque objet
        rows = []
        for feat in features:
            lat, lon = self._centroid_wgs84(feat, transform)
            rows.append((feat.id(), lat, lon))

        # Envoi par lots
        result = {}
        for batch_start in range(0, total, BAN_BATCH_SIZE):
            batch = rows[batch_start:batch_start + BAN_BATCH_SIZE]
            batch_result = self._ban_reverse_csv(batch)
            result.update(batch_result)

            if self.progress_callback:
                self.progress_callback(
                    min(batch_start + BAN_BATCH_SIZE, total), total
                )

        # Fallback OSM pour les objets non résolus par la BAN
        unknown_ids = [fid for fid, name in result.items() if name == "Inconnue"]
        if unknown_ids and self.grid_layer:
            roads = self._fetch_osm_roads()
            if roads:
                osm_result = self._match_osm(unknown_ids, roads)
                result.update(osm_result)

        return result
