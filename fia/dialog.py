"""Okno konfiguracji. Konfiguracja zapisywana jest w samym projekcie (sekcja "sophia"),
więc podróżuje razem z plikiem .qgz; plik .portal.json jest generowany przy zapisie/publikacji."""
from __future__ import annotations

import json
import os
import re
import unicodedata

from qgis.core import QgsLayerTreeGroup, QgsProject, QgsRasterLayer, QgsSettings, QgsVectorLayer
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import checks, credentials, photosync, publish, rasters
from .tools import ToolsTab

SCOPE = "sophia"
LEVEL_COLORS = {"error": QColor("#c92a2a"), "warning": QColor("#e67700"), "info": QColor("#1971c2")}


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.replace("ł", "l").replace("Ł", "L"))
    text = text.encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "projekt"


def load_config() -> dict:
    raw, ok = QgsProject.instance().readEntry(SCOPE, "config", "")
    try:
        return json.loads(raw) if ok and raw else {}
    except ValueError:
        return {}


def save_config(cfg: dict) -> None:
    QgsProject.instance().writeEntry(SCOPE, "config", json.dumps(cfg, ensure_ascii=False))
    QgsProject.instance().setDirty(True)


def _check_item(checked: bool, enabled: bool = True) -> QTableWidgetItem:
    item = QTableWidgetItem()
    flags = Qt.ItemFlag.ItemIsUserCheckable | (Qt.ItemFlag.ItemIsEnabled if enabled else Qt.ItemFlag.NoItemFlags)
    item.setFlags(flags)
    item.setCheckState(Qt.CheckState.Checked if checked and enabled else Qt.CheckState.Unchecked)
    return item


