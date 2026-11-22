"""Walidacja projektu pod kątem publikacji — te same reguły co /api/admin/projects/{id}/diagnostics,
ale wykonywane lokalnie, zanim cokolwiek trafi na serwer."""
from __future__ import annotations

import os

from qgis.core import Qgis, QgsDataSourceUri, QgsLayoutItemMap, QgsMapLayer, QgsProject, QgsRasterLayer, QgsVectorLayer

LIBRARY_DIR = "rasters"     # wspólna biblioteka: <katalog>/rasters  <->  /opt/sophia/data/rasters


def _raster_location(src: str, home: str) -> list[tuple[str, str]]:
    """Gdzie raster wyląduje na serwerze. Fia publikuje projekt do data/projects/<slug>/<slug>.qgz,
    więc działają dwa układy (te same ścieżki względne lokalnie i na serwerze):
      - obok projektu:      ./rastry/...           -> data/projects/<slug>/rastry/...
      - biblioteka wspólna: ../../rasters/<seria>   -> data/rasters/<seria>/...
    """
    if not home or not os.path.isabs(src):
        return []
    path = src.split("|")[0]                       # GDAL: "plik.tif|layername=..." itp.
    try:
        rel = os.path.relpath(path, home).replace("\\", "/")
    except ValueError:                             # inny dysk niż projekt (Windows)
        rel = None
    if rel and not rel.startswith("../"):
        return [("info", f"Raster obok projektu — na serwer do data/projects/<slug>/{rel}")]
    lib = f"../../{LIBRARY_DIR}/"
    if rel and rel.startswith(lib):
        return [("info", f"Biblioteka rastrów — na serwerze data/rasters/{rel[len(lib):]}")]
    expected = os.path.normpath(os.path.join(home, "..", "..", LIBRARY_DIR))
    return [("warning", (f"Raster poza katalogiem projektu i poza biblioteką rastrów ({expected}) — "
                         "serwer go nie znajdzie. Przenieś go do biblioteki albo obok projektu"))]


IMAGE_EXT = (".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif", ".tif", ".tiff", ".bmp")


def _resource_field_issues(layer: QgsVectorLayer) -> list[tuple[str, str]]:
    """Pola z widżetem „Załącznik” (zdjęcia w WebUI) — docs/user/zdjecia.md."""
    out: list[tuple[str, str]] = []
    for idx, fld in enumerate(layer.fields()):
        setup = layer.editorWidgetSetup(idx)
        if setup.type() != "ExternalResource":
            continue
        cfg = setup.config() or {}
        name = fld.name()
        if holds_urls(layer, idx):
            continue                    # pole z adresami internetowymi: WebUI pokazuje je jako linki
        if fld.isNumeric():
            out.append(("error", f"Pole „{name}”: widżet Załącznik wymaga pola tekstowego"))
        if int(cfg.get("RelativeStorage") or 0) != 1:
            out.append(("warning", (f"Pole „{name}”: ustaw „Ścieżka względna do projektu” — "
                                    "inaczej WebUI nie znajdzie zdjęć")))
        if not is_photo_config(cfg) and not str(cfg.get("FileWidgetFilter") or "").strip():
            out.append(("info", f"Pole „{name}”: brak filtra plików — WebUI przyjmie każdy typ "
                                "(poza wykonywalnymi). Ustaw np. „PDF (*.pdf);;GML (*.gml)”."))
    return out


def holds_urls(layer: QgsVectorLayer, idx: int) -> bool:
    """Pole „Załącznik” użyte na adresy internetowe (wartości http/https), nie na pliki."""
    try:
        values = [str(v) for v in layer.uniqueValues(idx, 50) if v not in (None, "") and str(v) != "NULL"]
    except Exception:  # noqa: BLE001 — np. warstwa niedostępna
        return False
    return bool(values) and all(v.strip().lower().startswith(("http://", "https://")) for v in values)


def is_photo_config(cfg: dict) -> bool:
    flt = str(cfg.get("FileWidgetFilter") or "").lower()
    return str(cfg.get("DocumentViewer")) == "1" or any(e in flt for e in IMAGE_EXT)


