# Pan-Auto 在线更新与发版步骤

方案完全按 `D:\Test Code\软件包更新方式.md`（OpenList 目录 + `update.json` + 独立 `update.exe`）。**那份文件是唯一标准**，和本文冲突时以它为准。

## 一、结构

| 东西 | 位置 | 说明 |
|---|---|---|
| 版本号唯一来源 | `VERSION` | `app/config.py`、`Pan-Auto.spec`（exe VERSIONINFO）、打包名、`update.json` 全从它读 |
| 更新协议（客户端逻辑） | `app/update_client.py` | 更新源配置、读清单、比版本、下载、SHA-256 校验、写 `.bat`、`cmd /c` 启动。**默认服务器 `DEFAULT_SERVER` 和链接路径 `DEFAULT_CHANNEL` 只写在这里** |
| 独立更新器 | `updater_main.py` + `app/ui/updater_window.py` → `update.exe` | 与主程序共用 `_internal`，由 `Pan-Auto.spec` 一起打出。带「更新服务器设置」 |
| 主程序按钮 | `app/ui/main_window.py` → `check_for_updates_manual` | 只做一件事：启动旁边的 `update.exe`（源码版启动 `updater_main.py`）。启动时另有静默检查，只在状态栏提示 |
| 打包 | `ci/win/package.ps1` | 清空旧构建 → PyInstaller → 校验两个 exe 的 VERSIONINFO = VERSION → `dist/Pan-Auto-v<版本>-portable.zip` + `.sha256` |
| 发布 | `ci/win/publish_openlist.ps1` | 目录自检 → 传包 → 传 `.sha256` → 刷新并轮询公开链接 → **最后**写 `update.json` → 自检 → 旧版本移进 `历史版本/` |
| 一键 | `release.ps1 -Version x.y.z` | 写 VERSION → 提交推送 → 打包 → 发布 |

## 二、更新源（服务器地址可自定义）

客户端把「去哪更新」拆成两段：

| 字段 | 默认值（`app/update_client.py`） | 含义 |
|---|---|---|
| `server` | `DEFAULT_SERVER`（当前 = 规范 2.1 的服务器地址） | 协议+主机+端口。**服务器换 IP 时用户改这个** |
| `channel` | `DEFAULT_CHANNEL` = `/sd/xIitmuVC/` | `/Pan-Auto` 的公开只读分享（旧模式，规范 2.2 表）。以 `/` 结尾 → 清单 = `server + channel + update.json`；不以 `/` 结尾 → 视为签名直链，清单 = `server + channel` |

- 用户配置：`%APPDATA%\Pan-Auto\update_config.json`（`{"server": "...", "channel": "..."}`，都可省略），优先于默认值。不在程序目录，整包覆盖不会冲掉；发布包里没有它。
- 界面：`update.exe` →「更新服务器设置」：改地址、高级里改链接路径、测试连接、保存、恢复默认。检查失败时窗口直接给「修改服务器地址」按钮，并显示当前用的服务器。
- 命令行：`update.exe --server http://新IP:5244` 写入配置后正常检查更新（批量改用）。
- 清单里只有文件名 `archive`（与清单同目录）或不含主机的 `archive_path`/`checksum_path`，**任何字段都不带服务器地址**。

### 换服务器 IP 时（规范第 0 节）

1. `setx OPENLIST_BASE_URL "http://新IP:5244"`，重开终端（发布脚本读它）。
2. 改 `app/update_client.py` 的 `DEFAULT_SERVER`，发一个新版本（只影响全新安装）。
3. 已安装的用户：`update.exe` →「更新服务器设置」填新地址 → 测试连接 → 保存。
4. OpenList 是连数据迁移的，`/sd/xIitmuVC/` 分享照常可用；如果是重装的，分享需要重建并改 `DEFAULT_CHANNEL`。

全项目里服务器 IP 只允许出现在 `DEFAULT_SERVER` 和发布脚本的兜底常量两处。

## 三、服务端

OpenList 的 `/Pan-Auto`（API 视角，真实路径是账号 base_path `/谷歌云盘/软件收集/myAPP` 下的 `Pan-Auto`），和其它软件目录平级，脚本里写死，**不读任何环境变量决定目录**。账号密码在用户环境变量 `OPENLIST_USERNAME` / `OPENLIST_PASSWORD`，不进源码、不进日志、不进包。

