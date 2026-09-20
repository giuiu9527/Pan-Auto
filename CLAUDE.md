# Pan-Auto 项目说明（给 AI 接手用）

网盘自动转存/同步桌面工具（PySide6 + Python，Windows）。支持**百度网盘**（主）和**夸克网盘**。
核心能力：分享链接转存、好友消息/群文件转存、**定时自动增量同步**、批量重命名、广告文件过滤、去重。

> 本文件是给后续 AI 助手的交接文档。**接手前务必读「关键坑」和「百度 mbox 接口速查」两节**——那些接口是抓包逆向出来的，代码里看不出来。

---

## 运行 & 调试

```powershell
# 启动（项目根目录）。pythonw = 无控制台；python = 有控制台看报错
.\.venv\Scripts\pythonw.exe main.py

# 跳过启动时的更新检查
$env:PAN_AUTO_DISABLE_UPDATE = "1"

# 语法检查
.\.venv\Scripts\python.exe -m py_compile app\core\transfer.py ...
```

- 入口 `main.py`：正常启动 GUI；带 `--baidu-login` 时以**子进程模式**跑 WebView2 登录（见 `app/baidu/webview_login.py`）。已**移除 QtWebEngine**（登录改用系统 Edge WebView2，包体 556MB→127MB）。
- **离屏冒烟测试 / 截图**：`QT_QPA_PLATFORM=offscreen` + `QT_QPA_FONTDIR=C:\Windows\Fonts`（否则中文全是方块），打桩 `db.list_accounts`/`db.get_active_account`/`app.netdisk.get_client_for_account`/`app.baidu.client.get_client_for_account` 返回假账号和 `None` 客户端、`Scheduler.start = lambda...`，然后逐页 `win.navigate(key)` + `win.grab().save()`，用 Read 工具看 PNG 就能肉眼检查排版（V3.0 重做界面就是这么验的）。结束用 `os._exit(0)`，否则残留线程会让进程挂住。
- **调真实接口**：venv python 里 `from app.baidu.client import get_client_for_account` + `db.get_active_account()` 拿真实登录态直接打接口。终端打印中文要 `.encode("utf-8","ignore").decode()`（Windows cp936 会报错）。
- **打包版**：`dist/Pan-Auto/` 是 PyInstaller 构建产物（`Pan-Auto.exe` + `update.exe` 共用 `_internal`），改源码不会反映到它。重新打包用 `.\ci\win\package.ps1`（会先删旧构建、校验 exe 的 VERSIONINFO = `VERSION`，再压成 `dist\Pan-Auto-v<版本>-portable.zip` + `.sha256`）。
- **更新流程本地调试**：设 `PAN_AUTO_UPDATE_BASE=http://127.0.0.1:8765/` 指向本机 `python -m http.server` 目录（放 `update.json`、zip、`.sha256`），跑 `update.exe` 或 `python updater_main.py` 即可走完整流程不碰服务器。改了 `update_client.build_install_bat` 模板，必须把生成的 `.bat` 用 `cmd /c` 真跑一遍（scratchpad 里 `bat_test.py` 的做法）。

---

## 架构分层

```
main.py                     入口：QApplication + init_db + MainWindow
app/config.py               路径、版本、常量（APP_VERSION、节流延迟）
app/db.py                   SQLite 持久化 + 迁移
app/theme.py                ★设计令牌（颜色/字号）+ 全局 QSS
app/netdisk.py              ★Provider 中立分发层（按账号 provider 选百度/夸克客户端）
app/baidu/
  client.py                 BaiduPanClient + mbox（好友/群）+ 分享转存 + 统一协议
  login.py                  百度扫码登录（passport）
app/quark/client.py         QuarkPanClient（仅 Cookie 登录）
app/core/
  transfer.py               ★run_task 统一编排（分享/好友/群），去重+去广告+重命名+调度判断
  scheduler.py              ★后台定时调度器（QThread）
  batch_rename.py           批量重命名编排
  rename.py                 关键词规则引擎
app/ui/
  main_window.py            主窗口、导航、调度器启停、更新检查
  widgets.py                ★排版积木：PageHeader / TwoColumn(可拖分栏) / SegmentBar / StatusPill /
                            setup_table / two_line_cell / hint(自动换行) / ElidedLabel … 所有页面都用它拼
  netdisk_browser.py        ★可复用网盘文件浏览器（provider 中立）
  group_picker.py           群文件夹选择器弹窗
  login_dialog.py           百度登录：子进程调系统 WebView2（缺运行时弹窗引导下载）
  baidu/webview_login.py    WebView2 登录子进程（pywebview + pythonnet，抓 Cookie）
  pages/                    home / auto_sync / batch_rename / ad_insert /
                            friend_message / logs / settings / placeholder
```

