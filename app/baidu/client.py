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
        self._bdstoken = _result_dict(r.json()).get("bdstoken", "")
        return self._bdstoken

    def get_user_info(self) -> dict:
        r = self.s.get(
            "https://pan.baidu.com/api/gettemplatevariable",
            params={"fields": '["bdstoken","username","loginstate"]'},
            timeout=15,
        )
        result = _result_dict(r.json())
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

    def move_files(self, file_paths: list[str], target_dir: str) -> dict:
        """把网盘内已有文件/文件夹移动到 target_dir（保持原名）。

        移动到已存在同名文件夹时，百度会合并（把内容并进去），
        用于「转存后去掉外层壳」时把叶子文件夹并入最终目录。
        """
        bd = self.get_bdstoken()
        filelist = []
        for path in file_paths:
            name = path.rsplit("/", 1)[-1]
            filelist.append({"path": path, "dest": target_dir, "newname": name})
        r = self.s.post(
            "https://pan.baidu.com/api/filemanager",
            params={
                "opera": "move",
                "async": 2,
                "bdstoken": bd,
                "onnest": "fail",
                "channel": "chunlei",
                "web": 1,
                "clienttype": 0,
                "app_id": 250528,
            },
            data={"filelist": json.dumps(filelist, ensure_ascii=False)},
            headers={"Referer": "https://pan.baidu.com/disk/home"},
            timeout=30,
        )
        return r.json()

    def delete_files(self, paths: list[str]) -> dict:
        """删除网盘内文件/文件夹（path 为完整路径）。"""
        bd = self.get_bdstoken()
        r = self.s.post(
            "https://pan.baidu.com/api/filemanager",
            params={
                "opera": "delete",
                "async": 2,
                "bdstoken": bd,
                "onnest": "fail",
                "channel": "chunlei",
                "web": 1,
                "clienttype": 0,
                "app_id": 250528,
            },
            data={"filelist": json.dumps(paths, ensure_ascii=False)},
            headers={"Referer": "https://pan.baidu.com/disk/home"},
            timeout=30,
        )
        return r.json()

    def wait_task(self, taskid, timeout: float = 120.0) -> dict:
        """轮询 filemanager 异步任务直到完成，返回最终状态。"""
        deadline = time.time() + timeout
        last = {}
        while time.time() < deadline:
            try:
                last = self.s.get(
                    "https://pan.baidu.com/share/taskquery",
                    params={"taskid": taskid, "clienttype": 0, "web": 1, "app_id": 250528},
                    timeout=15,
                ).json()
            except Exception:  # noqa: BLE001
                time.sleep(0.8)
                continue
            if last.get("status") in ("success", "failed"):
                return last
            time.sleep(0.8)
        return last or {"status": "timeout"}

    def _move_wait(self, paths: list[str], dest: str) -> None:
        """移动并等待完成；异步任务轮询到结束。"""
        r = self.move_files(paths, dest)
        if r.get("taskid"):
            self.wait_task(r["taskid"])

    def merge_move_into(self, src_dir: str, dst_dir: str) -> int:
        """把 src_dir 里的所有内容并入 dst_dir（递归处理同名文件夹冲突）。

        百度 move 到已存在同名文件夹会报 -8，不会自动合并，所以这里：
        - 目标没有同名项 → 直接移动（批量）。
        - 同名且都是文件夹 → 递归并入。
        - 同名文件 → 跳过（保留 dst 原有，避免覆盖）。
        返回移动的顶层项数。
        """
        self.ensure_dir(dst_dir)
        try:
            children = self.list_dir(src_dir)
        except Exception:  # noqa: BLE001
            return 0
        existing = {}
        try:
            for it in self.list_dir(dst_dir):
                existing[it.get("server_filename")] = int(it.get("isdir") or 0)
        except Exception:  # noqa: BLE001
            pass

        moved = 0
        to_move = []
        conflict_dirs = []
        for ch in children:
            name = ch.get("server_filename")
            if name is None:
                continue
            if name not in existing:
                to_move.append(src_dir.rstrip("/") + "/" + name)
            elif int(ch.get("isdir") or 0) and existing.get(name):
                conflict_dirs.append(name)
            # 同名文件：跳过
        if to_move:
            # 分批移动，防止单次请求过大
            for i in range(0, len(to_move), 100):
                self._move_wait(to_move[i : i + 100], dst_dir)
            moved += len(to_move)
        for name in conflict_dirs:
            moved += self.merge_move_into(
                src_dir.rstrip("/") + "/" + name, dst_dir.rstrip("/") + "/" + name
            )
        return moved

    def _dir_empty(self, path: str) -> bool:
        try:
            return len(self.list_dir(path)) == 0
        except Exception:  # noqa: BLE001
            return False

    def unnest_after_transfer(self, target_dir: str, leaf_rel: str) -> str:
        """去掉群文件转存自动重建的外层目录（含百度连带转来的无关兄弟内容）。

        百度群转存无视 fsidlist、总是把整条消息（整个顶层共享文件夹）按相对
        分享根的路径整包重建，导致选中的叶子文件夹被包在一层/多层「外壳」里、
        且外壳里还塞着别的兄弟文件。这里把叶子文件夹的内容并入
        target_dir/<叶子名>，再把整个外壳（连同无关兄弟）删掉。返回最终目录。

        leaf_rel 形如 '/2027白鹭申论全年班讲义/2027扎马步2.0'（相对分享根）。
        """
        target = (target_dir or "/").rstrip("/")
        segs = [s for s in leaf_rel.split("/") if s]
        if len(segs) < 2:
            # 没有外壳（叶子就在分享根下），无需处理
            return target + "/" + segs[0] if segs else target
        leaf_name = segs[-1]
        leaf_src = target + "/" + "/".join(segs)      # 外壳里的叶子
        final_dst = target + "/" + leaf_name          # 想要的最终位置
        wrapper_top = target + "/" + segs[0]          # 百度建的最顶层外壳
        if leaf_src == final_dst or wrapper_top == final_dst:
            # 叶子名与外壳顶层同名等边界情况：不做危险删除
            return final_dst
        self.merge_move_into(leaf_src, final_dst)
        # 叶子已挪出；把百度整包倒进来的外壳（含广告/无关兄弟）整个删掉
        if self._dir_empty(leaf_src):
            dr = self.delete_files([wrapper_top])
            if dr.get("taskid"):
                self.wait_task(dr["taskid"])
        return final_dst

    def extract_leaf(self, stage_dir: str, final_parent: str, leaf_rel: str) -> str:
        """把「临时中转目录」里的叶子文件夹内容并入 final_parent/<叶子名>，再删掉整个中转目录。

        群「具体文件夹」任务的正确落盘方式：先把整条消息整包转存到一个**空的**中转目录
        stage_dir（见 core/transfer），再从中把选中的叶子文件夹内容并入 final_parent/<叶子名>。
        该最终目录跨次同步固定不变，所以增量同步是**就地更新**、不会再生成 (1)(2) 副本。
        最后把整个 stage_dir 删掉（连同外壳、无关兄弟、广告）。返回最终叶子目录路径。

        ★关键坑：`leaf_rel` 来自 shareinfo 的 `path`，是**分享者网盘里的绝对路径**，
        开头可能带分享者自己的私有目录（如 `/我的资源/...`）；但百度整包转存重建时是
        **从被分享的顶层开始**、会**丢掉分享根以上的私有前缀**。所以不能直接用 `stage+leaf_rel`
        定位——那样会找不到叶子、把最终目录建成空的。这里改为**从叶子路径逐段去头、
        最长优先**地在 staging 里找真实存在的叶子位置（2026-07 实测逆向）。

        leaf_rel 为空时退化为把整个中转目录内容并入 final_parent（无法隔离叶子的兜底）。
        """
        stage = (stage_dir or "").rstrip("/")
        parent = (final_parent or "/").rstrip("/")
        segs = [s for s in (leaf_rel or "").split("/") if s]
        leaf_in_stage = None
        if segs:
            # 逐段去头找真实叶子位置：i=0 是完整绝对路径，i 越大前缀去得越多；最长匹配优先
            for i in range(len(segs)):
                cand = stage + "/" + "/".join(segs[i:])
                if self.dir_exists(cand):
                    leaf_in_stage = cand
                    break
        if leaf_in_stage:
            leaf_final = parent + "/" + segs[-1]
            self.merge_move_into(leaf_in_stage, leaf_final)
        else:
            # 找不到叶子（leaf_rel 为空，或结构异常）：兜底把整个 staging 内容并入 parent
            leaf_final = parent
            self.merge_move_into(stage, parent)
        # 删掉整个中转目录（外壳 + 无关兄弟 + 广告）
        if self.dir_exists(stage):
            dr = self.delete_files([stage])
            if dr.get("taskid"):
                self.wait_task(dr["taskid"])
        return leaf_final

    # ---- 分享转存（骨架，Phase 2 实现）----
    @staticmethod
    def parse_share_link(link: str) -> dict:
        """解析分享链接，提取 surl 与（可能内嵌的）提取码。

        支持两种形式：
        - /s/1XXXX?pwd=yyyy （surl 在路径，带前导 1）
        - /share/init?surl=XXXX&pwd=yyyy （surl 在查询参数，无前导 1）
        """
        pwd = ""
        m = re.search(r"(?:pwd|passcode)=([0-9a-zA-Z]+)", link)
        if m:
            pwd = m.group(1)
        surl = ""
        m_q = re.search(r"[?&]surl=([0-9a-zA-Z_-]+)", link)
        if m_q:
            surl = m_q.group(1)
        else:
            m2 = re.search(r"/s/1?([0-9a-zA-Z_-]+)", link)
            if m2:
                surl = m2.group(1)
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

    # ---- 好友消息 / 群文件（mbox 网页私有接口）----
    # 注意：mbox 系列为百度网页端私有接口，字段可能随版本调整；
    # 解析处均做多字段兜底，实跑异常时看日志按返回结构微调。
    def _mbox_params(self, extra: Optional[dict] = None) -> dict:
        p = {
            "bdstoken": self.get_bdstoken(),
            "json": 1,
            "channel": "chunlei",
            "web": 1,
            "clienttype": 0,
            "app_id": 250528,
        }
        if extra:
            p.update(extra)
        return p

    def list_friends(self, page_size: int = 50) -> list[dict]:
        """好友（关注/粉丝）列表（自动翻页取全）：返回 [{uk, name, avatar}]。"""
        out: list[dict] = []
        start = 0
        for _ in range(200):  # 安全上限，防接口异常时死循环
            batch = self._friends_page(start, page_size)
            out.extend(batch)
            if len(batch) < page_size:
                break
            start += page_size
        return out

    def _friends_page(self, start: int, limit: int) -> list[dict]:
        r = self.s.get(
            "https://pan.baidu.com/mbox/relation/getfollowlist",
            params=self._mbox_params({"start": start, "limit": limit, "type": 2}),
            timeout=20,
        )
        d = r.json()
        if d.get("errno") not in (0, None):
            raise RuntimeError(_share_err(d.get("errno"), "获取好友列表失败"))
        out = []
        for it in d.get("records", []) or d.get("list", []):
            uk = it.get("uk") or it.get("friend_uk") or it.get("mbox_uk")
            if not uk:
                continue
            out.append(
                {
                    "uk": str(uk),
                    "name": it.get("uname") or it.get("nick_name")
                    or it.get("name") or f"用户{uk}",
                    "avatar": it.get("avatar_url") or it.get("avatar") or "",
                }
            )
        return out

    def list_friend_files(self, friend_uk: str, page: int = 1, num: int = 50) -> list[dict]:
        """与某好友的聊天记录里含文件的消息：返回 [{msg_id, from_uk, ctime, files}]。"""
        r = self.s.get(
            "https://pan.baidu.com/mbox/msg/getrecord",
            params=self._mbox_params(
                {"to_uk": friend_uk, "page": page, "num": num, "desc": 1}
            ),
            timeout=20,
        )
        d = r.json()
        if d.get("errno") not in (0, None):
            raise RuntimeError(_share_err(d.get("errno"), "获取聊天文件失败"))
        return _parse_msg_records(_msg_list(d.get("records")), default_from=friend_uk)

    def transfer_friend_files(
        self, from_uk: str, msg_id: str, fsidlist: list, target_dir: str
    ) -> dict:
        """把好友消息里的文件转存到 target_dir。"""
        r = self.s.post(
            "https://pan.baidu.com/mbox/msg/transfer",
            params=self._mbox_params(
                {"from_uk": from_uk, "msg_id": msg_id, "type": 2, "async": 1}
            ),
            data={
                "fsidlist": "[" + ",".join(str(x) for x in fsidlist) + "]",
                "path": target_dir,
                "ondup": "newcopy",
            },
            headers={"Referer": "https://pan.baidu.com/disk/main"},
            timeout=30,
        )
        return r.json()

    def list_groups(self, page_size: int = 50) -> list[dict]:
        """群组列表（自动翻页取全）：返回 [{gid, name, count}]。"""
        out: list[dict] = []
        start = 0
        for _ in range(200):  # 安全上限，防接口异常时死循环
            batch = self._groups_page(start, page_size)
            out.extend(batch)
            if len(batch) < page_size:
                break
            start += page_size
        return out

    def _groups_page(self, start: int, limit: int) -> list[dict]:
        r = self.s.get(
            "https://pan.baidu.com/mbox/group/list",
            params=self._mbox_params({"start": start, "limit": limit}),
            timeout=20,
        )
        d = r.json()
        if d.get("errno") not in (0, None):
            raise RuntimeError(_share_err(d.get("errno"), "获取群组列表失败"))
        out = []
        for it in d.get("records", []) or d.get("list", []):
            gid = it.get("gid") or it.get("group_id")
            if not gid:
                continue
            out.append(
                {
                    "gid": str(gid),
                    "name": it.get("name") or it.get("gname") or f"群{gid}",
                    "count": it.get("member_count") or it.get("count") or 0,
                }
            )
        return out

    def list_group_files(self, gid: str, limit: int = 50) -> list[dict]:
        """群里分享/发送的文件消息：返回 [{msg_id, from_uk, ctime, files}]。"""
        r = self.s.get(
            "https://pan.baidu.com/mbox/group/listshare",
            params=self._mbox_params({"gid": gid, "limit": limit, "type": 2, "desc": 1}),
            timeout=20,
        )
        d = r.json()
        if d.get("errno") not in (0, None):
            raise RuntimeError(_share_err(d.get("errno"), "获取群文件失败"))
        return _parse_msg_records(_msg_list(d.get("records")), default_from="")

    def list_msg_folder(
        self, from_uk: str, msg_id: str, fs_id, gid: str = "", page_size: int = 100
    ) -> list[dict]:
        """进入好友/群消息里某个共享文件夹，列它的子内容（可逐级深入）。

        用 mbox/msg/shareinfo：同一 msg_id 授权访问整棵共享目录树，
        fs_id 指定当前要展开的文件夹。返回 [{fs_id, server_filename, isdir, size, path}]。
        """
        out: list[dict] = []
        page = 1
        while page <= 200:
            extra = {
                "from_uk": from_uk,
                "msg_id": msg_id,
                "fs_id": fs_id,
                "type": 2,
                "num": page_size,
                "page": page,
                "limit": page_size,
                "desc": 1,
            }
            if gid:
                extra["gid"] = gid
            r = self.s.get(
                "https://pan.baidu.com/mbox/msg/shareinfo",
                params=self._mbox_params(extra),
                timeout=20,
            )
            d = r.json()
            if d.get("errno") not in (0, None):
                raise RuntimeError(_share_err(d.get("errno"), "读取文件夹失败"))
            recs = d.get("records") or []
            for f in recs:
                fs = f.get("fs_id")
                name = f.get("server_filename")
                if not fs or not name:
                    continue
                out.append(
                    {
                        "fs_id": int(fs) if str(fs).isdigit() else fs,
                        "server_filename": name,
                        "isdir": int(f.get("isdir") or 0),
                        "size": int(f.get("size") or 0),
                        "path": f.get("path", ""),
                    }
                )
            if not d.get("has_more"):
                break
            page += 1
        return out

    def transfer_group_files(
        self, gid: str, from_uk: str, msg_id: str, fsidlist: list, target_dir: str
    ) -> dict:
        """把群文件转存到 target_dir。

        群转存与好友转存共用 mbox/msg/transfer，仅多带一个 gid 参数。
        """
        extra = {"gid": gid, "msg_id": msg_id, "type": 2, "async": 1}
        if from_uk:
            extra["from_uk"] = from_uk
        r = self.s.post(
            "https://pan.baidu.com/mbox/msg/transfer",
            params=self._mbox_params(extra),
            data={
                "fsidlist": "[" + ",".join(str(x) for x in fsidlist) + "]",
                "path": target_dir,
                "ondup": "newcopy",
            },
            headers={"Referer": "https://pan.baidu.com/disk/home"},
            timeout=30,
        )
        return r.json()

    # ---- 统一转存协议（供 core/transfer.py provider 中立调用）----
    def open_share(self, link: str, pwd: str = "") -> dict:
        """打开分享：解析 → 校验提取码 → 列根目录文件，返回统一 meta。

        meta = {shareid, uk, ref, files:[{fs_id, server_filename, isdir}]}
        """
        parsed = self.parse_share_link(link)
        surl = parsed["surl"]
        pwd = pwd or parsed["pwd"]
        if not surl:
            raise RuntimeError("分享链接解析失败")
        if pwd:
            self.verify_share_pwd(surl, pwd)
        return self.get_share_meta(surl)

    def share_key(self, meta: dict, f: dict) -> str:
        return f"{meta['shareid']}_{f['fs_id']}"

    def resolve_target(self, target_dir: str) -> str:
        """确保目标目录存在，返回目录路径（百度直接用路径定位）。"""
        target = target_dir or "/"
        if target != "/":
            try:
                self.ensure_dir(target)
            except Exception:  # noqa: BLE001
                pass
        return target

    def save_files(self, meta: dict, files: list[dict], target_ref: str) -> dict:
        """转存指定文件到 target_ref，返回 {"error": str|None}。"""
        fsidlist = [f["fs_id"] for f in files]
        try:
            res = self.transfer_files(
                meta["shareid"], meta["uk"], fsidlist, target_ref, meta["ref"]
            )
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        errno = res.get("errno")
        if errno not in (0, None):
            return {"error": _share_err(errno, "转存失败")}
        return {"error": None}

    def rename_in_dir(self, target_ref: str, old_name: str, new_name: str) -> None:
        """转存后按文件名改名（target_ref 为目录路径）。"""
        self.rename(_join_path(target_ref, old_name), new_name)

    def rename_item(self, item: dict, newname: str) -> dict:
        """按列目录项改名（批量重命名页用）。"""
        path = item.get("path")
        if not path:
            return {"error": "缺少文件路径"}
        try:
            res = self.rename(path, newname)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        errno = res.get("errno")
        return {"error": None if errno in (0, None) else _share_err(errno, "改名失败")}


