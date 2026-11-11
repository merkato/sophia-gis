"""Sprzątanie osieroconych plików w katalogu uploadów projektu (data/uploads/<slug>/).

Osierocony = plik, do którego nie odwołuje się żaden rekord żadnej warstwy projektu (pola z widżetem
„Załącznik”; liczą się WSZYSTKIE rekordy tabel — bez filtrów warstw i zakresów użytkowników).
Zasady bezpieczeństwa:
  * pliki młodsze niż `min_age_days` (domyślnie 7) zostają — zdjęcie wysłane, a nie zapisane jeszcze
    w formularzu, też nie ma odwołania,
  * nic nie jest kasowane od razu: pliki trafiają do kosza projektu (`.kosz/<data>/<ścieżka>`),
    kosz opróżniamy osobno (domyślnie wpisy starsze niż 30 dni),
  * jeśli którejkolwiek warstwy z polem „Załącznik” nie da się odczytać, projekt jest pomijany
    (błąd bazy nie może zrobić z plików sierot).

Użycie: panel administratora (zakładka „Pliki”) albo
  docker compose exec api python -m app.uploads              # raport
  docker compose exec api python -m app.uploads --apply      # przenieś sieroty do kosza
  docker compose exec api python -m app.uploads --purge 30   # opróżnij kosz (starsze niż 30 dni)
"""
from __future__ import annotations

import asyncio
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from psycopg import sql

from . import photos
from .config import get_settings
from .db import layer_conn
from .qgsproject import Project

TRASH = ".kosz"
SKIP_DIRS = {photos.THUMBS_DIR, TRASH}
DAY = 86400


@dataclass
class FileInfo:
    path: str            # względem katalogu uploadów projektu (POSIX)
    size: int
    mtime: float


@dataclass
class Report:
    slug: str
    files: int = 0
    size: int = 0
    orphans: list[FileInfo] = field(default_factory=list)       # do przeniesienia (starsze niż próg)
    recent: list[FileInfo] = field(default_factory=list)        # bez odwołania, ale świeże — zostają
    missing: int = 0                                            # odwołania do nieistniejących plików
    trash_files: int = 0
    trash_size: int = 0
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "slug": self.slug, "files": self.files, "size": self.size,
            "orphans": len(self.orphans), "orphans_size": sum(f.size for f in self.orphans),
            "orphan_paths": [f.path for f in self.orphans[:200]],
            "recent": len(self.recent), "missing": self.missing,
            "trash_files": self.trash_files, "trash_size": self.trash_size, "error": self.error,
        }


def uploads_dir(slug: str) -> Path:
    return get_settings().uploads_dir / slug


def scan_files(root: Path) -> list[FileInfo]:
    """Pliki w katalogu uploadów projektu, bez miniatur, kosza i niedokończonych zapisów (*.part)."""
    out: list[FileInfo] = []
    if not root.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        if Path(dirpath) == root:
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".part"):
                continue
            p = Path(dirpath) / name
            st = p.stat()
            out.append(FileInfo(p.relative_to(root).as_posix(), st.st_size, st.st_mtime))
    return out


def classify(files: list[FileInfo], referenced: set[str], min_age_days: float,
             now: float | None = None) -> tuple[list[FileInfo], list[FileInfo]]:
    """(sieroty starsze niż próg, sieroty świeże)."""
    now = now or time.time()
    unreferenced = [f for f in files if f.path not in referenced]
    old = [f for f in unreferenced if now - f.mtime >= min_age_days * DAY]
    recent = [f for f in unreferenced if now - f.mtime < min_age_days * DAY]
    return old, recent


async def referenced_paths(project: Project) -> set[str]:
    """Znormalizowane ścieżki ze wszystkich pól „Załącznik” wszystkich warstw PostGIS projektu.
    Wyjątek (np. brak połączenia z bazą) przerywa — wywołujący pomija wtedy projekt."""
    refs: set[str] = set()
    for lyr in project.layers.values():
        fields = [f.name for f in lyr.fields if photos.is_resource_field(f)]
        if not fields or not lyr.pg:
            continue
        async with layer_conn(lyr.pg.conninfo) as conn:
            for name in fields:
                rows = await (await conn.execute(sql.SQL(
                    "SELECT DISTINCT {c}::text AS v FROM {t} WHERE {c} IS NOT NULL").format(
                    c=sql.Identifier(name), t=sql.Identifier(lyr.pg.schema, lyr.pg.table)))).fetchall()
                for r in rows:
                    try:
                        refs.add(photos.normalize_value(r["v"]))
                    except photos.PhotoError:
                        continue          # adresy URL, ścieżki bezwzględne — nie dotyczą uploadów
    return refs