### Provider 抽象（重点）
`app/netdisk.get_client_for_account(account_id)` 按账号的 `provider` 字段返回 `BaiduPanClient` 或 `QuarkPanClient`。
两个客户端都实现**统一协议**，`core/transfer.py` 只调这套、不感知具体网盘：
`parse_share_link` · `open_share(link,pwd)` · `share_key(meta,f)` · `resolve_target(dir)` · `save_files(meta,files,ref)` · `rename_in_dir(ref,old,new)` · `rename_item(item,new)` · `list_dir(path)`

**加新网盘** = 新建 `app/<provider>/client.py` 实现这套协议 + 在 `netdisk.py` 注册分发。

---

## 数据库（app/db.py）

表：`accounts` `tasks` `rename_rules` `logs` `transferred` `app_settings`。迁移用 `_ensure_column`（`CREATE TABLE IF NOT EXISTS` + 补列），改 schema 照这个模式加，别写破坏性迁移。

**tasks 关键字段**：
- `kind`：`share`(分享链接) / `friend`(好友) / `group`(群)
- `account_id`：绑定账号
- `link`：分享任务=分享URL；**群任务=可选的"具体文件夹"引用 JSON** `{"fs_id","msg_id","from_uk"}`（空=同步整群）
- `target_dir`：保存位置
- `interval`：`30m`/`hourly`/`6h`/`daily`
- `rename_on` `ad_skip`：是否转存后重命名 / 过滤广告
- `entity_id`：好友 uk / 群 gid；`entity_name`：显示名
- `last_run`：上次跑的时间戳（**成败都更新**，调度器据此判断到期）
- `fail_count`：连续失败次数（成功清零）。`transfer.effective_period` = 间隔 × 2^fail_count，上限 1 小时 → 失败退避
- `interval` 新增 `5m`/`15m`；`1m` 只为兼容旧任务保留（UI 新建不再提供）。日志表 `prune_logs(5000)` 定期修剪

**去重** `transferred(task_id, fs_key)`：
- 分享：`fs_key = f"{shareid}_{fs_id}"`（`client.share_key`）
- 好友/群：`fs_key = f"{kind}_{entity_id}_{fs_id}"`

**设置** `app_settings(key,value)`：`get_setting/set_setting`。目前存 `ad_keywords`（广告关键词，换行/逗号分隔）。

---

## ★百度 mbox 接口速查（好友消息 / 群文件）

**这些是网页私有接口，抓包逆向来的，参数极易踩坑。** 通用参数：`bdstoken`(见 `get_bdstoken`) `channel=chunlei` `web=1` `clienttype=0` `app_id=250528` `json=1`。见 `BaiduPanClient._mbox_params`。

| 功能 | 方法 | 端点 & 关键参数 | 返回 |
|------|------|------|------|
| 好友列表 | `list_friends` | GET `/mbox/relation/getfollowlist` `type=2 start limit`（**自动翻页**） | `records[]{uk, uname/nick_name}` |
| 好友聊天文件 | `list_friend_files` | GET `/mbox/msg/getrecord` `to_uk page num desc=1` | records(可能是list或`{msg_list}`) |
| 群列表 | `list_groups` | GET `/mbox/group/list` `start limit`（**自动翻页**） | `records[]{gid, name}` |
| 群文件根(时间线) | `list_group_files` | GET `/mbox/group/listshare` `gid type=2 desc=1 limit` | `records={msg_count, msg_list:[{msg_id, uk, msg_ctime, file_list:[...]}]}` |
| **进文件夹(下级)** | `list_msg_folder` | GET **`/mbox/msg/shareinfo`** `from_uk msg_id fs_id=<文件夹> gid=<群才有> type=2 num page limit desc=1` | `records=[文件对象]` 扁平数组 + `has_more` |
| **转存(好友+群共用)** | `transfer_friend_files`/`transfer_group_files` | POST **`/mbox/msg/transfer`** `from_uk msg_id gid=<群才有> type=2 async=1` body:`fsidlist=[..] path=<目标> ondup=newcopy` | `errno==0` 即成功 |