def _resource_kinds(layer: QgsVectorLayer) -> list[str]:
    kinds = []
    for idx, fld in enumerate(layer.fields()):
        setup = layer.editorWidgetSetup(idx)
        if setup.type() == "ExternalResource":
            kind = "link" if holds_urls(layer, idx) else "zdjęcie" if is_photo_config(setup.config() or {}) else "plik"
            kinds.append(f"{kind} ({fld.name()})")
    return kinds


def attachment_summary(layer: QgsMapLayer) -> str:
    """Opis do tabeli warstw Fii: pola „Załącznik” i tabele zdjęć/plików w relacji (wariant A i B)."""
    if not isinstance(layer, QgsVectorLayer):
        return ""
    parts = _resource_kinds(layer)
    for rel in QgsProject.instance().relationManager().referencedRelations(layer):
        child = rel.referencingLayer()
        if child is not None and _resource_kinds(child):
            photo = any(k.startswith("zdjęcie") for k in _resource_kinds(child))
            parts.append(f"{'zdjęcia' if photo else 'pliki'}: {child.name()}")
    return "; ".join(parts)


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
        out.extend(_resource_field_issues(layer))
        props = layer.serverProperties() if hasattr(layer, "serverProperties") else layer
        if not props.shortName() and (not layer.name().isascii() or " " in layer.name()):
            out.append(("info", "Brak nazwy krótkiej (shortname) — WMS użyje pełnej nazwy warstwy"))

    if isinstance(layer, QgsRasterLayer) and layer.providerType() == "gdal":
        src = layer.source()
        out.extend(_raster_location(src, QgsProject.instance().homePath()))
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
    out.extend(layout_issues())
    return out


def _unavailable(layer: QgsMapLayer | None, restricted: set[str]) -> str | None:
    """Powód, dla którego QGIS Server Sophii nie narysuje warstwy (None — narysuje)."""
    if layer is None:
        return "usunięta z projektu"
    if layer.name() in restricted:
        return "wyłączona z WMS (Właściwości projektu → QGIS Server)"
    if not layer.isValid():
        return "nieprawidłowe źródło"
    errors = [m for lvl, m in layer_issues(layer) if lvl == "error"]
    return errors[0] if errors else None


def layout_issues() -> list[tuple[str, str, str]]:
    """Szablony wydruku: brak szablonów (info) i mapy szablonów pokazujące warstwy, których Sophia
    nie wydrukuje (warning). Mapa główna (pierwsza) dostaje w Sophii warstwy włączone w przeglądarce —
    dotyczy jej to tylko przy wydruku bez wybranych warstw; pozostałe mapy (np. przeglądowa) zawsze."""
    prj = QgsProject.instance()
    layouts = prj.layoutManager().printLayouts()
    if not layouts:
        msg = ("Brak szablonów wydruku — w Sophii dostępny będzie tylko układ Sophii "
               "(bez etykiet, legendy i innych elementów szablonu QGIS)")
        return [("Wydruki", "info", msg)]
    restricted = set(prj.readListEntry("WMSRestrictedLayers", "/")[0])
    themes = prj.mapThemeCollection()
    out: list[tuple[str, str, str]] = []
    for layout in layouts:
        maps = [i for i in layout.items() if isinstance(i, QgsLayoutItemMap)]
        if not maps:
            out.append((layout.name(), "info", "Szablon bez mapy — Sophia wydrukuje go bez widoku mapy"))
        for n, m in enumerate(maps):
            if m.followVisibilityPreset() and m.followVisibilityPresetName():
                name = m.followVisibilityPresetName()
                if not themes.hasMapTheme(name):
                    out.append((layout.name(), "warning", f"Mapa „{m.displayName()}” korzysta z nieistniejącego motywu „{name}”"))
                    continue
                layers = themes.mapThemeVisibleLayers(name)
            elif m.keepLayerSet():
                layers = m.layers()
            else:
                continue          # warstwy z widoku — w Sophii z przeglądarki
            bad = [f"{lyr.name() if lyr else '?'} ({why})" for lyr in layers if (why := _unavailable(lyr, restricted))]
            if bad:
                kto = "mapa główna, gdy w Sophii nie wybrano warstw" if n == 0 else "zawsze"
                out.append((layout.name(), "warning",
                            f"Mapa „{m.displayName()}” pokazuje warstwy, których Sophia nie wydrukuje ({kto}): "
                            + ", ".join(bad)))
    return out
