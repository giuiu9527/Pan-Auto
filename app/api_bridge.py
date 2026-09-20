"""One-shot JSON bridge for the native IMM 投屏 UI (see main.py `--api`).

Every function here is a thin wrapper around an already-existing Pan-Auto
function -- it only marshals plain-JSON-safe arguments in and results out.
None of Baidu's protocol, the scheduler, or the transfer pipeline is
reimplemented here; this module exists purely so a separate C++ process can
drive the same functions the PySide6 UI already called directly.
"""
from collections import deque
from typing import Any

from app.netdisk import get_client_for_account
from app.baidu.client import get_client_for_account as get_baidu_client
from app.core.rename import preview as rename_preview_fn
from app.core import batch_rename


def _client(account_id):
    client = get_client_for_account(account_id)
    if client is None:
        raise RuntimeError("账号不可用（未登录或 Cookie 失效）")
    return client


def _baidu(account_id):
    # mbox (friend/group) endpoints only exist on the Baidu client -- Quark
    # has no equivalent, same restriction the old PySide6 UI enforced.
    client = get_baidu_client(account_id)
    if client is None:
        raise RuntimeError("账号不可用（未登录、非百度账号，或 Cookie 失效）")
    return client


def list_dir(args: dict) -> Any:
    return _client(args["account_id"]).list_dir(args.get("path") or "/")


def delete_files(args: dict) -> Any:
    return _client(args["account_id"]).delete_files(args["paths"])


def copy_files(args: dict) -> Any:
    return _client(args["account_id"]).copy_files(args["paths"], args["target_dir"])


def rename_preview(args: dict) -> Any:
    return [{"old": o, "new": n} for o, n in rename_preview_fn(args["names"], args["rules"])]


def rename_run(args: dict) -> Any:
    return batch_rename.run_rename(
        args["account_id"],
        args["folder"],
        args["rules"],
        args.get("include_dirs", True),
        args.get("include_files", True),
    )


def ad_scan(args: dict) -> Any:
    """Same recursive walk-and-match loop as ad_clean.py's ScanWorker.run()
    -- that loop is plain BFS glue around list_dir(), not protocol logic, so
    duplicating the ~15 lines here (instead of importing a QThread meant to
    run inside a QApplication event loop) is fine."""
    client = _client(args["account_id"])
    keywords = [k.lower() for k in args.get("keywords", [])]
    whitelist = [w.lower() for w in args.get("whitelist", [])]
    recursive = args.get("recursive", True)
    matched: list[dict] = []
    q = deque([args.get("folder") or "/"])
    scanned = 0
    while q and scanned < 1000:
        cur = q.popleft()
        scanned += 1
        for it in client.list_dir(cur):
            name = it.get("server_filename", "")
            low = name.lower()
            if any(w in low for w in whitelist):
                continue
            if any(k in low for k in keywords):
                matched.append({
                    "name": name,
                    "path": it.get("path", ""),
                    "size": it.get("size", 0),
                    "dir": cur,
                    "isdir": bool(it.get("isdir")),
                })
                continue
            if it.get("isdir") and recursive and it.get("path"):
                q.append(it["path"])
    return matched


def list_friends(args: dict) -> Any:
    return _baidu(args["account_id"]).list_friends()


def list_friend_files(args: dict) -> Any:
    return _baidu(args["account_id"]).list_friend_files(args["uk"])


def list_groups(args: dict) -> Any:
    return _baidu(args["account_id"]).list_groups()


def list_group_files(args: dict) -> Any:
    client = _baidu(args["account_id"])
    msgs = client.list_group_files(args["gid"])
    out = []
    for m in msgs:
        for f in m["files"]:
            out.append({**f, "msg_id": m["msg_id"], "from_uk": m.get("from_uk", "")})
    return out


def list_msg_folder(args: dict) -> Any:
    client = _baidu(args["account_id"])
    kids = client.list_msg_folder(args["from_uk"], args["msg_id"], args["fs_id"], args.get("gid", ""))
    return [{**k, "msg_id": args["msg_id"], "from_uk": args["from_uk"]} for k in kids]


def transfer_friend_files(args: dict) -> Any:
    return _baidu(args["account_id"]).transfer_friend_files(
        args["from_uk"], args["msg_id"], args["fs_ids"], args["target_dir"]
    )


def transfer_group_files(args: dict) -> Any:
    return _baidu(args["account_id"]).transfer_group_files(
        args["gid"], args.get("from_uk", ""), args["msg_id"], args["fs_ids"], args["target_dir"]
    )


_COMMANDS = {
    "list_dir": list_dir,
    "delete_files": delete_files,
    "copy_files": copy_files,
    "rename_preview": rename_preview,
    "rename_run": rename_run,
    "ad_scan": ad_scan,
    "list_friends": list_friends,
    "list_friend_files": list_friend_files,
    "list_groups": list_groups,
    "list_group_files": list_group_files,
    "list_msg_folder": list_msg_folder,
    "transfer_friend_files": transfer_friend_files,
    "transfer_group_files": transfer_group_files,
}


def dispatch(command: str, args: dict) -> Any:
    fn = _COMMANDS.get(command)
    if fn is None:
        raise RuntimeError(f"未知命令：{command}")
    return fn(args)
