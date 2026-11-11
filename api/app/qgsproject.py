"""Odczyt projektu QGIS (.qgs / .qgz) bez PyQGIS.

Filozofia (w przeciwieństwie do Lizmapa): projekt QGIS jest jedynym źródłem prawdy.
Warstwy, drzewo, relacje, aliasy, widżety formularzy, ograniczenia i wydruki są wykrywane
automatycznie. Plik pomocniczy ``<projekt>.portal.json`` (tworzony wtyczką QGIS) zawiera
wyłącznie *nadpisania* — brak pliku oznacza rozsądne ustawienia domyślne, a nie błąd.
"""
from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyproj
from lxml import etree

# --------------------------------------------------------------------------- modele


@dataclass
class FieldDef:
    name: str
    alias: str | None = None
    type: str | None = None             # typ z QGIS (np. "integer", "text", "date")
    widget: str = "TextEdit"            # TextEdit | ValueMap | ValueRelation | DateTime | CheckBox | Range | Hidden | ...
    widget_config: dict[str, Any] = field(default_factory=dict)
    editable: bool = True
    not_null: bool = False
    default_expression: str | None = None


@dataclass
class PgSource:
    conninfo: str                       # np. "service=sophia" lub "service=sophia dbname=inna"
    schema: str
    table: str
    geometry_column: str | None
    key: str | None
    srid: int | None
    geometry_type: str | None
    sql_filter: str | None


@dataclass
class LayerDef:
    id: str
    name: str
    short_name: str | None
    type: str                           # vector | raster
    provider: str
    crs: str | None
    geometry_type: str | None           # Point | Line | Polygon | None (tabela bez geometrii)
    pg: PgSource | None = None
    fields: list[FieldDef] = field(default_factory=list)
    display_expression: str | None = None
    # z pliku .portal.json
    editable: bool = False
    popup: bool = True
    hidden: bool = False
    tile_format: str | None = None      # rastry: format kafli w WebUI (None = wektor, bez kafli)
    source: str | None = None           # źródło warstw WMS/WMTS/XYZ — dopasowanie podkładu z katalogu do wydruku
    attribution: str | None = None      # QGIS Server → Atrybucja (albo Metadane → Prawa): na mapie i wydruku
    attribution_url: str | None = None
    # zakres danych (app/scope.py): spatial | attribute | relation | none; "auto" rozstrzygane po wczytaniu
    scope_mode: str = "none"
    scope_field: str | None = None

    @property
    def wms_name(self) -> str:
        return self.short_name or self.name


# Kafle rastrów w WebUI. WebP w obrazie camptocamp zwraca pusty plik, więc:
# zdalne WMS/WMTS podawane jako JPEG (ortofoto, mapy topo) -> JPEG (4-5x mniejsze niż PNG),
# pozostałe rastry (skany z przezroczystym tłem po przycięciu) -> 8-bitowy PNG z przezroczystością.
TILE_JPEG = "image/jpeg"
TILE_PNG8 = "image/png; mode=8bit"


def raster_tile_format(provider: str, datasource: str) -> str:
    ds = datasource.lower()
    if provider == "wms" and ("format=image/jpeg" in ds or "format=image%2fjpeg" in ds):
        return TILE_JPEG
    return TILE_PNG8


@dataclass
class RelationDef:
    id: str
    name: str
    parent_layer: str                   # referencedLayer
    child_layer: str                    # referencingLayer
    pairs: list[tuple[str, str]]        # (pole_w_rodzicu, pole_w_dziecku)
    strength: str = "Association"       # Association | Composition


@dataclass
class TreeNode:
    kind: str                           # group | layer | raster_group
    name: str
    layer_id: str | None = None
    visible: bool = True
    expanded: bool = True
    mutually_exclusive: bool = False
    children: list[TreeNode] = field(default_factory=list)


@dataclass
class ReportDef:
    layout: str
    title: str
    layer_id: str | None = None         # warstwa atlasu — raport "dla obiektu"
    map_mm: list[float] | None = None   # rozmiar pierwszej mapy szablonu [szer., wys.] w mm (= map0 w GetPrint)
    labels: list[str] = field(default_factory=list)   # identyfikatory etykiet (np. tytul, opis)


