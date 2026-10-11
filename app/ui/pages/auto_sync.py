"""自动同步页：左侧任务表单（分享链接 / 群文件夹），右侧任务列表。"""
import json

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QStackedWidget,
    QSizePolicy,
    QMenu,
)
from PySide6.QtCore import Qt, QThread, Signal, QEvent, QTimer

from app import db
from app import theme
from app.core.transfer import (
    run_task, next_run_ts, running_task_ids, is_task_running,
    INTERVAL_CHOICES, INTERVAL_SECONDS, interval_label,
    ad_keywords, ad_action, ad_action_text,
)
from app.netdisk import account_display_name
from app.ui.icons import make_icon
from app.ui.netdisk_browser import NetdiskBrowser
from app.ui.group_picker import GroupPickerPopup
from app.ui.widgets import (
    card, field_group, hint, button, square_button, icon_button, input_with_button,
    SegmentBar, PageHeader, TwoColumn, scroll_wrap, setup_table, table_frame,
    actions_cell, pill_cell, fmt_time, InfoBox, two_line_cell,
)

DEFAULT_INTERVAL = "hourly"
DEFAULT_TARGET = "/来自好友的分享"


def _short_time(ts) -> str:
    """今天只显示 时:分，其它日期带 月-日。"""
    import time as _t

    if not ts:
        return ""
    if _t.strftime("%Y%m%d", _t.localtime(ts)) == _t.strftime("%Y%m%d"):
        return fmt_time(ts, "%H:%M")
    return fmt_time(ts)


class TransferWorker(QThread):
    finished_task = Signal(dict)

    def __init__(self, task: dict):
        super().__init__()
        self.task = task

    def run(self):
        self.finished_task.emit(run_task(self.task))


