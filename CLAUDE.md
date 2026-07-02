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

- 入口 `main.py`：顶部 `import PySide6.QtWebEngineWidgets`（内嵌浏览器登录用），**需要 GPU/OpenGL 上下文，无法纯 headless 跑完整 app**。
- **离屏冒烟测试**：`QT_QPA_PLATFORM=offscreen`，但要避开真实网络线程 —— 用 `db.list_accounts = lambda *a,**k: []` 打桩，否则页面构造时会起后台网络 QThread。
- **调真实接口**：venv python 里 `from app.baidu.client import get_client_for_account` + `db.get_active_account()` 拿真实登录态直接打接口。终端打印中文要 `.encode("utf-8","ignore").decode()`（Windows cp936 会报错）。
- **打包版**：`dist/Pan-Auto/Pan-Auto.exe` 是**旧的 PyInstaller 构建**，改源码不会反映到它。重新打包：`.\.venv\Scripts\pyinstaller.exe Pan-Auto.spec`。

---

## 架构分层

```
main.py                     入口：QApplication + init_db + MainWindow
app/config.py               路径、版本、常量（APP_VERSION、节流延迟）
app/db.py                   SQLite 持久化 + 迁移
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
  netdisk_browser.py        ★可复用网盘文件浏览器（provider 中立）
  group_picker.py           群文件夹选择器弹窗（NeoPan 风格）
  login_dialog.py           百度内嵌浏览器登录（WebEngine）
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
- `last_run`：上次跑的时间戳（调度器据此判断到期）

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
- 深层文件转存会**保留目录结构**（Baidu 按文件相对分享根的路径重建）。
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

`Scheduler(QThread)`：启动后等 15s，之后每 60s 扫一遍 `db.list_tasks()`，把**到期**（`transfer.is_task_due` 按 interval vs last_run）的**启用**任务逐个 `run_task`（串行，防风控）。
在 `MainWindow.__init__` 启动，`closeEvent` 里 `stop()`。跑完发信号刷新任务列表/日志。
`INTERVAL_SECONDS` 和 `is_task_due` 在 `transfer.py`。

---

## ★关键坑（务必知道）

1. **QThread 回收崩溃**：一个还在运行的 QThread 被 Python GC 回收 → `QThread: Destroyed while thread is still running` → 进程原生崩溃（退出码 `0xC0000409`）。**所有 worker 必须持有引用到 finished 为止**。约定：`self._workers.append(w)` + `w.finished.connect(移除)`。`netdisk_browser` 曾因 SettingsPage 连开两次 load 把第一个线程孤立而必崩，已修（用 `_workers` 列表 + `_seq` 只采纳最后结果）。
2. **崩溃排查法**：native 崩溃无 traceback。逐页构造 + 打桩网络定位；`0xC0000409` 基本都是上面那个 QThread 问题。
3. **中文终端编码**：探测脚本打印中文用 `.encode("utf-8","ignore").decode()`，否则 GBK 报 `UnicodeEncodeError`。
4. **接口抓包神器**：Claude Code 的 chrome-devtools MCP 连的浏览器**登录着用户的百度账号**。发现新接口的方法：`navigate` 到 `pan.baidu.com/disk/main#/im/session` → 点群 → 点「文件库」→ `evaluate_script` 注入 `window.fetch`/`XHR.open` 记录器 → 交互 → 读 `window.__reqs`。`mbox/msg/shareinfo` 就是这么抓到的。
5. **列目录项字段**：百度 `list_dir` 项有 `server_filename fs_id isdir path size`；夸克 `list_dir` 归一成同样的键 + `fid` + `quark://` 路径。

---

## UI 页面地图

| 导航 | 文件 | 说明 |
|------|------|------|
| 自动同步 | `pages/auto_sync.py` | ★分享同步/群组同步双 Tab + 右侧统一任务列表(可编辑)。群 Tab 用 `group_picker` 选群文件夹 |
| 好友消息 | `pages/friend_message.py` | 好友/群手动浏览转存（树可展开进多级文件夹）+ 该实体的定时同步任务 |
| 批量重命名 | `pages/batch_rename.py` | 选账号+文件夹+关键词规则，预览/执行 |
| 广告插入 | `pages/ad_insert.py` | 复制广告文件到多个文件夹（**仅百度**） |
| 设置 | `pages/settings.py` | 多账号管理、Cookie 添加、**广告关键词配置** |
| 转存记录 | `pages/logs.py` | 日志 |

- `netdisk_browser.NetdiskBrowser`：账号中立文件浏览器，多页复用。
- `group_picker.GroupPickerPopup`：`Qt.Popup` 弹窗，emit `picked(dict)`。整群=`{gid,gname,display}`，文件夹=多带 `{msg_id,from_uk,fs_id}`。

---

## 约定

- 提交信息结尾加 `Co-Authored-By: Claude ...`（按 Claude Code 默认）。
- **GitHub 仓库保持 public**（用户明确要求）。仓库：`loadingkuu/Pan-Auto`。
- 改动后：`py_compile` → 离屏冒烟（打桩网络）→ `pythonw main.py` 实跑 → 需要时用真实账号打接口验证。
- 不要把 Cookie / Token 写进代码或提交。

## 待办 / 已知限制

- 夸克分享转存：真实账号端到端验证。
- 夸克扫码登录：未做。
- 好友消息里"进文件夹选子文件"已支持；好友的 `getrecord` 对无文件的好友返回空属正常。
- "分享链接同步"的"指定分享内子文件夹"（NeoPan 有）：未做，目前默认整个分享。
