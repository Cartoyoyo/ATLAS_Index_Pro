import os
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon


def _icone_menu_extensions(iface, titre, icon):
    """Pose l'icone du plugin devant son entree du menu Extensions.

    addPluginToMenu() cree le sous-menu sans jamais rendre le QMenu
    accessible : on le retrouve par son titre parmi les actions du menu
    Extensions (QGIS retire les & des libelles, on compare a l'identique).
    """
    if icon is None or icon.isNull():
        return
    cible = titre.replace('&', '')
    for action in iface.pluginMenu().actions():
        sous_menu = action.menu()
        if sous_menu is not None and sous_menu.title().replace('&', '') == cible:
            sous_menu.setIcon(icon)
            return


class ATLASIndexProPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dialog = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'logo.png')
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        self.action = QAction(icon, 'ATLAS Index Pro', self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu('&ATLAS Index Pro', self.action)
        _icone_menu_extensions(self.iface, '&ATLAS Index Pro', icon)

    def unload(self):
        # Fermer le dialogue ouvert : sinon il survit au rechargement du
        # plugin et pilote encore l'ancien code.
        if self.dialog is not None:
            try:
                self.dialog.close()
                self.dialog.deleteLater()
            except RuntimeError:
                pass
            self.dialog = None
        self.iface.removePluginMenu('&ATLAS Index Pro', self.action)
        self.iface.removeToolBarIcon(self.action)
        self.action.deleteLater()

    def run(self):
        from .dialog import AtlasDialog
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
        self.dialog = AtlasDialog(self.iface)
        self.dialog.show()