_UNIT_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "pt": 25.4 / 72, "pica": 25.4 / 6}
MAP_ITEM, LABEL_ITEM = "65639", "65641"   # typy elementów układu QGIS (QgsLayoutItemRegistry)


def layout_items(layout_el: etree._Element) -> tuple[list[float] | None, list[str]]:
    """(rozmiar pierwszej mapy w mm, identyfikatory etykiet). QGIS Server adresuje mapy KOLEJNOŚCIĄ:
    map0 = pierwsza mapa układu, niezależnie od jej identyfikatora."""
    map_mm, labels = None, []
    for item in layout_el.iter("LayoutItem"):
        typ = item.get("type")
        if map_mm is None and (typ == MAP_ITEM or item.find("Extent") is not None):
            try:
                w, h, unit = (item.get("size") or "").split(",")
                k = _UNIT_MM.get(unit.strip(), 1.0)
                map_mm = [round(float(w) * k, 2), round(float(h) * k, 2)]
            except ValueError:
                pass
        elif (typ == LABEL_ITEM or item.get("labelText") is not None) and item.get("id"):
            labels.append(item.get("id"))
    return map_mm, labels


@dataclass
class ScopeDef:
    """Wymiar zakresu z Fii: warstwa granic (np. oddziały terenowe) i pole z kodem obszaru."""
    label: str
    layer_id: str
    field: str


SCOPE_MODES = {"auto", "spatial", "attribute", "relation", "none"}


def resolve_scope(cfg: dict, layer_cfg: dict, layers: dict[str, LayerDef], relations: list) -> ScopeDef | None:
    """Wymiar zakresu i reguły warstw. „auto”: warstwa z geometrią — przestrzennie, tabela bez geometrii
    będąca dzieckiem w relacji — przez relację, pozostałe (i sama warstwa granic) — bez ograniczeń."""
    sc = cfg.get("scope") or {}
    b = layers.get(sc.get("layer", ""))
    if not b or not b.pg or not b.geometry_type or not sc.get("field"):
        return None
    dim = ScopeDef(label=sc.get("label") or "Obszar", layer_id=b.id, field=sc["field"])
    children = {r.child_layer for r in relations}
    for lid, lyr in layers.items():
        if not lyr.pg:
            continue
        rule = (layer_cfg.get(lid, {}).get("scope") or {})
        mode = rule.get("mode", "auto") if rule.get("mode") in SCOPE_MODES else "auto"
        if lid == b.id and mode == "auto":
            mode = "none"
        if mode == "auto":
            mode = "spatial" if lyr.pg.geometry_column else "relation" if lid in children else "none"
        if mode == "spatial" and not lyr.pg.geometry_column:
            mode = "none"
        lyr.scope_mode = mode
        lyr.scope_field = rule.get("field") if mode == "attribute" else None
    return dim


@dataclass
class ToolDef:
    """Narzędzie pobierania z Fii: obiekt z usługi zewnętrznej (np. działka z ULDK) -> warstwa projektu."""
    id: str
    source: str                         # klucz w fetchers.SOURCES
    label: str
    layer_id: str                       # warstwa docelowa
    fields: dict[str, str]              # pole źródła -> pole warstwy docelowej
    open_form: bool = True              # po pobraniu otwórz formularz (uzupełnienie atrybutów)


def parse_tools(cfg: dict, layers: dict[str, LayerDef]) -> list[ToolDef]:
    """Narzędzia z .portal.json; pomija wpisy z nieznaną warstwą lub polami spoza warstwy."""
    out = []
    for i, t in enumerate(cfg.get("tools", []) or []):
        lyr = layers.get(t.get("layer", ""))
        if not lyr or not lyr.pg or not t.get("source"):
            continue
        names = {f.name for f in lyr.fields}
        fields = {src: dst for src, dst in (t.get("fields") or {}).items() if dst in names}
        out.append(ToolDef(id=str(t.get("id") or f"narzedzie{i + 1}"), source=t["source"],
                           label=t.get("label") or t["source"], layer_id=lyr.id, fields=fields,
                           open_form=bool(t.get("open_form", True))))
    return out


