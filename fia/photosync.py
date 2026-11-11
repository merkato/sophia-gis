"""Pobieranie zdjęć z Sophii do folderu projektu (tylko serwer -> QGIS).

W bazie są ścieżki względne (np. zdjecia/obiekty/2026-11/<uuid>.jpg), więc po skopiowaniu plików
do folderu projektu QGIS pokazuje je w formularzu bez żadnych zmian w projekcie, także offline.
Serwer zwraca tylko zdjęcia obiektów, które zalogowany użytkownik może oglądać (projekt, warstwa,
zasięg przestrzenny). Pobierane są tylko pliki nowe lub zmienione (rozmiar, data modyfikacji).
"""
from __future__ import annotations

import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

from .publish import ApiError, _request, _ssl_context


@dataclass
class SyncResult:
    downloaded: int = 0
    up_to_date: int = 0
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False


def manifest(base_url: str, token: str, slug: str, verify: bool = True) -> list[dict]:
    url = f"{base_url.rstrip('/')}/api/projects/{urllib.parse.quote(slug)}/photos"
    return _request(url, None, {"Authorization": f"Bearer {token}"}, verify, method="GET").get("files", [])


def _target(home: str, rel: str) -> str:
    dest = os.path.normpath(os.path.join(home, *rel.split("/")))
    if os.path.commonpath([dest, os.path.normpath(home)]) != os.path.normpath(home):
        raise ApiError(f"Ścieżka poza folderem projektu: {rel}")
    return dest


def _fresh(dest: str, entry: dict) -> bool:
    try:
        st = os.stat(dest)
    except OSError:
        return False
    return st.st_size == entry["size"] and int(st.st_mtime) == int(entry["mtime"])


def _download(base_url: str, token: str, slug: str, entry: dict, dest: str, verify: bool) -> None:
    q = urllib.parse.quote
    url = (f"{base_url.rstrip('/')}/api/projects/{q(slug)}/layers/{q(entry['layer_id'])}"
           f"/features/{q(str(entry['pk']))}/files/{q(entry['field'])}")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest), suffix=".part")
    try:
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(req, context=_ssl_context(verify), timeout=120) as r:
            while chunk := r.read(1024 * 256):
                out.write(chunk)
        os.replace(tmp, dest)
        os.utime(dest, (entry["mtime"], entry["mtime"]))   # porównanie przy następnej synchronizacji
    except urllib.error.HTTPError as e:
        raise ApiError(f"HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise ApiError(f"Brak połączenia: {e.reason}") from e
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def sync(base_url: str, token: str, slug: str, home: str, verify: bool = True,
         progress: Callable[[int, int, str], bool] | None = None) -> SyncResult:
    """progress(i, n, ścieżka) -> False przerywa."""
    res = SyncResult()
    files = manifest(base_url, token, slug, verify)
    for i, entry in enumerate(files):
        if progress and not progress(i, len(files), entry["path"]):
            res.cancelled = True
            break
        try:
            dest = _target(home, entry["path"])
            if _fresh(dest, entry):
                res.up_to_date += 1
                continue
            _download(base_url, token, slug, entry, dest, verify)
            res.downloaded += 1
        except (ApiError, OSError) as e:
            res.errors.append(f"{entry['path']}: {e}")
    return res
