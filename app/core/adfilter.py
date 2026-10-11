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


def signature(ad_kw: list[str], whitelist: list[str] | None = None) -> str:
    """关键词 + 白名单的指纹：词表变了就变，用来判断「该把新词应用到已有文件上」。"""
    import hashlib

    body = "\n".join(sorted({normalize(k) for k in ad_kw if k})) + "\n||\n" + \
        "\n".join(sorted({normalize(k) for k in (whitelist or []) if k}))
    return hashlib.sha1(body.encode("utf-8")).hexdigest()


def is_ad_to_remove(name: str, ad_kw: list[str], whitelist: list[str] | None = None) -> bool:
    """是否应作为广告清理/跳过：命中广告词、且未命中白名单。"""
    if whitelist and contains_any(name, whitelist):
        return False
    return contains_any(name, ad_kw)
