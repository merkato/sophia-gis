"""Lista projektów (menu w głównym oknie) i konfiguracja mapy dla WebUI."""
from dataclasses import asdict

from fastapi import APIRouter, Depends

from ..db import portal_conn
from ..permissions import load_project_context
from ..qgsproject import TreeNode
from ..security import CurrentUser, optional_user

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
async def list_projects(user: CurrentUser | None = Depends(optional_user)):
    async with portal_conn() as conn:
        if user and user.is_admin:
            rows = await (await conn.execute(
                "SELECT slug, title, description FROM portal.projects ORDER BY sort_order, title"
            )).fetchall()
        else:
            rows = await (await conn.execute(
                """SELECT DISTINCT p.slug, p.title, p.description, p.sort_order
                   FROM portal.projects p
                   LEFT JOIN portal.project_access pa ON pa.project_id = p.id AND pa.group_id = ANY(%s)
                   WHERE p.is_public OR pa.group_id IS NOT NULL
                   ORDER BY p.sort_order, p.title""",
                (user.group_ids if user else [],),
            )).fetchall()
    return [{"slug": r["slug"], "title": r["title"], "description": r["description"]} for r in rows]


def _filter_tree(node: TreeNode, visible_ids: set[str]) -> dict | None:
    if node.kind == "layer":
        return asdict(node) if node.layer_id in visible_ids else None
    children = [c for c in (_filter_tree(ch, visible_ids) for ch in node.children) if c]
    if node.kind == "raster_group":
        # Grupa rastrowa jest jednym węzłem — dzieci (pojedyncze GeoTIFF) nie trafiają do UI.
        d = asdict(node)
        d["children"] = []
        return d if children else None
    if not children and node.name:
        return None
    d = asdict(node)
    d["children"] = children
    return d


@router.get("/{slug}")
async def project_config(slug: str, user: CurrentUser | None = Depends(optional_user)):
    ctx = await load_project_context(slug, user)
    p = ctx.project
    layers = {}
    for lid, lyr in p.layers.items():
        perms = ctx.perms(lid)
        if not perms.view:
            continue
        layers[lid] = {
            "id": lid,
            "name": lyr.name,
            "wms_name": lyr.wms_name,
            "type": lyr.type,
            "tile_format": lyr.tile_format,
            "geometry_type": lyr.geometry_type,
            "crs": lyr.crs,
            "popup": lyr.popup,
            "attachments": lyr.attachments,
            "display_expression": lyr.display_expression,
            "primary_key": lyr.pg.key if lyr.pg else None,
            "fields": [asdict(f) for f in lyr.fields],
            "perms": asdict(perms),
        }
    visible = set(layers)
    return {
        "slug": ctx.slug,
        "title": ctx.title,
        "role": ctx.role,
        "crs": p.crs,
        # zmienia się przy każdej publikacji -> nowe adresy kafli (cache serwera i przeglądarki)
        "version": int(p.mtime),
        "extent": p.extent,
        "options": p.options,
        "tree": _filter_tree(p.tree, visible),
        "layers": layers,
        "relations": [
            asdict(r) for r in p.relations if r.parent_layer in visible and r.child_layer in visible
        ],
        "reports": [
            asdict(r) for r in p.reports if r.layer_id is None or r.layer_id in visible
        ],
    }
