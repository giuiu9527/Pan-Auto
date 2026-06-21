"""百度网盘扫码登录。

复用业界通行的 passport 扫码流程（手机百度网盘 App 扫码确认），
登录成功后拿到 BDUSS / STOKEN 等 Cookie。

注意：这些是百度网页端私有接口，百度可能调整参数；若失效，
在 设置页 可改用「手动粘贴 Cookie」兜底。
"""
import time
import random
import re
import json
from dataclasses import dataclass
from typing import Optional

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _gid() -> str:
    tpl = "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx"
    out = []
    for ch in tpl:
        if ch in "xy":
            r = random.randint(0, 15)
            v = r if ch == "x" else (r & 0x3) | 0x8
            out.append("0123456789ABCDEF"[v])
        else:
            out.append(ch)
    return "".join(out)


def _jsonp(text: str) -> dict:
    """从 jsonp 响应里抽出 JSON。"""
    m = re.search(r"\((\{.*\})\)", text, re.S)
    if not m:
        m = re.search(r"(\{.*\})", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


@dataclass
class QrSession:
    sign: str          # channel_id，用于轮询
    imgurl: str        # 二维码图片完整 URL
    gid: str


class BaiduQrLogin:
    """一次扫码登录会话。"""

    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Referer": "https://pan.baidu.com/"})
        self.gid = _gid()

    def get_qrcode(self) -> QrSession:
        ts = int(time.time() * 1000)
        params = {
            "lp": "pc",
            "qrloginfrom": "pc",
            "gid": self.gid,
            "callback": f"tangram_guid_{ts}",
            "apiver": "v3",
            "tt": ts,
            "tpl": "netdisk",
            "_": ts,
        }
        r = self.s.get(
            "https://passport.baidu.com/v2/api/getqrcode",
            params=params,
            timeout=15,
        )
        data = _jsonp(r.text)
        sign = data.get("sign", "")
        imgurl = data.get("imgurl", "")
        if not sign or not imgurl:
            raise RuntimeError("获取二维码失败，接口可能已变更")
        if not imgurl.startswith("http"):
            imgurl = "https://" + imgurl
        return QrSession(sign=sign, imgurl=imgurl, gid=self.gid)

    def fetch_qr_image(self, imgurl: str) -> bytes:
        return self.s.get(imgurl, timeout=15).content

    def poll(self, sign: str) -> dict:
        """轮询一次扫码状态。

        返回 {"state": "waiting"|"scanned"|"confirmed", "v": <bduss>}
        """
        ts = int(time.time() * 1000)
        params = {
            "channel_id": sign,
            "gid": self.gid,
            "tpl": "netdisk",
            "_sdkFrom": "1",
            "callback": f"tangram_guid_{ts}",
            "apiver": "v3",
            "tt": ts,
            "_": ts,
        }
        r = self.s.get(
            "https://passport.baidu.com/channel/unicast",
            params=params,
            timeout=20,
        )
        data = _jsonp(r.text)
        ch = data.get("channel_v")
        if isinstance(ch, str):
            try:
                ch = json.loads(ch)
            except json.JSONDecodeError:
                ch = {}
        ch = ch or {}
        status = ch.get("status")
        if status == 1:
            return {"state": "scanned"}
        if status == 0 and ch.get("v"):
            return {"state": "confirmed", "v": ch["v"]}
        return {"state": "waiting"}

    def finish(self, bduss_v: str) -> dict:
        """用扫码确认得到的 v 换取正式登录 Cookie，返回 cookies dict。"""
        ts = int(time.time() * 1000)
        params = {
            "v": ts,
            "u": "https://pan.baidu.com/disk/home",
            "loginVersion": "v4",
            "qrcode": "1",
            "tpl": "netdisk",
            "apiver": "v3",
            "tt": ts,
            "bduss": bduss_v,
            "_": ts,
        }
        self.s.get(
            "https://passport.baidu.com/v3/login/main/qrbdusslogin",
            params=params,
            timeout=15,
        )
        # 访问一次网盘首页，补全 STOKEN 等 Cookie
        self.s.get("https://pan.baidu.com/disk/home", timeout=15)
        cookies = self.s.cookies.get_dict()
        if "BDUSS" not in cookies:
            raise RuntimeError("登录未完成：未取得 BDUSS")
        return cookies
