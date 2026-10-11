"""转存编排：按任务类型分发（分享链接 / 好友消息 / 群文件）。

统一处理：去重 → 去广告 → 转存 → 关键字重命名。所有步骤写入日志表。
供「立即转存」按钮与后台定时调度共用。

★并发约束：同一时刻只允许一个任务在跑（全局锁），同一任务不允许重入。
以前「立即同步」按钮和后台调度器可以同时跑同一个任务，两边同时建目录 /
同时转存，就会出现重复文件夹和重复文件。
"""
import time
import random
import re
import json
import threading
from typing import Callable, Optional

from app.netdisk import get_client_for_account
from app.core.rename import apply_rules
from app.core import adfilter
from app import db
from app.config import DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY

# 回调签名：log(level, message)
LogFn = Callable[[str, str], None]

# 各间隔对应的秒数，供调度器判断任务是否到期
INTERVAL_SECONDS = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "hourly": 60 * 60,
    "6h": 6 * 60 * 60,
    "daily": 24 * 60 * 60,
}

INTERVAL_LABELS = {
    "1m": "每 1 分钟",
    "5m": "每 5 分钟",
    "15m": "每 15 分钟",
    "30m": "每 30 分钟",
    "hourly": "每小时",
    "6h": "每 6 小时",
    "daily": "每天",
}

# 新建任务可选的频率（1m 仍兼容旧任务，但不再推荐：每分钟全量枚举极易触发风控）
INTERVAL_CHOICES = ["5m", "15m", "30m", "hourly", "6h", "daily"]

# 连续失败后的退避：等待时间 = 间隔 × 2^失败次数，最长 1 小时
MAX_BACKOFF_SECONDS = 60 * 60

# 广告关键词默认值（文件名命中即视为广告垃圾文件）
DEFAULT_AD_KEYWORDS = (
    "推荐打印\n首单免费\n次日达\n加微信\n加V\n公众号\n关注\n扫码\n"
    "广告\n免费领\n资料群\n客服\n淘宝\n拼多多\n谨防\n防走丢\n更多资源"
)

STAGE_DIR_NAME = "_pan_auto_tmp_"

EMPTY = {"transferred": 0, "skipped": 0, "renamed": 0, "error": ""}


def interval_label(key: str) -> str:
    return INTERVAL_LABELS.get(key, key or "")


def _noop(level: str, msg: str) -> None:
    pass


# 正在运行的任务 id（供任务列表显示"运行中"）。跨线程读写，加锁。
_RUNNING_LOCK = threading.Lock()
_RUNNING_IDS: set = set()
# 全局串行锁：所有转存任务串行执行（防风控 + 防止同目录并发建目录）
_GLOBAL_RUN_LOCK = threading.Lock()


def _try_mark_running(task_id) -> bool:
    """原子地把任务标记为运行中；已在运行返回 False。"""
    if task_id is None:
        return True
    with _RUNNING_LOCK:
        if task_id in _RUNNING_IDS:
            return False
        _RUNNING_IDS.add(task_id)
        return True


def set_task_running(task_id, on: bool) -> None:
    if task_id is None:
        return
    with _RUNNING_LOCK:
        if on:
            _RUNNING_IDS.add(task_id)
        else:
            _RUNNING_IDS.discard(task_id)


def is_task_running(task_id) -> bool:
    with _RUNNING_LOCK:
        return task_id in _RUNNING_IDS


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
def effective_period(task: dict) -> int:
    """任务的实际等待秒数：基础间隔 × 失败退避倍数。"""
    period = INTERVAL_SECONDS.get(task.get("interval"), INTERVAL_SECONDS["daily"])
    fails = int(task.get("fail_count") or 0)
    if fails > 0:
        period = min(period * (2 ** min(fails, 6)), max(period, MAX_BACKOFF_SECONDS))
    return period


def is_task_due(task: dict, now: Optional[float] = None) -> bool:
    """任务是否到期该跑（按 interval 与 last_run，连续失败会指数退避）。"""
    now = now or time.time()
    last = task.get("last_run") or 0
    return (now - last) >= effective_period(task)


