"""关键字重命名规则引擎。

规则按顺序作用于文件名（不含路径）。支持的规则类型：

    replace  : 把 pattern 替换为 replacement（普通文本）
    remove   : 删除所有 pattern（等价于 replace -> ""）
    regex    : 用正则 pattern 替换为 replacement
    prefix   : 在名字前加 replacement
    suffix   : 在扩展名前加 replacement（保留后缀）

每条规则是 dict：{rule_type, pattern, replacement, enabled}
"""
import os
import re
from typing import Iterable

RULE_TYPES = {
    "replace": "替换文本",
    "remove": "删除关键字",
    "regex": "正则替换",
    "prefix": "添加前缀",
    "suffix": "添加后缀",
}


def apply_rule(name: str, rule: dict) -> str:
    if not rule.get("enabled", 1):
        return name
    rtype = rule.get("rule_type")
    pattern = rule.get("pattern", "") or ""
    repl = rule.get("replacement", "") or ""

    if rtype == "replace":
        if not pattern:
            return name
        return name.replace(pattern, repl)
    if rtype == "remove":
        if not pattern:
            return name
        return name.replace(pattern, "")
    if rtype == "regex":
        if not pattern:
            return name
        try:
            return re.sub(pattern, repl, name)
        except re.error:
            return name
    if rtype == "prefix":
        return repl + name
    if rtype == "suffix":
        stem, ext = os.path.splitext(name)
        return stem + repl + ext
    return name


def apply_rules(name: str, rules: Iterable[dict]) -> str:
    """依次应用规则，返回新文件名。空结果时回退为原名以防丢失。"""
    new = name
    for rule in rules:
        new = apply_rule(new, rule)
    new = new.strip()
    return new or name


def preview(names: Iterable[str], rules: list[dict]) -> list[tuple[str, str]]:
    """返回 (原名, 新名) 列表，便于 UI 预览。"""
    return [(n, apply_rules(n, rules)) for n in names]
