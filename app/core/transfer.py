"""转存编排：按任务类型分发（分享链接 / 好友消息 / 群文件）。

统一处理：去重 → 去广告 → 转存 → 关键字重命名。所有步骤写入日志表。
供「立即转存」按钮与后台定时调度共用。
"""
import time
import random
import re
import json
import threading
from typing import Callable, Optional

from app.netdisk import get_client_for_account
from app.core.rename import apply_rules
from app import db
from app.config import DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY

# 回调签名：log(level, message)
LogFn = Callable[[str, str], None]

# 各间隔对应的秒数，供调度器判断任务是否到期
INTERVAL_SECONDS = {
    "30m": 30 * 60,
    "hourly": 60 * 60,
    "6h": 6 * 60 * 60,
    "daily": 24 * 60 * 60,
}

# 广告关键词默认值（文件名命中即视为广告垃圾文件）
DEFAULT_AD_KEYWORDS = (
    "推荐打印\n首单免费\n次日达\n加微信\n加V\n公众号\n关注\n扫码\n"
    "广告\n免费领\n资料群\n客服\n淘宝\n拼多多\n谨防\n防走丢\n更多资源"
)

EMPTY = {"transferred": 0, "skipped": 0, "renamed": 0, "error": ""}


def _noop(level: str, msg: str) -> None:
    pass


# 正在运行的任务 id（供任务列表显示"运行中"）。跨线程读写，加锁。
_RUNNING_LOCK = threading.Lock()
_RUNNING_IDS: set = set()


def set_task_running(task_id, on: bool) -> None:
    if task_id is None:
        return
    with _RUNNING_LOCK:
        if on:
            _RUNNING_IDS.add(task_id)
        else:
            _RUNNING_IDS.discard(task_id)


def running_task_ids() -> set:
    with _RUNNING_LOCK:
        return set(_RUNNING_IDS)


def _result(transferred=0, skipped=0, renamed=0, error="") -> dict:
    return {
        "transferred": transferred,
        "skipped": skipped,
        "renamed": renamed,
        "error": error,
    }


# ---- 调度辅助 ----
def is_task_due(task: dict, now: Optional[float] = None) -> bool:
    """任务是否到期该跑（按 interval 与 last_run）。"""
    now = now or time.time()
    last = task.get("last_run") or 0
    period = INTERVAL_SECONDS.get(task.get("interval"), INTERVAL_SECONDS["daily"])
    return (now - last) >= period


def next_run_ts(task: dict) -> int:
    """任务下次运行的时间戳（last_run + 间隔）；从未跑过返回 0。"""
    last = task.get("last_run") or 0
    if not last:
        return 0
    period = INTERVAL_SECONDS.get(task.get("interval"), INTERVAL_SECONDS["daily"])
    return int(last) + period


# ---- 广告过滤 ----
def ad_keywords() -> list[str]:
    raw = db.get_setting("ad_keywords", DEFAULT_AD_KEYWORDS)
    return [k.strip() for k in re.split(r"[\n,，]", raw) if k.strip()]


def ad_whitelist() -> list[str]:
    """白名单关键词：文件名命中则永不清理/跳过（保护自己插入的广告等）。"""
    raw = db.get_setting("ad_whitelist", "")
    return [k.strip() for k in re.split(r"[\n,，]", raw) if k.strip()]


def _is_ad(name: str, keywords: list[str]) -> bool:
    low = (name or "").lower()
    return any(k.lower() in low for k in keywords)


def is_ad_to_remove(name: str, ad_kw: list[str], whitelist: list[str]) -> bool:
    """是否应作为广告清理/跳过：命中广告词、且未命中白名单。"""
    if whitelist and _is_ad(name, whitelist):
        return False
    return _is_ad(name, ad_kw)


def _folder_ref(link) -> Optional[dict]:
    """群任务的 link 若是 {fs_id,msg_id,from_uk} JSON，则解析为文件夹引用。"""
    if not link:
        return None
    try:
        d = json.loads(link)
    except (ValueError, TypeError):
        return None
    if isinstance(d, dict) and d.get("fs_id") and d.get("msg_id"):
        return {
            "fs_id": d["fs_id"],
            "msg_id": str(d["msg_id"]),
            "from_uk": str(d.get("from_uk", "")),
        }
    return None


