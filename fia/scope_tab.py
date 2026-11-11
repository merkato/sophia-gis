"""Zakładka „Zakres danych”: kto widzi i edytuje które rekordy (docs/user/uprawnienia.md).

Wymiar zakresu = warstwa granic (np. oddziały terenowe) + pole z kodem obszaru (np. kod = od01).
Reguła warstwy: przestrzennie / atrybut / przez relację / bez ograniczeń („auto” rozstrzyga serwer:
warstwa z geometrią — przestrzennie, tabela bez geometrii w relacji — przez relację, inne — bez).
Administrator w panelu Sophii nadaje grupom „cały obszar” albo wybrane kody.
"""
from __future__ import annotations

from qgis.core import QgsProject, QgsVectorLayer, QgsWkbTypes
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

MODES = [("auto", "automatycznie"), ("spatial", "przestrzennie (w granicy obszaru)"),
         ("attribute", "atrybut (pole z kodem)"), ("relation", "przez relację z obiektem"),
         ("none", "bez ograniczeń")]
WARN = QColor("#e67700")


def _pg_layers() -> list[QgsVectorLayer]:
    return sorted((lyr for lyr in QgsProject.instance().mapLayers().values()
                   if isinstance(lyr, QgsVectorLayer) and lyr.providerType() == "postgres"),
                  key=lambda x: x.name().lower())


class ScopeTab(QWidget):
    def __init__(self, scope_cfg: dict, layer_cfg: dict, parent=None):
        super().__init__(parent)
        self._loading = True
        self.layer_cfg = {lid: dict((c or {}).get("scope") or {}) for lid, c in layer_cfg.items()}

        self.label = QLineEdit(scope_cfg.get("label", ""))
        self.label.setPlaceholderText("np. Oddział terenowy")
        self.boundary = QComboBox()
        self.boundary.addItem("— brak (wszyscy widzą cały projekt) —", "")
        for lyr in _pg_layers():
            if lyr.geometryType() == QgsWkbTypes.GeometryType.PolygonGeometry:
                self.boundary.addItem(lyr.name(), lyr.id())
        self.boundary.setCurrentIndex(max(0, self.boundary.findData(scope_cfg.get("layer", ""))))
        self.boundary.currentIndexChanged.connect(self._on_boundary)
        self.field = QComboBox()
        self._fill_fields(scope_cfg.get("field", ""))

        dim = QGroupBox("Wymiar zakresu")
        form = QFormLayout(dim)
        form.addRow("Nazwa (np. Oddział terenowy)", self.label)
        form.addRow("Warstwa granic obszarów", self.boundary)
        form.addRow("Pole z kodem obszaru", self.field)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Warstwa", "Reguła", "Pole z kodem (atrybut)", "Uwagi"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)

        info = QLabel("Administrator nadaje grupie w projekcie „cały obszar” albo wybrane kody obszarów "
                      "(panel Sophii → Projekty → Grupy i zakres). Ten sam filtr działa w formularzach, na mapie, "
                      "w identyfikacji, wydrukach, zdjęciach, dokumentach i pobieraniu zdjęć do QGIS.\n"
                      "Przestrzennie: podgląd — obiekt przecina obszar; edycja — punkt wewnątrz obiektu leży "
                      "w obszarze. Warstwa granic musi być w tej samej bazie co warstwy z regułą przestrzenną.")
        info.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addWidget(dim)
        lay.addWidget(self.table)
        self._fill_table()
        self._loading = False

    # ------------------------------------------------------------------ wymiar
    def _fill_fields(self, current: str = ""):
        self.field.clear()
        lyr = QgsProject.instance().mapLayer(self.boundary.currentData() or "")
        if isinstance(lyr, QgsVectorLayer):
            for f in lyr.fields():
                self.field.addItem(f.name(), f.name())
        self.field.setCurrentIndex(max(0, self.field.findData(current)))

    def _on_boundary(self):
        if self._loading:
            return
        self._fill_fields()
        self._fill_table()

    # ------------------------------------------------------------------ reguły warstw
    def _children(self) -> set[str]:
        return {r.referencingLayerId() for r in QgsProject.instance().relationManager().relations().values()}

    def _effective(self, lyr: QgsVectorLayer, mode: str) -> str:
        if mode != "auto":
            return mode
        if lyr.id() == self.boundary.currentData():
            return "none"
        if lyr.isSpatial():
            return "spatial"
        return "relation" if lyr.id() in self._children() else "none"

    def _fill_table(self):
        layers = _pg_layers()
        self.table.setRowCount(len(layers))
        for row, lyr in enumerate(layers):
            cfg = self.layer_cfg.get(lyr.id(), {})
            name = QTableWidgetItem(lyr.name())
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            name.setData(Qt.ItemDataRole.UserRole, lyr.id())
            self.table.setItem(row, 0, name)
            mode = QComboBox()
            for key, label in MODES:
                if key == "spatial" and not lyr.isSpatial():
                    continue
                mode.addItem(label, key)
            mode.setCurrentIndex(max(0, mode.findData(cfg.get("mode", "auto"))))
            field = QComboBox()
            field.addItem("—", "")
            for f in lyr.fields():
                field.addItem(f.name(), f.name())
            field.setCurrentIndex(max(0, field.findData(cfg.get("field", ""))))
            mode.currentIndexChanged.connect(lambda _i, r=row: self._on_rule(r))
            field.currentIndexChanged.connect(lambda _i, r=row: self._on_rule(r))
            self.table.setCellWidget(row, 1, mode)
            self.table.setCellWidget(row, 2, field)
            self._update_row(row)

    def _on_rule(self, row: int):
        lid = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        mode = self.table.cellWidget(row, 1).currentData()
        field = self.table.cellWidget(row, 2).currentData()
        self.layer_cfg[lid] = {"mode": mode, **({"field": field} if mode == "attribute" and field else {})}
        self._update_row(row)

    def _update_row(self, row: int):
        lid = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        lyr = QgsProject.instance().mapLayer(lid)
        mode = self.table.cellWidget(row, 1).currentData()
        field_box = self.table.cellWidget(row, 2)
        field_box.setEnabled(mode == "attribute")
        eff = self._effective(lyr, mode)
        note, warn = "", False
        if not self.boundary.currentData():
            note = "brak wymiaru zakresu — reguła nieaktywna"
        elif mode == "attribute" and not field_box.currentData():
            note, warn = "wybierz pole z kodem obszaru", True
        elif mode == "auto":
            note = f"→ {dict(MODES)[eff]}"
            if eff == "none" and lid != self.boundary.currentData() and not lyr.isSpatial():
                note, warn = note + " — tabela widoczna w całości dla każdej grupy", True
        item = QTableWidgetItem(note)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        if warn:
            item.setForeground(WARN)
        self.table.setItem(row, 3, item)

    # ------------------------------------------------------------------ wynik
    def scope_value(self) -> dict | None:
        if not self.boundary.currentData() or not self.field.currentData():
            return None
        return {"label": self.label.text().strip() or "Obszar", "layer": self.boundary.currentData(),
                "field": self.field.currentData()}

    def layer_rules(self) -> dict[str, dict]:
        return {lid: rule for lid, rule in self.layer_cfg.items() if rule.get("mode")}
