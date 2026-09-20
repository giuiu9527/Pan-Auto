<#
Pan-Auto 一键发版（OpenList 方案，见 docs/UPDATE.md）

流程：写 VERSION -> 提交并推送 main -> ci\win\package.ps1 打包 -> ci\win\publish_openlist.ps1 发布并自检

用法（项目根目录）：
  .\release.ps1 -Version 3.0.1
  .\release.ps1 -Version 3.0.1 -Notes "本次更新说明"   # 否则取 RELEASE_NOTES.md 最上面一节
  .\release.ps1 -Version 3.0.1 -SkipPush              # 不改动 git
  .\release.ps1 -Version 3.0.1 -SkipBuild             # 用现有 dist\Pan-Auto 打包（调试用）
  .\release.ps1 -Version 3.0.1 -SkipPublish           # 只打包不发布

发布前提：用户环境变量 OPENLIST_USERNAME / OPENLIST_PASSWORD；app/update_client.py 里已填公开分享链接。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Notes = '',
    [switch]$SkipPush,
    [switch]$SkipBuild,
    [switch]$SkipPublish
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$Version = $Version.Trim().TrimStart('v', 'V')
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "版本号必须是 x.y.z 形式（如 3.0.1），收到：$Version" }

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Exec([scriptblock]$block, [string]$errMsg) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $block } finally { $ErrorActionPreference = $prev }
    if ($LASTEXITCODE -ne 0) { throw "$errMsg（退出码 $LASTEXITCODE）" }
}
function TryExec([scriptblock]$block) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $block } finally { $ErrorActionPreference = $prev }
    return $LASTEXITCODE
}

# ---- 1. 版本号（唯一来源：VERSION 文件）----
Step "版本号 -> $Version"
[IO.File]::WriteAllText((Join-Path $root 'VERSION'), $Version, (New-Object System.Text.UTF8Encoding($false)))

# ---- 2. 提交并推送 ----
if (-not $SkipPush) {
    Step '提交并推送到 main'
    Exec { git add -A } 'git add 失败'
    $dirty = (TryExec { git diff --cached --quiet }) -ne 0
    if ($dirty) {
        Exec { git commit -m "Release v$Version" } 'git commit 失败'
        Exec { git push origin main } 'git push 失败'
    } else {
        Write-Host '没有需要提交的改动' -ForegroundColor Yellow
    }
}

# ---- 3. 打包 ----
Step '打包'
if ($SkipBuild) { & (Join-Path $root 'ci\win\package.ps1') -SkipBuild } else { & (Join-Path $root 'ci\win\package.ps1') }

# ---- 4. 发布 ----
if (-not $SkipPublish) {
    Step '发布到 OpenList'
    & (Join-Path $root 'ci\win\publish_openlist.ps1') -Notes $Notes
}

Write-Host "`n完成  v$Version" -ForegroundColor Green
