"""Wysyłka rastrów z Fii: ścieżki, walidacja VRT, nadmiar, zatwierdzenie sesji z odświeżeniem projektów."""
import hashlib
import json
import os
import time
import zipfile

import pytest
from fastapi import HTTPException

from app.routers import rasters as r

TIFF = b"II*\x00" + b"\x00" * 60


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def vrt(*sources: str, rel: str = "1") -> bytes:
    body = "".join(f'<SimpleSource><SourceFilename relativeToVRT="{rel}">{s}</SourceFilename></SimpleSource>'
                   for s in sources)
    return f'<VRTDataset rasterXSize="1" rasterYSize="1"><VRTRasterBand band="1">{body}</VRTRasterBand></VRTDataset>'.encode()


def test_clean_path():
    assert r.clean_path("rastry/tk25/Arkusz 1.tif") == "rastry/tk25/Arkusz 1.tif"
    assert r.clean_path("a.vrt.ovr") == "a.vrt.ovr"
    assert r.clean_path("a.tif.aux.xml") == "a.tif.aux.xml"
    for bad in ("../a.tif", "/etc/a.tif", "a\\b.tif", "rastry/.ukryty/a.tif", "C:/a.tif", "a.qgz", "a.py", ""):
        with pytest.raises(HTTPException):
            r.clean_path(bad)


def test_validate_vrt():
    have = {"rastry/s/a.tif", "rastry/s/b.tif", "rastry/inne/c.tif"}.__contains__
    r.validate_vrt(vrt("a.tif", "b.tif", "../inne/c.tif"), "rastry/s/m.vrt", have)
    for data, msg in ((vrt("E:/gis/a.tif", rel="0"), "względn"), (vrt("/etc/passwd"), "względn"),
                      (vrt("/vsicurl/http://x/a.tif"), "względn"), (vrt("../../../a.tif"), "poza katalog"),
                      (vrt("A.TIF"), "wielkość liter"), (b"<x/>", "VRTDataset"), (b"<VRT", "XML"),
                      (b'<VRTDataset><VRTRasterBand><PixelFunctionLanguage>Python</PixelFunctionLanguage>'
                       b'</VRTRasterBand></VRTDataset>', "Python")):
        with pytest.raises(ValueError, match=msg):
            r.validate_vrt(data, "rastry/s/m.vrt", have)


def test_extra_and_hash_cache(tmp_path):
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "a.tif").write_bytes(TIFF)
    (tmp_path / "s" / "stary.tif").write_bytes(TIFF)
    (tmp_path / "s" / "notatki.txt").write_text("x")
    assert r.extra_files(tmp_path, {"s/a.tif"}) == ["s/stary.tif"]
    cache = {}
    assert r.server_hash(tmp_path, "s/a.tif", cache) == sha(TIFF)
    assert cache["s/a.tif"]["sha256"] == sha(TIFF)
    cache["s/a.tif"]["sha256"] = "z-pamieci"                       # ten sam rozmiar i czas -> z pamięci
    assert r.server_hash(tmp_path, "s/a.tif", cache) == "z-pamieci"
    assert r.server_hash(tmp_path, "s/brak.tif", cache) is None


def test_cleanup_stale(tmp_path):
    old = tmp_path / ".upload-old"
    old.mkdir()
    os.utime(old, (time.time() - 2 * r.SESSION_TTL_S,) * 2)
    (tmp_path / ".upload-new").mkdir()
    assert r.cleanup_stale(tmp_path) == 1
    assert not old.exists() and (tmp_path / ".upload-new").exists()


def _session(root, files: dict[str, bytes], target="project:p", upload=None, parts=None):
    sid = "0" * 32
    sdir = root / f".upload-{sid}"
    sdir.mkdir()
    upload = list(files) if upload is None else upload
    sess = {"id": sid, "user_id": 1, "target": target, "upload": upload,
            "files": {k: {"size": len(v), "sha256": sha(v)} for k, v in files.items()}}
    for rel in upload:
        part = sdir / (rel + ".part")
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes((parts or files)[rel])
    return sess, sdir


