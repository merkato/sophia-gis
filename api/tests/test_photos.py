import io
from datetime import date

import pytest
from PIL import Image

from app import photos
from app.qgsproject import FieldDef


def _jpeg_with_exif(w=4000, h=3000, orientation=6, gps=True) -> bytes:
    img = Image.new("RGB", (w, h), (200, 30, 30))
    exif = Image.Exif()
    exif[0x0112] = orientation
    exif[306] = "2026:11:11 09:30:00"
    exif.get_ifd(0x8769)[36867] = "2026:11:10 14:05:33"
    if gps:
        g = exif.get_ifd(0x8825)
        g[1], g[2] = "N", (50.0, 40.0, 30.0)       # 50°40'30" N
        g[3], g[4] = "E", (18.0, 12.0, 0.0)        # 18°12'00" E
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif.tobytes())
    return out.getvalue()


def test_process_photo_rotates_resizes_and_reads_exif():
    p = photos.process_photo(_jpeg_with_exif())
    # orientacja 6 = obrót o 90° -> pionowe; najdłuższy bok zmniejszony do PHOTO_MAX_PX
    assert (p.width, p.height) == (1920, photos.PHOTO_MAX_PX)
    assert p.taken_at == "2026-11-10T14:05:33"
    assert p.lat == pytest.approx(50.675)
    assert p.lon == pytest.approx(18.2)
    out = Image.open(io.BytesIO(p.jpeg))
    assert out.format == "JPEG"
    assert out.getexif().get(0x0112) == 1              # obraz już obrócony
    assert out.getexif().get_ifd(0x8825)                # GPS zostaje w pliku


def test_process_photo_png_without_exif():
    buf = io.BytesIO()
    Image.new("RGBA", (300, 200), (0, 0, 0, 0)).save(buf, "PNG")
    p = photos.process_photo(buf.getvalue())
    assert (p.width, p.height, p.lon, p.taken_at) == (300, 200, None, None)


def test_process_photo_rejects_non_image():
    with pytest.raises(photos.PhotoError):
        photos.process_photo(b"%PDF-1.7 to nie obraz")


def test_is_photo_field():
    assert photos.is_photo_field(FieldDef("foto", widget="ExternalResource", widget_config={"DocumentViewer": 1}))
    assert photos.is_photo_field(FieldDef("foto", widget="ExternalResource",
                                          widget_config={"DocumentViewer": 0, "FileWidgetFilter": "Obrazy (*.jpg *.png)"}))
    assert not photos.is_photo_field(FieldDef("plik", widget="ExternalResource", widget_config={"DocumentViewer": 0}))
    assert not photos.is_photo_field(FieldDef("foto", widget="TextEdit", widget_config={"DocumentViewer": 1}))


@pytest.mark.parametrize("value,expected", [
    ("zdjecia/a.jpg", "zdjecia/a.jpg"),
    ("./zdjecia\\b.jpg", "zdjecia/b.jpg"),
])
def test_normalize_value(value, expected):
    assert photos.normalize_value(value) == expected


@pytest.mark.parametrize("value", ["", None, "C:\\foto\\a.jpg", "/etc/passwd", "../../.env", "a/../../b.jpg",
                                   "https://example.com/a.jpg"])
def test_normalize_value_rejects(value):
    with pytest.raises(photos.PhotoError):
        photos.normalize_value(value)


def test_resolve_file_prefers_uploads_then_project(tmp_path):
    uploads, project = tmp_path / "uploads" / "proj", tmp_path / "projects" / "proj"
    (uploads / "zdjecia").mkdir(parents=True)
    (project / "zdjecia").mkdir(parents=True)
    (uploads / "zdjecia" / "a.jpg").write_bytes(b"u")
    (project / "zdjecia" / "a.jpg").write_bytes(b"p")
    (project / "zdjecia" / "b.jpg").write_bytes(b"p")
    assert photos.resolve_file("zdjecia/a.jpg", uploads, project).read_bytes() == b"u"
    assert photos.resolve_file("zdjecia/b.jpg", uploads, project).read_bytes() == b"p"
    assert photos.resolve_file("zdjecia/c.jpg", uploads, project) is None


def test_new_photo_path():
    p = photos.new_photo_path("Zdjęcia Obiektów", date(2026, 11, 11))
    assert p.startswith("zdjecia/zdj_cia_obiekt_w/2026-11/") and p.endswith(".jpg")


