"""Wysyłka rastrów projektu na serwer Sophii (GeoTIFF, piramidy .ovr, mozaiki VRT) — bez skryptów.

Spis: pliki każdej warstwy rastrowej z dysku (GDAL GetFileList: VRT -> arkusze, .ovr, .aux.xml) i ich miejsce
na serwerze według układu projektu (checks._raster_location):
  - obok projektu  ./rastry/…        -> projekt  (data/projects/<slug>/rastry/…)
  - biblioteka     ../../rasters/<s> -> biblioteka (data/rasters/<s>/…, tylko administrator)
Kontrola: ścieżki względne w projekcie i w VRT, wielkość liter (serwer na Linuksie ją rozróżnia), piramidy.
Przygotowanie: poprawa VRT, piramidy, kopia rastra spoza projektu do rastry/<nazwa>/ z przepięciem warstwy.
Wysyłka: sumy SHA-256 (z pamięcią w .fia-hash.json), plan na serwerze, części po 32 MB z wznawianiem,
zatwierdzenie — serwer podmienia pliki i odświeża projekty (QGIS Server bez restartu).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable

from qgis.core import QgsProject, QgsRasterLayer

from . import publish, rasters
from .checks import LIBRARY_DIR

CHUNK = 32 * 1024 * 1024
ALLOWED = (".tif", ".tiff", ".ovr", ".vrt", ".aux.xml", ".tfw")
HASH_FILE = ".fia-hash.json"
RETRIES = 5


class Cancelled(Exception):
    pass


@dataclass
class RFile:
    local: str                     # ścieżka na dysku (wielkość liter jak na dysku)
    target: str                    # "project" | "library"
    rel: str                       # ścieżka w katalogu docelowym na serwerze
    size: int = 0
    sha256: str | None = None


@dataclass
class RLayer:
    layer_id: str
    name: str
    source: str
    files: list[RFile] = field(default_factory=list)
    issues: list[tuple[str, str]] = field(default_factory=list)     # (error|warning|info, opis)
    fixes: set[str] = field(default_factory=set)                    # vrt | overviews | copy | source_case
    state: str = ""                                                  # po sprawdzeniu na serwerze

    @property
    def target(self) -> str | None:
        kinds = {f.target for f in self.files}
        return kinds.pop() if len(kinds) == 1 else None

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def blocked(self) -> bool:
        return any(lvl == "error" for lvl, _ in self.issues)


# ------------------------------------------------------------------------------ ścieżki

def actual_case(path: str) -> str:
    """Ścieżka z wielkością liter jak na dysku (Windows ją ignoruje, serwer na Linuksie — nie)."""
    path = os.path.abspath(path)
    drive, rest = os.path.splitdrive(path)
    cur = drive.upper() + os.sep if drive else os.sep
    parts = [p for p in rest.replace("\\", "/").split("/") if p]
    for i, part in enumerate(parts):
        try:
            names = os.listdir(cur)
        except OSError:
            return os.path.join(cur, *parts[i:])      # katalog niedostępny — reszta bez zmian
        match = next((n for n in names if n == part), None)             or next((n for n in names if n.lower() == part.lower()), part)
        cur = os.path.join(cur, match)
    return cur


def locate(path: str, home: str) -> tuple[str, str] | None:
    """(cel, ścieżka w katalogu docelowym) według układu projektu albo None (poza projektem i biblioteką)."""
    try:
        rel = os.path.relpath(path, home).replace("\\", "/")
    except ValueError:                      # inny dysk niż projekt
        return None
    if not rel.startswith("../"):
        return "project", rel
    lib = f"../../{LIBRARY_DIR}/"
    if rel.startswith(lib) and rel.count("/") > 3:
        return "library", rel[len(lib):]
    return None


def vrt_sources(vrt_path: str) -> list[tuple[str, bool]]:
    """Źródła VRT: (tekst ścieżki, czy względna do VRT)."""
    try:
        root = ET.parse(vrt_path).getroot()
    except (OSError, ET.ParseError):
        return []
    return [((el.text or "").strip(), el.get("relativeToVRT") == "1")
            for el in root.iter() if el.tag in ("SourceFilename", "SourceDataset")]


def _abs_source(vrt_path: str, text: str, relative: bool) -> str:
    return os.path.normpath(os.path.join(os.path.dirname(vrt_path), text) if relative else text)


def has_overviews(path: str) -> bool:
    from osgeo import gdal
    if os.path.exists(path + ".ovr"):
        return True
    ds = gdal.Open(path)
    try:
        return bool(ds and ds.RasterCount and ds.GetRasterBand(1).GetOverviewCount())
    finally:
        ds = None


def raster_size(path: str) -> int:
    from osgeo import gdal
    ds = gdal.Open(path)
    try:
        return max(ds.RasterXSize, ds.RasterYSize) if ds else 0
    finally:
        ds = None


def layer_files(src: str) -> list[str]:
    """Pliki warstwy z dysku: GDAL GetFileList (VRT -> źródła), plus .ovr / .aux.xml obok każdego pliku."""
    from osgeo import gdal
    ds = gdal.Open(src)
    files = list(ds.GetFileList() or []) if ds else []
    ds = None
    files = files or [src]
    out, seen = [], set()
    for f in files:
        for g in (f, f + ".ovr", f + ".aux.xml"):
            key = os.path.normcase(os.path.abspath(g))
            if key not in seen and os.path.isfile(g):
                seen.add(key)
                out.append(os.path.abspath(g))
    return out


def project_paths_relative(prj: QgsProject) -> bool:
    try:
        from qgis.core import Qgis
        return prj.filePathStorage() == Qgis.FilePathType.Relative
    except AttributeError:                  # QGIS < 3.22
        absolute, _ = prj.readBoolEntry("Paths", "/Absolute", False)
        return not absolute


# ------------------------------------------------------------------------------ spis i kontrola

def inventory(prj: QgsProject | None = None) -> tuple[list[RLayer], list[tuple[str, str]]]:
    """Warstwy rastrowe z plików i problemy; drugi element — problemy całego projektu."""
    prj = prj or QgsProject.instance()
    home = prj.homePath()
    general = []
    if not project_paths_relative(prj):
        general.append(("error", "Projekt zapisuje ścieżki bezwzględne — Projekt → Właściwości → Ogólne → "
                                 "„Zapisz ścieżki: względne”, potem zapisz projekt"))
    out = []
    for lyr in prj.mapLayers().values():
        if not isinstance(lyr, QgsRasterLayer) or lyr.providerType() != "gdal":
            continue
        src = lyr.source().split("|")[0]
        if src.lower().startswith(("/vsi", "http://", "https://")):
            continue
        r = RLayer(lyr.id(), lyr.name(), src)
        out.append(r)
        if not os.path.isfile(src):
            r.issues.append(("error", f"Brak pliku {src}"))
            continue
        real = actual_case(src)
        if real != os.path.abspath(src):
            r.issues.append(("error", "Wielkość liter w ścieżce warstwy różni się od nazwy na dysku"))
            r.fixes.add("source_case")
        outside = False
        for f in layer_files(src):
            f = actual_case(f)
            if not f.lower().endswith(ALLOWED):
                r.issues.append(("error", f"Plik {os.path.basename(f)}: wysyłka obsługuje GeoTIFF i VRT "
                                          "(przekonwertuj do GeoTIFF, np. Raster → Konwersja → Przekształć)"))
                continue
            loc = locate(f, home)
            if loc is None:
                outside = True
                continue
            r.files.append(RFile(f, loc[0], loc[1], os.path.getsize(f)))
        if outside:
            r.issues.append(("error", f"Pliki poza katalogiem projektu i poza biblioteką "
                                      f"({os.path.normpath(os.path.join(home, '..', '..', LIBRARY_DIR))})"))
            r.fixes.add("copy")
        elif len({f.target for f in r.files}) > 1:
            r.issues.append(("error", "Pliki warstwy leżą częściowo w projekcie, częściowo w bibliotece"))
            r.fixes.add("copy")
        if src.lower().endswith(".vrt"):
            for text, relative in vrt_sources(src):
                absolute = _abs_source(src, text, relative)
                if not relative:
                    r.issues.append(("error", f"VRT: źródło „{text}” ze ścieżką bezwzględną"))
                    r.fixes.add("vrt")
                    break
                if os.path.exists(absolute) and actual_case(absolute) != os.path.abspath(absolute):
                    r.issues.append(("error", f"VRT: wielkość liter „{text}” różni się od nazwy na dysku"))
                    r.fixes.add("vrt")
                    break
            if not os.path.exists(src + ".ovr"):
                r.issues.append(("error", "Mozaika VRT bez piramid (.vrt.ovr) — oddalony widok byłby bardzo wolny"))
                r.fixes.add("overviews")
        elif raster_size(src) > 2048 and not has_overviews(src):
            r.issues.append(("warning", "Duży raster bez piramid — wolniejsze wyświetlanie"))
            r.fixes.add("overviews")
    return out, general


# ------------------------------------------------------------------------------ przygotowanie

def fix_vrt(vrt_path: str) -> None:
    """Źródła VRT jako ścieżki względne, z wielkością liter jak na dysku; kopia .bak obok."""
    tree = ET.parse(vrt_path)
    base = os.path.dirname(os.path.abspath(vrt_path))
    changed = False
    for el in tree.getroot().iter():
        if el.tag not in ("SourceFilename", "SourceDataset"):
            continue
        text, relative = (el.text or "").strip(), el.get("relativeToVRT") == "1"
        absolute = _abs_source(vrt_path, text, relative)
        if os.path.exists(absolute):
            absolute = actual_case(absolute)
        try:
            new = os.path.relpath(absolute, base).replace("\\", "/")
        except ValueError as e:
            raise RuntimeError(f"Źródło {absolute} jest na innym dysku niż VRT — użyj „Kopiuj do projektu”") from e
        if new != text or not relative:
            el.text, changed = new, True
            el.set("relativeToVRT", "1")
    if changed:
        shutil.copy2(vrt_path, vrt_path + ".bak")
        tree.write(vrt_path, encoding="UTF-8")


def copy_into_project(lyr: QgsRasterLayer, home: str, folder: str) -> str:
    """Raster spoza projektu -> <projekt>/rastry/<folder>/ (VRT razem z arkuszami, źródła przepisane
    na nazwy plików); warstwa przepięta na kopię. Zwraca nową ścieżkę."""
    src = lyr.source().split("|")[0]
    dest_dir = os.path.join(home, "rastry", folder)
    os.makedirs(dest_dir, exist_ok=True)
    files = layer_files(src)
    names: dict[str, str] = {}
    for f in files:
        name = os.path.basename(f)
        if name.lower() in {n.lower() for n in names.values()}:
            raise RuntimeError(f"Dwa pliki o tej samej nazwie {name} — skopiuj ręcznie")
        names[f] = name
    for f, name in names.items():
        shutil.copy2(f, os.path.join(dest_dir, name))
    new_main = os.path.join(dest_dir, os.path.basename(src))
    if src.lower().endswith(".vrt"):
        tree = ET.parse(new_main)
        for el in tree.getroot().iter():
            if el.tag in ("SourceFilename", "SourceDataset"):
                absolute = _abs_source(src, (el.text or "").strip(), el.get("relativeToVRT") == "1")
                el.text = os.path.basename(absolute)
                el.set("relativeToVRT", "1")
        tree.write(new_main, encoding="UTF-8")
    lyr.setDataSource(new_main, lyr.name(), "gdal")
    return new_main


def prepare(r: RLayer, home: str, folder: str | None = None) -> list[str]:
    """Wykonuje poprawki z r.fixes; zwraca opis tego, co zrobiono."""
    lyr = QgsProject.instance().mapLayer(r.layer_id)
    done = []
    if "copy" in r.fixes:
        new = copy_into_project(lyr, home, folder or os.path.splitext(os.path.basename(r.source))[0])
        done.append(f"skopiowano do {os.path.relpath(new, home)}")
        r.source = new
    elif "source_case" in r.fixes:
        lyr.setDataSource(actual_case(r.source), lyr.name(), "gdal")
        r.source = actual_case(r.source)
        done.append("poprawiono wielkość liter w ścieżce warstwy")
    if "vrt" in r.fixes and r.source.lower().endswith(".vrt"):
        # QGIS trzyma VRT otwarty i przy zamknięciu zapisuje go z pamięci (np. ze statystykami) — nadpisałby
        # poprawkę. Najpierw przeładowanie (zapis starej treści), potem poprawka, przeładowanie i kontrola.
        for _ in range(3):
            lyr.reload()
            fix_vrt(r.source)
            lyr.reload()
            if all(rel for _, rel in vrt_sources(r.source)):
                break
        else:
            raise RuntimeError("QGIS przywraca starą treść VRT — zamknij projekt, otwórz go ponownie i powtórz")
        done.append("źródła VRT względne (kopia .bak)")
    if "overviews" in r.fixes:
        rasters.build_overviews(r.source)
        done.append("zbudowano piramidy")
    if done:
        lyr.reload()
        lyr.triggerRepaint()
    return done


# ------------------------------------------------------------------------------ sumy kontrolne

def _cache_path(home: str) -> str:
    return os.path.join(home, HASH_FILE)


def load_cache(home: str) -> dict:
    try:
        with open(_cache_path(home), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_cache(home: str, cache: dict) -> None:
    tmp = _cache_path(home) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, _cache_path(home))


def sha256_file(path: str, cache: dict, progress: Callable[[int], bool] | None = None) -> str:
    st = os.stat(path)
    hashes = cache.setdefault("hashes", {})
    hit = hashes.get(path)
    if hit and hit["size"] == st.st_size and hit["mtime"] == st.st_mtime_ns:
        if progress and not progress(st.st_size):
            raise Cancelled()
        return hit["sha256"]
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
            if progress and not progress(len(block)):
                raise Cancelled()
    hashes[path] = {"size": st.st_size, "mtime": st.st_mtime_ns, "sha256": h.hexdigest()}
    return hashes[path]["sha256"]


# ------------------------------------------------------------------------------ API

def _headers(token: str, ctype: str = "application/json") -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": ctype}


def _api(base: str) -> str:
    return f"{base.rstrip('/')}/api/admin/rasters"


def target_spec(target: str, slug: str) -> dict:
    return {"library": True} if target == "library" else {"project": slug}


def plan(base: str, token: str, spec: dict, files: list[RFile], verify: bool, dry_run: bool = False) -> dict:
    body = {**spec, "dry_run": dry_run, "files": [{"path": f.rel, "size": f.size, "sha256": f.sha256} for f in files]}
    return publish._request(f"{_api(base)}/plan", json.dumps(body).encode(), _headers(token), verify)


def session_status(base: str, token: str, sid: str, verify: bool) -> dict:
    return publish._request(f"{_api(base)}/sessions/{sid}", None, _headers(token), verify, method="GET")


def commit(base: str, token: str, sid: str, delete_extra: bool, verify: bool) -> dict:
    return publish._request(f"{_api(base)}/sessions/{sid}/commit", json.dumps({"delete_extra": delete_extra}).encode(),
                            _headers(token), verify)


def abort(base: str, token: str, sid: str, verify: bool) -> None:
    try:
        publish._request(f"{_api(base)}/sessions/{sid}", None, _headers(token), verify, method="DELETE")
    except publish.ApiError:
        pass


def upload(base: str, token: str, sid: str, files: list[RFile], verify: bool,
           progress: Callable[[int, int, str], bool] | None = None) -> None:
    """Wysyła pliki sesji częściami od już odebranej długości; zrywane połączenie -> ponowienie (do 5 razy).
    progress(wysłane, razem, plik) -> False przerywa (sesja zostaje, można wznowić)."""
    received = {rel: f["received"] for rel, f in session_status(base, token, sid, verify)["files"].items()}
    todo = [f for f in files if f.rel in received]
    total = sum(f.size for f in todo)
    sent = sum(min(received[f.rel], f.size) for f in todo)
    for f in todo:
        offset, failures = received[f.rel], 0
        with open(f.local, "rb") as fh:
            while offset < f.size:
                if progress and not progress(sent, total, f.rel):
                    raise Cancelled()
                fh.seek(offset)
                data = fh.read(CHUNK)
                url = f"{_api(base)}/sessions/{sid}/file?" + urllib.parse.urlencode({"path": f.rel, "offset": offset})
                try:
                    res = publish._request(url, data, _headers(token, "application/octet-stream"), verify, method="PUT")
                except publish.ApiError as e:
                    if e.status == 409 and isinstance(e.detail, dict) and "received" in e.detail:
                        sent += e.detail["received"] - offset
                        offset = e.detail["received"]           # serwer ma więcej/mniej — od jego długości
                        continue
                    failures += 1
                    if e.status is not None and e.status < 500 or failures > RETRIES:
                        raise
                    time.sleep(min(2 * failures, 10))
                    offset_now = session_status(base, token, sid, verify)["files"][f.rel]["received"]
                    sent += offset_now - offset
                    offset = offset_now
                    continue
                sent += res["received"] - offset
                offset = res["received"]
                failures = 0
    if progress:
        progress(total, total, "")


def resumable(base: str, token: str, sid: str, files: dict[str, RFile], verify: bool) -> bool:
    """Czy przerwaną sesję można dokończyć: istnieje, a pliki lokalne się nie zmieniły."""
    try:
        st = session_status(base, token, sid, verify)
    except publish.ApiError:
        return False
    return all(rel in files and files[rel].sha256 == f["sha256"] and files[rel].size == f["size"]
               for rel, f in st["files"].items())
