"""Nagłówki autoryzacji WMS muszą być w ASCII — polskie nazwy grup nie mogą wywracać kafli mapy (500)."""
import asyncio
import types

from starlette.requests import Request

from app.routers import ows
from app.security import CurrentUser


def test_authorize_headers_ascii(monkeypatch, tmp_path):
    project = types.SimpleNamespace(layers={}, tree=types.SimpleNamespace(kind="group", name="", children=[]))
    ctx = types.SimpleNamespace(path=tmp_path / "p.qgs", project=project, perms=lambda lid: None)

    async def fake_ctx(slug, user):
        return ctx
    monkeypatch.setattr(ows, "load_project_context", fake_ctx)
    monkeypatch.setattr(ows, "wms_filter_header", lambda c: "")
    user = CurrentUser(id=1, login="stanisław", full_name=None, is_admin=False, group_ids=[5],
                       group_names=["Przeglądający nadleśnictwo", "Edytor RDLP"])
    req = Request({"type": "http", "method": "GET", "path": "/api/ows/authorize", "headers": [],
                   "query_string": b"PROJECT=demo&REQUEST=GetMap&SERVICE=WMS"})
    resp = asyncio.run(ows.authorize(req, user))
    raw = dict(resp.raw_headers)
    assert raw[b"x-portal-groups"] == b"Przegl%C4%85daj%C4%85cy%20nadle%C5%9Bnictwo,Edytor%20RDLP"
    assert raw[b"x-portal-user"] == b"stanis%C5%82aw"