@dataclass
class Project:
    title: str
    crs: str
    extent: list[float] | None
    layers: dict[str, LayerDef]
    relations: list[RelationDef]
    tree: TreeNode
    reports: list[ReportDef]
    options: dict[str, Any]
    mtime: float
    tools: list[ToolDef] = field(default_factory=list)
    scope: ScopeDef | None = None

    def layer_by_wms_name(self, name: str) -> LayerDef | None:
        return next((lyr for lyr in self.layers.values() if lyr.wms_name == name), None)


# --------------------------------------------------------------------------- datasource

_KV_RE = re.compile(r"(\w+)=('(?:[^'\\]|\\.)*'|\S+)")
_TABLE_RE = re.compile(r'table="((?:[^"]|"")*)"\."((?:[^"]|"")*)"(?:\s*\(([^)]+)\))?')
_SQL_RE = re.compile(r"\bsql=(.*)$", re.DOTALL)
_CONN_KEYS = {"service", "dbname", "host", "port", "user", "password", "sslmode"}


def parse_pg_datasource(ds: str) -> PgSource:
    sql_match = _SQL_RE.search(ds)
    sql_filter = sql_match.group(1).strip() if sql_match else None
    head = ds[: sql_match.start()] if sql_match else ds

    table_match = _TABLE_RE.search(head)
    if not table_match:
        raise ValueError(f"Nieobsługiwane źródło PostgreSQL: {ds!r}")
    schema = table_match.group(1).replace('""', '"')
    table = table_match.group(2).replace('""', '"')
    geom_col = table_match.group(3)
    rest = head[: table_match.start()] + head[table_match.end():]

    kv: dict[str, str] = {}
    for k, v in _KV_RE.findall(rest):
        if v.startswith("'"):
            v = v[1:-1].replace("\\'", "'")
        kv[k] = v

    conn_parts = [f"{k}={kv[k]}" for k in ("service", "dbname", "host", "port", "user", "sslmode") if k in kv]
    if "service" not in kv:
        # Hasła w projekcie nie wspieramy celowo — wymuszamy pg_service.conf.
        raise ValueError(
            f"Warstwa {schema}.{table} nie używa 'service=' — skonfiguruj połączenie przez pg_service.conf"
        )
    return PgSource(
        conninfo=" ".join(conn_parts),
        schema=schema,
        table=table,
        geometry_column=geom_col,
        key=kv.get("key", "").strip('"') or None,
        srid=int(kv["srid"]) if kv.get("srid", "").isdigit() else None,
        geometry_type=kv.get("type"),
        sql_filter=sql_filter or None,
    )


# --------------------------------------------------------------------------- XML


def _load_xml(path: Path) -> etree._Element:
    if path.suffix.lower() == ".qgz":
        with zipfile.ZipFile(path) as zf:
            name = next(n for n in zf.namelist() if n.lower().endswith(".qgs"))
            data = zf.read(name)
    else:
        data = path.read_bytes()
    return etree.fromstring(data, parser=etree.XMLParser(huge_tree=True, resolve_entities=False))


def _options_to_dict(opt: etree._Element | None) -> Any:
    """Konwertuje zagnieżdżone <Option type="Map|List|..."> z QGIS na dict/list."""
    if opt is None:
        return {}
    typ = opt.get("type")
    if typ == "Map":
        return {child.get("name"): _options_to_dict(child) for child in opt.findall("Option")}
    if typ in ("List", "StringList"):
        return [_options_to_dict(child) for child in opt.findall("Option")]
    val = opt.get("value")
    if typ == "bool":
        return val == "true"
    if typ in ("int", "uint", "qlonglong"):
        return int(val) if val not in (None, "") else None
    if typ == "double":
        return float(val) if val not in (None, "") else None
    return val


def _geometry_kind(ml: etree._Element) -> str | None:
    g = ml.get("geometry") or ml.findtext("geometry")
    if not g or g in ("No geometry", "Unknown geometry"):
        return None
    return {"Point": "Point", "Line": "Line", "Polygon": "Polygon"}.get(g, g)