**文件对象字段**：`fs_id server_filename isdir size path owner_id`。
`file_list` 解析见模块函数 `_parse_msg_records` / `_msg_list` / `_extract_file_list`。
时间戳 `msg_ctime` 是**毫秒**，要 `//1000`。

**关键坑 / 陷阱端点（别再试了，都不行）**：
- 进文件夹是 `mbox/**msg**/shareinfo`，不是 `mbox/group/shareinfo`（后者返回空）。
- `listshare` 加 `fs_id`/`path`/`parent_fid` **会被忽略**、永远返回根目录——它只列时间线。
- 群转存端点是 `mbox/**msg**/transfer`+`gid`，不是 `mbox/group/transfer`（后者返回空）。
- `transfer` 成功后响应里的 `target_file_nums` **是误导字段**（常为 0），以 `errno==0` 判成功。判成功后要验证就去列目标目录看文件到没到。
- ★`transfer` 返回 **`errno=12` 且 `total`/`target_file_nums` 全 0** = 这些文件你网盘里**已存在**，百度**全盘按内容去重**、拒绝重复转存（不是路径冲突——转存到全新空目录也一样）。常见于：①你**自己**分享到群的文件又想转存回自己网盘（`from_uk == 自己的 uk`）②早已同步过。`core/transfer` 把这种情况当**软跳过**：标记去重 + 记 skip 日志，**不能当硬错误**——否则「每 1 分钟」类高频任务会永远重试、每次报错刷屏、狂打接口（2026-07 实测逆向）。
- 深层文件转存会**保留目录结构**（Baidu 按文件相对分享根的路径重建）。
- ★★`mbox/msg/transfer` **完全无视 `fsidlist`**：只要传该消息里任意一个 fs_id，Baidu 就把**整条消息（整个顶层共享文件夹 + 所有兄弟内容 + 广告）**按相对分享根的路径**整包**倒进 `path`。所以「选群里的子文件夹只同步它」在转存层**做不到**——只能整包倒进来后**在自己网盘里事后整理**（实测逆向，2026-07）。
- **所有好友/群任务统一走中转目录**（`core/transfer._run_msg_task` + `baidu/client.extract_leaf`/`merge_move_into`，V3.0 统一）：★不要直接转存进正式目录★。因为 `mbox/msg/transfer` 用 `ondup=newcopy`，只要正式目录里已有同名项，百度就生成 `xxx(1)(2)` 副本。做法：先做去重筛选，**没有新东西就完全不碰网盘**；有新东西才 **整包转存到空的中转目录** `target/_pan_auto_tmp_<任务id>`（转存前先删掉上次残留保证它空），在中转目录里 `purge_ad_items` 删广告，再**递归合并移动**进最终目录（群具体文件夹 → `extract_leaf` 落到固定的 `target/<叶子名>`；好友/整群 → `merge_move_into(stage, target)`）：move 到同名文件夹报 `-8` 不合并，故逐项、冲突目录递归、同名文件跳过保留旧的；最后把**整个中转目录删掉**。最终落点跨次同步不变 → 增量就是**就地更新**、不产生副本。move/delete 都是 `filemanager` **异步**（`async=2` 返回 `taskid`），要 `wait_task` 轮询 `share/taskquery` 到 `status==success/failed`（`_move_wait`/`delete_and_wait` 已封装并在失败时上抛）。**这条链路已用真实账号在隔离目录 `/_pan_auto_selftest` 下验证**：同名文件不重复、新文件并入、广告目录整棵删、中转目录清空、`ensure_dir` 重复调用不建副本。
- ★★**定位中转目录里的叶子别用 `stage + leaf_rel` 拼**：`leaf_rel`（=子项 `path` 去掉自身名）是 shareinfo 给的**分享者网盘绝对路径**，开头常带分享者私有目录（如 `/我的资源/...`）；但百度整包重建是**从被分享的顶层开始**、**丢掉分享根以上的私有前缀**。直接拼会找不到叶子、把最终目录建成**空的**（2026-07 实测：`电子资料` 案例）。`extract_leaf` 的正解 = 把 `leaf_rel` 拆成段，**从头逐段去掉、最长优先**地试 `stage/<segs[i:]>` 哪个真实存在，找到即叶子位置；`leaf_rel` 为空或都找不到时退化为把整个中转目录并入 `target`。
- 群「具体文件夹」去重按 **fs_id**、且 `core/transfer._enumerate_leaf_deep` 会**递归遍历叶子下所有层级**（文件+文件夹）来做检测——所以**深层子文件夹内部新增的文件也能被增量发现**（2026-07 加）。检测到任意深层新项就整包转存到中转目录、再 `merge_move_into` 就地并入 `target/<叶子名>`（`merge_move_into` 递归进冲突目录、只搬新名项，所以新深层文件会落到对应子目录、老文件不动、不产生副本）。递归枚举有防爆上限 `max_calls=800/max_items=8000`，超大目录会退化为不完全枚举（已发现的新项仍同步）。注意：**每次跑都要把整棵树列一遍**，「每 1 分钟」这类高频任务对大目录会有 N 次 `shareinfo` 调用的开销/风控压力。
- 多级导航时 `msg_id`/`from_uk` 始终用**最初那条消息的**，只换 `fs_id`。

