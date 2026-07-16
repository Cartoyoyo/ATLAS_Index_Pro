"""Détection + configuration automatique de la couverture d'une couche WMS
orthophoto précachée limitée en échelle (cas CRAIG/RTGE : la couche
principale ne sert des tuiles que jusqu'à un certain niveau de zoom ; le
serveur expose une couche soeur non précachée, nommée '<couche>_AAAA', pour
les échelles plus fines — voir son résumé WMS, ex. "affichée en dessous de
1:2000 et non précachée").

Le seuil est lu dans le résumé (Abstract) de la couche soeur la plus
récente ; s'il n'est pas trouvable automatiquement, l'utilisateur est
invité à le saisir. Une fois validé, la couche soeur est ajoutée au projet
et les deux couches reçoivent des plages de visibilité par échelle
complémentaires (voir QgsMapLayer::isInScaleRange : minimumScale = borne
basse du dénominateur d'échelle -zoom avant-, maximumScale = borne haute
-zoom arrière-).
"""
import re
from urllib.parse import urlparse, parse_qs, unquote, urlencode
import xml.etree.ElementTree as ET

from qgis.core import QgsProject, QgsRasterLayer, QgsBlockingNetworkRequest
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.PyQt.QtWidgets import QMessageBox, QInputDialog

_WMS_NS = '{http://www.opengis.net/wms}'
_SCALE_HINT_RE = re.compile(r"en\s+dessous\s+de\s*1\s*[:/]\s*([\d\s ]+)", re.IGNORECASE)


def _parse_wms_source(layer):
    """Retourne (base_url, nom_couche, dict des paramètres) depuis la source QGIS."""
    params = {}
    for part in layer.source().split('&'):
        if '=' not in part:
            continue
        k, _, v = part.partition('=')
        params[k.lower()] = v
    base_url = unquote(params.get('url', ''))
    layer_name = unquote(params.get('layers', ''))
    return base_url, layer_name, params


def _build_capabilities_url(base_url):
    parsed = urlparse(base_url)
    qs = parse_qs(parsed.query)
    qs['SERVICE'] = ['WMS']
    qs['REQUEST'] = ['GetCapabilities']
    qs.setdefault('VERSION', ['1.3.0'])
    query = urlencode({k: v[0] for k, v in qs.items()})
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{query}"


def _fetch_capabilities_xml(url):
    request = QNetworkRequest(QUrl(url))
    blocking = QgsBlockingNetworkRequest()
    err = blocking.get(request, forceRefresh=True)
    if err != QgsBlockingNetworkRequest.NoError:
        raise RuntimeError(f"Échec GetCapabilities ({err}) : {url}")
    return bytes(blocking.reply().content()).decode('utf-8', errors='replace')


def _find_sibling_layers(xml_text, base_name):
    """Couches nommées '<base_name>_AAAA', triées de la plus récente à la plus ancienne."""
    root = ET.fromstring(xml_text)
    pattern = re.compile(rf'^{re.escape(base_name)}_(\d{{4}})$')
    results = []
    for layer_el in root.iter(f'{_WMS_NS}Layer'):
        name_el = layer_el.find(f'{_WMS_NS}Name')
        if name_el is None or not name_el.text:
            continue
        m = pattern.match(name_el.text.strip())
        if not m:
            continue
        title_el = layer_el.find(f'{_WMS_NS}Title')
        abstract_el = layer_el.find(f'{_WMS_NS}Abstract')
        results.append((
            name_el.text.strip(),
            title_el.text.strip() if title_el is not None and title_el.text else '',
            abstract_el.text.strip() if abstract_el is not None and abstract_el.text else '',
            int(m.group(1)),
        ))
    results.sort(key=lambda r: -r[3])
    return results


def _extract_scale_threshold(text):
    m = _SCALE_HINT_RE.search(text or '')
    if not m:
        return None
    digits = re.sub(r'[\s ]', '', m.group(1))
    try:
        return int(digits)
    except ValueError:
        return None


