<#
Pan-Auto 一键发布脚本

流程：升版本号 -> 提交并推送 main -> PyInstaller 打包 -> 压成更新包 ->
创建 GitHub Release（上传 zip）-> 清理本地 zip。

用法（在项目根目录）：
  .\release.ps1 -Version V0.9
  .\release.ps1 -Version V0.9 -Notes "本次更新说明..."
  .\release.ps1 -Version V0.9 -SkipBuild        # 只推送+发布，不重新打包（用已存在的 dist）
  .\release.ps1 -Version V0.9 -SkipPush          # 不改动 git，只打包+发布
  .\release.ps1 -Version V0.9 -SkipRelease       # 只升版本+推送+打包，不建 Release

说明：
  - 发版说明：优先用 -Notes；否则读项目根的 RELEASE_NOTES.md；再否则用默认标题。
  - 需要本机已安装并登录 GitHub CLI (gh) 且 git 能推送到 origin。
  - dist/build/*.zip 已在 .gitignore，不会误提交。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Notes = "",
    [switch]$SkipBuild,
    [switch]$SkipPush,
    [switch]$SkipRelease
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if ($Version -notmatch '^[Vv]') { $Version = "V$Version" }

$repo = "loadingkuu/Pan-Auto"
$py = ".\.venv\Scripts\python.exe"
$zipName = "Pan-Auto-$Version-windows-x64.zip"

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Utf8NoBom($path, $text) {
    [IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))
}

# 运行原生程序（git/pyinstaller/gh）：这些会往 stderr 写日志，
# 在 EAP=Stop 下会被当致命错误。这里临时放开、只按退出码判成败。
function Exec([scriptblock]$block, [string]$errMsg) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $block } finally { $ErrorActionPreference = $prev }
    if ($LASTEXITCODE -ne 0) { throw "$errMsg（退出码 $LASTEXITCODE）" }
}
# 运行原生程序但不因退出码抛错，返回退出码（用于探测类命令）
function TryExec([scriptblock]$block) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $block } finally { $ErrorActionPreference = $prev }
    return $LASTEXITCODE
}

# ---- 预检 ----
if (-not (Test-Path $py)) { throw "找不到虚拟环境 Python：$py（先建好 .venv）" }
if (-not $SkipRelease -and -not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "未安装 GitHub CLI (gh)，无法建 Release。装 gh 或加 -SkipRelease"
}

# ---- 1. 升版本号 ----
Step "更新版本号 -> $Version"
$cfg = Join-Path $root "app\config.py"
$content = Get-Content $cfg -Raw
$updated = [regex]::Replace($content, 'APP_VERSION\s*=\s*"[^"]*"', "APP_VERSION = `"$Version`"")
if ($updated -ne $content) {
    Write-Utf8NoBom $cfg $updated
    Write-Host "app/config.py 已更新为 $Version"
} else {
    Write-Host "app/config.py 未变化（可能已是 $Version）" -ForegroundColor Yellow
}

# ---- 2. 提交并推送 ----
if (-not $SkipPush) {
    Step "提交并推送到 main"
    Exec { git add -A } "git add 失败"
    $dirty = (TryExec { git diff --cached --quiet }) -ne 0
    if ($dirty) {
        Exec { git commit -m "Release $Version" } "git commit 失败"
        Exec { git push origin main } "git push 失败"
    } else {
        Write-Host "没有需要提交的改动" -ForegroundColor Yellow
    }
}

# ---- 3. 打包 ----
if (-not $SkipBuild) {
    Step "PyInstaller 打包（约 2-5 分钟）"
    Exec { & $py -m PyInstaller --noconfirm Pan-Auto.spec } "PyInstaller 打包失败"
}
$exe = Join-Path $root "dist\Pan-Auto\Pan-Auto.exe"
if (-not (Test-Path $exe)) { throw "未找到运行包：$exe（去掉 -SkipBuild 重新打包）" }

# ---- 4. 压缩运行包 ----
Step "压缩运行包 -> $zipName"
$zipPath = Join-Path $root $zipName
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path (Join-Path $root "dist\Pan-Auto") -DestinationPath $zipPath -CompressionLevel Optimal
$mb = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
Write-Host "$zipName ($mb MB)"

# ---- 5. 创建 Release ----
if (-not $SkipRelease) {
    Step "创建 GitHub Release $Version"
    if (-not $Notes) {
        $notesFile = Join-Path $root "RELEASE_NOTES.md"
        if (Test-Path $notesFile) { $Notes = Get-Content $notesFile -Raw }
        else { $Notes = "Pan-Auto $Version`n`n自动更新：旧版本点「检查更新」即可升级。" }
    }
    $exists = (TryExec { gh release view $Version --repo $repo 1>$null 2>$null }) -eq 0
    if ($exists) {
        Write-Host "Release $Version 已存在，删除后重建..." -ForegroundColor Yellow
        Exec { gh release delete $Version --repo $repo --yes --cleanup-tag } "删除旧 Release 失败"
    }
    $tmp = New-TemporaryFile
    Write-Utf8NoBom $tmp.FullName $Notes
    try {
        Exec { gh release create $Version $zipPath --repo $repo --target main --title "Pan-Auto $Version" --notes-file $tmp.FullName } "创建 Release 失败"
    } finally {
        Remove-Item $tmp.FullName -Force -ErrorAction SilentlyContinue
    }
}

# ---- 6. 清理 ----
Step "清理本地 zip"
Remove-Item $zipPath -Force -ErrorAction SilentlyContinue

Write-Host "`n完成 ✅  $Version 已发布" -ForegroundColor Green
if (-not $SkipRelease) {
    Write-Host "https://github.com/$repo/releases/tag/$Version" -ForegroundColor Green
}
