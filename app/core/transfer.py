"""转存编排：解析分享 → 校验提取码 → 列文件 → 去重 → 转存 → 关键字重命名。

供「立即转存」按钮与（后续）定时调度共用。所有步骤写入日志表。
"""
import time
import random
from typing import Callable, Optional

from app.baidu.client import get_client_for_account, BaiduPanClient
from app.core.rename import apply_rules
from app import db
from app.config import DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY

# 回调签名：log(level, message)
LogFn = Callable[[str, str], None]


def _noop(level: str, msg: str) -> None:
    pass


def _join(target_dir: str, name: str) -> str:
    if target_dir.endswith("/"):
        return target_dir + name
    return target_dir + "/" + name


def run_task(task: dict, log: Optional[LogFn] = None) -> dict:
    """执行一个转存任务，返回统计 {transferred, skipped, renamed, error}。"""
    log = log or _noop
    task_id = task.get("id")

    def emit(level: str, msg: str):
        db.add_log(level, msg, task_id)
        log(level, msg)

    client = get_client_for_account(task.get("account_id"))
    if client is None:
        emit("error", "该任务绑定的账号未登录或已删除")
        return {"transferred": 0, "skipped": 0, "renamed": 0, "error": "账号不可用"}

    link = task["link"]
    parsed = BaiduPanClient.parse_share_link(link)
    surl = parsed["surl"]
    pwd = task.get("pwd") or parsed["pwd"]
    target_dir = task.get("target_dir") or "/"
    name_tag = task.get("note") or link

    if not surl:
        emit("error", f"链接解析失败：{link}")
        return {"transferred": 0, "skipped": 0, "renamed": 0, "error": "链接无效"}

    try:
        # 1. 校验提取码
        if pwd:
            client.verify_share_pwd(surl, pwd)
        # 2. 取分享元数据 + 根目录文件
        meta = client.get_share_meta(surl)
    except Exception as e:  # noqa: BLE001
        emit("error", f"[{name_tag}] {e}")
        return {"transferred": 0, "skipped": 0, "renamed": 0, "error": str(e)}

    files = meta["files"]
    if not files:
        emit("skip", f"[{name_tag}] 分享内没有可转存的文件")
        return {"transferred": 0, "skipped": 0, "renamed": 0, "error": ""}

    # 3. 确保目标目录存在（已存在则不重复创建，避免生成带时间戳的空壳）
    if target_dir != "/":
        try:
            client.ensure_dir(target_dir)
        except Exception:
            pass

    # 4. 去重：挑出未转存过的文件
    new_items = []
    skipped = 0
    for f in files:
        fs_key = f"{meta['shareid']}_{f['fs_id']}"
        if db.is_transferred(task_id, fs_key):
            skipped += 1
            continue
        new_items.append(f)

    if not new_items:
        emit("skip", f"[{name_tag}] 无新增文件（已全部转存过 {skipped} 项）")
        return {"transferred": 0, "skipped": skipped, "renamed": 0, "error": ""}

    # 5. 转存（分批，单次最多 100 个，降低风控）
    # 重命名规则统一取「批量重命名」页配置的全局规则
    rules = db.list_rules(None) if task.get("rename_on") else []
    transferred = 0
    renamed = 0
    errors = []

    for batch in _chunks(new_items, 100):
        fsidlist = [f["fs_id"] for f in batch]
        try:
            res = client.transfer_files(
                meta["shareid"], meta["uk"], fsidlist, target_dir, meta["ref"]
            )
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
            emit("error", f"[{name_tag}] 转存请求失败：{e}")
            continue

        errno = res.get("errno")
        if errno not in (0, None):
            from app.baidu.client import _share_err

            msg = _share_err(errno, "转存失败")
            errors.append(msg)
            emit("error", f"[{name_tag}] {msg}")
            continue

        # 转存成功：标记去重 + 可选重命名
        for f in batch:
            fs_key = f"{meta['shareid']}_{f['fs_id']}"
            db.mark_transferred(task_id, fs_key, f["server_filename"])
            transferred += 1

            if rules:
                old = f["server_filename"]
                new = apply_rules(old, rules)
                if new and new != old:
                    try:
                        client.rename(_join(target_dir, old), new)
                        renamed += 1
                        emit("ok", f"[{name_tag}] 转存并改名：{old} → {new}")
                    except Exception as e:  # noqa: BLE001
                        emit("ok", f"[{name_tag}] 转存：{old}（改名失败：{e}）")
                else:
                    emit("ok", f"[{name_tag}] 转存：{old}")
            else:
                emit("ok", f"[{name_tag}] 转存：{f['server_filename']}")

        # 节流，降低风控
        time.sleep(random.uniform(DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY))

    summary = f"[{name_tag}] 完成：新增 {transferred}，跳过 {skipped}，改名 {renamed}"
    if errors:
        summary += f"，失败 {len(errors)}"
    emit("info", summary)

    # 更新任务最后运行时间
    _touch_last_run(task_id)

    return {
        "transferred": transferred,
        "skipped": skipped,
        "renamed": renamed,
        "error": "; ".join(errors),
    }


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _touch_last_run(task_id):
    if task_id is None:
        return
    with db.get_conn() as c:
        c.execute(
            "UPDATE tasks SET last_run=? WHERE id=?", (int(time.time()), task_id)
        )