def trash_stats(root: Path) -> tuple[int, int]:
    n = size = 0
    for dirpath, _dirs, filenames in os.walk(root / TRASH):
        for name in filenames:
            n += 1
            size += (Path(dirpath) / name).stat().st_size
    return n, size


async def analyze(slug: str, project: Project | None, min_age_days: float = 7) -> Report:
    root = uploads_dir(slug)
    rep = Report(slug)
    files = scan_files(root)
    rep.files, rep.size = len(files), sum(f.size for f in files)
    rep.trash_files, rep.trash_size = trash_stats(root)
    if project is None:
        rep.error = "Brak pliku projektu — pliki nie są analizowane"
        return rep
    try:
        refs = await referenced_paths(project)
    except Exception as e:  # noqa: BLE001 — każdy błąd odczytu wyklucza sprzątanie projektu
        rep.error = f"Nie udało się odczytać warstw: {e}"
        return rep
    rep.orphans, rep.recent = classify(files, refs, min_age_days)
    present = {f.path for f in files}
    rep.missing = sum(1 for r in refs if r.startswith(("zdjecia/", "pliki/")) and r not in present)
    return rep


def move_to_trash(slug: str, paths: list[str], today: date | None = None) -> int:
    """Przenosi pliki do .kosz/<data>/<ścieżka> (z zachowaniem podkatalogów); kasuje ich miniatury."""
    root = uploads_dir(slug)
    day = (today or date.today()).isoformat()
    moved = 0
    for rel in paths:
        src = (root / rel).resolve()
        if not src.is_relative_to(root.resolve()) or not src.is_file():
            continue
        dest = root / TRASH / day / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        # miniatura bywa zapisana pod ścieżką z wysyłki i pod rozwiązaną ścieżką z podglądu
        for key in {src, root / rel}:
            photos.thumb_path(root, key).unlink(missing_ok=True)
        shutil.move(str(src), str(dest))
        moved += 1
        # puste katalogi po przeniesieniu (np. zdjecia/tabela/2026-11/) — sprzątamy w górę
        parent = src.parent
        while parent != root.resolve() and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    return moved


def purge_trash(slug: str, older_than_days: float = 30, now: float | None = None) -> tuple[int, int]:
    """Usuwa z kosza katalogi dni starsze niż próg (po dacie w nazwie). Zwraca (pliki, bajty)."""
    trash = uploads_dir(slug) / TRASH
    if not trash.is_dir():
        return 0, 0
    now = now or time.time()
    n = size = 0
    for day_dir in trash.iterdir():
        try:
            day = datetime.strptime(day_dir.name, "%Y-%m-%d").timestamp()
        except ValueError:
            continue
        if now - day < older_than_days * DAY:
            continue
        for dirpath, _d, filenames in os.walk(day_dir):
            for name in filenames:
                n += 1
                size += (Path(dirpath) / name).stat().st_size
        shutil.rmtree(day_dir)
    return n, size


# --------------------------------------------------------------------------- wiersz poleceń


async def _main(apply: bool, min_age: float, purge: float | None) -> None:
    from .db import close_pools, portal_conn
    from .qgsproject import get_project

    async with portal_conn() as conn:
        projects = await (await conn.execute("SELECT slug, file_name FROM portal.projects ORDER BY slug")).fetchall()
    try:
        for p in projects:
            path = (get_settings().projects_dir / p["file_name"]).resolve()
            project = get_project(path) if path.exists() else None
            rep = await analyze(p["slug"], project, min_age)
            d = rep.as_dict()
            line = (f"{p['slug']}: plików {d['files']} ({d['size'] / 1e6:.1f} MB), sierot {d['orphans']} "
                    f"({d['orphans_size'] / 1e6:.1f} MB), świeżych bez odwołania {d['recent']}, "
                    f"brakujących plików {d['missing']}, w koszu {d['trash_files']}")
            print(line + (f" — POMINIĘTY: {rep.error}" if rep.error else ""))
            if apply and not rep.error and rep.orphans:
                print(f"  przeniesiono do kosza: {move_to_trash(p['slug'], [f.path for f in rep.orphans])}")
            if purge is not None:
                n, size = purge_trash(p["slug"], purge)
                if n:
                    print(f"  usunięto z kosza: {n} plików ({size / 1e6:.1f} MB)")
    finally:
        await close_pools()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Osierocone pliki w data/uploads (zdjęcia, dokumenty)")
    ap.add_argument("--apply", action="store_true", help="przenieś sieroty do kosza (bez tego: tylko raport)")
    ap.add_argument("--min-age", type=float, default=7, help="pomiń pliki młodsze niż N dni (domyślnie 7)")
    ap.add_argument("--purge", type=float, default=None, metavar="DNI", help="opróżnij kosz z wpisów starszych niż N dni")
    a = ap.parse_args()
    asyncio.run(_main(a.apply, a.min_age, a.purge))