class AutoSyncPage(QWidget):
    tasks_changed = Signal()
    open_ad_settings = Signal()   # 「设置广告词」→ 主窗口切到广告清理页

    def __init__(self):
        super().__init__()
        self.editing_id = None
        self.mode = "share"
        self.group_ref = None
        self.scheduler = None  # 主窗口注入，新增任务后可立即唤醒扫描
        self._pickers = []
        self._workers = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.split = TwoColumn(self._build_form(), self._build_right(), left_width=390,
                               left_min=340, left_max=520)
        outer.addWidget(self.split)

        # 表格视口一变宽/变窄就重新决定是否隐藏「频率」列（页面自身的 resizeEvent
        # 早于分栏布局完成，拿到的宽度不准，所以监听视口）
        self.table.viewport().installEventFilter(self)
        self.refresh_accounts()
        self.reload_tasks()

    def eventFilter(self, obj, e):
        if obj is self.table.viewport() and e.type() == QEvent.Resize:
            self._adapt_columns()
        return super().eventFilter(obj, e)

    def _adapt_columns(self):
        """右栏太窄时隐藏「频率」列（仍可通过更多 → 编辑修改），保证任务名可读。"""
        if not hasattr(self, "table"):
            return
        narrow = self.table.viewport().width() < 480
        self.table.setColumnHidden(1, narrow)

    # ================= 左：表单 =================
    def _build_form(self) -> QWidget:
        left = QWidget()
        lay = QVBoxLayout(left)
        lay.setContentsMargins(24, 20, 10, 20)
        lay.setSpacing(12)

        self.form_header = PageHeader("新建同步任务", "填好后加入计划，后台会按频率自动增量转存")
        lay.addWidget(self.form_header)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(12)

        form = card()
        fl = QVBoxLayout(form)
        fl.setContentsMargins(18, 16, 18, 18)
        fl.setSpacing(14)

        self.seg = SegmentBar([("share", "分享链接"), ("group", "群文件夹")], "share")
        self.seg.changed.connect(self.set_tab)
        fl.addWidget(self.seg)

        self.account = QComboBox()
        fl.addWidget(field_group("转存到哪个账号", self.account))

        self.input_stack = QStackedWidget()
        self.input_stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.input_stack.addWidget(self._build_share_input())
        self.input_stack.addWidget(self._build_group_input())
        fl.addWidget(self.input_stack)

        self.target = QLineEdit(DEFAULT_TARGET)
        self.target.setPlaceholderText("/来自好友的分享")
        pick = square_button("folder", "浏览网盘选择文件夹")
        pick.clicked.connect(self.pick_folder)
        fl.addWidget(field_group("保存位置", input_with_button(self.target, pick),
                                 "群文件夹任务会落到「保存位置/文件夹名」，多次同步就地更新，不再生成副本"))

        self.interval = QComboBox()
        for key in INTERVAL_CHOICES:
            self.interval.addItem(interval_label(key), key)
        self.interval.setCurrentIndex(self.interval.findData(DEFAULT_INTERVAL))
        fl.addWidget(field_group("同步频率", self.interval,
                                 "频率越高越容易触发网盘风控；群文件夹每次都要遍历整棵目录，建议 30 分钟以上"))

        self.rename_on = QCheckBox("同步后按「批量重命名」里的规则自动改名")
        fl.addWidget(self.rename_on)
        self.ad_skip = QCheckBox("自动处理广告文件")
        self.ad_skip.setChecked(True)
        fl.addWidget(self.ad_skip)
        # 直接显示「现在到底按什么生效」：以前关键词在另一页、存没存上看不出来，结果一直用默认词表
        ad_row = QHBoxLayout()
        ad_row.setContentsMargins(24, 0, 0, 0)
        self.ad_status = hint("")
        ad_row.addWidget(self.ad_status, 1)
        ad_link = button("设置广告词", "Link")
        ad_link.clicked.connect(self.open_ad_settings.emit)
        ad_row.addWidget(ad_link, 0, Qt.AlignTop)
        fl.addLayout(ad_row)
        self._refresh_ad_status()

        self.note = QLineEdit()
        self.note.setPlaceholderText("便于识别，如：BL 讲义更新")
        fl.addWidget(field_group("任务备注（可选）", self.note))
        bl.addWidget(form)
        bl.addStretch()
        lay.addWidget(scroll_wrap(body), 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.cancel_edit_btn = button("取消编辑", "Ghost")
        self.cancel_edit_btn.clicked.connect(self.reset_form)
        self.cancel_edit_btn.hide()
        btn_row.addWidget(self.cancel_edit_btn)
        btn_row.addStretch()
        self.save_btn = button("加入同步计划", "PrimaryLarge", "plus")
        self.save_btn.clicked.connect(self.on_save)
        btn_row.addWidget(self.save_btn)
        lay.addLayout(btn_row)
        return left

    def _build_share_input(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        self.link = QLineEdit()
        self.link.setPlaceholderText("https://pan.baidu.com/s/xxxx?pwd=xxxx")
        lay.addWidget(field_group("分享链接", self.link))
        self.pwd = QLineEdit()
        self.pwd.setPlaceholderText("链接里已带 ?pwd= 可留空")
        self.pwd.setMaxLength(8)
        lay.addWidget(field_group("提取码（可选）", self.pwd))
        return w

    def _build_group_input(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        self.group_display = QLineEdit()
        self.group_display.setReadOnly(True)
        self.group_display.setPlaceholderText("点右侧按钮选择群，再进入要同步的文件夹")
        self.group_pick_btn = square_button("users", "选择百度群和文件夹", theme.PRIMARY)
        self.group_pick_btn.clicked.connect(self.open_group_picker)
        lay.addWidget(field_group("群 / 群文件夹", input_with_button(self.group_display, self.group_pick_btn),
                                 "选整群 = 同步群里所有新文件；选具体文件夹 = 只保留该文件夹内容（含深层新增）"))
        return w

    def set_tab(self, mode: str):
        self.mode = mode
        self.input_stack.setCurrentIndex(0 if mode == "share" else 1)

    def open_group_picker(self):
        acc_id = self.account.currentData()
        if acc_id is None:
            QMessageBox.warning(self, "提示", "请先在「设置」添加并选择百度账号")
            return
        pop = GroupPickerPopup(acc_id, self)
        pop.picked.connect(self._on_group_picked)
        pop.destroyed.connect(lambda _=None, p=pop: self._pickers.remove(p) if p in self._pickers else None)
        gp = self.group_display.mapToGlobal(self.group_display.rect().bottomLeft())
        pop.move(gp)
        pop.show()
        self._pickers.append(pop)

    def _on_group_picked(self, ref: dict):
        self.group_ref = ref
        self.group_display.setText(ref.get("display", ref.get("gname", "")))

    # ================= 右：任务列表 / 目录选择 =================
    def _build_right(self) -> QWidget:
        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self._build_task_page())
        self.right_stack.addWidget(self._build_folder_page())
        self.right_stack.setCurrentIndex(0)
        return self.right_stack

    def _build_task_page(self) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        rl.setContentsMargins(10, 20, 24, 20)
        rl.setSpacing(12)

        self.header = PageHeader("同步任务", "暂无任务")
        scan = button("立即扫描到期任务", "Ghost", "zap")
        scan.setToolTip("让后台调度器马上检查一遍哪些任务到期")
        scan.clicked.connect(self.wake_scheduler)
        self.header.add_action(scan)
        rl.addWidget(self.header)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["任务（账号 · 保存位置）", "频率", "状态", "操作"])
        setup_table(self.table, row_height=54)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        hh.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 104)
        self.table.setColumnWidth(2, 140)
        self.table.setColumnWidth(3, 104)
        rl.addWidget(table_frame(self.table), 1)

        rl.addWidget(InfoBox(
            "「立即同步」只转新增；「重新同步」会清掉该任务的去重记录再全量拉取（适合你删过目标文件想拉回来）。"
            "任务连续失败会自动延长等待时间，成功后恢复。"
        ))
        return page

    def _build_folder_page(self) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        rl.setContentsMargins(10, 20, 24, 20)
        rl.setSpacing(12)
        head = PageHeader("选择保存位置", "双击进入文件夹，选好后点「使用此文件夹」")
        close = icon_button("x", theme.TEXT_2, "返回")
        close.clicked.connect(lambda: self.right_stack.setCurrentIndex(0))
        head.add_action(close)
        rl.addWidget(head)
        c = card()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(10)
        self.browser = NetdiskBrowser()
        cl.addWidget(self.browser, 1)
        row = QHBoxLayout()
        row.addStretch()
        use = button("使用此文件夹", "Primary", "check")
        use.clicked.connect(self._use_folder)
        row.addWidget(use)
        cl.addLayout(row)
        rl.addWidget(c, 1)
        return page

    # ---- 主窗口切到本页 ----
    def on_shown(self):
        self.refresh_accounts()
        self.reload_tasks()
        self._refresh_ad_status()

    def _refresh_ad_status(self):
        kws = ad_keywords()
        custom = db.get_setting("ad_keywords", None) is not None
        action, text = ad_action(), ad_action_text()
        how = {"skip": "跳过不转存",
               "replace": f"把命中的词替换为「{text}」" if text else "删掉命中的词",
               "rename": f"整个名字改为「{text}」" if text else "改名（未填新名字，按跳过处理）"}[action]
        src = f"{len(kws)} 个自定义广告词" if custom else f"默认词表 {len(kws)} 个词（还没设置自己的广告词）"
        self.ad_status.setText(f"当前：{src}；命中后{how}")
        self.ad_status.setStyleSheet("" if custom else f"color:{theme.WARNING};")

    def refresh_accounts(self):
        prev = self.account.currentData()
        self.account.blockSignals(True)
        self.account.clear()
        for acc in db.list_accounts():
            self.account.addItem(account_display_name(acc), acc["id"])
        idx = self.account.findData(prev)
        if idx >= 0:
            self.account.setCurrentIndex(idx)
        self.account.blockSignals(False)

    def wake_scheduler(self):
        if self.scheduler is not None:
            self.scheduler.wake_now()
        self.header.set_subtitle("已通知后台调度器扫描到期任务")

    # ---- 保存位置选择 ----
    def pick_folder(self):
        acc_id = self.account.currentData()
        if acc_id is None:
            QMessageBox.warning(self, "提示", "请先在「设置」添加并选择账号")
            return
        self.right_stack.setCurrentIndex(1)
        self.browser.account_id = acc_id
        self.browser.load(self.target.text().strip() or "/")

    def _use_folder(self):
        self.target.setText(self.browser.current_dir())
        self.right_stack.setCurrentIndex(0)

    # ---- 保存（新增 / 更新）----
    def on_save(self):
        account_id = self.account.currentData()
        if account_id is None:
            QMessageBox.warning(self, "提示", "请先在「设置」添加并选择账号")
            return
        target = (self.target.text().strip() or "/").replace("\\", "/")
        if not target.startswith("/"):
            target = "/" + target
        if len(target) > 1:
            target = target.rstrip("/")
        common = {
            "account_id": account_id,
            "target_dir": target,
            "interval": self.interval.currentData(),
            "rename_on": 1 if self.rename_on.isChecked() else 0,
            "ad_skip": 1 if self.ad_skip.isChecked() else 0,
            "note": self.note.text().strip(),
            "enabled": 1,
        }
        if self.mode == "share":
            link = self.link.text().strip()
            if not link:
                QMessageBox.warning(self, "提示", "请填写分享链接")
                return
            data = {**common, "kind": "share", "link": link, "pwd": self.pwd.text().strip()}
        else:
            if not self.group_ref:
                QMessageBox.warning(self, "提示", "请先选择要同步的群 / 群文件夹")
                return
            ref = self.group_ref
            folder = ""
            if ref.get("fs_id"):
                folder = json.dumps(
                    {"fs_id": ref["fs_id"], "msg_id": ref["msg_id"], "from_uk": ref.get("from_uk", "")}
                )
            data = {
                **common,
                "kind": "group",
                "entity_id": str(ref["gid"]),
                "entity_name": ref.get("display") or ref.get("gname"),
                "link": folder,
                "pwd": "",
                "note": common["note"] or f"群：{ref.get('display') or ref.get('gname')}",
            }

        if self.editing_id is None:
            db.add_task(data)
            tip = "任务已加入自动同步计划，后台稍后会自动执行第一次同步。"
        else:
            db.update_task(self.editing_id, data)
            tip = "任务已更新。"
        db.add_log("info", f"{'更新' if self.editing_id else '新增'}同步任务：{data.get('note') or data.get('link')}")
        self.reset_form()
        self.reload_tasks()
        self.tasks_changed.emit()
        if self.scheduler is not None:
            self.scheduler.wake_now()
        QMessageBox.information(self, "已保存", tip)

    def reset_form(self):
        self.editing_id = None
        self.form_header.title.setText("新建同步任务")
        self.save_btn.setText("加入同步计划")
        self.save_btn.setIcon(make_icon("plus", "#ffffff", 16))
        self.cancel_edit_btn.hide()
        self.link.clear()
        self.pwd.clear()
        self.note.clear()
        self.group_ref = None
        self.group_display.clear()
        self.target.setText(DEFAULT_TARGET)
        self.rename_on.setChecked(False)
        self.ad_skip.setChecked(True)
        self.interval.setCurrentIndex(self.interval.findData(DEFAULT_INTERVAL))

    def load_for_edit(self, task: dict):
        self.editing_id = task["id"]
        self.form_header.title.setText("编辑同步任务")
        self.save_btn.setText("保存修改")
        self.save_btn.setIcon(make_icon("check", "#ffffff", 16))
        self.cancel_edit_btn.show()
        idx = self.account.findData(task["account_id"])
        if idx >= 0:
            self.account.setCurrentIndex(idx)
        self.target.setText(task["target_dir"] or "/")
        self.note.setText(task["note"] or "")
        self.rename_on.setChecked(bool(task["rename_on"]))
        self.ad_skip.setChecked(bool(task.get("ad_skip")))
        iv = self.interval.findData(task["interval"])
        if iv < 0:  # 旧任务的 1m 等不在可选列表里：临时加进去以便显示
            self.interval.addItem(interval_label(task["interval"]), task["interval"])
            iv = self.interval.count() - 1
        self.interval.setCurrentIndex(iv)
        if task.get("kind", "share") == "share":
            self.seg.set_current("share")
            self.set_tab("share")
            self.link.setText(task["link"] or "")
            self.pwd.setText(task.get("pwd") or "")
        else:
            self.seg.set_current("group")
            self.set_tab("group")
            ref = {"gid": task.get("entity_id"), "gname": task.get("entity_name"),
                   "display": task.get("entity_name")}
            try:
                fr = json.loads(task.get("link") or "")
                if isinstance(fr, dict) and fr.get("fs_id"):
                    ref.update({"fs_id": fr["fs_id"], "msg_id": str(fr["msg_id"]),
                                "from_uk": str(fr.get("from_uk", ""))})
            except (ValueError, TypeError):
                pass
            self.group_ref = ref
            self.group_display.setText(task.get("entity_name") or "")

    # ---- 任务列表 ----
    def reload_tasks(self):
        tasks = db.list_tasks()
        running = running_task_ids()
        self.table.setRowCount(0)
        self.table.setRowCount(len(tasks))
        enabled = 0
        for r, t in enumerate(tasks):
            if t["enabled"]:
                enabled += 1
            kind = t.get("kind", "share")
            name = t["note"] or t.get("entity_name") or t["link"] or "-"
            kind_text = {"share": "分享", "friend": "好友", "group": "群"}.get(kind, kind)
            sub = f"{kind_text} · {t.get('account_name') or '账号已删除'} · {t['target_dir'] or '/'}"
            self.table.setCellWidget(r, 0, two_line_cell(
                name, sub, "link" if kind == "share" else "users",
                theme.PRIMARY if kind == "share" else "#7C3AED",
            ))

            freq = QComboBox()
            freq.setObjectName("Compact")
            freq.setCursor(Qt.PointingHandCursor)
            keys = list(INTERVAL_CHOICES)
            if t["interval"] in INTERVAL_SECONDS and t["interval"] not in keys:
                keys.insert(0, t["interval"])
            for key in keys:
                freq.addItem(interval_label(key), key)
            fi = freq.findData(t["interval"])
            freq.setCurrentIndex(fi if fi >= 0 else 0)
            freq.setToolTip("修改该任务的同步频率，选择后立即生效")
            freq.activated.connect(
                lambda _=0, tid=t["id"], cb=freq: self.change_interval(tid, cb.currentData())
            )
            cell = QWidget()
            cl = QHBoxLayout(cell)
            cl.setContentsMargins(4, 0, 4, 0)
            cl.addWidget(freq)
            self.table.setCellWidget(r, 1, cell)

            fails = int(t.get("fail_count") or 0)
            if t["id"] in running:
                stxt, kind_ = "运行中", "primary"
            elif not t["enabled"]:
                stxt, kind_ = "已暂停", "muted"
            elif fails:
                nxt = next_run_ts(t)
                stxt, kind_ = f"失败 {fails} 次 · {_short_time(nxt)} 重试", "danger"
            else:
                nxt = next_run_ts(t)
                stxt, kind_ = (f"下次 {_short_time(nxt)}", "success") if nxt else ("等待首次同步", "info")
            self.table.setCellWidget(r, 2, pill_cell(stxt, kind_))

            run_b = icon_button("play", theme.PRIMARY, "立即同步（只转新增）")
            run_b.clicked.connect(lambda _=False, tt=dict(t): self.run_now(tt))
            toggle_b = icon_button(
                "pause" if t["enabled"] else "play",
                theme.WARNING if t["enabled"] else theme.SUCCESS,
                "暂停" if t["enabled"] else "启用",
            )
            toggle_b.clicked.connect(lambda _=False, tid=t["id"], en=t["enabled"]: self.toggle(tid, en))
            more_b = icon_button("more", theme.TEXT_2, "更多：编辑 / 重新同步 / 删除")
            more_b.clicked.connect(lambda _=False, tt=dict(t), b=more_b: self._show_more_menu(tt, b))
            self.table.setCellWidget(r, 3, actions_cell([run_b, toggle_b, more_b]))

        total = len(tasks)
        self.header.set_subtitle(
            f"启用 {enabled} / 共 {total} 个任务" if total else "暂无任务，在左侧新建"
        )

    def _show_more_menu(self, task: dict, anchor: QWidget):
        menu = QMenu(self)
        a_edit = menu.addAction(make_icon("edit", theme.TEXT_2, 16), "编辑任务")
        a_resync = menu.addAction(make_icon("refresh", theme.WARNING, 16), "重新同步（全量）")
        menu.addSeparator()
        a_del = menu.addAction(make_icon("trash", theme.DANGER, 16), "删除任务")
        chosen = menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        if chosen is a_edit:
            self.load_for_edit(task)
        elif chosen is a_resync:
            self.resync_now(task)
        elif chosen is a_del:
            self.on_delete(task["id"])

    def toggle(self, task_id: int, currently_enabled: int):
        db.set_task_enabled(task_id, not currently_enabled)
        self.reload_tasks()
        self.tasks_changed.emit()

    def change_interval(self, task_id: int, interval: str):
        db.set_task_interval(task_id, interval)
        db.add_log("info", f"已将任务同步频率改为「{interval_label(interval)}」", task_id)
        self.reload_tasks()
        self.tasks_changed.emit()

    def on_delete(self, task_id: int):
        if QMessageBox.question(self, "删除任务", "确定删除该任务？已同步的文件不会被删除。") == QMessageBox.Yes:
            db.delete_task(task_id)
            if self.editing_id == task_id:
                self.reset_form()
            self.reload_tasks()
            self.tasks_changed.emit()

    def resync_now(self, task: dict):
        if task.get("account_id") is None or db.get_account(task["account_id"]) is None:
            QMessageBox.warning(self, "账号不可用", "该任务绑定的账号已删除，请重建任务")
            return
        if QMessageBox.question(
            self, "重新同步",
            "将清除该任务的「已转记录」并重新转存全部文件。\n"
            "已存在于目标目录的同名文件会被跳过，不会产生副本。\n\n确定？",
        ) != QMessageBox.Yes:
            return
        n = db.clear_transferred(task["id"])
        db.add_log("info", f"重新同步「{task.get('note') or task.get('entity_name') or ''}」：已清除 {n} 条去重记录", task["id"])
        self.run_now(task)

    def run_now(self, task: dict):
        if task.get("account_id") is None or db.get_account(task["account_id"]) is None:
            QMessageBox.warning(self, "账号不可用", "该任务绑定的账号已删除，请重建任务")
            return
        if is_task_running(task.get("id")):
            QMessageBox.information(self, "正在运行", "该任务正在同步中，请稍候。")
            return
        # ★这里不能自己去标记「运行中」：标记由 run_task 在工作线程里原子地打、finally 里清。
        #   以前这里先 set_task_running(True)，run_task 一看「已经在跑」就直接返回、也不会清标记，
        #   结果任务永远显示「运行中」，调度器也因此再也不跑它（直到重启程序）。
        worker = TransferWorker(task)
        worker.finished_task.connect(self._on_transfer_done)
        worker.finished.connect(lambda w=worker: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(worker)
        worker.start()
        # 等工作线程打上运行标记后再刷新，列表才会显示「运行中」
        QTimer.singleShot(300, self.reload_tasks)
        self.header.set_subtitle("同步已在后台执行，完成后会弹窗提示，进度见「运行记录」")

    def _on_transfer_done(self, result: dict):
        if result.get("busy"):
            # 恰好调度器在跑同一个任务：不算错误，不弹框，等那一次跑完自然刷新
            self.reload_tasks()
            return
        msg = f"新增 {result['transferred']}，跳过 {result['skipped']}，改名 {result['renamed']}"
        if result.get("error"):
            QMessageBox.warning(self, "同步完成（含错误）", msg + f"\n错误：{result['error']}")
        else:
            QMessageBox.information(self, "同步完成", msg)
        self.reload_tasks()