# ---- 分发入口 ----
def run_task(task: dict, log: Optional[LogFn] = None) -> dict:
    """执行一个任务，返回统计 {transferred, skipped, renamed, error}。"""
    tid = task.get("id")
    set_task_running(tid, True)
    try:
        kind = task.get("kind", "share")
        if kind in ("friend", "group"):
            return _run_msg_task(task, log)
        return _run_share_task(task, log)
    finally:
        set_task_running(tid, False)


# ==========================================================================
# 分享链接转存
# ==========================================================================
def _run_share_task(task: dict, log: Optional[LogFn] = None) -> dict:
    """分享链接转存：适配百度与夸克（统一协议），本函数不感知具体网盘。"""
    log = log or _noop
    task_id = task.get("id")

    def emit(level: str, msg: str):
        db.add_log(level, msg, task_id)
        log(level, msg)

    client = get_client_for_account(task.get("account_id"))
    if client is None:
        emit("error", "该任务绑定的账号未登录或已删除")
        return _result(error="账号不可用")

    link = task["link"]
    pwd = task.get("pwd") or ""
    target_dir = task.get("target_dir") or "/"
    name_tag = task.get("note") or link

    try:
        meta = client.open_share(link, pwd)
    except Exception as e:  # noqa: BLE001
        emit("error", f"[{name_tag}] {e}")
        return _result(error=str(e))

    files = meta["files"]
    if not files:
        emit("skip", f"[{name_tag}] 分享内没有可转存的文件")
        return _result()

    try:
        target_ref = client.resolve_target(target_dir)
    except Exception as e:  # noqa: BLE001
        emit("error", f"[{name_tag}] 目标目录处理失败：{e}")
        return _result(error=str(e))

    ad_kw = ad_keywords() if task.get("ad_skip") else []
    ad_wl = ad_whitelist() if task.get("ad_skip") else []
    rules = db.list_rules(None) if task.get("rename_on") else []

    # 去重 + 去广告
    new_items = []
    skipped = 0
    for f in files:
        fs_key = client.share_key(meta, f)
        if db.is_transferred(task_id, fs_key):
            skipped += 1
            continue
        if ad_kw and is_ad_to_remove(f["server_filename"], ad_kw, ad_wl):
            db.mark_transferred(task_id, fs_key, f["server_filename"])  # 记下不再处理
            skipped += 1
            continue
        new_items.append(f)

    if not new_items:
        emit("skip", f"[{name_tag}] 无新增文件（跳过 {skipped} 项）")
        db.set_task_last_run(task_id)
        return _result(skipped=skipped)

    transferred = 0
    renamed = 0
    errors = []
    for batch in _chunks(new_items, 100):
        res = client.save_files(meta, batch, target_ref)
        if res.get("error"):
            errors.append(res["error"])
            emit("error", f"[{name_tag}] {res['error']}")
            continue
        for f in batch:
            db.mark_transferred(task_id, client.share_key(meta, f), f["server_filename"])
            transferred += 1
            renamed += _maybe_rename(client, target_ref, f, rules, name_tag, emit)
        time.sleep(random.uniform(DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY))

    _summary(emit, name_tag, transferred, skipped, renamed, errors)
    db.set_task_last_run(task_id)
    return _result(transferred, skipped, renamed, "; ".join(errors))


