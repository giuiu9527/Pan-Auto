"""Git-based self updater.

For source deployments, Pan-Auto can update itself by fetching the configured
Git remote, fast-forwarding the current branch, and restarting the process.
Private GitHub repositories should be authenticated by Git Credential Manager
or another user-level Git credential helper, not by storing tokens in this app.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REMOTE = os.environ.get("PAN_AUTO_UPDATE_REMOTE", "origin")


def _run_git(args: list[str], timeout: int = 60) -> tuple[bool, str]:
    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=flags,
        )
    except FileNotFoundError:
        return False, "未找到 Git，请先安装 Git for Windows"
    except subprocess.TimeoutExpired:
        return False, "Git 操作超时，请检查网络或私有库登录状态"
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    return p.returncode == 0, out or err


def is_git_repo() -> bool:
    ok, out = _run_git(["rev-parse", "--is-inside-work-tree"], timeout=10)
    return ok and out.strip().lower() == "true"


def check_for_update() -> dict:
    """Return update state without changing local files."""
    if os.environ.get("PAN_AUTO_DISABLE_UPDATE") == "1":
        return {"ok": False, "code": "disabled", "message": "已禁用更新检查"}
    if not is_git_repo():
        return {"ok": False, "code": "not_git", "message": "当前目录不是 Git 仓库"}

    ok, branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], timeout=10)
    if not ok or branch == "HEAD":
        branch = "main"

    ok, remote_url = _run_git(["remote", "get-url", REMOTE], timeout=10)
    if not ok:
        return {
            "ok": False,
            "code": "no_remote",
            "message": f"未配置远程仓库 {REMOTE}",
        }

    ok, fetch_msg = _run_git(["fetch", "--quiet", REMOTE], timeout=90)
    if not ok:
        return {
            "ok": False,
            "code": "fetch_failed",
            "message": fetch_msg or "拉取远程更新失败",
            "remote_url": remote_url,
        }

    ok, local_sha = _run_git(["rev-parse", "HEAD"], timeout=10)
    if not ok:
        return {"ok": False, "code": "bad_head", "message": local_sha}

    upstream = f"{REMOTE}/{branch}"
    ok, remote_sha = _run_git(["rev-parse", upstream], timeout=10)
    if not ok:
        return {
            "ok": False,
            "code": "bad_upstream",
            "message": f"远程分支不存在：{upstream}",
            "branch": branch,
            "remote_url": remote_url,
        }

    ok, counts = _run_git(["rev-list", "--left-right", "--count", f"HEAD...{upstream}"], timeout=10)
    if not ok:
        return {"ok": False, "code": "compare_failed", "message": counts}
    parts = counts.split()
    ahead = int(parts[0]) if parts else 0
    behind = int(parts[1]) if len(parts) > 1 else 0

    return {
        "ok": True,
        "code": "ok",
        "has_update": behind > 0,
        "ahead": ahead,
        "behind": behind,
        "branch": branch,
        "upstream": upstream,
        "remote_url": remote_url,
        "local_sha": local_sha[:8],
        "remote_sha": remote_sha[:8],
        "message": "发现更新" if behind > 0 else "已是最新版本",
    }


def apply_update() -> dict:
    """Fast-forward current branch from configured remote."""
    state = check_for_update()
    if not state.get("ok"):
        return state
    if not state.get("has_update"):
        return {**state, "updated": False, "message": "已是最新版本"}
    if state.get("ahead", 0) > 0:
        return {
            **state,
            "ok": False,
            "code": "local_ahead",
            "message": "本地有未推送提交，已停止自动更新",
        }

    ok, msg = _run_git(["pull", "--ff-only", REMOTE, state["branch"]], timeout=120)
    if not ok:
        return {**state, "ok": False, "code": "pull_failed", "message": msg}
    return {**state, "updated": True, "message": msg or "更新完成"}


def restart_app() -> tuple[bool, str]:
    """Start a fresh process with the current argv."""
    try:
        if getattr(sys, "frozen", False):
            args = [sys.executable]
        else:
            args = [sys.executable, *sys.argv]
        flags = 0
        if sys.platform == "win32":
            flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(args, cwd=str(ROOT), close_fds=True, creationflags=flags)
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, str(e)
