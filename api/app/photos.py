"""Zdjęcia i dokumenty w polach z widżetem QGIS „Załącznik” (ExternalResource).

W bazie (kolumna tekstowa) zapisujemy ścieżkę WZGLĘDNĄ, np. ``zdjecia/punkty/2026-11/<uuid>.jpg`` —
tak samo, jak zapisuje ją QGIS przy ustawieniu „Ścieżka względna do projektu”. Na serwerze plik
leży w katalogu uploadów projektu (``data/uploads/<slug>/...``); jeśli go tam nie ma, szukamy obok
pliku projektu (zdjęcia opublikowane razem z projektem z QGIS).

Zdjęcia z telefonu: obrót wg EXIF, zmniejszenie do PHOTO_MAX_PX, JPEG; data i GPS z EXIF zostają
w pliku i są zwracane (GPS -> geometria punktu w tabeli zdjęć). HEIC (iPhone) przez pillow-heif.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

try:  # HEIC/HEIF z iPhone'a — opcjonalnie, gdyby koło nie było dostępne na danej platformie
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:  # pragma: no cover
    pass

from .qgsproject import FieldDef

PHOTO_MAX_PX = 2560
THUMB_PX = 480
JPEG_QUALITY = 85
THUMBS_DIR = ".miniatury"

_IMAGE_EXT = re.compile(r"\.(jpe?g|png|gif|webp|heic|heif|tiff?|bmp)\b", re.IGNORECASE)


class PhotoError(ValueError):
    """Plik nie jest obrazem albo ścieżka jest niepoprawna."""


# --------------------------------------------------------------------------- pola


def is_resource_field(f: FieldDef) -> bool:
    return f.widget == "ExternalResource"


def is_photo_field(f: FieldDef) -> bool:
    """Pole „Załącznik” z podglądem obrazu (Podgląd zawartości: Obraz) albo filtrem plików graficznych."""
    if not is_resource_field(f):
        return False
    cfg = f.widget_config or {}
    viewer = cfg.get("DocumentViewer")
    if str(viewer) == "1":
        return True
    return bool(_IMAGE_EXT.search(str(cfg.get("FileWidgetFilter") or "")))


# --------------------------------------------------------------------------- ścieżki


def normalize_value(value: Any) -> str:
    """Wartość pola -> ścieżka względna w formacie POSIX. Bezwzględne ścieżki (C:\\..., /home/...) odrzucamy."""
    s = str(value or "").strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    if not s:
        raise PhotoError("Pole jest puste")
    if s.startswith("/") or re.match(r"^[A-Za-z]:", s) or "://" in s:
        raise PhotoError("Ścieżka bezwzględna lub adres URL — w QGIS ustaw „Ścieżka względna do projektu”")
    parts = PurePosixPath(s).parts
    if any(p == ".." for p in parts):
        raise PhotoError("Ścieżka wychodzi poza katalog projektu")
    return str(PurePosixPath(*parts))


def _inside(base: Path, rel: str) -> Path | None:
    p = (base / rel).resolve()
    return p if p.is_relative_to(base.resolve()) else None


def resolve_file(rel: str, uploads: Path, project_dir: Path) -> Path | None:
    """Plik dla ścieżki z pola: najpierw katalog uploadów projektu, potem katalog pliku .qgs."""
    for base in (uploads, project_dir):
        p = _inside(base, rel)
        if p is not None and p.is_file():
            return p
    return None


def new_photo_path(table: str, today: date | None = None) -> str:
    today = today or date.today()
    safe = re.sub(r"[^0-9A-Za-z_-]+", "_", table).strip("_").lower() or "warstwa"
    return f"zdjecia/{safe}/{today:%Y-%m}/{uuid.uuid4().hex}.jpg"


def thumb_path(uploads: Path, src: Path) -> Path:
    key = hashlib.sha1(str(src).encode()).hexdigest()
    return uploads / THUMBS_DIR / key[:2] / f"{key}.jpg"


# --------------------------------------------------------------------------- obrazy


@dataclass
class Photo:
    jpeg: bytes
    width: int
    height: int
    taken_at: str | None = None        # ISO 8601 z EXIF DateTimeOriginal (czas lokalny aparatu)
    lon: float | None = None
    lat: float | None = None


def _ratio(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError, ZeroDivisionError):
        num, den = v
        return num / den


def _gps(exif: Image.Exif) -> tuple[float, float] | None:
    g = exif.get_ifd(0x8825)
    try:
        lat = sum(_ratio(x) / 60 ** i for i, x in enumerate(g[2]))
        lon = sum(_ratio(x) / 60 ** i for i, x in enumerate(g[4]))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    if str(g.get(1, "N")).upper().startswith("S"):
        lat = -lat
    if str(g.get(3, "E")).upper().startswith("W"):
        lon = -lon
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    return lon, lat


def _taken_at(exif: Image.Exif) -> str | None:
    raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)       # DateTimeOriginal / DateTime
    m = re.match(r"(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})", str(raw or ""))
    return f"{m[1]}-{m[2]}-{m[3]}T{m[4]}:{m[5]}:{m[6]}" if m else None


def process_photo(data: bytes, max_px: int = PHOTO_MAX_PX) -> Photo:
    """Obraz z aparatu/galerii -> JPEG obrócony wg EXIF, najdłuższy bok <= max_px, z zachowanym EXIF."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise PhotoError("To nie jest obsługiwany plik graficzny (JPEG, PNG, HEIC, WebP…)") from e
    exif = img.getexif()
    gps = _gps(exif)
    taken = _taken_at(exif)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        rgba = img.convert("RGBA")
        img = Image.new("RGB", rgba.size, "white")
        img.paste(rgba, mask=rgba.split()[3])
    img.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
    exif[0x0112] = 1                        # obraz już obrócony
    out = io.BytesIO()
    img.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, exif=exif.tobytes())
    return Photo(out.getvalue(), img.width, img.height, taken, *(gps or (None, None)))


