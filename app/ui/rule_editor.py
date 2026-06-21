"""关键字重命名规则编辑器 + 实时预览。

供「自动转存」页使用：用户配置若干规则，转存完成后按规则给
新文件/文件夹批量改名。支持实时预览效果。
"""
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QLineEdit,
    QPushButton,
    QLabel,
    QHeaderView,
    QPlainTextEdit,
)
from PySide6.QtCore import Qt

from app.core.rename import RULE_TYPES, apply_rules


class RuleEditor(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # 工具行
        bar = QHBoxLayout()
        add = QPushButton("＋ 添加规则")
        add.setObjectName("Ghost")
        add.clicked.connect(self.add_rule)
        rm = QPushButton("－ 删除选中")
        rm.setObjectName("Ghost")
        rm.clicked.connect(self.remove_rule)
        bar.addWidget(add)
        bar.addWidget(rm)
        bar.addStretch()
        hint = QLabel("规则自上而下依次作用于文件名")
        hint.setObjectName("Muted")
        bar.addWidget(hint)
        lay.addLayout(bar)

        # 规则表
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["规则类型", "关键字 / 匹配", "替换为"])
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 130)
        self.table.setMaximumHeight(160)
        self.table.cellChanged.connect(self._refresh_preview)
        lay.addWidget(self.table)

        # 预览区
        pv_head = QLabel("效果预览（左：原名 → 右：新名）")
        pv_head.setObjectName("FieldLabel")
        lay.addWidget(pv_head)
        prow = QHBoxLayout()
        self.sample = QPlainTextEdit()
        self.sample.setPlaceholderText("在此粘贴几个示例文件名，每行一个")
        self.sample.setMaximumHeight(96)
        self.sample.setPlainText(
            "【广告】最新电影合集.mp4\n软件安装包_by群友.zip\n资料-2026更新.pdf"
        )
        self.sample.textChanged.connect(self._refresh_preview)
        self.result = QPlainTextEdit()
        self.result.setObjectName("Log")
        self.result.setReadOnly(True)
        self.result.setMaximumHeight(96)
        prow.addWidget(self.sample)
        prow.addWidget(self.result)
        lay.addLayout(prow)

        self._refresh_preview()

    # ---- 规则增删 ----
    def add_rule(self, rule: dict | None = None):
        rule = rule or {"rule_type": "remove", "pattern": "", "replacement": ""}
        r = self.table.rowCount()
        self.table.insertRow(r)
        combo = QComboBox()
        for key, name in RULE_TYPES.items():
            combo.addItem(name, key)
        idx = combo.findData(rule.get("rule_type", "remove"))
        combo.setCurrentIndex(max(0, idx))
        combo.currentIndexChanged.connect(self._refresh_preview)
        self.table.setCellWidget(r, 0, combo)
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
            combo = self.table.cellWidget(r, 0)
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
            mark = "" if new == n else "  ✔"
            lines.append(f"{new}{mark}")
        self.result.setPlainText("\n".join(lines))