def next_run_ts(task: dict) -> int:
    """任务下次运行的时间戳（last_run + 实际间隔）；从未跑过返回 0。"""
    last = task.get("last_run") or 0
    if not last:
        return 0
    return int(last) + effective_period(task)


# ---- 广告过滤 ----
def ad_keywords() -> list[str]:
    return adfilter.parse_keywords(db.get_setting("ad_keywords", DEFAULT_AD_KEYWORDS))


def ad_whitelist() -> list[str]:
    """白名单关键词：文件名命中则永不清理/跳过（保护自己插入的广告等）。"""
    return adfilter.parse_keywords(db.get_setting("ad_whitelist", ""))


def ad_action() -> str:
    """命中广告后的处理方式：skip（跳过/删除）/ replace（替换命中的词）/ rename（整个名字改掉）。"""
    a = db.get_setting("ad_action", adfilter.ACTION_SKIP)
    return a if a in adfilter.ACTIONS else adfilter.ACTION_SKIP


def ad_action_text() -> str:
    return db.get_setting("ad_action_text", "")


# 匹配规则（全角/半角、空白、I/l/1 混写）统一在 adfilter，这里只做别名保持旧调用不变
is_ad_to_remove = adfilter.is_ad_to_remove


def _log_ad_skipped(emit, name_tag: str, names: list[str]) -> None:
    """把被广告词跳过的名字记进运行记录，用户能看见「到底按哪个词、跳过了谁」。"""
    if not names:
        return
    shown = "、".join(names[:8]) + (f" 等 {len(names)} 项" if len(names) > 8 else "")
    emit("skip", f"[{name_tag}] 命中广告词，已跳过：{shown}")


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


def _enumerate_leaf_deep(
    client, from_uk, msg_id, gid, direct, max_calls=800, max_items=8000
):
    """递归枚举叶子文件夹下**所有层级**的项（文件+文件夹），供深层增量检测。

    只列一层的话，「已存在子文件夹内部新增的深层文件」永远发现不了；这里逐层深入，
    这样在文件夹 3 里新增的 ppt/mp4 也能被增量识别并同步。
    - `direct`：已列好的叶子直接子项，避免重复调用。
    - 防爆上限：调用次数/项数超限即停（超大目录退化为不完全枚举，已发现的新项仍会同步）。
    """
    out = list(direct)
    stack = [it for it in direct if it.get("isdir")]
    calls = 0
    while stack and calls < max_calls and len(out) < max_items:
        it = stack.pop()
        calls += 1
        try:
            kids = client.list_msg_folder(from_uk, msg_id, it["fs_id"], gid)
        except Exception:  # noqa: BLE001
            continue
        for k in kids:
            out.append(k)
            if k.get("isdir"):
                stack.append(k)
    return out