### 分享链接转存（已有，`baidu/client.py`）
`parse_share_link` → `verify_share_pwd`(写 BDCLND cookie) → `get_share_meta`(解析分享页 HTML + `share/list` 兜底) → `transfer_files`(`share/transfer`，`shareid/from=uk/fsidlist/path`，带 Referer)。错误码映射 `_share_err`。

---

## 夸克网盘（app/quark/client.py）

- **仅 Cookie 登录**（扫码未做，设置页夸克的"扫码添加"是禁用的）。
- 主机 `drive-pc.quark.cn/1/clouddrive/...`，通用参数 `pr=ucpro&fr=pc`（`COMMON`）。
- 路径编码：夸克用 fid 不用路径，UI 里用 `quark://<fid>|<显示路径>` 携带（`_encode_path`/`_decode_path`）。显示路径也能按层级解析回 fid（`_walk_to_fid`）。
- 分享转存链路：`open_share`（`/share/sharepage/token` 取 stoken → `/detail` 列文件 → `/save` 保存 → 轮询 `/task` 到 `status==2`）。已实现，需真实账号验证字段。
- **夸克没有"复制文件"接口** → 广告插入页（ad_insert）是**百度专属**，账号下拉只列百度。
- ⚠️ 夸克分享转存代码按公开协议写的，**未用真实夸克账号跑通验证过**。

---

## 定时调度器（app/core/scheduler.py）

`Scheduler(QThread)`：启动后等 15s，之后每 30s 扫一遍 `db.list_tasks()`，把**到期**（`transfer.is_task_due` 按 interval vs last_run，含失败退避）的**启用**且**未在运行**的任务逐个 `run_task`（串行，防风控）。
在 `MainWindow.__init__` 启动，`closeEvent` 里 `stop()`。跑完发信号刷新任务列表/日志；每 20 轮 `prune_logs`。无新增且无错误的运行**不写「定时同步完成」日志**（以前一个「每 1 分钟」任务几天攒了 1.3 万条）。
`INTERVAL_SECONDS`/`INTERVAL_CHOICES`/`is_task_due`/`effective_period` 在 `transfer.py`。

★`run_task` 的并发约束（V3.0）：`_try_mark_running` 原子标记 → 同一任务**不可重入**（正在跑就直接返回 `error="任务正在运行中"`）；`_GLOBAL_RUN_LOCK` 让**所有任务全局串行**（「立即同步」按钮和调度器不会同时跑）。`run_task` 在 `finally` 里统一 `set_task_last_run` + `bump_task_fail_count`，任何异常都不会漏更新（以前失败不更新 last_run → 每轮扫描都重跑 → 刷屏）。

---

## ★关键坑（务必知道）

0. **★「同一个文件夹被反复新建成 `xxx_20260920_073412`」的根因（V3.0 修复，别改回去）**：
   ① `api/create` 的 `rtype` 语义：`0`=冲突报 `-8`（已存在），`1`=**冲突时自动改名**（百度追加 `_YYYYMMDD_HHMMSS`），`3`=覆盖。旧代码用 `rtype=1` 还注释成「返回已存在目录」，完全反了。现在 `create_dir` 用 `rtype=0` 并把 `-8` 视为成功（真实账号验证过：连建两次只有一个目录）。
   ② 旧 `list_dir` 对接口报错（`errno≠0`：登录失效 / 频控 31034 / 超时）静默返回 `[]` → `dir_exists` 判成「不存在」→ 又去建目录 → 副本。现在 `list_dir` **报错上抛**并自动翻页；`dir_exists` 直接列该路径、只有 `errno=-9` 才算不存在；`_get_json` 对网络错误重试 2 次。**任何「列不出来就当空」的写法都是副本来源，别再写。**
   ③ `resolve_target` 以前吞掉建目录异常，转存接口就自己按 `ondup` 建目录；现在建不了目录直接报错停止本次同步。路径统一 `_norm_path`（去尾斜杠）。
