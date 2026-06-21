"""百度网盘网页私有接口客户端（基于 Cookie 登录态）。

Phase 1 仅实现：取用户信息、取 bdstoken、列目录、校验登录态。
分享链接转存 / 好友消息转存将在后续阶段补全（已留好方法骨架）。
"""
import re
import time
import json
from typing import Optional

import requests

from app import db

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class BaiduPanClient:
    def __init__(self, cookies: dict):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Referer": "https://pan.baidu.com/"})
        self.s.cookies.update(cookies)
        self._bdstoken: Optional[str] = None

    # ---- 基础 ----
    def is_logged_in(self) -> bool:
        try:
            info = self.get_user_info()
            return bool(info.get("username"))
        except Exception:
            return False

    def get_bdstoken(self) -> str:
        if self._bdstoken:
            return self._bdstoken
        r = self.s.get(
            "https://pan.baidu.com/api/gettemplatevariable",
            params={"fields": '["bdstoken","username"]'},
            timeout=15,
        )
        data = r.json()
        self._bdstoken = data.get("result", {}).get("bdstoken", "")
        return self._bdstoken

    def get_user_info(self) -> dict:
        r = self.s.get(
            "https://pan.baidu.com/api/gettemplatevariable",
            params={"fields": '["bdstoken","username","loginstate"]'},
            timeout=15,
        )
        result = r.json().get("result", {})
        return {
            "username": result.get("username", ""),
            "bdstoken": result.get("bdstoken", ""),
        }

    def get_quota(self) -> dict:
        """返回 {used, total}（字节）。"""
        r = self.s.get(
            "https://pan.baidu.com/api/quota",
            params={"checkfree": 1, "checkexpire": 1},
            timeout=15,
        )
        d = r.json()
        return {"used": d.get("used", 0), "total": d.get("total", 0)}

    def list_dir(self, path: str = "/") -> list[dict]:
        r = self.s.get(
            "https://pan.baidu.com/api/list",
            params={"dir": path, "order": "name", "web": 1, "num": 1000, "page": 1},
            timeout=20,
        )
        return r.json().get("list", [])

    def create_dir(self, path: str) -> dict:
        bd = self.get_bdstoken()
        r = self.s.post(
            "https://pan.baidu.com/api/create",
            params={"a": "commit", "bdstoken": bd},
            # rtype=1：路径冲突时返回已存在目录而非新建带时间戳的副本
            data={"path": path, "isdir": 1, "rtype": 1, "block_list": "[]"},
            timeout=15,
        )
        return r.json()

    def dir_exists(self, path: str) -> bool:
        """目标目录是否已存在（避免重复创建出带时间戳的空文件夹）。"""
        if path in ("/", ""):
            return True
        parent = path.rsplit("/", 1)[0] or "/"
        name = path.rsplit("/", 1)[-1]
        try:
            for it in self.list_dir(parent):
                if it.get("isdir") and it.get("server_filename") == name:
                    return True
        except Exception:  # noqa: BLE001
            pass
        return False

    def ensure_dir(self, path: str) -> None:
        """确保目录存在：已存在则什么都不做，不存在才创建。"""
        if path in ("/", ""):
            return
        if self.dir_exists(path):
            return
        self.create_dir(path)

    def rename(self, path: str, newname: str) -> dict:
        """重命名网盘内文件/文件夹。path 为完整路径。"""
        bd = self.get_bdstoken()
        filelist = f'[{{"path":"{path}","newname":"{newname}"}}]'
        r = self.s.post(
            "https://pan.baidu.com/api/filemanager",
            params={"opera": "rename", "async": 2, "bdstoken": bd, "onnest": "fail"},
            data={"filelist": filelist},
            timeout=15,
        )
        return r.json()

    def copy_files(self, file_paths: list[str], target_dir: str) -> dict:
        """把网盘内已有文件复制到 target_dir。"""
        bd = self.get_bdstoken()
        filelist = []
        for path in file_paths:
            name = path.rsplit("/", 1)[-1]
            filelist.append({"path": path, "dest": target_dir, "newname": name})
        r = self.s.post(
            "https://pan.baidu.com/api/filemanager",
            params={
                "opera": "copy",
                "async": 2,
                "bdstoken": bd,
                "onnest": "fail",
            },
            data={"filelist": json.dumps(filelist, ensure_ascii=False)},
            timeout=30,
        )
        return r.json()

    # ---- 分享转存（骨架，Phase 2 实现）----
    @staticmethod
    def parse_share_link(link: str) -> dict:
        """解析分享链接，提取 surl 与（可能内嵌的）提取码。"""
        pwd = ""
        m = re.search(r"pwd=([0-9a-zA-Z]+)", link)
        if m:
            pwd = m.group(1)
        m2 = re.search(r"/s/1?([0-9a-zA-Z_-]+)", link)
        surl = m2.group(1) if m2 else ""
        return {"surl": surl, "pwd": pwd}

    # ---- 分享转存完整流程 ----
    def verify_share_pwd(self, surl: str, pwd: str) -> None:
        """校验提取码，成功后写入 BDCLND Cookie（后续访问分享必需）。"""
        from urllib.parse import quote

        bd = self.get_bdstoken()
        ref = f"https://pan.baidu.com/s/1{surl}"
        r = self.s.post(
            "https://pan.baidu.com/share/verify",
            params={
                "surl": surl,
                "bdstoken": bd,
                "t": int(time.time() * 1000),
                "channel": "chunlei",
                "web": 1,
                "app_id": 250528,
                "clienttype": 0,
            },
            data={"pwd": pwd, "vcode": "", "vcode_str": ""},
            headers={"Referer": ref},
            timeout=15,
        )
        d = r.json()
        if d.get("errno") != 0:
            raise RuntimeError(_share_err(d.get("errno"), "提取码校验失败"))
        randsk = d.get("randsk", "")
        if randsk:
            self.s.cookies.set("BDCLND", quote(randsk), domain=".baidu.com")

    def get_share_meta(self, surl: str) -> dict:
        """访问分享页，解析 shareid / uk / 根目录文件列表（含 fs_id）。"""
        ref = f"https://pan.baidu.com/s/1{surl}"
        html = self.s.get(ref, headers={"Referer": "https://pan.baidu.com/"},
                          timeout=20).text

        # 提取码未通过时页面会要求输入提取码
        if ("请输入提取码" in html or "verify-form" in html) and "FileInfo" not in html:
            raise RuntimeError("需要提取码或提取码无效，请检查任务里的提取码")

        shareid = _first(html, r'"shareid"\s*:\s*"?(\d+)"?')
        uk = (
            _first(html, r'"share_uk"\s*:\s*"?(\d+)"?')
            or _first(html, r'"uk"\s*:\s*"?(\d+)"?')
        )
        files = _parse_share_files(html)

        # 页面没拿到文件 → 退回 share/list API 再试
        if not files and shareid and uk:
            try:
                files = self._list_share(uk, shareid, "")
            except Exception:
                files = []

        if not shareid or not uk or not files:
            raise RuntimeError(
                "无法解析分享信息（链接失效/提取码错误/页面结构变化）："
                f"shareid={'有' if shareid else '无'}, "
                f"uk={'有' if uk else '无'}, "
                f"文件数={len(files)}, 页面长度={len(html)}"
            )

        return {"shareid": shareid, "uk": uk, "files": files, "ref": ref}

    def _list_share(self, uk: str, shareid: str, sub_path: str) -> list[dict]:
        params = {
            "uk": uk,
            "shareid": shareid,
            "order": "name",
            "desc": 0,
            "showempty": 0,
            "web": 1,
            "page": 1,
            "num": 1000,
            "channel": "chunlei",
            "clienttype": 0,
            "app_id": 250528,
        }
        if sub_path:
            params["dir"] = sub_path
            params["root"] = 0
        else:
            params["root"] = 1
        r = self.s.get(
            "https://pan.baidu.com/share/list",
            params=params,
            headers={"Referer": "https://pan.baidu.com/"},
            timeout=20,
        )
        d = r.json()
        if d.get("errno") not in (0, None):
            raise RuntimeError(_share_err(d.get("errno"), "获取分享文件列表失败"))
        return d.get("list", [])

    def transfer_files(
        self, shareid: str, uk: str, fsidlist: list, target_dir: str, ref: str
    ) -> dict:
        """把指定 fs_id 列表转存到 target_dir。"""
        bd = self.get_bdstoken()
        r = self.s.post(
            "https://pan.baidu.com/share/transfer",
            params={
                "shareid": shareid,
                "from": uk,
                "bdstoken": bd,
                "channel": "chunlei",
                "web": 1,
                "clienttype": 0,
                "app_id": 250528,
            },
            data={
                "fsidlist": "[" + ",".join(str(x) for x in fsidlist) + "]",
                "path": target_dir,
            },
            headers={"Referer": ref},
            timeout=30,
        )
        return r.json()


