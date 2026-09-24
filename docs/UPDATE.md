# Pan-Auto 在线更新与发版步骤

方案完全按 `D:\Test Code\软件包更新方式.md`（OpenList 目录 + `update.json` + 独立 `update.exe`），不用 GitHub Releases。

## 一、结构

| 东西 | 位置 | 说明 |
|---|---|---|
| 版本号唯一来源 | `VERSION`（`3.0.0`） | `app/config.py`、`Pan-Auto.spec`（exe VERSIONINFO）、打包名、`update.json` 全从它读 |
| 更新协议（客户端逻辑） | `app/update_client.py` | 读清单、比版本、下载、SHA-256 校验、写 `.bat`、`cmd /c` 启动。**公开分享链接 `UPDATE_PUBLIC_BASE` 只写在这里** |
| 独立更新器 | `updater_main.py` + `app/ui/updater_window.py` → `update.exe` | 与主程序共用 `_internal`，由 `Pan-Auto.spec` 一起打出 |
| 主程序按钮 | `app/ui/main_window.py` → `check_for_updates_manual` | 只做一件事：启动旁边的 `update.exe`（源码版启动 `updater_main.py`）。启动时另有静默检查，只在状态栏提示 |
| 打包 | `ci/win/package.ps1` | 清空旧构建 → PyInstaller → 校验两个 exe 的 VERSIONINFO = VERSION → `dist/Pan-Auto-v<版本>-portable.zip` + `.sha256` |
| 发布 | `ci/win/publish_openlist.ps1` | 传包 → 传 `.sha256` → refresh → 轮询公开链接 200 → **最后**写 `update.json` → 自检 |
| 一键 | `release.ps1 -Version x.y.z` | 写 VERSION → 提交推送 → 打包 → 发布 |

服务端目录：OpenList `http://209.146.116.186:5244` 的 `/Pan-Auto`（已建好，和 `/IMM-Touping-Next` 平级，脚本里写死，**不读 `OPENLIST_UPDATE_PATH`**）。账号密码在用户环境变量 `OPENLIST_USERNAME` / `OPENLIST_PASSWORD`，不进源码、不进日志、不进包。

## 二、首次接入（已完成，记录做法）

1. `POST /api/fs/mkdir {"path":"/Pan-Auto"}` 建目录（普通 fs 接口用相对路径）。
2. `POST /api/share/create` 建公开分享。**`files` 必须写账号真实根路径下的绝对路径** `/谷歌云盘/软件收集/myAPP/Pan-Auto`（`GET /api/me` 的 `base_path` 是 `/谷歌云盘/软件收集/myAPP`），否则 permission denied。其余字段：`expires` 2099、`pwd` 空、`disabled` false、`extract_folder` front。
3. `GET /api/share/list` 找到它的 `id`（本项目 `xIitmuVC`），公开链接 `http://209.146.116.186:5244/sd/xIitmuVC/`，填进 `app/update_client.py` 的 `UPDATE_PUBLIC_BASE`。分享目录本身 `/sd/xxx/` 访问 500 是正常的，只有文件路径才 200。
4. **首次要手动把 zip 发给用户**：旧版（V2.6 及以前）没有 `update.exe`，无法自动升上来；从 3.0.0 起以后的版本都能点「检查更新」自动升级。

## 三、每次发版

```powershell
# 1. 把本次改动写进 RELEASE_NOTES.md 最上面一节（发布脚本会把这一节原样放进 update.json 的 notes）
# 2. 一键发版
.\release.ps1 -Version 3.0.1
```

脚本会自己验证：公开链接的 `update.json` 版本号、zip 是否 200、公开 `.sha256` 与本地包一致。**脚本报成功后，再用一台装了旧版的机器点「检查更新」实际升一次**，确认能更新并重启到新版本。

轮询公开链接超时（5 分钟）会报错且**不写清单**，等几分钟重跑 `ci\win\publish_openlist.ps1` 即可，不用重新打包。

## 四、客户端流程（update.exe）

1. 本地版本：读 `Pan-Auto.exe` 的 VERSIONINFO，读不到退回 `_internal/VERSION`，再退回编译进去的值。
2. `GET <公开链接>/update.json`；缺 `version` / `archive` 一律拒绝。
3. 去 `v` 前缀按 `.` 拆成整数逐段比（不比字符串）。
4. 有新版本 → 显示 `当前 → 新版本` + `notes`，等用户点「立即更新」。
5. 下载到 `%TEMP%\Pan-Auto-update\`（先 `.part` 再改名），有进度，可取消。
6. `GET` 同名 `.sha256` 比对，不一致删 zip 报错。
7. 先通过命名管道（`app/single_instance.py`）让主程序**正常退出**（收托盘图标、停调度器），6 秒内没退再 `taskkill /F /IM Pan-Auto.exe`。强杀会在通知区留幽灵图标，Win11 上程序无法自动清理。
8. 写临时 `.bat`（UTF-8 **带 BOM**，`chcp 65001`），用 **`cmd.exe /c`** 启动，失败弹窗；自己退出。
9. `.bat`：等旧进程退出 → `Expand-Archive` 到临时目录 → `xcopy /Y /E /H /C /I` 覆盖程序目录 → `start Pan-Auto.exe` → 删 zip 和自己。输出在程序目录 `update.log`。

本地调试：设环境变量 `PAN_AUTO_UPDATE_BASE=http://127.0.0.1:8765/` 指向本机 `python -m http.server` 目录，就能不碰服务器走完整流程（`ci/win/selftest_update.ps1` 就是这么测的）。

## 五、铁律

- `.bat` 不能被 `Popen([bat])` 直接启动，必须 `cmd.exe /c`；`for /d %%I` 恰好两个 `%`，`del "%~f0"` 一个 `%`。改了 `build_install_bat` 模板必须把生成出来的字节写成 `.bat` 用 `cmd /c` 真跑一遍。
- 打包脚本先删 `dist\Pan-Auto` 再构建，并校验 exe 时间戳与 VERSIONINFO，防历史残留。
- 发布顺序不能调换；`update.json` 永远最后写。
- 纯 HTTP，SHA-256 只防传坏不防篡改；以后加固：先 HTTPS，再给清单签名。
