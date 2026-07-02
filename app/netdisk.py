"""Provider-neutral netdisk client helpers."""
from __future__ import annotations

from typing import Optional

from app import db
from app.baidu.client import BaiduPanClient
from app.quark.client import QuarkPanClient

PROVIDER_LABELS = {
    "baidu": "百度网盘",
    "quark": "夸克网盘",
}


def provider_label(provider: str | None) -> str:
    return PROVIDER_LABELS.get(provider or "baidu", provider or "百度网盘")


def get_client_for_account(account_id: Optional[int]):
    if account_id is None:
        acc = db.get_active_account()
    else:
        acc = db.get_account(account_id)
    if not acc or not acc.get("cookies"):
        return None
    provider = acc.get("provider") or "baidu"
    if provider == "quark":
        return QuarkPanClient(acc["cookies"])
    return BaiduPanClient(acc["cookies"])


def account_display_name(acc: dict) -> str:
    name = acc.get("username") or provider_label(acc.get("provider"))
    return f"{provider_label(acc.get('provider'))} · {name}"
