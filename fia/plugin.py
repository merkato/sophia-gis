from qgis.PyQt.QtWidgets import QAction


class FiaPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.photos_action = None

    def initGui(self):  # noqa: N802
        self.action = QAction("Fia – konfiguracja i publikacja w Sophii…", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToWebMenu("Fia", self.action)
        self.iface.addWebToolBarIcon(self.action)
        self.photos_action = QAction("Fia – pobierz zdjęcia z Sophii", self.iface.mainWindow())
        self.photos_action.triggered.connect(self.sync_photos)
        self.iface.addPluginToWebMenu("Fia", self.photos_action)

    def unload(self):
        self.iface.removePluginWebMenu("Fia", self.action)
        self.iface.removeWebToolBarIcon(self.action)
        self.iface.removePluginWebMenu("Fia", self.photos_action)

    def run(self):
        from .dialog import FiaDialog

        dlg = FiaDialog(self.iface, self.iface.mainWindow())
        dlg.exec()

    def sync_photos(self):
        """Bez otwierania okna: adres i login z ustawień Fii, hasło z menedżera uwierzytelniania QGIS."""
        from .dialog import FiaDialog

        dlg = FiaDialog(self.iface, self.iface.mainWindow())
        dlg.on_sync_photos()