1. **QThread 回收崩溃**：一个还在运行的 QThread 被 Python GC 回收 → `QThread: Destroyed while thread is still running` → 进程原生崩溃（退出码 `0xC0000409`）。**所有 worker 必须持有引用到 finished 为止**。约定：`self._workers.append(w)` + `w.finished.connect(移除)`。`netdisk_browser` 曾因 SettingsPage 连开两次 load 把第一个线程孤立而必崩，已修（用 `_workers` 列表 + `_seq` 只采纳最后结果）。
2. **崩溃排查法**：native 崩溃无 traceback。逐页构造 + 打桩网络定位；`0xC0000409` 基本都是上面那个 QThread 问题。
3. **中文终端编码**：探测脚本打印中文用 `.encode("utf-8","ignore").decode()`，否则 GBK 报 `UnicodeEncodeError`。
4. **接口抓包神器**：Claude Code 的 chrome-devtools MCP 连的浏览器**登录着用户的百度账号**。发现新接口的方法：`navigate` 到 `pan.baidu.com/disk/main#/im/session` → 点群 → 点「文件库」→ `evaluate_script` 注入 `window.fetch`/`XHR.open` 记录器 → 交互 → 读 `window.__reqs`。`mbox/msg/shareinfo` 就是这么抓到的。
5. **列目录项字段**：百度 `list_dir` 项有 `server_filename fs_id isdir path size`；夸克 `list_dir` 归一成同样的键 + `fid` + `quark://` 路径。
6. **百度 `result` 可能是 list**：未登录时 `gettemplatevariable` 返回 `{"errno":-6,"result":[]}`——`result` 是**空 list 不是 dict**。取前必须判类型（见 `baidu/client._result_dict`），否则 `result.get(...)` 抛 `'list' object has no attribute 'get'`。
7. **WebView2 登录**（`baidu/webview_login.py`，子进程）：`pywebview.get_cookies()` 返回 **list of `SimpleCookie`**（dict 子类，键=cookie名、值=Morsel）——见 `_flatten_cookies`。**BDUSS 出现 ≠ 登录态建好**，必须用接口 `_verify_login` 校验拿到 username 才算成功，否则会抓到半截无效 Cookie。缺 WebView2 运行时查注册表 `webview2_installed()`，弹窗引导下载。
9. **Qt 界面排版坑（V3.0 重做界面时踩的）**：
   - QSS 里 8 位十六进制颜色 `#RRGGBBAA` 会被 Qt 解析成 **`#AARRGGBB`**，半透明底色要写 `rgba(r,g,b,a)`。
   - 给自动换行的 QLabel 重设 `setSizePolicy(Ignored, Preferred)` 会**丢掉 heightForWidth 标志**，布局少算行高、控件互相重叠；要 `sp = lb.sizePolicy(); sp.setHorizontalPolicy(Ignored); sp.setHeightForWidth(True)`（见 `widgets._wrap_policy`）。
   - `QTableWidget` 默认 `wordWrap=True`：列窄时文字换行、被固定行高裁掉一半 → 所有表格走 `widgets.setup_table`（不换行 + 省略号 + tooltip）。
   - 不要在文字里放 emoji / 特殊符号（● ○ ⟳ 🔗 ⏱ ✕ ＋）：Microsoft YaHei 没有这些字形，回退到 Segoe UI Emoji/Symbol 后行高被撑大、文字顶出控件。状态用 `StatusPill`，按钮用 `icons.py` 的矢量图标。
   - 字号只用整数 px；输入框/按钮统一 `min-height:34px`（QSS 里），图标按钮 32×32。
   - 页面左右分栏用 `widgets.TwoColumn`（QSplitter，左栏有 min/max），不要 `setFixedWidth(438)` 这种写死宽度——窗口一小右边表格就被挤没。
8. **PowerShell 5.1 读中文文件必须显式 UTF-8**：`Get-Content -Raw` 默认按 GBK 解码，读 UTF-8 中文文件会乱码；若再写回就**毁掉文件**。用 `[IO.File]::ReadAllText($p,(New-Object System.Text.UTF8Encoding($false)))`。`release.ps1` 曾因此把 `config.py` 读乱写坏（已修，见其 `Read-Utf8`）。.ps1 脚本本身也要存成 **UTF-8 BOM**，否则 PS5.1 按 GBK 读脚本里的中文会解析报错。