class FiaDialog(QDialog):
    LAYER_COLS = ["Warstwa", "Edycja", "Zdjęcia / pliki", "Popup", "Tylko w QGIS", "Stan"]

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Fia – konfiguracja projektu Sophia")
        self.resize(900, 600)
        self.cfg = load_config()
        self.prj = QgsProject.instance()

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_layers_tab(), "Warstwy")
        self.tabs.addTab(self._build_rasters_tab(), "Rastry")
        self.tabs.addTab(self._build_reports_tab(), "Raporty")
        self.tools_tab = ToolsTab(self.cfg.get("tools", []))
        self.tabs.addTab(self.tools_tab, "Narzędzia pobierania")
        self.tabs.addTab(self._build_diag_tab(), "Diagnostyka")
        self.tabs.addTab(self._build_publish_tab(), "Serwer")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Zapisz konfigurację")
        buttons.accepted.connect(self.on_save)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addWidget(buttons)

    # ------------------------------------------------------------------ Warstwy
    def _build_layers_tab(self) -> QWidget:
        w = QWidget()
        self.layer_table = QTableWidget(0, len(self.LAYER_COLS))
        self.layer_table.setHorizontalHeaderLabels(self.LAYER_COLS)
        self.layer_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.layer_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.layer_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.layer_table.itemChanged.connect(self._on_layer_item_changed)
        self._fill_layers()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel(
            "Pola, aliasy, widżety formularza, relacje i wydruki są odczytywane automatycznie z projektu.\n"
            "Tutaj wskazujesz tylko, co ma być edytowalne w portalu. Zdjęcia i pliki: widżet „Załącznik” "
            "w polu albo tabela w relacji (docs/user/zalaczniki.md)."))
        lay.addWidget(self.layer_table)
        return w

    def _fill_layers(self):
        layer_cfg = self.cfg.get("layers", {})
        vectors = [lyr for lyr in self.prj.mapLayers().values() if isinstance(lyr, QgsVectorLayer)]
        self.layer_table.blockSignals(True)
        self.layer_table.setRowCount(len(vectors))
        for row, lyr in enumerate(sorted(vectors, key=lambda x: x.name().lower())):
            c = layer_cfg.get(lyr.id(), {})
            is_pg = lyr.providerType() == "postgres"
            name = QTableWidgetItem(lyr.name())
            name.setData(Qt.ItemDataRole.UserRole, lyr.id())
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.layer_table.setItem(row, 0, name)
            self.layer_table.setItem(row, 1, _check_item(c.get("editable", False), is_pg))
            att = QTableWidgetItem(checks.attachment_summary(lyr))
            att.setFlags(Qt.ItemFlag.ItemIsEnabled)
            att.setToolTip("Wykryte z projektu: pola z widżetem Załącznik i tabele w relacji")
            self.layer_table.setItem(row, 2, att)
            self.layer_table.setItem(row, 3, _check_item(c.get("popup", True)))
            self.layer_table.setItem(row, 4, _check_item(c.get("hidden", False)))
            self._update_layer_status(row)
        self.layer_table.blockSignals(False)

    def _update_layer_status(self, row: int):
        lid = self.layer_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        lyr = self.prj.mapLayer(lid)
        want_edit = self.layer_table.item(row, 1).checkState() == Qt.CheckState.Checked
        issues = checks.layer_issues(lyr, want_edit)
        worst = next((lvl for lvl in ("error", "warning", "info") if any(i[0] == lvl for i in issues)), None)
        item = QTableWidgetItem("; ".join(m for _, m in issues) or "OK")
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setToolTip("\n".join(f"[{lvl}] {m}" for lvl, m in issues))
        if worst:
            item.setForeground(LEVEL_COLORS[worst])
        self.layer_table.blockSignals(True)
        self.layer_table.setItem(row, 5, item)
        self.layer_table.blockSignals(False)

    def _on_layer_item_changed(self, item: QTableWidgetItem):
        if item.column() == 1:
            self._update_layer_status(item.row())

    # ------------------------------------------------------------------ Rastry
    def _build_rasters_tab(self) -> QWidget:
        w = QWidget()
        self.raster_table = QTableWidget(0, 2)
        self.raster_table.setHorizontalHeaderLabels(["Grupa w drzewie warstw", "Mozaika (jedna warstwa w portalu)"])
        self.raster_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._fill_raster_groups()

        btn_group = QPushButton("Dodaj katalog GeoTIFF jako grupę…")
        btn_group.clicked.connect(self.on_add_tiff_group)
        btn_vrt = QPushButton("Zbuduj VRT + piramidy z katalogu GeoTIFF… (zalecane)")
        btn_vrt.clicked.connect(self.on_build_vrt)
        row = QHBoxLayout()
        row.addWidget(btn_group)
        row.addWidget(btn_vrt)
        row.addStretch()

        lay = QVBoxLayout(w)
        lay.addWidget(QLabel(
            "Grupa oznaczona jako mozaika jest w portalu jednym przełącznikiem — "
            "wszystkie arkusze włączają się razem.\n"
            "Przy dużej liczbie arkuszy użyj VRT: jeden plik, piramidy i szybkie renderowanie przez QGIS Server."))
        lay.addLayout(row)
        lay.addWidget(self.raster_table)
        return w

    def _fill_raster_groups(self):
        marked = set(self.cfg.get("raster_groups", []))
        groups: list[QgsLayerTreeGroup] = []

        def walk(g: QgsLayerTreeGroup):
            for ch in g.children():
                if isinstance(ch, QgsLayerTreeGroup):
                    groups.append(ch)
                    walk(ch)
        walk(self.prj.layerTreeRoot())
        self.raster_table.setRowCount(len(groups))
        for row, g in enumerate(groups):
            name = QTableWidgetItem(g.name())
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.raster_table.setItem(row, 0, name)
            only_rasters = bool(g.findLayers()) and all(isinstance(n.layer(), QgsRasterLayer)
                                                       for n in g.findLayers())
            self.raster_table.setItem(row, 1, _check_item(g.name() in marked, only_rasters))

    def _mark_group(self, name: str):
        self.cfg.setdefault("raster_groups", [])
        if name not in self.cfg["raster_groups"]:
            self.cfg["raster_groups"].append(name)
        self._fill_raster_groups()

    def on_add_tiff_group(self):
        folder = QFileDialog.getExistingDirectory(self, "Katalog z plikami GeoTIFF")
        if not folder:
            return
        name, ok = QInputDialog.getText(self, "Nazwa grupy", "Nazwa grupy w drzewie:", text=os.path.basename(folder))
        if ok and name:
            rasters.add_as_group(folder, name)
            self._mark_group(name)

    def on_build_vrt(self):
        folder = QFileDialog.getExistingDirectory(self, "Katalog z plikami GeoTIFF")
        if not folder:
            return
        name, ok = QInputDialog.getText(self, "Nazwa warstwy", "Nazwa mozaiki:", text=os.path.basename(folder))
        if not (ok and name):
            return
        vrt_path = os.path.join(folder, f"{slugify(name)}.vrt")
        try:
            self.setCursor(Qt.CursorShape.WaitCursor)
            rasters.build_vrt(folder, vrt_path, name)
            self._mark_group(name)
            QMessageBox.information(self, "Fia", f"Utworzono {vrt_path}.\n"
                                    "Skopiuj cały katalog (GeoTIFF + VRT + .ovr) do data/rasters na serwerze.")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Fia", str(e))
        finally:
            self.unsetCursor()

    # ------------------------------------------------------------------ Raporty
    def _build_reports_tab(self) -> QWidget:
        w = QWidget()
        self.report_table = QTableWidget(0, 4)
        self.report_table.setHorizontalHeaderLabels(["Wydruk (layout)", "Tytuł w portalu", "Włączony", "Rodzaj"])
        self.report_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        rep_cfg = {r["layout"]: r for r in self.cfg.get("reports", [])}
        layouts = self.prj.layoutManager().printLayouts()
        self.report_table.setRowCount(len(layouts))
        for row, layout in enumerate(layouts):
            rc = rep_cfg.get(layout.name(), {})
            name = QTableWidgetItem(layout.name())
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.report_table.setItem(row, 0, name)
            self.report_table.setItem(row, 1, QTableWidgetItem(rc.get("title", layout.name())))
            self.report_table.setItem(row, 2, _check_item(rc.get("enabled", True)))
            atlas = layout.atlas()
            kind = (f"Dla obiektu (atlas: {atlas.coverageLayer().name()})"
                    if atlas.enabled() and atlas.coverageLayer() else "Wydruk widoku mapy")
            k = QTableWidgetItem(kind)
            k.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.report_table.setItem(row, 3, k)
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Raporty to wydruki z projektu. Wydruk z włączonym atlasem staje się raportem "
                             "dla wskazanego obiektu (np. karta działki z tabelą właścicieli)."))
        lay.addWidget(self.report_table)
        return w

    # ------------------------------------------------------------------ Diagnostyka
    def _build_diag_tab(self) -> QWidget:
        w = QWidget()
        self.diag_tree = QTreeWidget()
        self.diag_tree.setHeaderLabels(["Obiekt", "Poziom", "Komunikat"])
        self.diag_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        btn = QPushButton("Sprawdź projekt")
        btn.clicked.connect(self.run_diagnostics)
        lay = QVBoxLayout(w)
        lay.addWidget(btn)
        lay.addWidget(self.diag_tree)
        self.run_diagnostics()
        return w

    def run_diagnostics(self) -> int:
        self.diag_tree.clear()
        layer_cfg = self._collect()["layers"]
        rows = list(checks.project_issues())
        for lyr in self.prj.mapLayers().values():
            want_edit = layer_cfg.get(lyr.id(), {}).get("editable", False)
            rows += [(lyr.name(), lvl, msg) for lvl, msg in checks.layer_issues(lyr, want_edit)]
        errors = 0
        for obj, lvl, msg in sorted(rows, key=lambda r: ("error", "warning", "info").index(r[1])):
            it = QTreeWidgetItem([obj, lvl, msg])
            it.setForeground(1, LEVEL_COLORS[lvl])
            self.diag_tree.addTopLevelItem(it)
            errors += lvl == "error"
        if not rows:
            self.diag_tree.addTopLevelItem(QTreeWidgetItem(["Projekt", "ok", "Nie znaleziono problemów"]))
        return errors

    # ------------------------------------------------------------------ Publikacja
    def _build_publish_tab(self) -> QWidget:
        w = QWidget()
        s = QgsSettings()
        self.url = QLineEdit(s.value("fia/url", "https://localhost"))
        self.login = QLineEdit(s.value("fia/login", "admin"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.remember = QCheckBox("Zapamiętaj w menedżerze uwierzytelniania QGIS")
        self.remember.setChecked(bool(credentials.saved_id()))
        if credentials.saved_id():
            self.password.setPlaceholderText("zapisane w menedżerze uwierzytelniania QGIS")
        self.verify = QCheckBox("Weryfikuj certyfikat SSL")
        self.verify.setChecked(s.value("fia/verify_ssl", True, type=bool))
        title = self.cfg.get("title") or self.prj.title() or self.prj.baseName()
        self.title = QLineEdit(title)
        self.slug = QLineEdit(self.cfg.get("slug") or slugify(title))
        btn = QPushButton("Zapisz projekt i opublikuj")
        btn.clicked.connect(self.on_publish)
        sync_btn = QPushButton("Pobierz zdjęcia z serwera do folderu projektu")
        sync_btn.clicked.connect(self.on_sync_photos)

        form = QFormLayout(w)
        form.addRow("Adres portalu", self.url)
        form.addRow("Login", self.login)
        form.addRow("Hasło", self.password)
        form.addRow("", self.remember)
        form.addRow("", self.verify)
        form.addRow("Tytuł projektu (menu)", self.title)
        form.addRow("Identyfikator (URL)", self.slug)
        form.addRow("", btn)
        note = QLabel("Publikacja (konto administratora) wysyła tylko plik projektu i konfigurację; "
                      "rastry biblioteki (data/rasters) kopiuj na serwer osobno.")
        note.setWordWrap(True)
        form.addRow(note)
        form.addRow("", sync_btn)
        note2 = QLabel("Zdjęcia dodane w WebUI trafiają do podkatalogu „zdjecia” folderu projektu — QGIS pokazuje je "
                       "w formularzu (widżet Załącznik, ścieżka względna). Pobierane są tylko zdjęcia obiektów, "
                       "które Twoje konto może oglądać, i tylko nowe lub zmienione pliki.")
        note2.setWordWrap(True)
        form.addRow(note2)
        return w

    # ------------------------------------------------------------------ zapis / publikacja
    def _collect(self) -> dict:
        cfg = dict(self.cfg)
        layers = {}
        for row in range(self.layer_table.rowCount()):
            lid = self.layer_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            layers[lid] = {
                "editable": self.layer_table.item(row, 1).checkState() == Qt.CheckState.Checked,
                "popup": self.layer_table.item(row, 3).checkState() == Qt.CheckState.Checked,
                "hidden": self.layer_table.item(row, 4).checkState() == Qt.CheckState.Checked,
            }
        cfg["layers"] = layers
        cfg["raster_groups"] = [
            self.raster_table.item(r, 0).text() for r in range(self.raster_table.rowCount())
            if self.raster_table.item(r, 1).checkState() == Qt.CheckState.Checked
        ]
        cfg["tools"] = self.tools_tab.value()
        cfg["reports"] = [
            {"layout": self.report_table.item(r, 0).text(), "title": self.report_table.item(r, 1).text(),
             "enabled": self.report_table.item(r, 2).checkState() == Qt.CheckState.Checked}
            for r in range(self.report_table.rowCount())
        ]
        if hasattr(self, "title"):
            cfg["title"] = self.title.text().strip()
            cfg["slug"] = self.slug.text().strip()
        cfg["version"] = 1
        return cfg

    def _portal_json(self, cfg: dict) -> dict:
        return {k: cfg[k] for k in ("version", "layers", "raster_groups", "reports", "tools", "map") if k in cfg}

    def on_save(self):
        self.cfg = self._collect()
        save_config(self.cfg)
        if self.prj.fileName():
            path = os.path.splitext(self.prj.fileName())[0] + ".portal.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._portal_json(self.cfg), f, ensure_ascii=False, indent=2)
        self.iface.messageBar().pushSuccess("Fia", "Konfiguracja zapisana (zapisz też projekt).")

    # ------------------------------------------------------------------ logowanie / zdjęcia
    def _token(self) -> str | None:
        """Loguje do Sophii: hasło z pola albo z menedżera uwierzytelniania QGIS. Rzuca publish.ApiError."""
        url, login, password = self.url.text().strip(), self.login.text().strip(), self.password.text()
        typed = bool(password)
        if not typed:
            saved = credentials.load()
            if saved and (not login or saved[0] == login):
                login, password = saved
        if not password:
            QMessageBox.warning(self, "Fia", "Podaj hasło (albo zapisz je w menedżerze uwierzytelniania QGIS).")
            return None
        s = QgsSettings()
        s.setValue("fia/url", url)
        s.setValue("fia/login", login)
        s.setValue("fia/verify_ssl", self.verify.isChecked())
        token = publish.login(url, login, password, self.verify.isChecked())
        if self.remember.isChecked() and (typed or not credentials.saved_id()):
            if not credentials.save(url, login, password):
                self.iface.messageBar().pushWarning("Fia", "Nie udało się zapisać hasła w menedżerze uwierzytelniania.")
        elif not self.remember.isChecked() and credentials.saved_id():
            credentials.forget()
        self.password.clear()
        if credentials.saved_id():
            self.password.setPlaceholderText("zapisane w menedżerze uwierzytelniania QGIS")
        return token

    def on_sync_photos(self):
        home = self.prj.homePath()
        slug = (self.cfg.get("slug") or self.slug.text()).strip()
        if not self.prj.fileName() or not home:
            QMessageBox.warning(self, "Fia", "Najpierw zapisz projekt — zdjęcia trafią do jego folderu.")
            return
        if not slug:
            QMessageBox.warning(self, "Fia", "Projekt nie był publikowany — brak identyfikatora (URL).")
            return
        prog = QProgressDialog("Pobieranie listy zdjęć…", "Przerwij", 0, 0, self)
        prog.setWindowTitle("Fia – zdjęcia")
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(300)

        def progress(i: int, n: int, path: str) -> bool:
            prog.setMaximum(n)
            prog.setValue(i)
            prog.setLabelText(f"{i + 1} / {n}\n{path}")
            QApplication.processEvents()
            return not prog.wasCanceled()

        try:
            token = self._token()
            if token is None:
                return
            res = photosync.sync(self.url.text().strip(), token, slug, home, self.verify.isChecked(), progress)
        except publish.ApiError as e:
            QMessageBox.critical(self, "Fia", f"Pobieranie zdjęć nie powiodło się:\n{e}")
            return
        finally:
            prog.close()
        msg = f"Pobrano: {res.downloaded}, aktualne: {res.up_to_date}."
        if res.cancelled:
            msg += " Przerwano."
        if res.errors:
            QMessageBox.warning(self, "Fia", msg + f"\n\nBłędy ({len(res.errors)}):\n" + "\n".join(res.errors[:15]))
        else:
            self.iface.messageBar().pushSuccess("Fia", f"Zdjęcia z Sophii → {home}. {msg}")

    def on_publish(self):
        if self.run_diagnostics():
            self.tabs.setCurrentIndex(self.tabs.indexOf(self.diag_tree.parentWidget()))
            if QMessageBox.question(self, "Fia", "Projekt zawiera błędy. Opublikować mimo to?") \
                    != QMessageBox.StandardButton.Yes:
                return
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", self.slug.text().strip()):
            QMessageBox.warning(self, "Fia", "Identyfikator: tylko małe litery, cyfry, '-' i '_'.")
            return
        self.cfg = self._collect()
        save_config(self.cfg)
        if not self.prj.fileName().lower().endswith(".qgz"):
            QMessageBox.warning(self, "Fia", "Najpierw zapisz projekt jako plik .qgz.")
            return
        self.prj.write()

        try:
            self.setCursor(Qt.CursorShape.WaitCursor)
            token = self._token()
            if token is None:
                return
            res = publish.publish(self.url.text().strip(), token, self.cfg["slug"], self.cfg["title"],
                                  self.prj.fileName(), self._portal_json(self.cfg), self.verify.isChecked())
        except publish.ApiError as e:
            QMessageBox.critical(self, "Fia", f"Publikacja nie powiodła się:\n{e}")
            return
        finally:
            self.unsetCursor()
        QMessageBox.information(
            self, "Fia",
            f"Opublikowano jako {res.get('file_name')}.\n"
            f"Pamiętaj o nadaniu grupom dostępu do projektu w panelu administracyjnym.\n\n"
            f"{self.url.text().rstrip('/')}/?p={self.cfg['slug']}")