def _join_path(target_dir: str, name: str) -> str:
    if target_dir.endswith("/"):
        return target_dir + name
    return target_dir + "/" + name


def _result_dict(data) -> dict:
    """取百度接口的 result 字段。未登录时百度返回 result:[]（list），需兜底成 {}。"""
    if isinstance(data, dict):
        res = data.get("result")
        if isinstance(res, dict):
            return res
    return {}


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


def _msg_list(records) -> list:
    """把 mbox 的 records 归一成消息列表。

    群接口返回 {"msg_count":N, "msg_list":[...]}；有的接口直接是列表。
    """
    if isinstance(records, dict):
        return records.get("msg_list") or records.get("list") or []
    if isinstance(records, list):
        return records
    return []


def _parse_msg_records(records, default_from: str = "") -> list[dict]:
    """把 mbox 消息记录解析成含文件的消息列表。

    只保留带文件的消息；每条 = {msg_id, from_uk, ctime, files:[...]}。
    百度不同接口的文件字段名不统一，这里做多路兜底。
    """
    out = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        msg_id = rec.get("msg_id") or rec.get("id") or rec.get("mid")
        from_uk = rec.get("from_uk") or rec.get("uk") or rec.get("sender_uk") or default_from
        ctime = (
            rec.get("ctime") or rec.get("time") or rec.get("create_time")
            or rec.get("msg_ctime") or 0
        )
        ctime = int(ctime) if str(ctime).isdigit() else 0
        if ctime > 10**12:  # 毫秒 → 秒
            ctime //= 1000

        raw_files = _extract_file_list(rec)
        files = []
        for f in raw_files:
            if not isinstance(f, dict):
                continue
            fs_id = f.get("fs_id") or f.get("fsid") or f.get("fid")
            name = f.get("server_filename") or f.get("filename") or f.get("name")
            if not fs_id or not name:
                continue
            files.append(
                {
                    "fs_id": int(fs_id) if str(fs_id).isdigit() else fs_id,
                    "server_filename": name,
                    "isdir": int(f.get("isdir") or 0),
                    "size": int(f.get("size") or 0),
                    "path": f.get("path", ""),
                }
            )
        if not files or not msg_id:
            continue
        out.append(
            {
                "msg_id": str(msg_id),
                "from_uk": str(from_uk) if from_uk else "",
                "ctime": int(ctime) if str(ctime).isdigit() else 0,
                "files": files,
            }
        )
    return out


