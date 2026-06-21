"""批量重命名：对网盘某文件夹内的文件 / 文件夹按关键字规则改名。"""
import time
from typing import Callable, Optional

from app.baidu.client import get_client_for_account
from app.core.rename import apply_rules
from app import db

LogFn = Callable[[str, str], None]


def _join(folder: str, name: str) -> str:
    return (folder.rstrip("/") + "/" + name) if folder != "/" else "/" + name


def list_folder(account_id: int, folder: str) -> list[dict]:
    client = get_client_for_account(account_id)
    if client is None:
        raise RuntimeError("账号不可用")
    return client.list_dir(folder)


def run_rename(
    account_id: int,
    folder: str,
    rules: list[dict],
    include_dirs: bool = True,
    include_files: bool = True,
    log: Optional[LogFn] = None,
) -> dict:
    """执行重命名，返回 {total, renamed, error}。"""
    def emit(level, msg):
        db.add_log(level, msg, None)
        if log:
            log(level, msg)

    client = get_client_for_account(account_id)
    if client is None:
        emit("error", "账号不可用")
        return {"total": 0, "renamed": 0, "error": "账号不可用"}

    try:
        items = client.list_dir(folder)
    except Exception as e:  # noqa: BLE001
        emit("error", f"列目录失败：{e}")
        return {"total": 0, "renamed": 0, "error": str(e)}

    renamed = 0
    errors = 0
    for it in items:
        isdir = bool(it.get("isdir"))
        if isdir and not include_dirs:
            continue
        if not isdir and not include_files:
            continue
        old = it["server_filename"]
        new = apply_rules(old, rules)
        if not new or new == old:
            continue
        try:
            res = client.rename(_join(folder, old), new)
            if res.get("errno") in (0, None):
                renamed += 1
                emit("ok", f"改名：{old} → {new}")
            else:
                errors += 1
                emit("error", f"改名失败({res.get('errno')})：{old}")
        except Exception as e:  # noqa: BLE001
            errors += 1
            emit("error", f"改名异常：{old}：{e}")
        time.sleep(0.6)  # 轻节流

    emit("info", f"批量重命名完成：成功 {renamed}，失败 {errors}")
    return {"total": len(items), "renamed": renamed, "error": f"{errors} 个失败" if errors else ""}
