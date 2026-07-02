"""夸克网盘网页接口客户端（基于 Cookie 登录态）。

实现：账号校验、目录浏览、分享转存全链路（解析链接 → 取 stoken →
列分享文件 → 保存转存 → 轮询异步任务）、建目录、重命名。

夸克用 file id（fid）而非路径定位文件，目录在 UI 里用
`quark://<fid>|<显示路径>` 编码携带，见 `_encode_path` / `_decode_path`。
"""
from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import quote, unquote

import requests

from app import db

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

ROOT_FID = "0"

API = "https://drive-pc.quark.cn/1/clouddrive"
# 夸克网页接口都要带的固定查询参数
COMMON = {"pr": "ucpro", "fr": "pc", "uc_param_str": ""}


def _encode_path(fid: str, display_path: str) -> str:
    display = display_path or "/"
    return f"quark://{fid}|{quote(display, safe='/')}"


def _decode_path(path: str) -> tuple[str, str]:
    if not path or path == "/":
        return ROOT_FID, "/"
    if path.startswith("quark://"):
        raw = path[len("quark://") :]
        if "|" in raw:
            fid, display = raw.split("|", 1)
            return fid or ROOT_FID, unquote(display or "/")
        return raw or ROOT_FID, "/"
    return path, "/"


def is_quark_path(path: str) -> bool:
    return bool(path and path.startswith("quark://"))


def display_path(path: str) -> str:
    return _decode_path(path)[1] if is_quark_path(path) else (path or "/")