def _extract_file_list(rec: dict) -> list:
    """从一条消息里挖出文件数组（兼容 filelist / file_list / content JSON）。"""
    for key in ("filelist", "file_list", "files"):
        val = rec.get(key)
        if isinstance(val, list):
            return val
        if isinstance(val, dict) and isinstance(val.get("list"), list):
            return val["list"]
    # 有的接口把文件塞在 content / msg 的 JSON 字符串里
    for key in ("content", "msg", "message"):
        val = rec.get(key)
        if isinstance(val, str) and val.strip().startswith("{"):
            try:
                obj = json.loads(val)
            except (json.JSONDecodeError, ValueError):
                continue
            inner = obj.get("file_list") or obj.get("filelist") or obj.get("list")
            if isinstance(inner, list):
                return inner
    return []


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
    if not acc or acc.get("provider", "baidu") != "baidu" or not acc.get("cookies"):
        return None
    return BaiduPanClient(acc["cookies"])


def get_active_client() -> Optional["BaiduPanClient"]:
    """当前活跃账号的客户端；未登录返回 None。"""
    acc = db.get_active_account()
    if not acc or acc.get("provider", "baidu") != "baidu" or not acc.get("cookies"):
        return None
    return BaiduPanClient(acc["cookies"])


# 兼容旧调用
def get_client() -> Optional["BaiduPanClient"]:
    return get_active_client()
