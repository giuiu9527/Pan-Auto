"""广告关键词匹配（全工程唯一实现：自动同步、广告清理页、百度清理递归、外部桥接都用它）。

以前每处各写一份 `k.lower() in name.lower()`，字符稍有出入就匹配不上：
  - 全角 / 半角：名字里是「：」「Ｖ」，关键词是 ":"、"V"
  - 空格 / 零宽字符：「家瘦猴 V」「家瘦猴​V」
  - 大写 I / 小写 l / 数字 1 / 竖线 |：广告群号常用这几个字符互相替换，眼睛看是一样的，
    例如名字里是 `lxwx2653`，抄关键词时写成 `Ixwx2653`
所以匹配统一做两路比较，任一路命中即视为命中：
  1. 精确路：NFKC 归一 + 去空白/零宽 + 忽略大小写（与旧逻辑兼容，旧能命中的现在一定命中）
  2. 容错路：在 1 的基础上，把 I / l / 1 / | 视为同一个字符再比
"""
import re
import unicodedata

# 大小写折叠之前先把「长得像竖线」的字符并成小写 l，再统一 lower()
_CONFUSABLE = str.maketrans({"I": "l", "1": "l", "|": "l", "ǀ": "l", "ｌ": "l", "Ｉ": "l"})


def parse_keywords(raw: str) -> list[str]:
    """一行一个或用逗号分隔。"""
    return [k.strip() for k in re.split(r"[\n,，]", raw or "") if k.strip()]


def _strip_invisible(text: str) -> str:
    # 去掉所有空白（Zs/Zl/Zp 与控制类）以及零宽等格式字符（Cf）
    return "".join(
        ch for ch in text
        if not ch.isspace() and unicodedata.category(ch) not in ("Cf", "Cc", "Zs", "Zl", "Zp")
    )


def normalize(text: str) -> str:
    """精确路：NFKC + 去空白/零宽 + 忽略大小写。"""
    return _strip_invisible(unicodedata.normalize("NFKC", text or "")).casefold()


def fold(text: str) -> str:
    """容错路：先把 I / 1 / | 并成 l（在小写化之前，否则 I 会先变成 i），再走精确路。"""
    nfkc = unicodedata.normalize("NFKC", text or "").translate(_CONFUSABLE)
    return _strip_invisible(nfkc).casefold()


def contains_any(name: str, keywords: list[str]) -> bool:
    """文件名是否含有任一关键词（精确路或容错路命中即可）。"""
    if not name or not keywords:
        return False
    n_exact, n_fold = normalize(name), fold(name)
    for k in keywords:
        ke, kf = normalize(k), fold(k)
        if not ke:
            continue
        if ke in n_exact or kf in n_fold:
            return True
    return False


def signature(ad_kw: list[str], whitelist: list[str] | None = None,
              action: str = "skip", text: str = "") -> str:
    """关键词 + 白名单 + 处理方式的指纹：任一变了就变，用来判断「该把新设置应用到已有文件上」。"""
    import hashlib

    body = "\n".join(sorted({normalize(k) for k in ad_kw if k})) + "\n||\n" + \
        "\n".join(sorted({normalize(k) for k in (whitelist or []) if k}))
    if action != "skip":                      # 兼容：跳过模式的指纹和以前一样，升级后不会误触发
        body += f"\n||{action}||{text}"
    return hashlib.sha1(body.encode("utf-8")).hexdigest()


# ---- 命中广告后的处理方式 ----
ACTION_SKIP = "skip"          # 不转存（已在网盘里的会被删除）
ACTION_REPLACE = "replace"    # 把名字里命中的词替换成指定内容
ACTION_RENAME = "rename"      # 整个名字改成指定内容（文件保留扩展名）
ACTIONS = (ACTION_SKIP, ACTION_REPLACE, ACTION_RENAME)

_ZW = "[\\s​‌‍⁠﻿]*"         # 关键词字符之间允许的空白 / 零宽字符
_CONFUSABLE_GROUP = "Il1|ǀｌＩ"
_ILLEGAL = re.compile(r'[\\/:*?"<>|]')               # 百度网盘文件名不允许的字符（半角）


def _char_class(ch: str) -> str:
    """关键词里一个字符 → 正则字符类：大小写、全角/半角、I/l/1/| 混写都能匹配上。"""
    if ch in _CONFUSABLE_GROUP:
        variants = set(_CONFUSABLE_GROUP)
    else:
        variants = {ch, ch.lower(), ch.upper()}
    for v in list(variants):
        if "!" <= v <= "~":                            # 半角 ASCII → 加上全角写法
            variants.add(chr(ord(v) + 0xFEE0))
    return "[" + "".join(re.escape(v) for v in sorted(variants)) + "]"


def _keyword_regex(keyword: str):
    chars = _strip_invisible(unicodedata.normalize("NFKC", keyword or ""))
    if not chars:
        return None
    return re.compile(_ZW.join(_char_class(c) for c in chars))


def _clean_name(name: str) -> str:
    name = _ILLEGAL.sub("_", name or "").strip().strip(".").strip()
    return name


def replace_keywords(name: str, keywords: list[str], repl: str) -> str:
    """把名字里命中的关键词（宽松匹配）替换成 repl；长的关键词先替换，避免被短词截断。"""
    out = name
    for k in sorted({k for k in keywords if k}, key=len, reverse=True):
        rx = _keyword_regex(k)
        if rx is not None:
            out = rx.sub(lambda _m: repl, out)
    return out


def ad_target_name(name: str, isdir: bool, ad_kw: list[str], whitelist: list[str] | None,
                   action: str, text: str):
    """命中广告时该怎么处理：返回 None = 不是广告；"" = 跳过；其它 = 改成这个名字。"""
    if not ad_kw or not is_ad_to_remove(name, ad_kw, whitelist):
        return None
    if action == ACTION_REPLACE:
        raw = replace_keywords(name, ad_kw, text or "")
        stem, dot, _ext = raw.strip().rpartition(".")
        if not isdir and dot and not stem.strip():     # 只剩下 ".jpg" 这种 → 没有可用的名字
            return ""
        new = _clean_name(raw)
    elif action == ACTION_RENAME:
        new = _clean_name(text or "")
        if new and not isdir:
            _stem, dot, ext = name.rpartition(".")
            if dot and _stem and 0 < len(ext) <= 8 and " " not in ext and not new.lower().endswith("." + ext.lower()):
                new = f"{new}.{ext}"
    else:
        return ""
    return new or ""                                    # 替换完是空的 → 只能跳过


def is_ad_to_remove(name: str, ad_kw: list[str], whitelist: list[str] | None = None) -> bool:
    """是否应作为广告清理/跳过：命中广告词、且未命中白名单。"""
    if whitelist and contains_any(name, whitelist):
        return False
    return contains_any(name, ad_kw)