def test_thumb(tmp_path):
    src = tmp_path / "a.jpg"
    src.write_bytes(photos.process_photo(_jpeg_with_exif(gps=False)).jpeg)
    t = photos.ensure_thumb(src, photos.thumb_path(tmp_path / "up", src))
    assert max(Image.open(t).size) == photos.THUMB_PX


# ---------------------------------------------------------------- widoczność zdjęć wg obiektu nadrzędnego

class _Ctx:
    def __init__(self, layers, relations, viewable):
        from types import SimpleNamespace
        self.project = SimpleNamespace(layers=layers, relations=relations)
        self._viewable = viewable

    def perms(self, layer_id):
        from types import SimpleNamespace
        return SimpleNamespace(view=layer_id in self._viewable)


def _visibility_sql(viewable):
    from app.qgsproject import LayerDef, PgSource, RelationDef
    from app.routers.photos import visible_condition
    obj = LayerDef(id="obiekty", name="Obiekty", short_name=None, type="vector", provider="postgres", crs=None,
                   geometry_type="Polygon", display_expression=None,
                   pg=PgSource("service=sophia", "dane", "obiekty", "geom", "fid", None, None, None))
    pho = LayerDef(id="zdjecia", name="Zdjęcia", short_name=None, type="vector", provider="postgres", crs=None,
                   geometry_type=None, display_expression=None,
                   pg=PgSource("service=sophia", "dane", "obiekty_zdjecia", None, "fid", None, None, None))
    ctx = _Ctx({"obiekty": obj, "zdjecia": pho},
               [RelationDef("r1", "Zdjęcia", "obiekty", "zdjecia", [("fid", "obiekt_fid")])], viewable)
    return (visible_condition(ctx, pho, b"\x01").as_string(None),
            visible_condition(ctx, pho, None).as_string(None))


def test_photo_table_visibility_follows_parent_extent():
    with_extent, no_extent = _visibility_sql({"obiekty", "zdjecia"})
    assert 'EXISTS (SELECT 1 FROM "dane"."obiekty" AS __p WHERE "__p"."fid" = "__t"."obiekt_fid"' in with_extent
    assert 'ST_Intersects(ST_Transform("__p"."geom"' in with_extent
    assert no_extent == "true"                      # bez zasięgu: wystarczy dostęp do warstwy


def test_photo_table_hidden_when_parent_layer_not_viewable():
    with_extent, _ = _visibility_sql({"zdjecia"})
    assert with_extent.endswith("false")


# ---------------------------------------------------------------- dokumenty (PDF, GML…)

def _file_field(flt: str | None) -> FieldDef:
    return FieldDef("dokument", widget="ExternalResource", widget_config={"DocumentViewer": 0, "FileWidgetFilter": flt})


def test_allowed_extensions_from_qgis_filter():
    assert photos.allowed_extensions(_file_field("PDF (*.pdf);;GML z podpisem (*.gml *.xml)")) == {"pdf", "gml", "xml"}
    assert photos.allowed_extensions(_file_field("Wszystkie pliki (*.*)")) is None
    assert photos.allowed_extensions(_file_field("")) is None
    assert photos.allowed_extensions(_file_field(None)) is None


def test_check_extension():
    f = _file_field("PDF (*.pdf);;GML (*.gml)")
    assert photos.check_extension(f, "decyzja.PDF") == "pdf"
    with pytest.raises(photos.PhotoError, match="Dozwolone"):
        photos.check_extension(f, "skan.docx")
    with pytest.raises(photos.PhotoError, match="niedozwolone"):
        photos.check_extension(_file_field(None), "strona.html")   # zawsze blokowane, nawet bez filtra


@pytest.mark.parametrize("name,expected", [
    ("Decyzja nr 12_2026.pdf", "Decyzja nr 12_2026.pdf"),
    (r"C:\Users\x\Wniosek: ZPL?.gml", "Wniosek_ ZPL_.gml"),
    ("../../etc/passwd", "passwd"),
    ("   ", "plik"),
    (None, "plik"),
])
def test_safe_file_name(name, expected):
    assert photos.safe_file_name(name) == expected


def test_new_file_path_keeps_original_name():
    p = photos.new_file_path("decyzje", "Decyzja ZPL.gml", date(2026, 11, 11))
    assert p.startswith("pliki/decyzje/2026-11/") and p.endswith("/Decyzja ZPL.gml")
    assert photos.normalize_value(p) == p
    assert photos.is_file_field(_file_field("*.pdf")) and not photos.is_photo_field(_file_field("*.pdf"))
