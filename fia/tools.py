"""Zakładka „Narzędzia pobierania”: obiekt z usługi zewnętrznej (ULDK…) -> warstwa projektu.

Autor projektu wskazuje warstwę docelową i to, do których jej pól trafiają identyfikator TERYT,
numer działki, obręb, gmina… Geometria trafia do geometrii warstwy (poligon albo punkt wewnątrz
obiektu dla warstwy punktowej). Lista pól musi być zgodna z api/app/fetchers.py (SOURCES).
docs/user/uldk.md
"""
from __future__ import annotations

import re

from qgis.core import QgsProject, QgsVectorLayer, QgsWkbTypes
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# (klucz, nazwa, pola (klucz, etykieta)) — tak samo jak api/app/fetchers.py
SOURCES = {
    "uldk_dzialka": ("Działka ewidencyjna (ULDK)", [
        ("teryt", "Identyfikator działki (TERYT)"), ("numer", "Numer działki"), ("obreb", "Obręb (nazwa)"),
        ("obreb_nr", "Obręb (numer)"), ("gmina", "Gmina"), ("gmina_teryt", "Gmina (TERYT)"),
        ("powiat", "Powiat"), ("wojewodztwo", "Województwo")]),
    "uldk_budynek": ("Budynek (ULDK)", [
        ("teryt", "Identyfikator budynku"), ("obreb", "Obręb (nazwa)"), ("obreb_nr", "Obręb (numer)"),
        ("gmina", "Gmina"), ("gmina_teryt", "Gmina (TERYT)"), ("powiat", "Powiat"),
        ("wojewodztwo", "Województwo")]),
}

# Podpowiedź mapowania po nazwie pola warstwy
GUESS = {
    "teryt": ["teryt", "id_dzialki", "identyfikator", "id_teryt", "idd", "id_budynku"],
    "numer": ["numer", "nr", "nr_dzialki", "numer_dzialki", "nr_dz"],
    "obreb": ["obreb", "nazwa_obrebu", "obreb_nazwa"],
    "obreb_nr": ["obreb_nr", "nr_obrebu", "numer_obrebu"],
    "gmina": ["gmina", "nazwa_gminy"],
    "gmina_teryt": ["gmina_teryt", "teryt_gminy", "kod_gminy"],
    "powiat": ["powiat"],
    "wojewodztwo": ["wojewodztwo", "woj"],
}

NONE = "— nie zapisuj —"


def _target_layers() -> list[QgsVectorLayer]:
    out = []
    for lyr in QgsProject.instance().mapLayers().values():
        if isinstance(lyr, QgsVectorLayer) and lyr.providerType() == "postgres" and lyr.geometryType() in (
                QgsWkbTypes.GeometryType.PolygonGeometry, QgsWkbTypes.GeometryType.PointGeometry):
            out.append(lyr)
    return sorted(out, key=lambda x: x.name().lower())


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "narzedzie"