```
/Pan-Auto/
├─ update.json
├─ Pan-Auto-v<当前>-portable.zip
├─ Pan-Auto-v<当前>-portable.zip.sha256
└─ 历史版本/        ← 旧版本由发布脚本移进来（只移动，不删除；要删手动删）
```

公开分享 `xIitmuVC` 是首次接入时用 `POST /api/share/create` 建的（`files` 必须写真实绝对路径 `/谷歌云盘/软件收集/myAPP/Pan-Auto`，否则 permission denied）。分享目录本身 `/sd/xxx/` 访问 500 是正常的，只有文件路径才 200。

## 四、每次发版

```powershell
# 1. 把本次改动写进 RELEASE_NOTES.md 最上面一节（发布脚本把这一节原样放进 update.json 的 notes；
#    notes 里不要写 http:// 或 IP，脚本会拒绝）
# 2. 一键发版
.\release.ps1 -Version 3.0.2
```

脚本会自己验证（规范 7.4）：公开链接的 `update.json` 版本号、zip 是否 200/206、公开 `.sha256` 与本地包一致。**脚本报成功后，再用一台装了旧版的机器点「检查更新」实际升一次**，确认能更新并重启到新版本。

轮询公开链接超时（20 次 × 10 秒）会报错且**不写清单**，等几分钟重跑 `ci\win\publish_openlist.ps1` 即可，不用重新打包。

## 五、客户端流程（update.exe）

1. 读更新源配置，拼出清单地址。
2. 本地版本：读 `Pan-Auto.exe` 的 VERSIONINFO，读不到退回 `_internal/VERSION`，再退回编译进去的值。
3. `GET` 清单；缺 `version` 或 `archive`/`archive_path` 一律拒绝。失败 → 显示错误 +「修改服务器地址」。
4. 去 `v` 前缀按 `.` 拆成整数逐段比（不比字符串）。
5. 有新版本 → 显示 `当前 → 新版本` + `notes`，等用户点「立即更新」。
6. 下载到 `%TEMP%\Pan-Auto-update\`（先 `.part` 再改名），有进度，可取消。
7. `GET` `.sha256` 比对，不一致删 zip 报错。
8. 先通过命名管道（`app/single_instance.py`）让主程序**正常退出**（收托盘图标、停调度器），6 秒内没退再 `taskkill /F /IM Pan-Auto.exe`。强杀会在通知区留幽灵图标。
9. 写临时 `.bat`（UTF-8、首行 `@echo off`、第二行 `chcp 65001`），用 **`cmd.exe /c`** 启动，失败弹窗；自己退出。
   - 与规范「UTF-8 带 BOM」不同：实测带 BOM 时 cmd 把首行读成 `﻿@echo off` 报错、回显关不掉；不带 BOM + `chcp 65001` 中文输出和 `update.log` 都正常。
10. `.bat`：等旧进程退出 → `Expand-Archive` 到临时目录 → `xcopy /Y /E /H /C /I` 覆盖程序目录 → `start Pan-Auto.exe` → 删 zip 和自己。输出在程序目录 `update.log`。

本地调试：设环境变量 `PAN_AUTO_UPDATE_BASE=http://127.0.0.1:8765/` 指向本机 `python -m http.server` 目录（放 `update.json`、zip、`.sha256`），就能不碰服务器走完整流程。

## 六、铁律

- `.bat` 不能被 `Popen([bat])` 直接启动，必须 `cmd.exe /c`；`for /d %%I` 恰好两个 `%`，`del "%~f0"` 一个 `%`。改了 `build_install_bat` 模板必须把生成出来的字节写成 `.bat` 用 `cmd /c` 真跑一遍。
- 打包脚本先删 `dist\Pan-Auto` 再构建，并校验 exe 时间戳与 VERSIONINFO，防历史残留。
- 发布顺序不能调换；`update.json` 永远最后写；脚本里不许有删除调用。
- 纯 HTTP，SHA-256 只防传坏不防篡改；以后加固：先 HTTPS，再给清单签名。
