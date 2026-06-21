# Pan-Auto · 百度网盘自动转存

定时把好友分享的链接 / 聊天发来的文件夹自动转存到自己的网盘，带关键字重命名清洗。

## 运行

```bash
pip install -r requirements.txt
python main.py
```

## 私有库更新

软件支持两种半热更新：启动后自动检查，底部状态栏也可以手动点「检查更新」。

- 源码版：检查当前 Git 仓库的 `origin` 是否有新提交；发现更新后提示拉取，更新完成会重启软件生效。
- 打包版：检查 GitHub Releases 最新运行包；发现更新后下载 zip，关闭软件后由外部更新器替换文件并重启。

使用条件：

- 当前目录必须是从你的 GitHub 私有库 clone 下来的 Git 仓库，或者已经配置 `origin`。
- 打包版访问私有 Releases 时，本机需安装并登录 GitHub CLI (`gh auth login`)，或设置 `PAN_AUTO_GITHUB_TOKEN`。
- 不要把 GitHub Token 写进源码；如需 token，放在系统凭据管理器或 Git 凭据助手里。

强制更新：

在 GitHub Release notes 中加入下面任意一行即可强制旧版本更新：

```text
PAN_AUTO_FORCE_BELOW=V0.6
PAN_AUTO_MIN_SUPPORTED=V0.6
```

从 V0.6 起，低于该版本的打包版检查到策略后会要求必须更新。

可选环境变量：

```bash
PAN_AUTO_UPDATE_REMOTE=origin
PAN_AUTO_DISABLE_UPDATE=1
PAN_AUTO_GITHUB_REPO=loadingkuu/Pan-Auto
PAN_AUTO_GITHUB_TOKEN=你的临时访问令牌
```

## 当前进度（Phase 1）

- ✅ NeoPan 风格界面：无边框蓝色标题栏 + 左侧导航 + 卡片内容
- ✅ 扫码登录（手机百度网盘 App 扫码）/ Cookie 兜底登录
- ✅ 自动转存任务管理（链接 + 提取码 + 目标目录 + 定时间隔）
- ✅ 关键字重命名规则引擎（替换 / 删除 / 正则 / 前后缀）+ 实时预览
- ✅ SQLite 持久化（账号、任务、规则、日志、去重）
- ✅ 运行日志页
- ✅ Git 私有库半热更新（拉取更新后重启生效）
- ✅ 打包版 GitHub Releases 更新与强制更新策略

## 待实现

- ⏳ Phase 2：分享链接转存的真实接口对接（解析→验证提取码→列文件→转存）
- ⏳ Phase 3：好友消息文件夹自动转存
- ⏳ Phase 4：APScheduler 定时调度 + 系统托盘 + PyInstaller 打包 exe

## 数据位置

用户数据存于 `%APPDATA%\Pan-Auto\pan_auto.db`。

## 注意

转存调用的是百度网页端私有接口（官方开放平台不提供转存能力）。
属于个人使用，请勿高频大量转存，已内置节流参数以降低风控风险。