# ---- 分发入口 ----
def run_task(task: dict, log: Optional[LogFn] = None) -> dict:
    """执行一个任务，返回统计 {transferred, skipped, renamed, error}。

    - 同一任务不可重入：正在跑时再次调用直接返回（不报错、不写库）。
    - 所有任务全局串行：调度器与「立即同步」互不打架。
    - 无论成败都会更新 last_run；失败累计 fail_count 触发退避，成功清零。
    """
    tid = task.get("id")
    if not _try_mark_running(tid):
        # busy=True：不是真正的失败，界面不要弹错误框。运行标记归「正在跑的那一次」管，这里绝不能去清
        return {**_result(error="任务正在运行中，本次跳过"), "busy": True}
    try:
        with _GLOBAL_RUN_LOCK:
            kind = task.get("kind", "share")
            try:
                if kind in ("friend", "group"):
                    res = _run_msg_task(task, log)
                else:
                    res = _run_share_task(task, log)
            except Exception as e:  # noqa: BLE001  兜底：任何未预期异常都不能让调度器崩
                db.add_log("error", f"任务执行异常：{e}", tid)
                res = _result(error=str(e))
            db.set_task_last_run(tid)
            db.bump_task_fail_count(tid, failed=bool(res.get("error")))
            return res
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

    # 能列分享子目录的客户端（百度）走「递归逐文件」模式；夸克沿用下面按顶层条目的老逻辑
    if hasattr(client, "list_share_dir"):
        return _share_deep(client, meta, task, target_dir, ad_kw, ad_wl, rules, name_tag, emit)

    # 去重 + 去广告
    new_items = []
    skipped = 0
    ad_names = []
    for f in files:
        fs_key = client.share_key(meta, f)
        if db.is_transferred(task_id, fs_key):
            skipped += 1
            continue
        if ad_kw and is_ad_to_remove(f["server_filename"], ad_kw, ad_wl):
            db.mark_transferred(task_id, fs_key, f["server_filename"])  # 记下不再处理
            skipped += 1
            ad_names.append(f["server_filename"])
            continue
        new_items.append(f)
    _log_ad_skipped(emit, name_tag, ad_names)

    if not new_items:
        _quiet_done(emit, name_tag, skipped)
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

    # 分享接口按选中项转存，但广告文件夹本身仍可能已在目标目录或由服务端
    # 连带写入；百度客户端支持递归删除命中广告词的文件夹及其所有内容。
    if transferred and ad_kw and hasattr(client, "purge_ad_items"):
        try:
            removed = client.purge_ad_items(target_ref, ad_kw, ad_wl)
            if removed:
                emit("info", f"[{name_tag}] 已清理 {removed} 个广告文件/文件夹")
        except Exception as e:  # noqa: BLE001
            emit("error", f"[{name_tag}] 广告清理失败：{e}")

    _summary(emit, name_tag, transferred, skipped, renamed, errors)
    return _result(transferred, skipped, renamed, "; ".join(errors))


# 递归枚举分享时最多列多少个目录（防超大分享把接口打爆）；超出的目录本次不处理并写警告
SHARE_MAX_DIRS = 400


def _mirror_dir(target_dir: str, rel: tuple) -> str:
    base = (target_dir or "/").rstrip("/")
    return base + "/" + "/".join(rel) if rel else (base or "/")


def _scan_share_tree(client, meta, task_id, ad_kw, ad_wl,
                     action: str = adfilter.ACTION_SKIP, action_text: str = ""):
    """递归枚举分享里的所有文件，返回 (groups, skipped, ad_names, dirs, truncated)。

    groups = {相对目录元组: [新文件项]}，只含「没同步过」的文件；
    命中广告词时按处理方式：
      - 跳过：文件/文件夹整棵不进入（不转存、不在目标里建目录）；
      - 替换 / 改名：文件夹在目标里直接以**新名字**建出来（内容照常同步），
        文件照常转存，项里带 ``_final_name``，转存后改成新名字。

    ★兼容老任务：老逻辑把分享根下的顶层文件夹整个转存并按「文件夹自己的 fs_id」记已同步。
    遇到「自己已被记为已同步」的文件夹，说明它当时是整包进来的，里面现存的文件都按「已同步」
    处理（只记录、不转存），这样升级后不会把整个分享再拉一遍，只会同步之后新增的文件。
    """
    groups: dict = {}
    skipped = 0
    ad_names: list[str] = []
    dirs = 0
    truncated = False

    root_items = []
    try:
        root_items = client.list_share_dir(meta, "")
    except Exception:  # noqa: BLE001  根目录接口失败 → 用分享页解析出的顶层条目兜底
        root_items = []
    if not root_items:
        root_items = [
            {**f, "isdir": int(f.get("isdir") or 0),
             "path": f.get("path") or "/" + f["server_filename"]}
            for f in meta["files"]
        ]

    # 「迁移完成」标记：老记录只在第一次递归扫描时当作基线，扫完写 deep_<key>，之后不再生效，
    # 否则之后新增的文件会被永远当成「老的」而发现不了
    migrated: list[tuple[str, str]] = []

    # 栈元素：(分享内路径, 相对目标目录的路径, 是否老逻辑已整包同步过, 预取的子项或 None)
    stack = [("", (), False, root_items)]
    while stack:
        path, rel, baseline, items = stack.pop()
        if items is None:
            if dirs >= SHARE_MAX_DIRS:
                truncated = True
                continue
            dirs += 1
            items = client.list_share_dir(meta, path)   # 报错上抛：列不出来不能当成「没文件」
            time.sleep(0.2)
        subdirs = []
        for f in items:
            name = f["server_filename"]
            key = client.share_key(meta, f)
            isdir = bool(int(f.get("isdir") or 0))
            final = adfilter.ad_target_name(name, isdir, ad_kw, ad_wl, action, action_text) \
                if ad_kw else None
            if final == "":                          # 跳过（或替换后没有可用的名字）
                # 跳过标记用 ad_ 前缀：不能和「老逻辑整包同步过」的文件夹标记混在一起，
                # 否则改成「替换/改名」后这个文件夹会被当成老数据、里面的东西永远不同步
                if not db.is_transferred(task_id, "ad_" + key):
                    db.mark_transferred(task_id, "ad_" + key, name)   # 只记一次，之后不再重复提示
                    ad_names.append(name)
                skipped += 1
                continue
            if isdir:
                legacy = db.is_transferred(task_id, key) and not db.is_transferred(task_id, "deep_" + key)
                if legacy:
                    migrated.append(("deep_" + key, name))
                subdirs.append((f.get("path") or "", rel + (final or name,), baseline or legacy))
                continue
            if final:
                f = {**f, "_final_name": final}
            if db.is_transferred(task_id, key):
                skipped += 1
                continue
            if baseline:
                db.mark_transferred(task_id, key, name)
                skipped += 1
                continue
            groups.setdefault(rel, []).append(f)
        for sd in reversed(subdirs):          # 反向入栈 → 按名字顺序处理
            stack.append((sd[0], sd[1], sd[2], None))
    if not truncated:                         # 完整扫完才算迁移完成
        for mkey, mname in migrated:
            db.mark_transferred(task_id, mkey, mname)
    return groups, skipped, ad_names, dirs, truncated