class ToolsTab(QWidget):
    def __init__(self, tools: list[dict], parent=None):
        super().__init__(parent)
        self.tools = [dict(t) for t in tools]
        self._loading = False

        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._show)
        add = QPushButton("Dodaj narzędzie")
        add.clicked.connect(self._add)
        rem = QPushButton("Usuń")
        rem.clicked.connect(self._remove)

        self.source = QComboBox()
        for key, (name, _) in SOURCES.items():
            self.source.addItem(name, key)
        self.source.currentIndexChanged.connect(self._on_source)
        self.label = QLineEdit()
        self.label.textEdited.connect(self._store)
        self.layer = QComboBox()
        self.layer.currentIndexChanged.connect(self._on_layer)
        self.open_form = QCheckBox("Po pobraniu otwórz formularz (uzupełnienie pozostałych pól)")
        self.open_form.toggled.connect(self._store)
        self.mapping = QTableWidget(0, 2)
        self.mapping.setHorizontalHeaderLabels(["Dane z usługi", "Pole warstwy docelowej"])
        self.mapping.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.mapping.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.mapping.verticalHeader().setVisible(False)

        self.editor = QWidget()
        form = QFormLayout(self.editor)
        form.addRow("Usługa", self.source)
        form.addRow("Nazwa (podpowiedź na pasku)", self.label)
        form.addRow("Warstwa docelowa (geometria)", self.layer)
        form.addRow(self.mapping)
        form.addRow("", self.open_form)

        left = QVBoxLayout()
        left.addWidget(self.list)
        btns = QHBoxLayout()
        btns.addWidget(add)
        btns.addWidget(rem)
        left.addLayout(btns)
        row = QHBoxLayout()
        row.addLayout(left, 1)
        row.addWidget(self.editor, 3)
        lay = QVBoxLayout(self)
        info = QLabel("Narzędzie na pasku WebUI: kliknięcie na mapie pobiera obiekt z usługi (np. działkę z ULDK), "
                      "pokazuje go i po potwierdzeniu dodaje do wskazanej warstwy. Geometria trafia do geometrii "
                      "warstwy, a dane (TERYT, numer, obręb…) do pól wybranych poniżej. Warstwa musi być edytowalna.")
        info.setWordWrap(True)
        lay.addWidget(info)
        lay.addLayout(row)

        for t in self.tools:
            self.list.addItem(QListWidgetItem(t.get("label") or t.get("id")))
        self.editor.setEnabled(bool(self.tools))
        if self.tools:
            self.list.setCurrentRow(0)

    # ------------------------------------------------------------------ zdarzenia
    def _current(self) -> dict | None:
        i = self.list.currentRow()
        return self.tools[i] if 0 <= i < len(self.tools) else None

    def _add(self):
        layers = _target_layers()
        n = len(self.tools) + 1
        t = {"id": f"uldk_dzialka_{n}" if n > 1 else "uldk_dzialka", "source": "uldk_dzialka",
             "label": "Działka z ULDK", "layer": layers[0].id() if layers else "", "fields": {}, "open_form": True}
        self.tools.append(t)
        self.list.addItem(QListWidgetItem(t["label"]))
        self.editor.setEnabled(True)
        self.list.setCurrentRow(len(self.tools) - 1)
        self._guess_mapping()

    def _remove(self):
        i = self.list.currentRow()
        if i < 0:
            return
        self.tools.pop(i)
        self.list.takeItem(i)
        self.editor.setEnabled(bool(self.tools))

    def _show(self, _row: int):
        t = self._current()
        if t is None:
            return
        self._loading = True
        self.source.setCurrentIndex(max(0, self.source.findData(t.get("source", "uldk_dzialka"))))
        self.label.setText(t.get("label", ""))
        self.layer.clear()
        for lyr in _target_layers():
            self.layer.addItem(lyr.name(), lyr.id())
        self.layer.setCurrentIndex(max(0, self.layer.findData(t.get("layer"))))
        self.open_form.setChecked(t.get("open_form", True))
        self._loading = False
        self._fill_mapping()

    def _on_source(self):
        t = self._current()
        if t is None or self._loading:
            return
        t["source"] = self.source.currentData()
        name = SOURCES[t["source"]][0]
        if not self.label.text().strip() or self.label.text() in ("Działka z ULDK", "Budynek z ULDK"):
            self.label.setText("Budynek z ULDK" if "budynek" in t["source"] else "Działka z ULDK")
        t["id"] = _slug(t["source"]) + (f"_{self.list.currentRow() + 1}" if self.list.currentRow() else "")
        self.label.setToolTip(name)
        self._store()
        self._fill_mapping()

    def _on_layer(self):
        t = self._current()
        if t is None or self._loading:
            return
        t["layer"] = self.layer.currentData()
        t["fields"] = {}
        self._fill_mapping()
        self._guess_mapping()

    def _store(self, *_):
        t = self._current()
        if t is None or self._loading:
            return
        t["label"] = self.label.text().strip() or SOURCES[t["source"]][0]
        t["open_form"] = self.open_form.isChecked()
        item = self.list.currentItem()
        if item:
            item.setText(t["label"])

    # ------------------------------------------------------------------ mapowanie pól
    def _layer_fields(self) -> list[str]:
        lyr = QgsProject.instance().mapLayer(self.layer.currentData() or "")
        if not isinstance(lyr, QgsVectorLayer):
            return []
        pk = set(lyr.primaryKeyAttributes())
        return [f.name() for i, f in enumerate(lyr.fields()) if i not in pk]

    def _fill_mapping(self):
        t = self._current()
        if t is None:
            return
        fields = SOURCES[t.get("source", "uldk_dzialka")][1]
        names = self._layer_fields()
        self.mapping.setRowCount(len(fields))
        for row, (key, label) in enumerate(fields):
            item = QTableWidgetItem(label)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.mapping.setItem(row, 0, item)
            combo = QComboBox()
            combo.addItem(NONE, "")
            for n in names:
                combo.addItem(n, n)
            combo.setCurrentIndex(max(0, combo.findData(t.get("fields", {}).get(key, ""))))
            combo.currentIndexChanged.connect(lambda _i, k=key, c=combo: self._set_field(k, c.currentData()))
            self.mapping.setCellWidget(row, 1, combo)

    def _set_field(self, key: str, dst: str):
        t = self._current()
        if t is None:
            return
        if dst:
            t.setdefault("fields", {})[key] = dst
        else:
            t.get("fields", {}).pop(key, None)

    def _guess_mapping(self):
        t = self._current()
        if t is None:
            return
        names = {n.lower(): n for n in self._layer_fields()}
        for key, _ in SOURCES[t["source"]][1]:
            if key in t.get("fields", {}):
                continue
            hit = next((names[g] for g in GUESS.get(key, []) if g in names), None)
            if hit:
                t.setdefault("fields", {})[key] = hit
        self._fill_mapping()

    def value(self) -> list[dict]:
        return [t for t in self.tools if t.get("layer")]
