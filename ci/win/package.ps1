<#
打包：PyInstaller 构建 -> dist\Pan-Auto-v<版本>-portable.zip + .sha256

用法（项目根目录）：
  .\ci\win\package.ps1              # 清空 dist\Pan-Auto 后重新构建再打包
  .\ci\win\package.ps1 -SkipBuild   # 用现有 dist\Pan-Auto 直接打包（仅调试用）

规则（软件包更新方式.md 第 3、4 节）：
  - 版本号只从 VERSION 文件读；exe 的 VERSIONINFO 由 Pan-Auto.spec 从同一文件生成。
  - zip 里是一层目录（目录名 = 包名），目录里是程序目录的全部内容。
  - .sha256 是 `小写hex  文件名`，两个空格，ASCII，无 BOM，无换行。
  - 构建前删除 dist\Pan-Auto，避免历史残留文件被一起打进包里。
#>
[CmdletBinding()]
param(
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $root

function Read-Utf8($path) {
    return [IO.File]::ReadAllText($path, (New-Object System.Text.UTF8Encoding($false)))
}
function Exec([scriptblock]$block, [string]$errMsg) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $block } finally { $ErrorActionPreference = $prev }
    if ($LASTEXITCODE -ne 0) { throw "$errMsg（退出码 $LASTEXITCODE）" }
}

$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "找不到虚拟环境 Python：$py" }
$version = (Read-Utf8 (Join-Path $root 'VERSION')).Trim().TrimStart('v', 'V')
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw "VERSION 文件内容不是 x.y.z 形式：$version" }

$distApp = Join-Path $root 'dist\Pan-Auto'
if (-not $SkipBuild) {
    Write-Host "==> 清理旧构建并用 PyInstaller 构建 v$version（约 2-5 分钟）" -ForegroundColor Cyan
    if (Test-Path $distApp) { Remove-Item $distApp -Recurse -Force }
    $buildStart = Get-Date
    Exec { & $py -m PyInstaller --noconfirm Pan-Auto.spec } 'PyInstaller 构建失败'
}

foreach ($exe in 'Pan-Auto.exe', 'update.exe') {
    $p = Join-Path $distApp $exe
    if (-not (Test-Path $p)) { throw "构建产物缺少 $exe：$p" }
    $fv = (Get-Item $p).VersionInfo.FileVersion
    if ($fv -ne $version) { throw "$exe 的 VERSIONINFO 是 $fv，不等于 VERSION 文件的 $version（spec 没用新值？）" }
    if (-not $SkipBuild -and (Get-Item $p).LastWriteTime -lt $buildStart) { throw "$exe 时间戳早于本次构建，疑似残留" }
}
$shipped = (Read-Utf8 (Join-Path $distApp '_internal\VERSION')).Trim()
if ($shipped -ne $version) { throw "_internal\VERSION 是 $shipped，不等于 $version" }

$packageName = "Pan-Auto-v$version-portable"
$dist = Join-Path $root 'dist'
$stage = Join-Path $dist $packageName
$archive = Join-Path $dist "$packageName.zip"
$checksum = "$archive.sha256"
foreach ($old in $stage, $archive, $checksum) { if (Test-Path $old) { Remove-Item $old -Recurse -Force } }

Write-Host "==> 打包 -> $archive" -ForegroundColor Cyan
New-Item -ItemType Directory -Path $stage -Force | Out-Null
Get-ChildItem $distApp -Force | Where-Object { $_.Name -ne 'update.log' } | Copy-Item -Destination $stage -Recurse -Force
if (Test-Path (Join-Path $root 'RELEASE_NOTES.md')) { Copy-Item (Join-Path $root 'RELEASE_NOTES.md') -Destination $stage }
Compress-Archive -Path $stage -DestinationPath $archive -CompressionLevel Optimal
Remove-Item $stage -Recurse -Force

$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText($checksum, "$hash  $packageName.zip", (New-Object System.Text.ASCIIEncoding))

$mb = [math]::Round((Get-Item $archive).Length / 1MB, 1)
Write-Host "完成：$archive ($mb MB)" -ForegroundColor Green
Write-Host "SHA256：$hash"