def _parse_fields(ml: etree._Element) -> list[FieldDef]:
    fields: dict[str, FieldDef] = {}
    for f in ml.findall("./fieldConfiguration/field"):
        name = f.get("name")
        widget = f.find("editWidget")
        fd = FieldDef(name=name)
        if widget is not None:
            fd.widget = widget.get("type") or "TextEdit"
            fd.widget_config = _options_to_dict(widget.find("./config/Option"))
        fields[name] = fd

    for a in ml.findall("./aliases/alias"):
        if a.get("field") in fields and a.get("name"):
            fields[a.get("field")].alias = a.get("name")
    for d in ml.findall("./defaults/default"):
        if d.get("field") in fields and d.get("expression"):
            fields[d.get("field")].default_expression = d.get("expression")
    for c in ml.findall("./constraints/constraint"):
        if c.get("field") in fields and c.get("notnull_strength", "0") != "0":
            fields[c.get("field")].not_null = True
    for e in ml.findall("./editable/field"):
        if e.get("name") in fields:
            fields[e.get("name")].editable = e.get("editable") == "1"
    return list(fields.values())


def _parse_tree(group_el: etree._Element, raster_groups: set[str]) -> TreeNode:
    node = TreeNode(
        kind="group",
        name=group_el.get("name") or "",
        visible=group_el.get("checked") != "Qt::Unchecked",
        expanded=group_el.get("expanded") != "0",
        mutually_exclusive=group_el.get("mutually-exclusive") == "1",
    )
    for child in group_el:
        if child.tag == "layer-tree-group":
            sub = _parse_tree(child, raster_groups)
            if sub.name in raster_groups:
                sub.kind = "raster_group"   # wiele GeoTIFF jako jedna warstwa WMS (nazwa grupy)
            node.children.append(sub)
        elif child.tag == "layer-tree-layer":
            node.children.append(
                TreeNode(
                    kind="layer",
                    name=child.get("name") or "",
                    layer_id=child.get("id"),
                    visible=child.get("checked") != "Qt::Unchecked",
                    expanded=child.get("expanded") != "0",
                )
            )
    return node


def _valid_extent(ext: list[float]) -> list[float] | None:
    return ext if len(ext) == 4 and ext[2] > ext[0] and ext[3] > ext[1] else None


def start_extent(root: etree._Element, crs: str) -> list[float] | None:
    """Widok startowy WebUI z projektu QGIS, w układzie projektu. Kolejność:
    1. ProjectViewSettings/DefaultViewExtent — widok, w którym QGIS otwiera projekt (zapisywany
       przy zapisie projektu; QGIS >= 3.18),
    2. properties/WMSExtent — rozgłaszany zasięg (Właściwości projektu -> QGIS Server),
    3. mapcanvas/extent — widok mapy w chwili zapisu (starsze projekty).
    """
    el = root.find("./ProjectViewSettings/DefaultViewExtent")
    if el is not None and el.get("xmin") is not None:
        try:
            ext = _valid_extent([float(el.get(k)) for k in ("xmin", "ymin", "xmax", "ymax")])
        except (TypeError, ValueError):
            ext = None
        src = el.findtext(".//spatialrefsys/authid")
        if ext and src and src != crs:
            try:
                ext = list(pyproj.Transformer.from_crs(src, crs, always_xy=True).transform_bounds(*ext))
            except Exception:  # noqa: BLE001 — nieznany układ: lepiej brak widoku niż zły
                ext = None
        if ext:
            return ext
    wms = root.find("./properties/WMSExtent")
    if wms is not None:
        try:
            ext = _valid_extent([float(v.text) for v in wms.findall("value") if v.text])
        except ValueError:
            ext = None
        if ext:
            return ext
    canvas = root.find("./mapcanvas/extent")
    if canvas is not None:
        try:
            return _valid_extent([float(canvas.findtext(k)) for k in ("xmin", "ymin", "xmax", "ymax")])
        except (TypeError, ValueError):
            return None
    return None


def layer_attribution(ml: etree._Element) -> tuple[str | None, str | None]:
    """Atrybucja warstwy: QGIS Server → Atrybucja (tytuł + URL); bez niej — Metadane → Prawa."""
    el = ml.find("attribution")
    text = (el.text or "").strip() if el is not None else ""
    url = (el.get("href") or "").strip() if el is not None else ""
    if not text:
        rights = [(r.text or "").strip() for r in ml.findall("./resourceMetadata/rights")]
        text = "; ".join(r for r in rights if r)
    if not url.lower().startswith(("http://", "https://")):
        url = ""
    return text or None, url or None


