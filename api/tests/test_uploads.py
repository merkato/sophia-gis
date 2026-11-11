import os
import time
from datetime import date

import pytest

from app import photos, uploads


@pytest.fixture
def root(tmp_path, monkeypatch):
    base = tmp_path / "uploads"
    monkeypatch.setattr(uploads, "uploads_dir", lambda slug: base / slug)
    r = base / "proj"
    for rel in ("zdjecia/punkty/2026-01/a.jpg", "zdjecia/punkty/2026-01/b.jpg",
                "pliki/decyzje/2026-01/x1/Decyzja.pdf", "zdjecia/punkty/2026-11/swieze.jpg"):
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * 10)
    old = time.time() - 30 * uploads.DAY
    for rel in ("zdjecia/punkty/2026-01/a.jpg", "zdjecia/punkty/2026-01/b.jpg", "pliki/decyzje/2026-01/x1/Decyzja.pdf"):
        os.utime(r / rel, (old, old))
    (r / photos.THUMBS_DIR / "ab").mkdir(parents=True)
    (r / photos.THUMBS_DIR / "ab" / "t.jpg").write_bytes(b"t")
    (r / uploads.TRASH).mkdir()
    (r / "zdjecia/punkty/2026-11/w_trakcie.jpg.part").write_bytes(b"p")
    return r


def test_scan_skips_thumbnails_trash_and_partial(root):
    paths = sorted(f.path for f in uploads.scan_files(root))
    assert paths == ["pliki/decyzje/2026-01/x1/Decyzja.pdf", "zdjecia/punkty/2026-01/a.jpg",
                     "zdjecia/punkty/2026-01/b.jpg", "zdjecia/punkty/2026-11/swieze.jpg"]


def test_classify_keeps_referenced_and_recent(root):
    files = uploads.scan_files(root)
    old, recent = uploads.classify(files, {"zdjecia/punkty/2026-01/a.jpg"}, min_age_days=7)
    assert sorted(f.path for f in old) == ["pliki/decyzje/2026-01/x1/Decyzja.pdf", "zdjecia/punkty/2026-01/b.jpg"]
    assert [f.path for f in recent] == ["zdjecia/punkty/2026-11/swieze.jpg"]


def test_move_to_trash_and_purge(root):
    thumb = photos.thumb_path(root, (root / "zdjecia/punkty/2026-01/b.jpg").resolve())
    thumb.parent.mkdir(parents=True, exist_ok=True)
    thumb.write_bytes(b"t")
    moved = uploads.move_to_trash("proj", ["zdjecia/punkty/2026-01/b.jpg", "pliki/decyzje/2026-01/x1/Decyzja.pdf",
                                           "../poza/katalogiem.txt", "nie/ma/pliku.jpg"], today=date(2026, 1, 20))
    assert moved == 2
    assert (root / ".kosz/2026-01-20/zdjecia/punkty/2026-01/b.jpg").is_file()
    assert (root / ".kosz/2026-01-20/pliki/decyzje/2026-01/x1/Decyzja.pdf").is_file()
    assert not thumb.exists()                                   # miniatura usunięta
    assert not (root / "pliki").exists()                        # puste katalogi posprzątane
    assert (root / "zdjecia/punkty/2026-01/a.jpg").is_file()    # pozostałe nietknięte
    assert uploads.trash_stats(root) == (2, 20)
    # kosz: wpis z 20.01 jest starszy niż 30 dni względem 1.03, młodszy względem 25.01
    assert uploads.purge_trash("proj", 30, now=time.mktime((2026, 1, 25, 0, 0, 0, 0, 0, -1))) == (0, 0)
    assert uploads.purge_trash("proj", 30, now=time.mktime((2026, 3, 1, 0, 0, 0, 0, 0, -1))) == (2, 20)
    assert uploads.trash_stats(root) == (0, 0)