def write_atomic(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def ensure_thumb(src: Path, dest: Path, px: int = THUMB_PX) -> Path:
    """Miniatura tworzona przy pierwszym żądaniu (także dla zdjęć opublikowanych z projektem)."""
    if dest.is_file() and dest.stat().st_mtime >= src.stat().st_mtime:
        return dest
    with Image.open(src) as img:
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail((px, px), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, "JPEG", quality=80)
    write_atomic(dest, out.getvalue())
    return dest


# --------------------------------------------------------------------------- pliki (PDF, GML, …)
# Dokumenty zapisujemy bajt w bajt (podpisy elektroniczne, np. XAdES w GML, muszą zostać nienaruszone),
# z oryginalną nazwą w osobnym podkatalogu: pliki/<tabela>/<rok-miesiąc>/<id>/<nazwa>.

# Zawsze odrzucane: pliki wykonywalne i treści, które przeglądarka mogłaby uruchomić
BLOCKED_EXT = {"exe", "com", "bat", "cmd", "msi", "scr", "ps1", "vbs", "js", "jse", "wsf", "sh", "jar",
               "html", "htm", "xhtml", "svg", "hta", "php", "dll", "lnk"}
# Wyświetlane w przeglądarce; pozostałe są pobierane (Content-Disposition: attachment)
INLINE_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp"}

_FILTER_EXT = re.compile(r"\*\.([0-9A-Za-z_+-]+)")


def is_file_field(f: FieldDef) -> bool:
    """Pole „Załącznik” na dokumenty (bez podglądu obrazu)."""
    return is_resource_field(f) and not is_photo_field(f)


def allowed_extensions(f: FieldDef) -> set[str] | None:
    """Rozszerzenia z filtra plików widżetu (np. „PDF (*.pdf);;GML (*.gml *.xml)”). None = dowolne."""
    flt = str((f.widget_config or {}).get("FileWidgetFilter") or "")
    if not flt.strip() or "*.*" in flt or re.search(r"\(\s*\*\s*\)", flt):
        return None
    exts = {e.lower() for e in _FILTER_EXT.findall(flt)}
    return exts or None


def safe_file_name(name: str | None) -> str:
    """Oryginalna nazwa pliku bez ścieżki i znaków niedozwolonych w Windows/Linux."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r'[\x00-\x1f<>:"|?*]+', "_", base).strip(" .")
    if len(base) > 120:
        stem, dot, ext = base.rpartition(".")
        base = (stem[:110] + dot + ext[:9]) if dot else base[:120]
    return base or "plik"


def check_extension(f: FieldDef, name: str) -> str:
    ext = name.rpartition(".")[2].lower() if "." in name else ""
    if ext in BLOCKED_EXT:
        raise PhotoError(f"Pliki .{ext} są niedozwolone")
    allowed = allowed_extensions(f)
    if allowed is not None and ext not in allowed:
        raise PhotoError("Dozwolone typy plików: " + ", ".join(f".{e}" for e in sorted(allowed)))
    return ext


def new_file_path(table: str, name: str, today: date | None = None) -> str:
    today = today or date.today()
    safe = re.sub(r"[^0-9A-Za-z_-]+", "_", table).strip("_").lower() or "warstwa"
    return f"pliki/{safe}/{today:%Y-%m}/{uuid.uuid4().hex[:12]}/{safe_file_name(name)}"


def display_name(rel: str) -> str:
    return rel.rsplit("/", 1)[-1]
