"""后台定时调度器。

一个常驻后台线程，周期性扫描已启用的任务，把到期的（按 interval 与
last_run 判断）逐个执行。任务执行本身会把日志写入数据库。

设计上串行执行任务：转存都是网络操作且需要节流防风控，串行更安全。
"""
import threading

from PySide6.QtCore import QThread, Signal

from app import db
from app.core.transfer import run_task, is_task_due, next_run_ts


class Scheduler(QThread):
    # 一个任务开始跑：task_id（UI 可显示"运行中"）
    task_started = Signal(int)
    # 一个任务跑完：task_id, 统计结果
    task_ran = Signal(int, dict)
    # 每轮扫描结束（UI 可借此刷新列表/日志）
    swept = Signal()

    def __init__(self, check_interval: int = 60, startup_delay: int = 15):
        super().__init__()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self.check_interval = check_interval
        self.startup_delay = startup_delay

    def run(self):
        # 启动后先等一会，让界面加载完再开始扫描
        if self._stop.wait(self.startup_delay):
            return
        while not self._stop.is_set():
            self._sweep_once()
            self.swept.emit()
            # 可被 wake_now() 提前唤醒；否则睡到下一轮
            self._wake.wait(self.check_interval)
            self._wake.clear()

    def _sweep_once(self):
        try:
            tasks = db.list_tasks()
        except Exception as e:  # noqa: BLE001
            db.add_log("error", f"调度器读取任务失败：{e}")
            return
        for t in tasks:
            if self._stop.is_set():
                return
            if not t.get("enabled"):
                continue
            if not is_task_due(t):
                continue
            try:
                self.task_started.emit(t["id"])
                result = run_task(t)
                self.task_ran.emit(t["id"], result)
                self._log_done(t, result)
            except Exception as e:  # noqa: BLE001
                db.add_log("error", f"任务执行异常（id={t.get('id')}）：{e}", t.get("id"))

    def _log_done(self, task: dict, result: dict):
        """定时同步跑完记一条清晰的完成提示（带下次同步时间）。"""
        import time

        name = task.get("note") or task.get("entity_name") or task.get("link") or "任务"
        # run_task 已更新 last_run，这里据此算下次时间
        fresh = db.get_task(task["id"]) or task
        nxt = next_run_ts(fresh)
        nxt_text = time.strftime("%m-%d %H:%M", time.localtime(nxt)) if nxt else "稍后"
        db.add_log(
            "info",
            f"⏱ 定时同步「{name}」完成：新增 {result.get('transferred', 0)}、"
            f"跳过 {result.get('skipped', 0)}、改名 {result.get('renamed', 0)}；"
            f"下次约 {nxt_text}",
            task["id"],
        )

    def wake_now(self):
        """立即触发一轮扫描（如新增任务后）。"""
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()
