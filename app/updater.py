"""Self updater.

Source deployments update through Git. Frozen Windows release builds update by
downloading the latest GitHub Release zip, starting an external updater script,
and quitting so files can be replaced safely.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from app.config import APP_NAME, APP_VERSION, DATA_DIR


if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parents[1]

REMOTE = os.environ.get("PAN_AUTO_UPDATE_REMOTE", "origin")
# 打包版查 Release 用「公开发布库」（源码库私有，普通用户免登录即可下更新）；
# 源码版更新走 git origin（私有源码库，开发者本机有凭据）。
GITHUB_REPO = os.environ.get("PAN_AUTO_GITHUB_REPO", "loadingkuu/Pan-Auto-release")
GITHUB_TOKEN_ENV = "PAN_AUTO_GITHUB_TOKEN"
ASSET_PATTERN = re.compile(r"Pan-Auto-.*windows-x64\.zip$", re.IGNORECASE)


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
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=flags,
            stdin=subprocess.DEVNULL,  # 无控制台打包版必须关 stdin，否则子进程卡死
        )
    except FileNotFoundError:
        return False, "未找到 Git，请先安装 Git for Windows"
    except subprocess.TimeoutExpired:
        return False, "Git 操作超时，请检查网络或私有库登录状态"
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    return p.returncode == 0, out or err


def _run_gh(args: list[str], timeout: int = 90) -> tuple[bool, str]:
    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run(
            ["gh", *args],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=flags,
            stdin=subprocess.DEVNULL,  # 无控制台打包版必须关 stdin，否则子进程卡死
        )
    except FileNotFoundError:
        return False, "未找到 GitHub CLI，请安装 gh 或设置 PAN_AUTO_GITHUB_TOKEN"
    except subprocess.TimeoutExpired:
        return False, "GitHub 请求超时，请检查网络"
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    return p.returncode == 0, out or err


def _version_tuple(version: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", version or "")
    return tuple(int(x) for x in nums) if nums else (0,)


def _is_newer(remote: str, current: str) -> bool:
    return _version_tuple(remote) > _version_tuple(current)


def _parse_policy(body: str) -> dict:
    policy: dict[str, str] = {}
    for line in (body or "").splitlines():
        line = line.strip().strip("`")
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().upper()
        value = value.strip()
        if key.startswith("PAN_AUTO_"):
            policy[key] = value
    return policy


def _asset_from_release(release: dict) -> dict | None:
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if ASSET_PATTERN.search(name):
            return asset
    return None


def _latest_release_via_gh() -> tuple[bool, dict | str]:
    ok, out = _run_gh(
        [
            "release",
            "view",
            "--repo",
            GITHUB_REPO,
            "--json",
            "tagName,name,body,url,assets,isDraft,isPrerelease,publishedAt",
        ]
    )
    if not ok:
        return False, out
    try:
        return True, json.loads(out)
    except json.JSONDecodeError as e:
        return False, f"解析 GitHub Release 信息失败：{e}"


def _github_headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{APP_NAME}/{APP_VERSION}",
    }
    token = os.environ.get(GITHUB_TOKEN_ENV, "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _latest_release_via_api() -> tuple[bool, dict | str]:
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(url, headers=_github_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return False, f"读取 GitHub Release 失败：{e}"


def _latest_release() -> tuple[bool, dict | str, str]:
    # 公开发布库：优先匿名 HTTP API（快、无需 gh 子进程，避免打包版卡住）；
    # gh 仅作兜底（私有仓库或 API 被限流时）。
    ok, data = _latest_release_via_api()
    if ok:
        return True, data, "api"
    api_msg = str(data)
    ok, data = _latest_release_via_gh()
    if ok:
        return True, data, "gh"
    return False, f"{api_msg}\n{data}", ""


def is_git_repo() -> bool:
    ok, out = _run_git(["rev-parse", "--is-inside-work-tree"], timeout=10)
    return ok and out.strip().lower() == "true"


def check_for_update() -> dict:
    """Return update state without changing local files."""
    if os.environ.get("PAN_AUTO_DISABLE_UPDATE") == "1":
        return {"ok": False, "code": "disabled", "message": "已禁用更新检查"}
    if getattr(sys, "frozen", False) or not is_git_repo():
        return check_release_update()
    return check_git_update()


def check_git_update() -> dict:
    """Check source deployment updates through Git."""
    if not is_git_repo():
        return {"ok": False, "kind": "git", "code": "not_git", "message": "当前目录不是 Git 仓库"}

    ok, branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], timeout=10)
    if not ok or branch == "HEAD":
        branch = "main"

    ok, remote_url = _run_git(["remote", "get-url", REMOTE], timeout=10)
    if not ok:
        return {
            "ok": False,
            "kind": "git",
            "code": "no_remote",
            "message": f"未配置远程仓库 {REMOTE}",
        }

    ok, fetch_msg = _run_git(["fetch", "--quiet", REMOTE], timeout=90)
    if not ok:
        return {
            "ok": False,
            "kind": "git",
            "code": "fetch_failed",
            "message": fetch_msg or "拉取远程更新失败",
            "remote_url": remote_url,
        }

    ok, local_sha = _run_git(["rev-parse", "HEAD"], timeout=10)
    if not ok:
        return {"ok": False, "kind": "git", "code": "bad_head", "message": local_sha}

    upstream = f"{REMOTE}/{branch}"
    ok, remote_sha = _run_git(["rev-parse", upstream], timeout=10)
    if not ok:
        return {
            "ok": False,
            "kind": "git",
            "code": "bad_upstream",
            "message": f"远程分支不存在：{upstream}",
            "branch": branch,
            "remote_url": remote_url,
        }

    ok, counts = _run_git(["rev-list", "--left-right", "--count", f"HEAD...{upstream}"], timeout=10)
    if not ok:
        return {"ok": False, "kind": "git", "code": "compare_failed", "message": counts}
    parts = counts.split()
    ahead = int(parts[0]) if parts else 0
    behind = int(parts[1]) if len(parts) > 1 else 0

    return {
        "ok": True,
        "kind": "git",
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


def check_release_update() -> dict:
    """Check frozen release updates through GitHub Releases."""
    ok, release_or_msg, source = _latest_release()
    if not ok:
        return {
            "ok": False,
            "kind": "release",
            "code": "release_check_failed",
            "message": str(release_or_msg),
        }

    release = release_or_msg
    tag = release.get("tagName") or release.get("tag_name") or ""
    latest_version = tag.upper().replace("V", "V", 1)
    asset = _asset_from_release(release)
    body = release.get("body", "") or ""
    policy = _parse_policy(body)
    force_below = policy.get("PAN_AUTO_FORCE_BELOW") or policy.get("PAN_AUTO_MIN_SUPPORTED")
    force_update = bool(force_below and _version_tuple(APP_VERSION) < _version_tuple(force_below))
    has_update = _is_newer(latest_version, APP_VERSION)

    if not asset and has_update:
        return {
            "ok": False,
            "kind": "release",
            "code": "asset_missing",
            "message": "发现新版本，但 Release 中没有 Windows x64 运行包",
            "release_url": release.get("url", ""),
        }

    return {
        "ok": True,
        "kind": "release",
        "code": "ok",
        "has_update": has_update,
        "force_update": force_update,
        "force_below": force_below or "",
        "current_version": APP_VERSION,
        "latest_version": latest_version,
        "tag_name": tag,
        "release_name": release.get("name", tag),
        "release_url": release.get("url", ""),
        "asset_name": asset.get("name", "") if asset else "",
        "asset_size": asset.get("size", 0) if asset else 0,
        "asset_url": asset.get("url") or asset.get("apiUrl", "") if asset else "",
        "browser_download_url": asset.get("browser_download_url", "") if asset else "",
        "source": source,
        "message": "发现新版本" if has_update else "已是最新版本",
    }


def apply_update() -> dict:
    """Apply update for the current deployment type."""
    if getattr(sys, "frozen", False) or not is_git_repo():
        return apply_release_update()
    return apply_git_update()


def apply_git_update() -> dict:
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


def apply_release_update() -> dict:
    """Download latest release zip and launch the external replacement script."""
    state = check_release_update()
    if not state.get("ok"):
        return state
    if not state.get("has_update"):
        return {**state, "updated": False, "message": "已是最新版本"}
    if sys.platform != "win32":
        return {**state, "ok": False, "code": "unsupported_platform", "message": "打包版自动替换目前仅支持 Windows"}

    ok, zip_path_or_msg = download_release_asset(state)
    if not ok:
        return {**state, "ok": False, "code": "download_failed", "message": zip_path_or_msg}

    ok, msg = launch_windows_replacer(Path(zip_path_or_msg))
    if not ok:
        return {**state, "ok": False, "code": "replace_failed", "message": msg}
    return {
        **state,
        "updated": True,
        "restart_managed": True,
        "downloaded_path": str(zip_path_or_msg),
        "message": "更新包已下载，关闭软件后将自动替换并重启",
    }


def download_release_asset(state: dict, progress_cb=None) -> tuple[bool, str]:
    """下载更新包。progress_cb(downloaded_bytes, total_bytes) 用于报告进度。"""
    updates_dir = DATA_DIR / "updates"
    updates_dir.mkdir(parents=True, exist_ok=True)
    asset_name = state.get("asset_name") or f"Pan-Auto-{state.get('tag_name', 'latest')}-windows-x64.zip"
    target = updates_dir / asset_name

    token = os.environ.get(GITHUB_TOKEN_ENV, "").strip()
    errors = []

    # 1) 公开发布库：匿名直链下载（无需 gh 子进程 / token），快且稳
    for url, need_token in _download_candidates(state, token):
        headers = {
            "User-Agent": f"{APP_NAME}/{APP_VERSION}",
            "Accept": "application/octet-stream",
        }
        if need_token and token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=300) as r, target.open("wb") as f:
                total = int(r.headers.get("Content-Length", 0) or 0)
                downloaded = 0
                while True:
                    chunk = r.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(downloaded, total)
            if target.exists() and target.stat().st_size > 0:
                return True, str(target)
            errors.append("下载内容为空")
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))

    # 2) 兜底：gh（私有库或直链失败时）
    ok, msg = _run_gh(
        [
            "release", "download", state["tag_name"],
            "--repo", GITHUB_REPO, "--pattern", asset_name,
            "--dir", str(updates_dir), "--clobber",
        ],
        timeout=300,
    )
    if ok and target.exists():
        return True, str(target)
    if msg:
        errors.append(msg)

    detail = "; ".join(str(e) for e in errors if e)
    return False, f"下载更新包失败：{detail or '未找到可用下载地址'}"


def _download_candidates(state: dict, token: str) -> list[tuple[str, bool]]:
    """按优先级返回 (下载地址, 是否需要 token)。公开直链优先、免登录。"""
    cands: list[tuple[str, bool]] = []
    bdl = state.get("browser_download_url") or ""
    au = state.get("asset_url") or ""
    # 公开发布直链 github.com/<repo>/releases/download/...：任何人可下，免登录
    if bdl:
        cands.append((bdl, False))
    if au and "/releases/download/" in au:
        cands.append((au, False))
    # API 资产直链 api.github.com/.../assets/<id>：私有库需 token
    if au and "api.github.com" in au:
        cands.append((au, True))
    return cands


def launch_windows_replacer(zip_path: Path) -> tuple[bool, str]:
    exe = Path(sys.executable).resolve()
    install_dir = exe.parent
    if not exe.exists() or exe.suffix.lower() != ".exe":
        return False, "当前程序不是可替换的 Windows exe"
    if not (install_dir / exe.name).exists():
        return False, "安装目录校验失败"
    if not (install_dir / "_internal").exists():
        return False, "未找到 _internal 目录，当前不是标准运行包结构"

    script = DATA_DIR / "updates" / f"apply-update-{int(time.time())}.ps1"
    script.write_text(_windows_replacer_script(), encoding="utf-8")
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return False, "未找到 PowerShell，无法自动替换运行包"

    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-Zip",
            str(zip_path),
            "-InstallDir",
            str(install_dir),
            "-ExeName",
            exe.name,
            "-PidToWait",
            str(os.getpid()),
        ],
        cwd=str(install_dir),
        close_fds=True,
        creationflags=flags,
    )
    return True, "外部更新器已启动"


def _windows_replacer_script() -> str:
    return r'''
param(
    [Parameter(Mandatory=$true)][string]$Zip,
    [Parameter(Mandatory=$true)][string]$InstallDir,
    [Parameter(Mandatory=$true)][string]$ExeName,
    [Parameter(Mandatory=$true)][int]$PidToWait
)

$marker = Join-Path $InstallDir $ExeName
$internal = Join-Path $InstallDir "_internal"
$logDir = Split-Path -Parent $Zip
$log = Join-Path $logDir "update.log"
function Log($m) { try { Add-Content -LiteralPath $log -Value ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $m) } catch {} }
function Restart() { try { Start-Process -FilePath $marker -WorkingDirectory $InstallDir; Log "restarted" } catch { Log ("restart failed: " + $_) } }

Log ("updater start pid=" + $PidToWait + " dir=" + $InstallDir)

# 1. 等主进程退出 + 杀残留子进程（WebView2 等），释放文件占用
Wait-Process -Id $PidToWait -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 1200
Get-Process -Name msedgewebview2 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
try {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.ToLower().StartsWith($InstallDir.ToLower()) } |
        ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }
} catch {}
Start-Sleep -Milliseconds 800

# 2. 解压
$workRoot = Join-Path $logDir ("stage-" + [guid]::NewGuid().ToString("N"))
try {
    New-Item -ItemType Directory -Path $workRoot -Force | Out-Null
    Expand-Archive -LiteralPath $Zip -DestinationPath $workRoot -Force
} catch {
    Log ("unzip failed: " + $_); Restart; exit 1
}
$source = Join-Path $workRoot "Pan-Auto"
if (-not (Test-Path -LiteralPath $source)) { $source = $workRoot }
if (-not (Test-Path -LiteralPath (Join-Path $source $ExeName))) {
    Log "bad package: exe missing"; Restart; exit 1
}

# 3. 带重试删除旧文件（等解锁，最多约 24 秒）
function Try-Remove($path) {
    for ($i = 0; $i -lt 40; $i++) {
        if (-not (Test-Path -LiteralPath $path)) { return $true }
        try { Remove-Item -LiteralPath $path -Force -Recurse -ErrorAction Stop; return $true }
        catch { Start-Sleep -Milliseconds 600 }
    }
    return $false
}
$okExe = Try-Remove $marker
$okInt = Try-Remove $internal
if (-not ($okExe -and $okInt)) { Log "old files locked, remove failed" }

# 4. 复制新文件
try {
    Copy-Item -LiteralPath (Join-Path $source $ExeName) -Destination $InstallDir -Force
    Copy-Item -LiteralPath (Join-Path $source "_internal") -Destination $InstallDir -Recurse -Force
    Log "replaced ok"
} catch {
    Log ("copy failed: " + $_)
}

Remove-Item -LiteralPath $workRoot -Recurse -Force -ErrorAction SilentlyContinue
try { Remove-Item -LiteralPath $Zip -Force -ErrorAction SilentlyContinue } catch {}

# 5. 无论成败都重启（避免"更新后打不开"）
Start-Sleep -Milliseconds 500
Restart
'''


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
