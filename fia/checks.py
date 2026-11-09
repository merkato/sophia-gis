"""Walidacja projektu pod kątem publikacji — te same reguły co /api/admin/projects/{id}/diagnostics,
ale wykonywane lokalnie, zanim cokolwiek trafi na serwer."""
from __future__ import annotations

import os

from qgis.core import Qgis, QgsDataSourceUri, QgsMapLayer, QgsProject, QgsRasterLayer, QgsVectorLayer


def layer_issues(layer: QgsMapLayer, want_edit: bool = False) -> list[tuple[str, str]]:
    """Lista (poziom, komunikat) dla jednej warstwy. Poziomy: error | warning | info."""
    out: list[tuple[str, str]] = []
    if not layer.isValid():
        out.append(("error", "Warstwa nieprawidłowa (brak źródła danych)"))
        return out

    if isinstance(layer, QgsVectorLayer):
        if layer.providerType() == "postgres":
            uri = QgsDataSourceUri(layer.source())
            if not uri.service():
                out.append(("error", "Połączenie bez 'service=' — użyj pg_service.conf (usługa 'sophia')"))
            if uri.password():
                out.append(("warning", "Hasło zapisane w projekcie — usuń je i użyj pg_service.conf"))
            if not uri.keyColumn():
                out.append(("error" if want_edit else "warning", "Brak klucza głównego"))
            if uri.wkbType() == Qgis.WkbType.Unknown and layer.isSpatial():
                out.append(("warning", "Nieokreślony typ geometrii — ustaw go w źródle warstwy"))
        elif want_edit:
            out.append(("error", f"Edycja w portalu wymaga PostGIS (dostawca: {layer.providerType()})"))
        elif layer.providerType() == "ogr":
            out.append(("warning", "Plik lokalny — na serwerze musi leżeć w tej samej ścieżce względnej"))
        props = layer.serverProperties() if hasattr(layer, "serverProperties") else layer
        if not props.shortName() and (not layer.name().isascii() or " " in layer.name()):
            out.append(("info", "Brak nazwy krótkiej (shortname) — WMS użyje pełnej nazwy warstwy"))

    if isinstance(layer, QgsRasterLayer) and layer.providerType() == "gdal":
        src = layer.source()
        if os.path.isabs(src) and QgsProject.instance().homePath() not in src:
            out.append(("warning", "Raster poza katalogiem projektu — skopiuj go do data/rasters na serwerze"))
        try:
            has_overviews = any(p.getExists() for p in layer.dataProvider().buildPyramidList())
        except Exception:  # noqa: BLE001 — API piramid różni się między wersjami QGIS
            has_overviews = True
        if not has_overviews and src.lower().endswith((".tif", ".tiff", ".vrt")):
            out.append(("info", "Brak piramid (overviews) — renderowanie w małych skalach będzie wolne"))
    return out


def project_issues() -> list[tuple[str, str, str]]:
    """(warstwa/obiekt, poziom, komunikat) dla całego projektu."""
    prj = QgsProject.instance()
    out: list[tuple[str, str, str]] = []
    if not prj.fileName().lower().endswith(".qgz"):
        out.append(("Projekt", "error", "Zapisz projekt jako .qgz"))
    if prj.readBoolEntry("Paths", "/Absolute", False)[0]:
        out.append(("Projekt", "warning", "Ścieżki bezwzględne — ustaw ścieżki względne w Właściwościach projektu"))
    if prj.readBoolEntry("WMSUseLayerIDs", "/", False)[0]:
        out.append(("Projekt", "error", "Opcja QGIS Server 'Użyj ID warstw jako nazw' musi być wyłączona"))

    for rel in prj.relationManager().relations().values():
        if not rel.isValid():
            out.append((rel.name(), "error", "Relacja nieprawidłowa (brak warstwy lub pól)"))
            continue
        a, b = rel.referencedLayer(), rel.referencingLayer()
        if a.providerType() == b.providerType() == "postgres":
            ua, ub = QgsDataSourceUri(a.source()), QgsDataSourceUri(b.source())
            if (ua.service(), ua.database()) != (ub.service(), ub.database()):
                out.append((rel.name(), "warning", "Relacja między różnymi bazami — portal jej nie obsłuży"))
    return out
