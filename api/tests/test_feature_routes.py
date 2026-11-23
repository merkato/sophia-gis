"""Klucz obiektu z ukośnikiem (np. identyfikator działki) trafia do właściwych endpointów."""
from starlette.routing import Match

from app.routers import features, photos


def _endpoint(routes, method: str, path: str):
    """Pierwsza pasująca trasa — w kolejności, w jakiej Sophia je sprawdza (lista tras routera)."""
    scope = {"type": "http", "method": method, "path": path, "root_path": "", "query_string": b"", "headers": []}
    for r in routes:
        match, child = r.matches(scope)
        if match == Match.FULL:
            return getattr(r, "name", None), child.get("path_params", {})
    return None, {}


def test_slash_in_feature_key():
    # kolejność jak w API (main.ROUTERS, czytana ze źródła — import main wymaga konfiguracji): pliki przed obiektem
    import ast
    from pathlib import Path
    src = (Path(__file__).parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    names = next(n.value for n in ast.parse(src).body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "ROUTERS")
    seq = [e.id for e in names.elts]
    assert seq.index("photos") < seq.index("features")
    order = [photos, features]
    app = [r for m in order for r in m.router.routes]
    base = "/api/projects/p/layers/l/features"
    pk = "ULDK:999901_1.0001.12/1"
    name, params = _endpoint(app, "GET", f"{base}/{pk}")
    assert name == "get_feature" and params["pk"] == pk
    name, params = _endpoint(app, "GET", f"{base}/{pk}/related")
    assert name != "get_feature" and params["pk"] == pk
    name, params = _endpoint(app, "POST", f"{base}/{pk}/copy")
    assert params.get("pk") == pk
    name, params = _endpoint(app, "PATCH", f"{base}/{pk}")
    assert params.get("pk") == pk
    name, params = _endpoint(app, "GET", f"{base}/{pk}/files/foto")
    assert params == {"slug": "p", "layer_id": "l", "pk": pk, "field": "foto"}
    name, params = _endpoint(app, "POST", f"{base}/split")
    assert name is not None and "pk" not in params


def test_writable_values_natural_key():
    # nowy obiekt może dostać klucz naturalny (np. identyfikator działki z wtyczki); zmiana obiektu — nigdy
    from app.qgsproject import FieldDef, LayerDef, PgSource
    lyr = LayerDef(id="h", name="h", short_name=None, type="vector", provider="postgres", crs=None, geometry_type="Polygon",
                   pg=PgSource("service=x", "s", "t", "geom", "teryt", 2180, "MultiPolygon", None),
                   fields=[FieldDef("teryt", widget="Hidden"), FieldDef("zrodlo"), FieldDef("dodano", editable=False)])
    props = {"teryt": "146301_1.0001.1", "zrodlo": "ULDK"}
    assert features._writable_values(lyr, props, with_key=True) == props
    assert features._writable_values(lyr, props) == {"zrodlo": "ULDK"}
    assert features._writable_values(lyr, {"teryt": "", "zrodlo": "ULDK"}, with_key=True) == {"zrodlo": "ULDK"}