---

## UI 页面地图

| 导航 | 文件 | 说明 |
|------|------|------|
| 概览 | `pages/home.py` | 统计卡（`db.task_counts`）+ 快捷入口 |
| 自动同步 | `pages/auto_sync.py` | ★左：新建/编辑任务表单（分享链接 / 群文件夹 SegmentBar）；右：任务表（两行单元格 任务名+账号·路径、就地改频率、状态药丸、更多菜单=编辑/重新同步/删除）。窄时自动隐藏频率列。`scheduler` 由主窗口注入，新建任务后 `wake_now()` |
| 好友 / 群文件 | `pages/friend_message.py` | 好友/群手动浏览转存（树可展开进多级文件夹）+ 底部「定时同步」卡（加入 + 任务表）。与自动同步页通过 `tasks_changed` 信号互刷 |
| 批量重命名 | `pages/batch_rename.py` | 选账号+文件夹+关键词规则（`rule_editor`），预览/执行 |
| 广告清理 | `pages/ad_clean.py` | 递归扫描文件夹里命中广告关键词的文件 → 勾选删除 + **广告关键词/白名单配置** |
| 广告插入 | `pages/ad_insert.py` | 复制广告文件到多个文件夹（**仅百度**） |
| 运行记录 | `pages/logs.py` | 级别芯片筛选 + 搜索 + 清空（`db.list_logs(limit, level, query)`） |
| 设置 | `pages/settings.py` | 账号列表 / 添加账号（WebView2 登录 或 Cookie）/ 通用（开机自启、关闭行为）/ 目录预览；整页可滚动 |

- 每页统一：`PageHeader(标题, 副标题)` 放页首，副标题当状态栏用（加载中 / 结果统计）；双栏页用 `TwoColumn`。
- `netdisk_browser.NetdiskBrowser`：账号中立文件浏览器（带当前目录筛选），多页复用。
- `group_picker.GroupPickerPopup`：`Qt.Popup` 弹窗，emit `picked(dict)`。整群=`{gid,gname,display}`，文件夹=多带 `{msg_id,from_uk,fs_id}`。

---

## 约定

- 提交信息结尾加 `Co-Authored-By: Claude ...`（按 Claude Code 默认）。
- **GitHub 仓库保持 public**（用户明确要求）。仓库：`loadingkuu/Pan-Auto`。
- 改动后：`py_compile` → 离屏冒烟/截图（打桩网络）→ `pythonw main.py` 实跑 → 需要时用真实账号打接口验证。改动转存/目录逻辑后，**必须**在隔离目录（如 `/_pan_auto_selftest`）用真实账号跑一遍「建中转目录 → copy 文件进去 → purge_ad_items → extract_leaf/merge_move_into → 校验最终目录无副本 → 删除」的自检，别只看日志。
- **在线更新 / 发版**：OpenList 方案（`D:\Test Code\软件包更新方式.md`），步骤见 `docs/UPDATE.md`。版本号唯一来源 `VERSION`；`app/update_client.py`（协议）+ `updater_main.py`/`app/ui/updater_window.py`（独立 `update.exe`）；`ci/win/package.ps1` 打包、`ci/win/publish_openlist.ps1` 发布、`release.ps1` 一键。远端目录写死 `/Pan-Auto`，公开分享链接只写在 `update_client.UPDATE_PUBLIC_BASE`（发布脚本从源码解析同一值）。旧的 GitHub Releases 更新器（`app/updater.py`）已删除。
- `main.py` 还带 `--headless`（只跑调度器）和 `--api <cmd>`（`app/api_bridge.py`，给外部原生 UI 的一次性 JSON 桥）两种模式，是用户为另一个项目加的，改 `run_task`/客户端签名时别把它们弄坏。
- 不要把 Cookie / Token 写进代码或提交。

## 待办 / 已知限制

- 夸克分享转存：真实账号端到端验证。
- 夸克扫码登录：未做。
- 好友消息里"进文件夹选子文件"已支持；好友的 `getrecord` 对无文件的好友返回空属正常。
- "分享链接同步"的"指定分享内子文件夹"（NeoPan 有）：未做，目前默认整个分享。
