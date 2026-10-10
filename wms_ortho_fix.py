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

from qgis.core import QgsProject, QgsRasterLayer, QgsBlockingNetworkRequest
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.PyQt.QtWidgets import QMessageBox, QInputDialog
from qgis.PyQt.QtXml import QDomDocument

_WMS_NS = 'http://www.opengis.net/wms'
_SCALE_HINT_RE = re.compile(r"en\s+dessous\s+de\s*1\s*[:/]\s*([\d\s ]+)", re.IGNORECASE)

_TR = {
    'title': {'fr': "Couverture WMS", 'en': "WMS coverage"},
    'none': {'fr': "Aucune couche WMS (hors XYZ/WMTS) trouvée dans le projet.",
             'en': "No WMS layer (excluding XYZ/WMTS) found in the project."},
    'choose': {'fr': "Couche orthophoto précachée à corriger :",
               'en': "Pre-cached orthophoto layer to fix:"},
    'bad_src': {'fr': "Impossible de lire l'URL/le nom de couche WMS pour '{name}'.",
                'en': "Unable to read the WMS URL/layer name for '{name}'."},
    'caps_err': {'fr': "Échec de la lecture du GetCapabilities :\n{err}",
                 'en': "Failed to read GetCapabilities:\n{err}"},
    'no_sib': {'fr': "Aucune couche '{base}_AAAA' trouvée sur ce serveur pour '{name}' "
                     "— rien à configurer automatiquement.",
               'en': "No '{base}_YYYY' layer found on this server for '{name}' "
                     "— nothing to configure automatically."},
    'ask_thr': {'fr': "Seuil d'échelle non détecté automatiquement dans le résumé de "
                      "'{sib}' :\n« {abstract} »\n\nEntrez le dénominateur d'échelle en "
                      "dessous duquel cette couche doit être utilisée (ex. 2000 pour 1:2000) :",
                'en': "Scale threshold not found in the abstract of '{sib}':\n"
                      "\"{abstract}\"\n\nEnter the scale denominator below which this "
                      "layer must be used (e.g. 2000 for 1:2000):"},
    'confirm': {'fr': "Couche soeur trouvée : {sib} ({title})\n\nConfiguration proposée :\n"
                      "  • {name} : visible à partir de 1:{thr} (zoom arrière)\n"
                      "  • {sib} : visible en dessous de 1:{thr} (zoom avant)\n\n"
                      "Ajouter la couche et configurer les plages d'échelle des deux couches ?",
                'en': "Sibling layer found: {sib} ({title})\n\nProposed configuration:\n"
                      "  • {name}: visible from 1:{thr} (zoomed out)\n"
                      "  • {sib}: visible below 1:{thr} (zoomed in)\n\n"
                      "Add the layer and configure the scale ranges of both layers?"},
    'invalid': {'fr': "La couche '{sib}' n'a pas pu être chargée (source WMS invalide).",
                'en': "Layer '{sib}' could not be loaded (invalid WMS source)."},
    'done': {'fr': "'{sib}' ajoutée et plages d'échelle configurées (seuil 1:{thr}). "
                   "Pensez à enregistrer le projet.",
             'en': "'{sib}' added and scale ranges configured (threshold 1:{thr}). "
                   "Remember to save the project."},
}


def _tr(key, lang, **kw):
    entry = _TR[key]
    return entry.get(lang, entry['en']).format(**kw)


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


def _sibling_source(source, sibling_name):
    """Source de la couche soeur : la source d'origine à l'identique (casse
    des clés, jetons sans valeur comme « styles », ordre), seul le paramètre
    layers= change — sinon le fournisseur WMS rejette la source."""
    parts = []
    for part in source.split('&'):
        if part.lower().startswith('layers='):
            part = f"layers={sibling_name}"
        parts.append(part)
    return '&'.join(parts)


def _build_capabilities_url(base_url):
    parsed = urlparse(base_url)
    qs = {k.upper(): v for k, v in parse_qs(parsed.query).items()}
    qs['SERVICE'] = ['WMS']
    qs['REQUEST'] = ['GetCapabilities']
    qs.setdefault('VERSION', ['1.3.0'])
    query = urlencode({k: v[0] for k, v in qs.items()})
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{query}"


def _fetch_capabilities_xml(url, authcfg=''):
    request = QNetworkRequest(QUrl(url))
    blocking = QgsBlockingNetworkRequest()
    # Serveurs authentifiés (ex. RTGE) : même configuration que la couche
    if authcfg:
        blocking.setAuthCfg(authcfg)
    err = blocking.get(request, forceRefresh=True)
    if err != QgsBlockingNetworkRequest.NoError:
        raise RuntimeError(f"GetCapabilities ({err}) : {url}\n{blocking.errorMessage()}")
    return bytes(blocking.reply().content()).decode('utf-8', errors='replace')


