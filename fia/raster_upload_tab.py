"""Zakładka „Wysyłka rastrów”: spis rastrów projektu, kontrola, „Przygotuj…”, sprawdzenie i wysyłka na serwer
(fia/rasterupload.py). Logowanie i adres serwera — z zakładki „Serwer” (przekazane funkcje)."""
from __future__ import annotations

import os
import time
from typing import Callable

from qgis.core import QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import publish
from . import rasterupload as ru

COLS = ["Warstwa", "Na serwerze", "Pliki", "Rozmiar", "Stan", "Uwagi"]
COLORS = {"error": QColor("#c92a2a"), "warning": QColor("#e67700"), "ok": QColor("#2b8a3e"),
          "info": QColor("#1971c2")}
TARGET_LABEL = {"project": "obok projektu", "library": "biblioteka rastrów"}


def mb(n: int) -> str:
    return f"{n / 2**20:,.1f} MB".replace(",", " ")


class RasterUploadTab(QWidget):
    def __init__(self, iface, server: Callable[[], tuple[str, bool]], token: Callable[[], str | None],
                 slug: Callable[[], str], parent=None):
        super().__init__(parent)
        self.iface, self.server, self.token_fn, self.slug_fn = iface, server, token, slug
        self.layers: list[ru.RLayer] = []
        self.general: list[tuple[str, str]] = []

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(True)
        self.summary = QLabel()
        self.summary.setWordWrap(True)

        buttons = QHBoxLayout()
        for text, slot in (("Odśwież", self.refresh), ("Przygotuj zaznaczone…", self.on_prepare),
                           ("Sprawdź na serwerze", self.on_check), ("Wyślij zmienione", self.on_send)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        buttons.addStretch()

        lay = QVBoxLayout(self)
        info = QLabel(
            "Rastry z plików (GeoTIFF, mozaiki VRT, piramidy .ovr) trafiają na serwer według położenia w projekcie: "
            "folder obok projektu (np. rastry/) → katalog projektu na serwerze; biblioteka ../../rasters/<seria> → "
            "biblioteka rastrów (tylko administrator). Wysyłane są tylko pliki nowe i zmienione; po wysyłce mapa "
            "pokazuje nowe rastry bez restartu serwera. Przerwaną wysyłkę wznawia ponowne „Wyślij zmienione”.")
        info.setWordWrap(True)
        lay.addWidget(info)
        lay.addLayout(buttons)
        lay.addWidget(self.table)
        lay.addWidget(self.summary)
        self.refresh()

    # ------------------------------------------------------------------ spis
    def refresh(self):
        prj = QgsProject.instance()
        if not prj.fileName():
            self.layers, self.general = [], [("error", "Najpierw zapisz projekt")]
        else:
            try:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                self.layers, self.general = ru.inventory(prj)
            finally:
                QApplication.restoreOverrideCursor()
        self._fill()

    def _fill(self):
        self.table.setRowCount(len(self.layers))
        for row, r in enumerate(self.layers):
            issues = "; ".join(t for _, t in r.issues)
            level = "error" if r.blocked else ("warning" if r.issues else "ok")
            state = r.state or ("do poprawy" if r.blocked else "")
            cells = [r.name, TARGET_LABEL.get(r.target or "", "—"), str(len(r.files)), mb(r.size), state,
                     issues + (" — „Przygotuj…” poprawi" if r.fixes else "")]
            for col, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setToolTip(text if col != 2 else "\n".join(f.rel for f in r.files))
                if col in (4, 5) and (r.issues or r.state):
                    it.setForeground(COLORS["ok"] if r.state == "aktualne" else COLORS[level])
                self.table.setItem(row, col, it)
        self.table.resizeRowsToContents()
        lines = [t for _, t in self.general]
        total = sum(r.size for r in self.layers)
        lines.append(f"Rastrów: {len(self.layers)}, plików: {sum(len(r.files) for r in self.layers)}, {mb(total)}. "
                     f"Do poprawy: {sum(r.blocked for r in self.layers)}.")
        self.summary.setText("\n".join(lines))

    def _selected(self) -> list[ru.RLayer]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.layers[r] for r in rows]

    # ------------------------------------------------------------------ przygotowanie
    def on_prepare(self):
        sel = [r for r in self._selected() if r.fixes] or [r for r in self.layers if r.fixes]
        if not sel:
            QMessageBox.information(self, "Fia", "Nie ma czego poprawiać.")
            return
        home = QgsProject.instance().homePath()
        plan = "\n".join(f"• {r.name}: " + ", ".join(
            {"vrt": "źródła VRT względne (kopia .bak)", "overviews": "piramidy (.ovr)",
             "copy": "kopia do folderu rastry/ obok projektu i przepięcie warstwy",
             "source_case": "wielkość liter w ścieżce warstwy"}[f] for f in sorted(r.fixes)) for r in sel)
        if QMessageBox.question(self, "Fia", f"Przygotować rastry?\n\n{plan}") != QMessageBox.StandardButton.Yes:
            return
        report = []
        for r in sel:
            folder = None
            if "copy" in r.fixes:
                folder, ok = QInputDialog.getText(self, "Fia", f"Folder w rastry/ dla „{r.name}”:",
                                                  text=os.path.splitext(os.path.basename(r.source))[0])
                if not ok or not folder.strip():
                    continue
            try:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                done = ru.prepare(r, home, folder.strip() if folder else None)
                report.append(f"{r.name}: {', '.join(done) or 'bez zmian'}")
            except Exception as e:  # noqa: BLE001 — błąd GDAL / pliku
                report.append(f"{r.name}: BŁĄD — {e}")
            finally:
                QApplication.restoreOverrideCursor()
        if any("skopiowano" in x or "wielkość" in x for x in report):
            QgsProject.instance().setDirty(True)
            report.append("\nZapisz projekt (zmieniły się źródła warstw).")
        QMessageBox.information(self, "Fia", "\n".join(report))
        self.refresh()

    # ------------------------------------------------------------------ sumy i plan
    def _progress(self, title: str) -> QProgressDialog:
        prog = QProgressDialog(title, "Przerwij", 0, 1000, self)
        prog.setWindowTitle("Fia – rastry")
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(300)
        return prog

    def _hash_all(self, layers: list[ru.RLayer]) -> bool:
        home = QgsProject.instance().homePath()
        cache = ru.load_cache(home)
        files = [f for r in layers for f in r.files]
        total, done = max(sum(f.size for f in files), 1), 0
        prog = self._progress("Liczenie sum kontrolnych…")

        def step(n: int) -> bool:
            nonlocal done
            done += n
            prog.setValue(int(done * 1000 / total))
            QApplication.processEvents()
            return not prog.wasCanceled()

        try:
            for f in files:
                prog.setLabelText(f"Sumy kontrolne: {f.rel}")
                f.sha256 = ru.sha256_file(f.local, cache, step)
        except ru.Cancelled:
            return False
        finally:
            ru.save_cache(home, cache)
            prog.close()
        return True

    def _ready(self) -> tuple[list[ru.RLayer], str, bool] | None:
        """Warstwy do wysyłki po kontroli; None — przerwane albo błąd."""
        self.refresh()
        if any(lvl == "error" for lvl, _ in self.general):
            QMessageBox.warning(self, "Fia", "\n".join(t for _, t in self.general))
            return None
        blocked = [r for r in self.layers if r.blocked]
        ok = [r for r in self.layers if not r.blocked and r.files]
        if blocked:
            names = "\n".join(f"• {r.name}" for r in blocked)
            if not ok or QMessageBox.question(
                    self, "Fia", f"Te rastry wymagają poprawy („Przygotuj zaznaczone…”) i zostaną pominięte:\n{names}"
                                 "\n\nKontynuować z pozostałymi?") != QMessageBox.StandardButton.Yes:
                return None
        slug = self.slug_fn().strip()
        if any(r.target == "project" for r in ok) and not slug:
            QMessageBox.warning(self, "Fia", "Projekt nie był publikowany — brak identyfikatora (zakładka „Serwer”).")
            return None
        base, verify = self.server()
        return ok, base, verify

    @staticmethod
    def _groups(layers: list[ru.RLayer]) -> dict[str, list[ru.RFile]]:
        groups: dict[str, dict[str, ru.RFile]] = {}
        for r in layers:
            for f in r.files:
                groups.setdefault(f.target, {})[f.rel] = f      # ten sam plik w dwóch warstwach — raz
        return {t: list(fs.values()) for t, fs in groups.items()}

    def _mark(self, layers: list[ru.RLayer], target: str, upload: set[str]):
        for r in layers:
            if r.target == target:
                n = sum(f.rel in upload for f in r.files)
                r.state = f"do wysłania: {n}" if n else "aktualne"

    def on_check(self):
        ready = self._ready()
        if not ready:
            return
        layers, base, verify = ready
        if not self._hash_all(layers):
            return
        try:
            token = self.token_fn()
            if token is None:
                return
            lines = []
            for target, files in self._groups(layers).items():
                res = ru.plan(base, token, ru.target_spec(target, self.slug_fn()), files, verify, dry_run=True)
                self._mark(layers, target, set(res["upload"]))
                lines.append(f"{TARGET_LABEL[target].capitalize()}: do wysłania {len(res['upload'])} "
                             f"({mb(res['need_bytes'])}), aktualne {len(res['same'])}"
                             + (f", na serwerze bez odpowiednika lokalnie: {len(res['extra'])}" if res["extra"] else ""))
        except publish.ApiError as e:
            QMessageBox.critical(self, "Fia", f"Sprawdzenie nie powiodło się:\n{e}")
            return
        self._fill()
        self.summary.setText(self.summary.text() + "\n" + "\n".join(lines))

    # ------------------------------------------------------------------ wysyłka
    def on_send(self, quiet_when_nothing: bool = False) -> bool:
        ready = self._ready()
        if not ready:
            return False
        layers, base, verify = ready
        if not layers:
            return True
        if not self._hash_all(layers):
            return False
        home = QgsProject.instance().homePath()
        try:
            token = self.token_fn()
            if token is None:
                return False
            report = []
            for target, files in self._groups(layers).items():
                spec = ru.target_spec(target, self.slug_fn())
                key = f"{base.rstrip('/')}|{target}|{spec.get('project', '')}"
                cache = ru.load_cache(home)
                old = cache.get("sessions", {}).get(key)
                by_rel = {f.rel: f for f in files}
                if old and ru.resumable(base, token, old, by_rel, verify):
                    sid, delete_extra = old, False
                    st = ru.session_status(base, token, sid, verify)["files"]
                    upload = set(st)
                    report_head = f"{TARGET_LABEL[target].capitalize()}: wznowiono przerwaną wysyłkę"
                else:
                    if old:
                        ru.abort(base, token, old, verify)
                    res = ru.plan(base, token, spec, files, verify)
                    upload, sid = set(res["upload"]), res["session"]
                    self._mark(layers, target, upload)
                    if not sid:
                        report.append(f"{TARGET_LABEL[target].capitalize()}: wszystko aktualne")
                        continue
                    msg = (f"{TARGET_LABEL[target].capitalize()}: do wysłania {len(upload)} plików "
                           f"({mb(res['need_bytes'])}), wolne na serwerze {mb(res['free_bytes'])}.")
                    delete_extra = False
                    if res["extra"]:
                        listing = "\n".join(res["extra"][:20]) + ("\n…" if len(res["extra"]) > 20 else "")
                        ans = QMessageBox.question(
                            self, "Fia", f"{msg}\n\nNa serwerze są pliki, których nie ma w projekcie lokalnie:\n"
                                         f"{listing}\n\nUsunąć je z serwera?",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                            | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.No)
                        if ans == QMessageBox.StandardButton.Cancel:
                            ru.abort(base, token, sid, verify)
                            return False
                        delete_extra = ans == QMessageBox.StandardButton.Yes
                    elif QMessageBox.question(self, "Fia", f"{msg}\n\nWysłać?") != QMessageBox.StandardButton.Yes:
                        ru.abort(base, token, sid, verify)
                        return False
                    report_head = msg
                    cache.setdefault("sessions", {})[key] = sid
                    ru.save_cache(home, cache)
                if not self._upload(base, token, sid, [by_rel[r] for r in upload if r in by_rel], verify):
                    self.summary.setText("Wysyłka przerwana — „Wyślij zmienione” wznowi ją od miejsca przerwania.")
                    return False
                res = ru.commit(base, token, sid, delete_extra, verify)
                cache = ru.load_cache(home)
                cache.get("sessions", {}).pop(key, None)
                ru.save_cache(home, cache)
                self._mark(layers, target, set())
                report.append(f"{report_head}\nDodane: {len(res['added'])}, podmienione: {len(res['replaced'])}, "
                              f"usunięte: {len(res['deleted'])}. Odświeżone projekty: "
                              f"{', '.join(res['projects']) or '—'}.")
        except publish.ApiError as e:
            QMessageBox.critical(self, "Fia", f"Wysyłka rastrów nie powiodła się:\n{e}\n\n"
                                              "Ponowne „Wyślij zmienione” wznowi ją od miejsca przerwania.")
            return False
        finally:
            self._fill()
        if report and not (quiet_when_nothing and all("wszystko aktualne" in x for x in report)):
            QMessageBox.information(self, "Fia", "\n\n".join(report))
        return True

    def _upload(self, base: str, token: str, sid: str, files: list[ru.RFile], verify: bool) -> bool:
        prog = self._progress("Wysyłanie rastrów…")
        t0, first = time.monotonic(), None

        def step(sent: int, total: int, rel: str) -> bool:
            nonlocal first
            first = sent if first is None else first
            prog.setValue(int(sent * 1000 / max(total, 1)))
            speed = (sent - first) / max(time.monotonic() - t0, 0.1)
            eta = (total - sent) / speed if speed > 0 else 0
            prog.setLabelText(f"{rel}\n{mb(sent)} / {mb(total)} · {mb(int(speed))}/s"
                              + (f" · zostało ok. {int(eta // 60)} min {int(eta % 60)} s" if speed > 0 else ""))
            QApplication.processEvents()
            return not prog.wasCanceled()

        try:
            ru.upload(base, token, sid, files, verify, step)
            return True
        except ru.Cancelled:
            return False
        finally:
            prog.close()