def load_project(path: Path) -> Project:
    root = _load_xml(path)
    sidecar_path = path.with_suffix(".portal.json")
    cfg: dict[str, Any] = json.loads(sidecar_path.read_text("utf-8")) if sidecar_path.exists() else {}
    layer_cfg: dict[str, dict] = cfg.get("layers", {})

    layers: dict[str, LayerDef] = {}
    for ml in root.iter("maplayer"):
        lid = ml.findtext("id")
        if not lid:
            continue
        provider = (ml.findtext("provider") or "").strip()
        lyr = LayerDef(
            id=lid,
            name=ml.findtext("layername") or lid,
            short_name=ml.findtext("shortname") or None,
            type=ml.get("type", "vector"),
            provider=provider,
            crs=ml.findtext("./srs/spatialrefsys/authid"),
            geometry_type=_geometry_kind(ml) if ml.get("type") == "vector" else None,
            display_expression=ml.findtext("previewExpression") or None,
        )
        lyr.attribution, lyr.attribution_url = layer_attribution(ml)
        if lyr.type == "raster":
            lyr.tile_format = raster_tile_format(provider, ml.findtext("datasource") or "")
            if provider == "wms":
                lyr.source = ml.findtext("datasource") or None
        if lyr.type == "vector":
            lyr.fields = _parse_fields(ml)
            if provider == "postgres":
                try:
                    lyr.pg = parse_pg_datasource(ml.findtext("datasource") or "")
                except ValueError:
                    lyr.pg = None
        over = layer_cfg.get(lid, {})
        # Edycja możliwa tylko dla warstw PostGIS z kluczem głównym.
        lyr.editable = bool(over.get("editable", False)) and lyr.pg is not None and lyr.pg.key is not None
        lyr.popup = bool(over.get("popup", True))
        lyr.hidden = bool(over.get("hidden", False))
        if over.get("display_expression"):
            lyr.display_expression = over["display_expression"]
        layers[lid] = lyr

    relations = []
    for r in root.findall("./relations/relation"):
        pairs = [(fr.get("referencedField"), fr.get("referencingField")) for fr in r.findall("fieldRef")]
        relations.append(
            RelationDef(
                id=r.get("id"),
                name=r.get("name") or r.get("id"),
                parent_layer=r.get("referencedLayer"),
                child_layer=r.get("referencingLayer"),
                pairs=pairs,
                strength=r.get("strength", "Association"),
            )
        )

    raster_groups = set(cfg.get("raster_groups", []))
    tree_el = root.find("layer-tree-group")
    tree = _parse_tree(tree_el, raster_groups) if tree_el is not None else TreeNode("group", "")

    reports_cfg = {r["layout"]: r for r in cfg.get("reports", [])}
    reports = []
    for layout_el in root.findall("./Layouts/Layout"):
        name = layout_el.get("name")
        rc = reports_cfg.get(name, {})
        if rc.get("enabled", True) is False:
            continue
        atlas = layout_el.find("Atlas")
        atlas_layer = atlas.get("coverageLayer") if atlas is not None and atlas.get("enabled") == "1" else None
        map_mm, labels = layout_items(layout_el)
        reports.append(ReportDef(layout=name, title=rc.get("title", name), layer_id=atlas_layer,
                                 map_mm=map_mm, labels=labels))

    crs = root.findtext("./projectCrs/spatialrefsys/authid") or "EPSG:2180"

    return Project(
        title=root.get("projectname") or root.findtext("title") or path.stem,
        crs=crs,
        extent=cfg.get("map", {}).get("extent") or start_extent(root, crs),
        layers=layers,
        relations=relations,
        tree=tree,
        reports=reports,
        options=cfg.get("map", {}),
        mtime=path.stat().st_mtime,
        tools=parse_tools(cfg, layers),
        scope=resolve_scope(cfg, layer_cfg, layers, relations),
    )


# --------------------------------------------------------------------------- cache

_cache: dict[Path, Project] = {}


def get_project(path: Path) -> Project:
    """Projekt z cache, przeładowany automatycznie po zmianie pliku .qgz lub .portal.json."""
    sidecar = path.with_suffix(".portal.json")
    mtime = max(path.stat().st_mtime, sidecar.stat().st_mtime if sidecar.exists() else 0)
    cached = _cache.get(path)
    if cached is None or cached.mtime < mtime:
        cached = load_project(path)
        cached.mtime = mtime
        _cache[path] = cached
    return cached
