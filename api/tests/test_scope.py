"""Zakres danych (app/scope.py) na fikcyjnym przykładzie urzędu z oddziałami terenowymi: granice
oddziałów, działki (przestrzennie), decyzje (atrybut), oględziny (przez relację z działką), słownik."""
import base64
import json
import zlib
from types import SimpleNamespace

from app import scope
from app.qgsproject import FieldDef, LayerDef, PgSource, RelationDef, resolve_scope


def _layer(lid: str, table: str, geom: str | None, gtype: str | None, srid: int | None = 2180) -> LayerDef:
    lyr = LayerDef(id=lid, name=lid, short_name=None, type="vector", provider="postgres", crs=None,
                   geometry_type=gtype, display_expression=None,
                   pg=PgSource("service=sophia", "dane", table, geom, "fid", srid if geom else None, None, None))
    lyr.fields = [FieldDef("fid"), FieldDef("oddzial"), FieldDef("dzialka_fid")]
    return lyr


def _project(cfg_layers: dict | None = None):
    layers = {
        "odd": _layer("odd", "oddzialy", "geom", "Polygon"),
        "dz": _layer("dz", "dzialki", "geom", "Polygon"),
        "dec": _layer("dec", "decyzje", None, None),
        "lus": _layer("lus", "ogledziny", None, None),
        "slow": _layer("slow", "slownik", None, None),
    }
    relations = [RelationDef("r1", "Oględziny", "dz", "lus", [("fid", "dzialka_fid")])]
    cfg = {"scope": {"label": "Oddział terenowy", "layer": "odd", "field": "kod"}}
    layer_cfg = cfg_layers if cfg_layers is not None else {"dec": {"scope": {"mode": "attribute", "field": "oddzial"}}}
    dim = resolve_scope(cfg, layer_cfg, layers, relations)
    return SimpleNamespace(layers=layers, relations=relations, scope=dim)


def _ctx(codes):
    return SimpleNamespace(project=_project(), scope_codes=codes)


def test_resolve_scope_auto_rules():
    p = _project()
    assert p.scope.label == "Oddział terenowy" and p.scope.field == "kod"
    modes = {lid: lyr.scope_mode for lid, lyr in p.layers.items()}
    assert modes == {"odd": "none", "dz": "spatial", "dec": "attribute", "lus": "relation", "slow": "none"}
    assert p.layers["dec"].scope_field == "oddzial"


def test_unrestricted_user_sees_everything():
    ctx = _ctx(None)
    for lyr in ctx.project.layers.values():
        assert scope.scope_condition(ctx, lyr).as_string(None) == "true"
        assert scope.wms_subset(ctx, lyr) is None


def test_spatial_view_and_edit():
    ctx = _ctx(["od01"])
    dz = ctx.project.layers["dz"]
    view = scope.scope_condition(ctx, dz, scope.T, "view").as_string(None)
    assert 'FROM "dane"."oddzialy" AS "__b0"' in view
    assert '"__b0"."kod"::text = ANY(\'{od01}\'::text[])' in view
    assert 'ST_Intersects("__b0"."geom", "__t"."geom")' in view
    edit = scope.scope_condition(ctx, dz, scope.T, "edit").as_string(None)
    assert 'ST_Covers("__b0"."geom", ST_PointOnSurface("__t"."geom"))' in edit


def test_attribute_and_relation():
    ctx = _ctx(["od01", "od02"])
    dec = scope.scope_condition(ctx, ctx.project.layers["dec"]).as_string(None)
    assert dec == '"__t"."oddzial"::text = ANY(\'{od01,od02}\'::text[])'
    lus = scope.scope_condition(ctx, ctx.project.layers["lus"]).as_string(None)
    assert 'FROM "dane"."dzialki" AS "__p0" WHERE "__p0"."fid" = "__t"."dzialka_fid"' in lus
    assert 'ST_Intersects("__b1"."geom", "__p0"."geom")' in lus          # zakres działki nadrzędnej
    assert scope.scope_condition(ctx, ctx.project.layers["slow"]).as_string(None) == "true"


def test_no_codes_means_nothing_in_scoped_layers():
    ctx = _ctx([])
    assert "ARRAY[]::text[]" in scope.scope_condition(ctx, ctx.project.layers["dec"]).as_string(None) \
        or "'{}'::text[]" in scope.scope_condition(ctx, ctx.project.layers["dec"]).as_string(None)


def test_wms_subset_uses_table_names_and_header():
    ctx = _ctx(["od01"])
    subset = scope.wms_subset(ctx, ctx.project.layers["dz"])
    assert '"dane"."dzialki"."geom"' in subset and "__t" not in subset
    raw = scope.wms_filter_header(ctx)
    filters = json.loads(zlib.decompress(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))))
    assert set(filters) == {"dz", "dec", "lus"}                         # słownik i granice bez filtra


def test_srid_transform_when_layers_differ():
    ctx = _ctx(["od01"])
    ctx.project.layers["dz"].pg.srid = 4326
    view = scope.scope_condition(ctx, ctx.project.layers["dz"]).as_string(None)
    assert 'ST_Transform("__t"."geom", 2180)' in view


def test_explicit_none_and_single_code():
    p = _project({"dz": {"scope": {"mode": "none"}}})
    assert p.layers["dz"].scope_mode == "none"
    assert scope.single_code(SimpleNamespace(scope_codes=["od01"])) == "od01"
    assert scope.single_code(SimpleNamespace(scope_codes=["a", "b"])) is None
    assert scope.single_code(SimpleNamespace(scope_codes=None)) is None