def fix_ortho_coverage(iface, parent):
    """Point d'entrée UI : détecte et configure la couverture WMS orthophoto."""
    project = QgsProject.instance()
    candidates = [
        lyr for lyr in project.mapLayers().values()
        if getattr(lyr, 'providerType', lambda: None)() == 'wms'
        and 'type=xyz' not in lyr.source().lower()
        and 'wmts' not in lyr.source().lower()
    ]
    if not candidates:
        QMessageBox.information(
            parent, "Couverture WMS",
            "Aucune couche WMS (hors XYZ/WMTS) trouvée dans le projet.")
        return

    if len(candidates) == 1:
        layer = candidates[0]
    else:
        names = [lyr.name() for lyr in candidates]
        choice, ok = QInputDialog.getItem(
            parent, "Couverture WMS",
            "Couche orthophoto précachée à corriger :", names, 0, False)
        if not ok:
            return
        layer = candidates[names.index(choice)]

    base_url, layer_name, params = _parse_wms_source(layer)
    if not base_url or not layer_name:
        QMessageBox.warning(parent, "Couverture WMS",
                             "Impossible de lire l'URL/le nom de couche WMS "
                             f"pour '{layer.name()}'.")
        return

    try:
        xml_text = _fetch_capabilities_xml(_build_capabilities_url(base_url))
        siblings = _find_sibling_layers(xml_text, layer_name)
    except Exception as e:
        QMessageBox.critical(parent, "Couverture WMS",
                              f"Échec de la lecture du GetCapabilities :\n{e}")
        return

    if not siblings:
        QMessageBox.information(
            parent, "Couverture WMS",
            f"Aucune couche '{layer_name}_AAAA' trouvée sur ce serveur pour "
            f"'{layer.name()}' — rien à configurer automatiquement.")
        return

    sibling_name, sibling_title, sibling_abstract, _year = siblings[0]
    threshold = _extract_scale_threshold(sibling_abstract)
    if threshold is None:
        threshold, ok = QInputDialog.getInt(
            parent, "Couverture WMS",
            f"Seuil d'échelle non détecté automatiquement dans le résumé de "
            f"'{sibling_name}' :\n« {sibling_abstract} »\n\n"
            "Entrez le dénominateur d'échelle en dessous duquel cette couche "
            "doit être utilisée (ex. 2000 pour 1:2000) :",
            2000, 1, 1000000)
        if not ok:
            return

    msg = (f"Couche soeur trouvée : {sibling_name} ({sibling_title})\n\n"
           f"Configuration proposée :\n"
           f"  • {layer.name()} : visible à partir de 1:{threshold} (zoom arrière)\n"
           f"  • {sibling_name} : visible en dessous de 1:{threshold} (zoom avant)\n\n"
           "Ajouter la couche et configurer les plages d'échelle des deux "
           "couches ?")
    if QMessageBox.question(parent, "Couverture WMS", msg,
                             QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
        return

    new_params = dict(params)
    new_params['layers'] = sibling_name
    new_source = '&'.join(f"{k}={v}" for k, v in new_params.items())
    new_layer = QgsRasterLayer(new_source, sibling_name, 'wms')
    if not new_layer.isValid():
        QMessageBox.critical(parent, "Couverture WMS",
                              f"La couche '{sibling_name}' n'a pas pu être chargée "
                              "(source WMS invalide).")
        return

    project.addMapLayer(new_layer, False)
    root = project.layerTreeRoot()
    node = root.findLayer(layer.id())
    group = node.parent() if node else root
    idx = group.children().index(node) if node else 0
    group.insertLayer(idx, new_layer)

    # cf. QgsMapLayer::isInScaleRange : visible quand
    # minimumScale <= dénominateur < maximumScale (0 = pas de borne)
    layer.setScaleBasedVisibility(True)
    layer.setMinimumScale(float(threshold))
    layer.setMaximumScale(0.0)

    new_layer.setScaleBasedVisibility(True)
    new_layer.setMinimumScale(0.0)
    new_layer.setMaximumScale(float(threshold))

    if iface is not None:
        iface.mapCanvas().refresh()

    QMessageBox.information(
        parent, "Couverture WMS",
        f"'{sibling_name}' ajoutée et plages d'échelle configurées "
        f"(seuil 1:{threshold}). Pensez à enregistrer le projet.")