# ==========================================================================
# 好友消息 / 群文件转存（仅百度）
# ==========================================================================
def _run_msg_task(task: dict, log: Optional[LogFn] = None) -> dict:
    log = log or _noop
    task_id = task.get("id")
    kind = task["kind"]

    def emit(level: str, msg: str):
        db.add_log(level, msg, task_id)
        log(level, msg)

    client = get_client_for_account(task.get("account_id"))
    if client is None:
        emit("error", "该任务绑定的账号未登录或已删除")
        return _result(error="账号不可用")

    entity = task.get("entity_id")
    name_tag = task.get("note") or task.get("entity_name") or entity or ""
    if not entity:
        emit("error", f"[{name_tag}] 任务未绑定好友/群")
        return _result(error="未绑定好友/群")

    try:
        if kind == "friend":
            messages = client.list_friend_files(entity)
        else:
            # 群任务：link 里可能带"具体文件夹"引用，只同步该文件夹；否则整群
            ref = _folder_ref(task.get("link"))
            if ref:
                children = client.list_msg_folder(
                    ref["from_uk"], ref["msg_id"], ref["fs_id"], entity
                )
                messages = [
                    {"msg_id": ref["msg_id"], "from_uk": ref["from_uk"], "files": children}
                ]
            else:
                messages = client.list_group_files(entity)
    except Exception as e:  # noqa: BLE001
        emit("error", f"[{name_tag}] 拉取文件消息失败：{e}")
        return _result(error=str(e))

    target_dir = task.get("target_dir") or "/"
    try:
        target_ref = client.resolve_target(target_dir)
    except Exception as e:  # noqa: BLE001
        emit("error", f"[{name_tag}] 目标目录处理失败：{e}")
        return _result(error=str(e))

    ad_kw = ad_keywords() if task.get("ad_skip") else []
    ad_wl = ad_whitelist() if task.get("ad_skip") else []
    rules = db.list_rules(None) if task.get("rename_on") else []

    transferred = 0
    skipped = 0
    renamed = 0
    errors = []

    for msg in messages:
        new_files = []
        for f in msg["files"]:
            fs_key = f"{kind}_{entity}_{f['fs_id']}"
            if db.is_transferred(task_id, fs_key):
                skipped += 1
                continue
            if ad_kw and is_ad_to_remove(f["server_filename"], ad_kw, ad_wl):
                db.mark_transferred(task_id, fs_key, f["server_filename"])
                skipped += 1
                continue
            new_files.append(f)
        if not new_files:
            continue

        fsids = [f["fs_id"] for f in new_files]
        try:
            if kind == "friend":
                res = client.transfer_friend_files(
                    msg["from_uk"], msg["msg_id"], fsids, target_ref
                )
            else:
                res = client.transfer_group_files(
                    entity, msg["from_uk"], msg["msg_id"], fsids, target_ref
                )
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
            emit("error", f"[{name_tag}] 转存请求失败：{e}")
            continue

        errno = res.get("errno")
        if errno not in (0, None):
            from app.baidu.client import _share_err

            m = _share_err(errno, "转存失败")
            errors.append(m)
            emit("error", f"[{name_tag}] {m}")
            continue

        for f in new_files:
            db.mark_transferred(
                task_id, f"{kind}_{entity}_{f['fs_id']}", f["server_filename"]
            )
            transferred += 1
            renamed += _maybe_rename(client, target_ref, f, rules, name_tag, emit)
        time.sleep(random.uniform(DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY))

    _summary(emit, name_tag, transferred, skipped, renamed, errors)
    db.set_task_last_run(task_id)
    return _result(transferred, skipped, renamed, "; ".join(errors))


# ---- 公共小工具 ----
def _maybe_rename(client, target_ref, f, rules, name_tag, emit) -> int:
    """转存成功后按规则改名，返回 1（改名）或 0。"""
    if not rules:
        emit("ok", f"[{name_tag}] 转存：{f['server_filename']}")
        return 0
    old = f["server_filename"]
    new = apply_rules(old, rules)
    if not new or new == old:
        emit("ok", f"[{name_tag}] 转存：{old}")
        return 0
    try:
        client.rename_in_dir(target_ref, old, new)
        emit("ok", f"[{name_tag}] 转存并改名：{old} → {new}")
        return 1
    except Exception as e:  # noqa: BLE001
        emit("ok", f"[{name_tag}] 转存：{old}（改名失败：{e}）")
        return 0


def _summary(emit, name_tag, transferred, skipped, renamed, errors):
    summary = f"[{name_tag}] 完成：新增 {transferred}，跳过 {skipped}，改名 {renamed}"
    if errors:
        summary += f"，失败 {len(errors)}"
    emit("info", summary)


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]