class QuarkPanClient:
    def __init__(self, cookies: dict):
        self.s = requests.Session()
        self.s.headers.update(
            {
                "User-Agent": UA,
                "Referer": "https://pan.quark.cn/",
                "Origin": "https://pan.quark.cn",
                "Accept": "application/json, text/plain, */*",
            }
        )
        self.s.cookies.update(cookies)
        # 转存后改名时复用：{父目录fid: {文件名: fid}}
        self._dir_cache: dict[str, dict[str, str]] = {}

    # ---- 基础 ----
    def get_user_info(self) -> dict:
        """返回 {username, bdstoken} 形状，方便复用账号表。"""
        candidates = [
            "https://pan.quark.cn/account/info",
            "https://drive-pc.quark.cn/1/clouddrive/member",
        ]
        for url in candidates:
            try:
                r = self.s.get(url, params=COMMON, timeout=15)
                d = r.json()
                data = d.get("data") or d.get("result") or d
                name = (
                    data.get("nickname")
                    or data.get("nick_name")
                    or data.get("username")
                    or data.get("user_name")
                    or data.get("mobile")
                )
                if name:
                    return {"username": str(name), "bdstoken": ""}
            except Exception:  # noqa: BLE001
                pass

        # 部分接口不返回用户信息，但目录能列出来也说明 Cookie 有效。
        self.list_dir("/")
        return {"username": "夸克账号", "bdstoken": ""}

    def is_logged_in(self) -> bool:
        try:
            self.get_user_info()
            return True
        except Exception:
            return False

    # ---- 目录浏览 ----
    def _list_fid(self, fid: str) -> list[dict]:
        """列出某 fid 下的原始文件项（夸克接口原样返回）。"""
        r = self.s.get(
            f"{API}/file/sort",
            params={
                **COMMON,
                "pdir_fid": fid,
                "_page": 1,
                "_size": 200,
                "_fetch_total": 1,
                "_fetch_sub_dirs": 0,
                "_sort": "file_type:asc,updated_at:desc",
            },
            timeout=20,
        )
        d = r.json()
        _check(d, "夸克目录读取失败")
        return (d.get("data") or {}).get("list") or d.get("list") or []

    def list_dir(self, path: str = "/") -> list[dict]:
        if is_quark_path(path) or not path or path == "/":
            fid, current_display = _decode_path(path)
        else:
            # 浏览器/任务里回传的是人类显示路径（如 /子目录），按层级解析成 fid
            fid = self._walk_to_fid(path, create=False)
            current_display = path
        raw_items = self._list_fid(fid)
        return [self._normalize_item(item, current_display) for item in raw_items]

    def _normalize_item(self, item: dict, parent_display: str) -> dict:
        name = item.get("file_name") or item.get("name") or item.get("title") or ""
        fid = str(item.get("fid") or item.get("file_id") or item.get("id") or "")
        isdir = bool(item.get("dir") or item.get("isdir") or item.get("file_type") == 0)
        display = _join_display(parent_display, name)
        return {
            "fs_id": fid,
            "fid": fid,
            "server_filename": name,
            "isdir": 1 if isdir else 0,
            "size": int(item.get("size") or 0),
            "path": _encode_path(fid, display) if isdir else fid,
            "display_path": display,
            "provider": "quark",
            "raw": item,
        }

    # ---- 建目录 ----
    def create_dir(self, parent_fid: str, name: str) -> str:
        """在 parent_fid 下新建目录，返回新目录 fid。"""
        r = self.s.post(
            f"{API}/file",
            params=COMMON,
            json={
                "pdir_fid": parent_fid,
                "file_name": name,
                "dir_path": "",
                "dir_init_lock": False,
            },
            timeout=15,
        )
        d = r.json()
        # 已存在时夸克会返回对应错误，这里退回到目录里按名查 fid
        if not _is_ok(d):
            fid = self._find_child_dir(parent_fid, name)
            if fid:
                return fid
            _check(d, "夸克建目录失败")
        return str((d.get("data") or {}).get("fid") or "")

    def _find_child_dir(self, parent_fid: str, name: str) -> Optional[str]:
        for it in self._list_fid(parent_fid):
            if (it.get("dir") or it.get("file_type") == 0) and it.get("file_name") == name:
                return str(it.get("fid") or "")
        return None

    def _ensure_child_dir(self, parent_fid: str, name: str) -> str:
        existing = self._find_child_dir(parent_fid, name)
        if existing:
            return existing
        return self.create_dir(parent_fid, name)

    def _walk_to_fid(self, display: str, create: bool) -> str:
        """沿显示路径逐级解析出 fid。create=True 时缺失目录会被创建。"""
        parts = [p for p in (display or "/").strip().split("/") if p]
        cur = ROOT_FID
        for part in parts:
            if create:
                cur = self._ensure_child_dir(cur, part)
            else:
                nxt = self._find_child_dir(cur, part)
                if not nxt:
                    raise RuntimeError(f"目录不存在：{display}")
                cur = nxt
        return cur

    def resolve_target(self, target_dir: str) -> str:
        """把目标目录（quark:// 编码或显示路径）解析成 fid，沿途缺失的目录会创建。"""
        if is_quark_path(target_dir):
            fid, _ = _decode_path(target_dir)
            return fid or ROOT_FID
        return self._walk_to_fid(target_dir, create=True)

    # ---- 重命名 ----
    def rename_by_fid(self, fid: str, newname: str) -> dict:
        r = self.s.post(
            f"{API}/file/rename",
            params=COMMON,
            json={"fid": fid, "file_name": newname},
            timeout=15,
        )
        d = r.json()
        return {"error": None if _is_ok(d) else _msg(d, "改名失败")}

    def rename_item(self, item: dict, newname: str) -> dict:
        """按列目录项改名（批量重命名页用）。"""
        fid = item.get("fid") or item.get("fs_id")
        if not fid:
            return {"error": "缺少文件 fid"}
        return self.rename_by_fid(str(fid), newname)

    def delete_files(self, fids: list[str]) -> dict:
        """删除文件/文件夹（fids 为文件 fid 列表）。"""
        r = self.s.post(
            f"{API}/file/delete",
            params=COMMON,
            json={"action_type": 2, "filelist": [str(x) for x in fids], "exclude_fids": []},
            timeout=20,
        )
        d = r.json()
        if not _is_ok(d):
            return {"errno": d.get("code") or -1, "message": _msg(d, "删除失败")}
        task_id = (d.get("data") or {}).get("task_id") or ""
        if task_id:
            try:
                self._wait_task(task_id)
            except Exception as e:  # noqa: BLE001
                return {"errno": -1, "message": str(e)}
        return {"errno": 0}

    def rename_in_dir(self, target_fid: str, old_name: str, new_name: str) -> None:
        """转存后按文件名定位 fid 改名（转存自动改名用）。"""
        cache = self._dir_cache.get(target_fid)
        if cache is None:
            cache = {
                it.get("file_name", ""): str(it.get("fid") or "")
                for it in self._list_fid(target_fid)
            }
            self._dir_cache[target_fid] = cache
        fid = cache.get(old_name)
        if not fid:
            raise RuntimeError(f"转存后未找到文件：{old_name}")
        res = self.rename_by_fid(fid, new_name)
        if res.get("error"):
            raise RuntimeError(res["error"])
        # 改名后缓存键同步更新，避免同名冲突
        cache.pop(old_name, None)
        cache[new_name] = fid

    # ---- 分享转存 ----
    @staticmethod
    def parse_share_link(link: str) -> dict:
        """解析夸克分享链接，提取 pwd_id 与（可能内嵌的）提取码。"""
        pwd_id = ""
        m = re.search(r"/s/([0-9a-zA-Z]+)", link)
        if m:
            pwd_id = m.group(1)
        passcode = ""
        m2 = re.search(r"(?:pwd|passcode)=([0-9a-zA-Z]+)", link)
        if m2:
            passcode = m2.group(1)
        return {"pwd_id": pwd_id, "passcode": passcode}

    def _get_stoken(self, pwd_id: str, passcode: str) -> str:
        r = self.s.post(
            f"{API}/share/sharepage/token",
            params=COMMON,
            json={"pwd_id": pwd_id, "passcode": passcode or ""},
            timeout=15,
        )
        d = r.json()
        if not _is_ok(d):
            raise RuntimeError(_msg(d, "提取码校验失败"))
        stoken = (d.get("data") or {}).get("stoken") or ""
        if not stoken:
            raise RuntimeError("未取得分享 stoken（链接失效或需要提取码）")
        return stoken

    def _list_share(self, pwd_id: str, stoken: str, pdir_fid: str = "0") -> list[dict]:
        r = self.s.get(
            f"{API}/share/sharepage/detail",
            params={
                **COMMON,
                "pwd_id": pwd_id,
                "stoken": stoken,
                "pdir_fid": pdir_fid,
                "force": 0,
                "_page": 1,
                "_size": 200,
                "_fetch_banner": 0,
                "_fetch_share": 0,
                "_fetch_total": 1,
                "_sort": "file_type:asc,updated_at:desc",
            },
            timeout=20,
        )
        d = r.json()
        if not _is_ok(d):
            raise RuntimeError(_msg(d, "获取分享文件列表失败"))
        return (d.get("data") or {}).get("list") or []

    def open_share(self, link: str, pwd: str = "") -> dict:
        """打开分享：解析 → 取 stoken → 列根目录文件，返回统一 meta。

        meta = {pwd_id, stoken, files:[{fs_id, fid, server_filename, isdir,
                size, share_fid_token}], ...}
        """
        parsed = self.parse_share_link(link)
        pwd_id = parsed["pwd_id"]
        passcode = pwd or parsed["passcode"]
        if not pwd_id:
            raise RuntimeError("夸克分享链接解析失败")
        stoken = self._get_stoken(pwd_id, passcode)
        raw = self._list_share(pwd_id, stoken, "0")
        files = []
        for it in raw:
            fid = str(it.get("fid") or "")
            files.append(
                {
                    "fs_id": fid,
                    "fid": fid,
                    "server_filename": it.get("file_name") or "",
                    "isdir": 1 if (it.get("dir") or it.get("file_type") == 0) else 0,
                    "size": int(it.get("size") or 0),
                    "share_fid_token": it.get("share_fid_token") or "",
                }
            )
        return {"pwd_id": pwd_id, "stoken": stoken, "files": files}

    def share_key(self, meta: dict, f: dict) -> str:
        return f"{meta['pwd_id']}_{f['fid']}"

    def save_files(self, meta: dict, files: list[dict], target_fid: str) -> dict:
        """把分享里指定文件保存到 target_fid，返回 {"error": str|None}。"""
        # 新一批保存前清掉旧的目录缓存，确保改名能查到最新文件
        self._dir_cache.pop(target_fid, None)
        r = self.s.post(
            f"{API}/share/sharepage/save",
            params=COMMON,
            json={
                "fid_list": [f["fid"] for f in files],
                "fid_token_list": [f.get("share_fid_token", "") for f in files],
                "to_pdir_fid": target_fid or ROOT_FID,
                "pwd_id": meta["pwd_id"],
                "stoken": meta["stoken"],
                "pdir_fid": "0",
                "pdir_save_all": False,
                "exclude_fids": [],
                "scene": "link",
            },
            timeout=30,
        )
        d = r.json()
        if not _is_ok(d):
            return {"error": _msg(d, "转存失败")}
        task_id = (d.get("data") or {}).get("task_id") or ""
        if not task_id:
            return {"error": None}
        try:
            self._wait_task(task_id)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        return {"error": None}

    def _wait_task(self, task_id: str, retries: int = 40) -> dict:
        """轮询异步任务直到完成。status：1=进行中，2=成功。"""
        for i in range(retries):
            r = self.s.get(
                f"{API}/task",
                params={**COMMON, "task_id": task_id, "retry_index": i},
                timeout=15,
            )
            d = r.json()
            if not _is_ok(d):
                raise RuntimeError(_msg(d, "转存任务失败"))
            data = d.get("data") or {}
            status = data.get("status")
            if status == 2:
                return data
            time.sleep(0.8)
        raise RuntimeError("转存任务超时未完成")


