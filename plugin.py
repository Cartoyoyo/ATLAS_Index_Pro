import os
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon


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

    def unload(self):
        self.iface.removePluginMenu('&ATLAS Index Pro', self.action)
        self.iface.removeToolBarIcon(self.action)

    def run(self):
        from .dialog import AtlasDialog
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
        self.dialog = AtlasDialog(self.iface)
        self.dialog.show()
