def classFactory(iface):  # noqa: N802 — wymagane przez QGIS
    from .plugin import FiaPlugin
    return FiaPlugin(iface)