def test_apply_project_session(tmp_path):
    projects = tmp_path / "projects"
    root = projects / "p"
    (root / "rastry" / "s").mkdir(parents=True)
    qgz = root / "p.qgz"
    qgz.write_bytes(b"x")
    os.utime(qgz, (1_000_000, 1_000_000))
    (root / "rastry" / "s" / "a.tif").write_bytes(b"MM\x00*stary")
    (root / "rastry" / "s" / "usuniety.tif").write_bytes(TIFF)
    m = vrt("a.tif", "b.tif")
    sess, sdir = _session(root, {"rastry/s/a.tif": TIFF, "rastry/s/b.tif": TIFF + b"b", "rastry/s/m.vrt": m})
    res = r.apply_session(sess, sdir, root, False, projects)
    assert res["added"] == ["rastry/s/b.tif", "rastry/s/m.vrt"] and res["replaced"] == ["rastry/s/a.tif"]
    assert res["extra"] == ["rastry/s/usuniety.tif"] and res["deleted"] == [] and res["projects"] == ["p"]
    assert (root / "rastry" / "s" / "a.tif").read_bytes() == TIFF and not sdir.exists()
    assert qgz.stat().st_mtime > 1_000_000                          # projekt odświeżony -> QGIS Server przeładuje
    assert json.loads((root / r.HASH_CACHE).read_text())["rastry/s/m.vrt"]["sha256"] == sha(m)

    # drugi raz: usunięcie nadmiaru
    sess, sdir = _session(root, {"rastry/s/a.tif": TIFF, "rastry/s/b.tif": TIFF + b"b", "rastry/s/m.vrt": m},
                          upload=["rastry/s/m.vrt"])
    res = r.apply_session(sess, sdir, root, True, projects)
    assert res["deleted"] == ["rastry/s/usuniety.tif"] and not (root / "rastry/s/usuniety.tif").exists()


def test_apply_rejects(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    # niedokończona wysyłka
    sess, sdir = _session(root, {"a.tif": TIFF}, parts={"a.tif": TIFF[:10]})
    with pytest.raises(ValueError, match="dokończ"):
        r.apply_session(sess, sdir, root, False, tmp_path)
    (sdir / "a.tif.part").write_bytes(b"X" * len(TIFF))             # zła suma
    with pytest.raises(ValueError, match="suma"):
        r.apply_session(sess, sdir, root, False, tmp_path)
    assert not (sdir / "a.tif.part").exists()                        # do ponownej wysyłki
    import shutil
    shutil.rmtree(sdir)
    # nie-TIFF i VRT z brakującym źródłem — nic nie trafia na miejsce
    sess, sdir = _session(root, {"a.tif": b"GIF89a.....", "m.vrt": vrt("brak.tif")})
    with pytest.raises(ValueError):
        r.apply_session(sess, sdir, root, False, tmp_path)
    assert not (root / "a.tif").exists() and not (root / "m.vrt").exists() and sdir.exists()


def test_library_touches_projects_using_series(tmp_path):
    projects, lib = tmp_path / "projects", tmp_path / "rasters"
    for slug, src in (("uzywa", "../../rasters/tk25/tk25.vrt"), ("nie", "./rastry/x.tif")):
        (projects / slug).mkdir(parents=True)
        with zipfile.ZipFile(projects / slug / f"{slug}.qgz", "w") as z:
            z.writestr(f"{slug}.qgs", f"<qgis><datasource>{src}</datasource></qgis>")
        os.utime(projects / slug / f"{slug}.qgz", (1_000_000, 1_000_000))
    lib.mkdir()
    sess, sdir = _session(lib, {"tk25/a.tif": TIFF, "tk25/tk25.vrt": vrt("a.tif")}, target="library")
    res = r.apply_session(sess, sdir, lib, False, projects)
    assert res["projects"] == ["uzywa"]
    assert (projects / "nie" / "nie.qgz").stat().st_mtime == 1_000_000
