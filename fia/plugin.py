from qgis.PyQt.QtWidgets import QAction


class FiaPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):  # noqa: N802
        self.action = QAction("Fia – konfiguracja i publikacja w Sophii…", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToWebMenu("Fia", self.action)
        self.iface.addWebToolBarIcon(self.action)

    def unload(self):
        self.iface.removePluginWebMenu("Fia", self.action)
        self.iface.removeWebToolBarIcon(self.action)

    def run(self):
        from .dialog import FiaDialog

        dlg = FiaDialog(self.iface, self.iface.mainWindow())
        dlg.exec()