def _share_deep(client, meta, task, target_dir, ad_kw, ad_wl, rules, name_tag, emit) -> dict:
    """分享链接「递归逐文件」同步（百度）。

    以前只比对分享根下的顶层条目、整个文件夹一起转存：根下只有一个包着所有内容的文件夹时
    （很常见），等于每次整包转存——广告看不到、文件夹里后来新增的文件也发现不了。
    现在：递归列出分享里所有文件 → 跳过广告 → 只转存没同步过的文件，并按分享里的层级
    在目标目录里镜像出同样的文件夹（目录已存在不会另建副本，同名文件跳过不会生成副本）。
    """
    task_id = task.get("id")
    action = ad_action()
    action_text = ad_action_text()
    try:
        groups, skipped, ad_names, dirs, truncated = _scan_share_tree(
            client, meta, task_id, ad_kw, ad_wl, action, action_text
        )
    except Exception as e:  # noqa: BLE001
        emit("error", f"[{name_tag}] 读取分享目录失败：{e}")
        return _result(error=str(e))
    _log_ad_skipped(emit, name_tag, ad_names)
    if truncated:
        emit("warn", f"[{name_tag}] 分享里的文件夹太多（超过 {SHARE_MAX_DIRS} 个），"
                     f"本次只处理了前 {SHARE_MAX_DIRS} 个目录")

    # 词表变了就把新词应用到目标目录里已有的文件上（用户明确保存过自定义词时，首次也算「变了」）；
    # 只用默认词表且没有历史指纹的老任务首次只记录指纹，不去清理，避免升级后突然删东西
    sig = adfilter.signature(ad_kw, ad_wl, action, action_text) if ad_kw else ""
    sig_key = f"ad_sig_{task_id}"
    stored_sig = db.get_setting(sig_key, "")
    custom_saved = db.get_setting("ad_keywords", None) is not None
    sig_changed = bool(ad_kw and stored_sig != sig and (stored_sig or custom_saved))

    transferred = 0
    renamed = 0
    errors: list[str] = []
    for rel, flist in groups.items():
        dest = _mirror_dir(target_dir, rel)
        try:
            if client.dir_exists(dest):
                existing = {i.get("server_filename") for i in client.list_dir(dest)}
            else:
                existing = set()
                client.resolve_target(dest)     # 建目录；已存在不会生成副本
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
            emit("error", f"[{name_tag}] 处理目录 {dest} 失败：{e}")
            continue
        # 先定每个文件最终叫什么：普通文件先占名，广告改名的再避让，绝不去改普通文件的名字
        taken = set(existing)
        fresh = []
        plain = [f for f in flist if not f.get("_final_name")]
        ad_renamed = [f for f in flist if f.get("_final_name")]
        for f in plain + ad_renamed:
            orig = f["server_filename"]
            final = f.get("_final_name") or orig
            if rules:
                final = apply_rules(final, rules) or final
            if orig in existing or final in existing:   # 目标里已有：记为已同步，不重复转存
                db.mark_transferred(task_id, client.share_key(meta, f), orig)
                skipped += 1
                continue
            if final != orig:
                final = _unique_name(final, taken)
            taken.update((orig, final))
            fresh.append((f, final))
        for batch in _chunks(fresh, 100):
            res = client.save_files(meta, [f for f, _ in batch], dest)
            if res.get("error"):
                errors.append(res["error"])
                emit("error", f"[{name_tag}] {dest}：{res['error']}")
                continue
            for f, final in batch:
                db.mark_transferred(task_id, client.share_key(meta, f), f["server_filename"])
                transferred += 1
                renamed += _rename_landed(client, dest, f["server_filename"], final,
                                          bool(f.get("_final_name")), name_tag, emit)
            time.sleep(random.uniform(DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY))

    # 目标目录里已有的广告：有新转存、或广告设置刚改过时处理一遍（跳过模式=删除，替换/改名模式=改名）
    if ad_kw and (transferred or sig_changed):
        try:
            if action == adfilter.ACTION_SKIP and hasattr(client, "purge_ad_items"):
                removed_names: list[str] = []
                n = client.purge_ad_items(_norm_target(target_dir), ad_kw, ad_wl, removed=removed_names)
                if n:
                    shown = "、".join(removed_names[:8]) + (f" 等 {n} 项" if n > 8 else "")
                    emit("info", f"[{name_tag}] 已清理 {n} 个广告文件/文件夹：{shown}")
            elif action != adfilter.ACTION_SKIP and hasattr(client, "rename_ad_items"):
                pairs: list = []
                n = client.rename_ad_items(
                    _norm_target(target_dir),
                    lambda nm, isdir: adfilter.ad_target_name(nm, isdir, ad_kw, ad_wl, action, action_text) or None,
                    renamed=pairs,
                )
                if n:
                    shown = "、".join(f"{a} → {b}" for a, b in pairs[:6]) + (f" 等 {n} 项" if n > 6 else "")
                    emit("info", f"[{name_tag}] 已把 {n} 个广告文件/文件夹改名：{shown}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"广告处理失败：{e}")
            emit("error", f"[{name_tag}] 广告处理失败：{e}")
    if ad_kw and not errors:
        db.set_setting(sig_key, sig)

    if not transferred and not errors:
        _quiet_done(emit, name_tag, skipped)
        return _result(skipped=skipped)
    _summary(emit, name_tag, transferred, skipped, renamed, errors, ad_kw)
    return _result(transferred, skipped, renamed, "; ".join(errors))


def _unique_name(name: str, taken: set) -> str:
    """同目录重名时在扩展名前加 (2)(3)…"""
    if name not in taken:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        stem, ext = name, ""
    for i in range(2, 1000):
        cand = f"{stem} ({i}).{ext}" if ext else f"{stem} ({i})"
        if cand not in taken:
            return cand
    return name


def _rename_landed(client, dest, orig, final, ad_hit, name_tag, emit) -> int:
    """转存落盘后改成最终名字（广告改名 + 批量重命名规则），返回 1（改了）或 0。"""
    if final == orig:
        emit("ok", f"[{name_tag}] 转存：{orig}")
        return 0
    try:
        client.rename_in_dir(dest, orig, final)
        emit("ok", f"[{name_tag}] 转存并改名{'（广告）' if ad_hit else ''}：{orig} → {final}")
        return 1
    except Exception as e:  # noqa: BLE001
        emit("ok", f"[{name_tag}] 转存：{orig}（改名失败：{e}）")
        return 0


def _norm_target(path: str) -> str:
    p = (path or "/").strip()
    return "/" + p.strip("/") if p.strip("/") else "/"


# ==========================================================================
# 好友消息 / 群文件转存（仅百度）
# ==========================================================================
def _run_msg_task(task: dict, log: Optional[LogFn] = None) -> dict:
    """好友 / 群 / 群「具体文件夹」同步。

    ★统一走「中转目录」：`mbox/msg/transfer` 无视 fsidlist、总是把整条消息整包倒进
    目标，且 `ondup=newcopy` 会在已有同名项时生成 `(1)(2)` 副本。所以三种任务都：
      1. 先整包转存到一个**空的**中转目录 `target/_pan_auto_tmp_<任务id>`；
      2. 在中转目录里删掉广告；
      3. 把内容**合并移动**进最终目录（同名文件夹递归合并、同名文件跳过保留旧的）；
      4. 删掉整个中转目录。
    最终目录跨次同步固定，增量就是就地更新，永远不会再长出副本文件夹。
    """
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
    if not hasattr(client, "transfer_friend_files"):
        emit("error", "好友/群同步仅支持百度网盘账号")
        return _result(error="账号类型不支持")

    entity = task.get("entity_id")
    name_tag = task.get("note") or task.get("entity_name") or entity or ""
    if not entity:
        emit("error", f"[{name_tag}] 任务未绑定好友/群")
        return _result(error="未绑定好友/群")

    # 群"具体文件夹"任务：转存后要去掉百度自动重建的外层壳，落到叶子文件夹本身
    leaf_ref = _folder_ref(task.get("link")) if kind == "group" else None
    leaf_rel = ""
    try:
        if kind == "friend":
            messages = client.list_friend_files(entity)
        elif leaf_ref:
            direct = client.list_msg_folder(
                leaf_ref["from_uk"], leaf_ref["msg_id"], leaf_ref["fs_id"], entity
            )
            # 直接子项的 path 去掉自身名即叶子文件夹路径（用于中转后定位叶子）
            for ch in direct:
                p = ch.get("path") or ""
                if "/" in p.strip("/"):
                    leaf_rel = "/" + p.strip("/").rsplit("/", 1)[0]
                    break
            # ★递归遍历叶子下所有层级：深层子文件夹内新增的文件也能被增量发现
            all_items = _enumerate_leaf_deep(
                client, leaf_ref["from_uk"], leaf_ref["msg_id"], entity, direct
            )
            messages = [
                {"msg_id": leaf_ref["msg_id"], "from_uk": leaf_ref["from_uk"], "files": all_items}
            ]
        else:
            messages = client.list_group_files(entity)
    except Exception as e:  # noqa: BLE001
        emit("error", f"[{name_tag}] 拉取文件消息失败：{e}")
        return _result(error=str(e))

    ad_kw = ad_keywords() if task.get("ad_skip") else []
    ad_wl = ad_whitelist() if task.get("ad_skip") else []
    rules = db.list_rules(None) if task.get("rename_on") else []

    # 先做去重/去广告筛选，没有新东西就不碰网盘（不建目录、不建中转目录）
    skipped = 0
    ad_names = []
    pending = []  # [(msg, new_files)]
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
                ad_names.append(f["server_filename"])
                continue
            new_files.append(f)
        if new_files:
            pending.append((msg, new_files))
    _log_ad_skipped(emit, name_tag, ad_names)

    if not pending:
        _quiet_done(emit, name_tag, skipped)
        return _result(skipped=skipped)

    target_dir = task.get("target_dir") or "/"
    try:
        target_ref = client.resolve_target(target_dir)
    except Exception as e:  # noqa: BLE001
        emit("error", f"[{name_tag}] 目标目录处理失败：{e}")
        return _result(error=str(e))

    # 准备一个空的中转目录（每个任务独立，避免同目录多任务互相干扰）
    stage_dir = f"{target_ref.rstrip('/')}/{STAGE_DIR_NAME}{task_id or ''}"
    try:
        if client.dir_exists(stage_dir):
            client.delete_and_wait([stage_dir])  # 清掉上次异常残留，保证为空
        client.ensure_dir(stage_dir)
    except Exception as e:  # noqa: BLE001
        emit("error", f"[{name_tag}] 中转目录准备失败：{e}")
        return _result(error=str(e))

    transferred = 0
    renamed = 0
    errors = []
    landed = []  # 成功转存的文件（落盘后再按规则改名）

    for msg, new_files in pending:
        fsids = [f["fs_id"] for f in new_files]
        try:
            if kind == "friend":
                res = client.transfer_friend_files(
                    msg["from_uk"], msg["msg_id"], fsids, stage_dir
                )
            else:
                res = client.transfer_group_files(
                    entity, msg["from_uk"], msg["msg_id"], fsids, stage_dir
                )
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
            emit("error", f"[{name_tag}] 转存请求失败：{e}")
            continue

        errno = res.get("errno")
        # errno=12 且一个都没转（total/target_file_nums=0）：这些文件你网盘里已存在，
        # 百度全盘去重拒绝重复转存（常见：你自己分享到群的文件、或早已同步过的文件）。
        # 标记为已处理并软跳过——否则高频任务会永远重试、每次报错刷屏、狂打接口。
        if errno == 12 and not (res.get("total") or res.get("target_file_nums")):
            for f in new_files:
                db.mark_transferred(
                    task_id, f"{kind}_{entity}_{f['fs_id']}", f["server_filename"]
                )
            skipped += len(new_files)
            emit(
                "skip",
                f"[{name_tag}] {len(new_files)} 个文件已存在于你的网盘，百度不允许重复转存，已跳过",
            )
            continue
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
            landed.append(f)
        time.sleep(random.uniform(DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY))

    # 中转 → 最终目录
    final_dir = target_ref
    if transferred:
        try:
            if ad_kw:
                removed = client.purge_ad_items(stage_dir, ad_kw, ad_wl)
                if removed:
                    emit("info", f"[{name_tag}] 已清理 {removed} 个广告文件/文件夹")
            if leaf_ref:
                final_dir = client.extract_leaf(stage_dir, target_ref, leaf_rel)
            else:
                client.merge_move_into(stage_dir, target_ref)
                if client.dir_exists(stage_dir):
                    client.delete_and_wait([stage_dir])
            emit("info", f"[{name_tag}] 已整理到 → {final_dir}")
            for f in landed:  # 落盘后在最终目录里按规则改名并记日志
                renamed += _maybe_rename(client, final_dir, f, rules, name_tag, emit)
        except Exception as e:  # noqa: BLE001
            emit(
                "error",
                f"[{name_tag}] 目录整理失败（文件已在中转目录 {stage_dir}，下次同步会先清掉它）：{e}",
            )
            errors.append(f"目录整理失败：{e}")
    else:
        # 一个都没转成功：清掉刚建的空中转目录，别在网盘里留垃圾
        try:
            if client.dir_exists(stage_dir):
                client.delete_and_wait([stage_dir])
        except Exception:  # noqa: BLE001
            pass

    _summary(emit, name_tag, transferred, skipped, renamed, errors)
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


def _quiet_done(emit, name_tag, skipped):
    """没有新增时只记一条简短的跳过记录，避免高频任务刷屏。"""
    emit("skip", f"[{name_tag}] 无新增（已同步 {skipped} 项）")


def _summary(emit, name_tag, transferred, skipped, renamed, errors, ad_kw=None):
    summary = f"[{name_tag}] 完成：新增 {transferred}，跳过 {skipped}，改名 {renamed}"
    if errors:
        summary += f"，失败 {len(errors)}"
    if ad_kw:
        custom = db.get_setting("ad_keywords", None) is not None
        summary += f"；本次按 {len(ad_kw)} 个广告词过滤" + ("" if custom else "（默认词表，未保存自定义词）")
    emit("error" if errors else "info", summary)


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]