def _join_display(parent: str, name: str) -> str:
    if not parent or parent == "/":
        return "/" + name
    return parent.rstrip("/") + "/" + name


def _is_ok(d: dict) -> bool:
    code = d.get("code")
    status = d.get("status")
    return code in (0, "0", None) and status in (200, "200", None, 0)


def _msg(d: dict, default: str) -> str:
    code = d.get("code")
    text = d.get("message") or d.get("msg") or default
    return f"{text}（code={code}）" if code not in (0, None) else text


def _check(d: dict, default: str) -> None:
    if not _is_ok(d):
        raise RuntimeError(_msg(d, default))


def parse_quark_cookie(raw: str) -> dict:
    cookies = {}
    for part in re.split(r";\s*", raw.strip()):
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def get_client_for_account(account_id: Optional[int]) -> Optional["QuarkPanClient"]:
    if account_id is None:
        return get_active_client()
    acc = db.get_account(account_id)
    if not acc or acc.get("provider") != "quark" or not acc.get("cookies"):
        return None
    return QuarkPanClient(acc["cookies"])


def get_active_client() -> Optional["QuarkPanClient"]:
    acc = db.get_active_account()
    if not acc or acc.get("provider") != "quark" or not acc.get("cookies"):
        return None
    return QuarkPanClient(acc["cookies"])
