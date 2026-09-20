"""关键字重命名规则编辑器 + 实时预览。

供「批量重命名」页使用（规则同时被「自动同步」的自动改名套用）。
"""
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QPlainTextEdit,
    QHeaderView,
    QAbstractItemView,
    QSizePolicy,
)
from PySide6.QtCore import Qt

from app import theme
from app.core.rename import RULE_TYPES, apply_rules
from app.ui.widgets import button, hint, field_label, table_frame


class RuleEditor(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        add = button("添加规则", "Ghost", "plus")
        add.clicked.connect(lambda: self.add_rule())
        rm = button("删除选中", "Ghost", "minus")
        rm.clicked.connect(self.remove_rule)
        bar.addWidget(add)
        bar.addWidget(rm)
        bar.addStretch()
        lay.addLayout(bar)
        lay.addWidget(hint("规则自上而下依次作用于文件名；双击单元格编辑关键字 / 替换文本。"))

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["规则类型", "关键字 / 匹配", "替换为"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setFrameShape(QTableWidget.NoFrame)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked)
        hh = self.table.horizontalHeader()
        hh.setFixedHeight(32)
        hh.setMinimumSectionSize(60)
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 112)
        self.table.setMinimumHeight(120)
        self.table.setMaximumHeight(170)
        self.table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.table.cellChanged.connect(self._refresh_preview)
        lay.addWidget(table_frame(self.table))

        lay.addWidget(field_label("效果预览（左：示例原名 → 右：新名）"))
        prow = QHBoxLayout()
        prow.setSpacing(8)
        self.sample = QPlainTextEdit()
        self.sample.setPlaceholderText("在此粘贴几个示例文件名，每行一个")
        self.sample.setPlainText(
            "【广告】最新电影合集.mp4\n软件安装包_by群友.zip\n资料-2026更新.pdf"
        )
        self.sample.textChanged.connect(self._refresh_preview)
        self.result = QPlainTextEdit()
        self.result.setObjectName("Log")
        self.result.setReadOnly(True)
        for w in (self.sample, self.result):
            w.setFixedHeight(88)
            w.setMinimumWidth(40)
            w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            w.setLineWrapMode(QPlainTextEdit.NoWrap)
        prow.addWidget(self.sample, 1)
        prow.addWidget(self.result, 1)
        lay.addLayout(prow)
        self._refresh_preview()

    # ---- 规则增删 ----
    def add_rule(self, rule: dict | None = None):
        rule = rule or {"rule_type": "remove", "pattern": "", "replacement": ""}
        r = self.table.rowCount()
        self.table.insertRow(r)
        combo = QComboBox()
        combo.setObjectName("Compact")
        for key, name in RULE_TYPES.items():
            combo.addItem(name, key)
        idx = combo.findData(rule.get("rule_type", "remove"))
        combo.setCurrentIndex(max(0, idx))
        combo.currentIndexChanged.connect(self._refresh_preview)
        cell = QWidget()
        cl = QHBoxLayout(cell)
        cl.setContentsMargins(4, 0, 4, 0)
        cl.addWidget(combo)
        self.table.setCellWidget(r, 0, cell)
        self.table.setItem(r, 1, QTableWidgetItem(rule.get("pattern", "")))
        self.table.setItem(r, 2, QTableWidgetItem(rule.get("replacement", "")))
        self._refresh_preview()

    def remove_rule(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)
            self._refresh_preview()

    # ---- 取值 / 赋值 ----
    def get_rules(self) -> list[dict]:
        rules = []
        for r in range(self.table.rowCount()):
            cell = self.table.cellWidget(r, 0)
            combo = cell.findChild(QComboBox) if cell else None
            if combo is None:
                continue
            pat = self.table.item(r, 1)
            rep = self.table.item(r, 2)
            rules.append(
                {
                    "rule_type": combo.currentData(),
                    "pattern": pat.text() if pat else "",
                    "replacement": rep.text() if rep else "",
                    "enabled": 1,
                }
            )
        return rules

    def set_rules(self, rules: list[dict]):
        self.table.setRowCount(0)
        for rule in rules:
            self.add_rule(rule)

    # ---- 预览 ----
    def _refresh_preview(self, *args):
        rules = self.get_rules()
        names = [n for n in self.sample.toPlainText().splitlines() if n.strip()]
        lines = []
        for n in names:
            new = apply_rules(n, rules)
            lines.append(new if new == n else f"{new}   (已改)")
        self.result.setPlainText("\n".join(lines))