def _child_text(elem, tag):
    child = elem.firstChildElement(tag)
    return child.text().strip() if not child.isNull() else ''


def _find_sibling_layers(xml_text, base_name):
    """Couches nommées '<base_name>_AAAA', triées de la plus récente à la plus ancienne.

    Analyse via QDomDocument (sans résolution d'entités externes) plutôt
    que xml.etree, signalé par Bandit (B314) sur des données réseau.
    """
    doc = QDomDocument()
    ok = doc.setContent(xml_text, True)
    if isinstance(ok, tuple):
        ok = ok[0]
    if not ok:
        raise ValueError("GetCapabilities XML invalide")
    pattern = re.compile(rf'^{re.escape(base_name)}_(\d{{4}})$')
    results = []
    layers = doc.elementsByTagNameNS(_WMS_NS, 'Layer')
    if layers.count() == 0:  # WMS 1.1.1 : pas d'espace de noms
        layers = doc.elementsByTagName('Layer')
    for i in range(layers.count()):
        el = layers.at(i).toElement()
        name = _child_text(el, 'Name')
        m = pattern.match(name)
        if not m:
            continue
        results.append((name, _child_text(el, 'Title'), _child_text(el, 'Abstract'),
                        int(m.group(1))))
    results.sort(key=lambda r: -r[3])
    return results


def _extract_scale_threshold(text):
    m = _SCALE_HINT_RE.search(text or '')
    if not m:
        return None
    digits = re.sub(r'[\s ]', '', m.group(1))
    try:
        return int(digits)
    except ValueError:
        return None


def fix_ortho_coverage(iface, parent, lang='fr'):
    """Point d'entrée UI : détecte et configure la couverture WMS orthophoto."""
    title = _tr('title', lang)
    project = QgsProject.instance()
    candidates = [
        lyr for lyr in project.mapLayers().values()
        if getattr(lyr, 'providerType', lambda: None)() == 'wms'
        and 'type=xyz' not in lyr.source().lower()
        and 'wmts' not in lyr.source().lower()
    ]
    if not candidates:
        QMessageBox.information(parent, title, _tr('none', lang))
        return

    if len(candidates) == 1:
        layer = candidates[0]
    else:
        names = [lyr.name() for lyr in candidates]
        choice, ok = QInputDialog.getItem(
            parent, title, _tr('choose', lang), names, 0, False)
        if not ok:
            return
        layer = candidates[names.index(choice)]

    base_url, layer_name, params = _parse_wms_source(layer)
    if not base_url or not layer_name:
        QMessageBox.warning(parent, title, _tr('bad_src', lang, name=layer.name()))
        return

    try:
        xml_text = _fetch_capabilities_xml(_build_capabilities_url(base_url),
                                           params.get('authcfg', ''))
        siblings = _find_sibling_layers(xml_text, layer_name)
    except Exception as e:
        QMessageBox.critical(parent, title, _tr('caps_err', lang, err=e))
        return

    if not siblings:
        QMessageBox.information(parent, title,
                                _tr('no_sib', lang, base=layer_name, name=layer.name()))
        return

    sibling_name, sibling_title, sibling_abstract, _year = siblings[0]
    threshold = _extract_scale_threshold(sibling_abstract)
    if threshold is None:
        threshold, ok = QInputDialog.getInt(
            parent, title,
            _tr('ask_thr', lang, sib=sibling_name, abstract=sibling_abstract),
            2000, 1, 1000000)
        if not ok:
            return

    msg = _tr('confirm', lang, sib=sibling_name, title=sibling_title,
              name=layer.name(), thr=threshold)
    if QMessageBox.question(parent, title, msg,
                            QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
        return

    new_layer = QgsRasterLayer(_sibling_source(layer.source(), sibling_name),
                               sibling_name, 'wms')
    if not new_layer.isValid():
        QMessageBox.critical(parent, title, _tr('invalid', lang, sib=sibling_name))
        return

    project.addMapLayer(new_layer, False)
    root = project.layerTreeRoot()
    node = root.findLayer(layer.id())
    group = node.parent() if node else root
    idx = group.children().index(node) if node else 0
    group.insertLayer(idx, new_layer)

    # API QGIS : minimumScale = échelle la plus « zoom arrière » (plus grand
    # dénominateur) où la couche reste visible, maximumScale = la plus
    # « zoom avant » (0 = pas de borne). Couche précachée : du 1:seuil vers
    # le zoom arrière ; couche soeur : en dessous du seuil (zoom avant).
    layer.setScaleBasedVisibility(True)
    layer.setMinimumScale(0.0)
    layer.setMaximumScale(float(threshold))

    new_layer.setScaleBasedVisibility(True)
    new_layer.setMinimumScale(float(threshold))
    new_layer.setMaximumScale(0.0)

    if iface is not None:
        iface.mapCanvas().refresh()

    QMessageBox.information(parent, title, _tr('done', lang, sib=sibling_name, thr=threshold))