def _first(text: str, pattern: str) -> str:
    m = re.search(pattern, text)
    return m.group(1) if m else ""


def _unescape(raw: str) -> str:
    """把页面里 JSON 转义的文件名还原（\\uXXXX、\\/ 等）。"""
    import json as _json

    try:
        return _json.loads('"' + raw + '"')
    except Exception:  # noqa: BLE001
        return raw.replace("\\/", "/")


def _parse_share_files(html: str) -> list[dict]:
    """从分享页 HTML 内嵌数据中解析根目录文件列表。

    页面里每个文件对象都含 server_filename / fs_id / isdir，按出现顺序配对。
    """
    names = re.findall(r'"server_filename":"((?:[^"\\]|\\.)*)"', html)
    fs_ids = re.findall(r'"fs_id":\s*"?(\d+)"?', html)
    isdirs = re.findall(r'"isdir":\s*"?(\d)"?', html)

    if not fs_ids or not names:
        return []

    n = min(len(names), len(fs_ids))
    files = []
    for i in range(n):
        files.append(
            {
                "fs_id": int(fs_ids[i]),
                "server_filename": _unescape(names[i]),
                "isdir": int(isdirs[i]) if i < len(isdirs) else 0,
            }
        )
    return files


_SHARE_ERRNO = {
    -1: "分享链接已失效或被删除",
    -4: "登录态失效，请重新登录",
    -6: "请重新登录",
    -8: "目标目录中已存在同名文件",
    -9: "提取码错误",
    -10: "网盘容量不足",
    -12: "提取码错误",
    -33: "转存文件数超过单次限制（一次最多约 1000 个）",
    2: "参数错误或分享已失效",
    4: "文件已转存过",
    12: "部分文件转存失败（可能已存在）",
    105: "链接格式不正确",
    115: "该分享不支持转存",
}


def _share_err(errno, default: str) -> str:
    return f"{_SHARE_ERRNO.get(errno, default)}（errno={errno}）"


def get_client_for_account(account_id: Optional[int]) -> Optional["BaiduPanClient"]:
    """按账号 id 构建客户端；找不到返回 None。"""
    if account_id is None:
        return get_active_client()
    acc = db.get_account(account_id)
    if not acc or not acc.get("cookies"):
        return None
    return BaiduPanClient(acc["cookies"])


def get_active_client() -> Optional["BaiduPanClient"]:
    """当前活跃账号的客户端；未登录返回 None。"""
    acc = db.get_active_account()
    if not acc or not acc.get("cookies"):
        return None
    return BaiduPanClient(acc["cookies"])


# 兼容旧调用
def get_client() -> Optional["BaiduPanClient"]:
    return get_active_client()
