<#
发布到 OpenList（规范：D:\Test Code\软件包更新方式.md 第 3、5、7 节）

用法（项目根目录，先跑 ci\win\package.ps1）：
  .\ci\win\publish_openlist.ps1
  .\ci\win\publish_openlist.ps1 -Notes "本次更新说明"      # 否则取 RELEASE_NOTES.md 最上面一节

顺序（不能调换）：
  0 目录自检 -> 1 传包 -> 2 传 .sha256 -> 3 刷新目录并轮询公开链接 200
  -> 4 最后写 update.json -> 自检(7.4) -> 5 把根目录旧版本移进 历史版本/

约束：
  - 服务器地址只从用户环境变量 OPENLIST_BASE_URL 读（下面的兜底常量与规范 2.1 一致），不在脚本里散落 IP。
  - 远端目录写死 /Pan-Auto，不读任何环境变量（尤其 OPENLIST_UPDATE_PATH，那是 IMM 投屏的目录）。
  - 账号密码只从 OPENLIST_USERNAME / OPENLIST_PASSWORD 读，不打印、不落盘。
  - 链接路径（channel）只写在 app/update_client.py 的 DEFAULT_CHANNEL，这里解析同一个值做自检。
    Pan-Auto 是旧的公开分享模式（/sd/xIitmuVC/），清单里只写文件名 archive，不写任何服务器地址。
  - 每次上传都校验 code==200 并用认证 API fs/list 确认文件真的落盘，否则重传一次。
  - 脚本里没有任何删除调用；旧版本只「移动」进 历史版本/。
#>
[CmdletBinding()]
param(
    [string]$Notes = ''
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $root

# ---- 地址 / 凭据（规范 7.1）----
$baseUrl = if ($env:OPENLIST_BASE_URL) { $env:OPENLIST_BASE_URL.TrimEnd('/') } else { 'http://38.65.91.124:5244' }
foreach ($name in 'OPENLIST_USERNAME', 'OPENLIST_PASSWORD') {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        throw "缺少环境变量 $name（在用户环境变量里设置，新开终端生效）"
    }
}
$username = [Environment]::GetEnvironmentVariable('OPENLIST_USERNAME')
$password = [Environment]::GetEnvironmentVariable('OPENLIST_PASSWORD')

# ---- 0. 远端目录（写死）+ 自检（规范 3.3）----
$App = 'Pan-Auto'
$remotePath = "/$App"
if ($remotePath -notmatch '^/[^/]+$') { throw "远端目录必须是一层: $remotePath" }
if ($remotePath -match '谷歌云盘|软件收集|myAPP') { throw "远端目录不能含 base_path 片段: $remotePath" }
# 规范 2.2 表里【除本软件以外】的所有目录
$others = '/IMM-Touping-Next', '/TFF-Card-Refill', '/深造机型修改', '/DeviceSpoofer-Scope', '/IMM-PDD-AutoReply', '/IMM-Compressor', '/IMM-iCloud-Todo', '/IMM-Xianyu-Assistant'
if ($others -contains $remotePath) { throw "这是别的软件的目录: $remotePath" }
$Hist = '历史版本'
$histPath = "$remotePath/$Hist"

function Read-Utf8($path) {
    return [IO.File]::ReadAllText($path, (New-Object System.Text.UTF8Encoding($false)))
}

# 链接路径：从客户端源码解析，保证发布自检和客户端下载的是同一个地址
$clientSrc = Read-Utf8 (Join-Path $root 'app\update_client.py')
$m = [regex]::Match($clientSrc, 'DEFAULT_CHANNEL\s*=\s*"([^"]*)"')
$channel = if ($m.Success) { $m.Groups[1].Value.Trim() } else { '' }
if (-not $channel.StartsWith('/') -or -not $channel.EndsWith('/')) {
    throw "app/update_client.py 的 DEFAULT_CHANNEL 不是公开分享目录形式（/sd/xxx/）：'$channel'"
}
$publicBase = $baseUrl + $channel.TrimEnd('/')

$version = (Read-Utf8 (Join-Path $root 'VERSION')).Trim().TrimStart('v', 'V')
$packageName = "Pan-Auto-v$version-portable"
$archive = Join-Path $root "dist\$packageName.zip"
$checksum = "$archive.sha256"
if (-not (Test-Path -LiteralPath $archive) -or -not (Test-Path -LiteralPath $checksum)) {
    throw "缺少包，先跑 ci\win\package.ps1：$archive"
}
$localHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()

if (-not $Notes) {
    $notesFile = Join-Path $root 'RELEASE_NOTES.md'
    if (Test-Path $notesFile) {
        # 取最上面一节（到下一个 "## " 之前）
        $text = Read-Utf8 $notesFile
        $parts = [regex]::Split($text, '(?m)^## ')
        $first = ($parts | Where-Object { $_.Trim() } | Select-Object -First 1)
        if ($first) { $Notes = ('## ' + $first).Trim() }
    }
    if (-not $Notes) { $Notes = "Pan-Auto v$version" }
}

Write-Host "服务器 $baseUrl  远端目录 $remotePath  链接 $channel  版本 v$version" -ForegroundColor Cyan

# ---- 登录 ----
$login = Invoke-RestMethod -Uri "$baseUrl/api/auth/login" -Method Post -ContentType 'application/json' `
    -Body (@{ username = $username; password = $password } | ConvertTo-Json -Compress)
if ($login.code -ne 200 -or [string]::IsNullOrWhiteSpace($login.data.token)) { throw "OpenList 登录失败：$($login.message)" }
$token = $login.data.token
$headers = @{ Authorization = $token }

function Invoke-OpenListJson([string]$api, $obj) {
    # PS 5.1 直接传字符串会把中文发成 ?，要转 UTF-8 字节
    $bytes = [Text.Encoding]::UTF8.GetBytes(($obj | ConvertTo-Json -Compress -Depth 5))
    Invoke-RestMethod -Uri "$baseUrl$api" -Method Post -Headers $headers -ContentType 'application/json; charset=utf-8' -Body $bytes
}

function Get-Listing([string]$path) {
    $r = Invoke-OpenListJson '/api/fs/list' @{ path = $path; refresh = $true; page = 1; per_page = 0 }
    if ($r.code -ne 200) { throw "fs/list $path 失败：$($r.message)" }
    return @($r.data.content)
}

function Get-RemoteListing { return Get-Listing $remotePath }

# 根目录 / 里必须能看到 Pan-Auto；不存在就建，再列一次确认
$rootNames = @(Get-Listing '/' | ForEach-Object { $_.name })
$junk = @($rootNames | Where-Object { $_ -match '^(谷歌云盘|软件收集|myAPP)$' })
if ($junk.Count) { Write-Warning "根目录里有以前错误嵌套留下的目录（请手动清理，脚本不会往里传）：$($junk -join ', ')" }
if ($rootNames -notcontains $App) {
    $r = Invoke-OpenListJson '/api/fs/mkdir' @{ path = $remotePath }
    if ($r.code -ne 200) { throw "建目录 $remotePath 失败：$($r.message)" }
    if (@(Get-Listing '/' | ForEach-Object { $_.name }) -notcontains $App) { throw "建了 $remotePath 但根目录里仍看不到" }
}
$appEntries = Get-RemoteListing
if (-not ($appEntries | Where-Object { $_.is_dir -and $_.name -eq $Hist })) {
    $r = Invoke-OpenListJson '/api/fs/mkdir' @{ path = $histPath }
    if ($r.code -ne 200) { throw "建目录 $histPath 失败：$($r.message)" }
}
$extraDirs = @($appEntries | Where-Object { $_.is_dir -and $_.name -ne $Hist } | ForEach-Object { $_.name })
if ($extraDirs.Count) { Write-Warning "$remotePath 下除 $Hist 外还有子目录（规范只允许 $Hist）：$($extraDirs -join ', ')" }

function Send-OpenListFile([string]$localFile, [string]$contentType) {
    $leaf = Split-Path $localFile -Leaf
    $remoteFile = "$remotePath/$leaf"
    $encodedPath = [uri]::EscapeDataString($remoteFile)
    $size = (Get-Item -LiteralPath $localFile).Length
    foreach ($attempt in 1..2) {
        $response = & curl.exe -sS -X PUT -H "Authorization: $token" -H "File-Path: $encodedPath" -H "Content-Type: $contentType" --upload-file $localFile "$baseUrl/api/fs/put"
        $result = $null
        try { $result = $response | ConvertFrom-Json } catch { $result = $null }
        if ($null -eq $result -or $result.code -ne 200) {
            Write-Warning "上传 $leaf 第 $attempt 次响应异常：$response"
            if ($attempt -eq 2) { throw "上传 $leaf 失败" }
            continue
        }
        # PUT 返回 200 不等于真落盘：用认证 API 确认文件在且大小一致，否则重传
        $found = Get-RemoteListing | Where-Object { $_.name -eq $leaf }
        if ($found -and [int64]$found.size -eq $size) {
            Write-Host "已上传 $leaf ($size 字节)"
            return
        }
        Write-Warning "上传 $leaf 后在目录里没看到或大小不符（第 $attempt 次），重传…"
    }
    throw "上传 $leaf 两次后仍未落盘"
}

# ---- 1. 包  2. .sha256 ----
Send-OpenListFile $archive 'application/zip'
Send-OpenListFile $checksum 'text/plain'

# ---- 3. 刷新目录缓存 + 轮询公开链接，直到包和 .sha256 都能取到（每 10 秒，最多 20 次）----
$publicChecksum = "$publicBase/$packageName.zip.sha256"
$publicZip = "$publicBase/$packageName.zip"
$visible = $false
foreach ($attempt in 1..20) {
    $null = Invoke-OpenListJson '/api/fs/list' @{ path = $remotePath; refresh = $true; page = 1; per_page = 1 }
    $c1 = & curl.exe -sS -o NUL -w '%{http_code}' $publicChecksum
    $c2 = & curl.exe -sS -r 0-0 -o NUL -w '%{http_code}' $publicZip
    if ($c1 -eq '200' -and ($c2 -eq '200' -or $c2 -eq '206')) { $visible = $true; break }
    Write-Host "公开链接还没就绪（sha256 HTTP $c1 / zip HTTP $c2），$attempt/20，10 秒后重试"
    Start-Sleep -Seconds 10
}
if (-not $visible) {
    throw "包已上传但公开链接仍不可达，update.json 未写入。等缓存追上后重跑本脚本即可（不用重新打包）。"
}

# ---- 4. 最后才写 update.json（不含任何服务器地址）----
$manifestPath = Join-Path ([IO.Path]::GetTempPath()) "Pan-Auto-update-$version.json"
try {
    $manifest = [ordered]@{
        version      = $version
        versionCode  = [int]($version.Split('.')[0]) * 10000 + [int]($version.Split('.')[1]) * 100 + [int]($version.Split('.')[2])
        archive      = "$packageName.zip"
        notes        = $Notes
        published_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    } | ConvertTo-Json -Compress
    if ($manifest -match 'https?://|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}') { throw 'update.json 里不能出现 http:// 或 IP（规范第 5 节）' }
    [IO.File]::WriteAllText($manifestPath, $manifest, (New-Object System.Text.UTF8Encoding($false)))
    # 远端固定名 update.json（覆盖同名文件立刻可见）
    $encoded = [uri]::EscapeDataString("$remotePath/update.json")
    $ok = $false
    foreach ($attempt in 1..2) {
        $response = & curl.exe -sS -X PUT -H "Authorization: $token" -H "File-Path: $encoded" -H 'Content-Type: application/json' --upload-file $manifestPath "$baseUrl/api/fs/put"
        $result = $null
        try { $result = $response | ConvertFrom-Json } catch { $result = $null }
        if ($null -ne $result -and $result.code -eq 200) {
            $found = Get-RemoteListing | Where-Object { $_.name -eq 'update.json' }
            if ($found -and [int64]$found.size -eq (Get-Item -LiteralPath $manifestPath).Length) { $ok = $true; break }
        }
        Write-Warning "写 update.json 第 $attempt 次未确认落盘：$response"
    }
    if (-not $ok) { throw '写 update.json 失败' }
} finally {
    if (Test-Path -LiteralPath $manifestPath) { Remove-Item -LiteralPath $manifestPath -Force }
}

# ---- 自检（规范 7.4）：脚本报成功 ≠ 客户端能更新 ----
Write-Host "==> 自检公开链接" -ForegroundColor Cyan
# curl 的 UTF-8 输出直接进管道会被 PS5.1 按 GBK 解码、中文变乱码导致 JSON 解析失败：先落盘再按 UTF-8 读
$pubFile = Join-Path ([IO.Path]::GetTempPath()) 'Pan-Auto-public-update.json'
$pubManifest = $null
foreach ($attempt in 1..6) {
    & curl.exe -sS -o $pubFile "$publicBase/update.json"
    try { $pubManifest = (Read-Utf8 $pubFile) | ConvertFrom-Json } catch { $pubManifest = $null }
    if ($pubManifest -and $pubManifest.version -eq $version) { break }
    Start-Sleep -Seconds 10
}
if (Test-Path -LiteralPath $pubFile) { Remove-Item -LiteralPath $pubFile -Force }
if (-not $pubManifest -or $pubManifest.version -ne $version -or $pubManifest.archive -ne "$packageName.zip") {
    throw "公开链接上的 update.json 不对：version=$($pubManifest.version) archive=$($pubManifest.archive)"
}
$zipCode = & curl.exe -sS -r 0-0 -o NUL -w '%{http_code}' $publicZip
if ($zipCode -ne '200' -and $zipCode -ne '206') { throw "公开链接下载包返回 HTTP $zipCode" }
$pubHash = ((& curl.exe -sS $publicChecksum) -split '\s+')[0].ToLowerInvariant()
if ($pubHash -ne $localHash) { throw "公开 .sha256 ($pubHash) 与本地包 ($localHash) 不一致" }

Write-Host "已发布 v$version -> $publicBase/update.json（包 $packageName.zip，SHA256 一致）" -ForegroundColor Green

# ---- 5. 归档旧版本（规范 3.4）：把根目录里不是本次版本的 zip/.sha256 移到 历史版本/ ----
# 放最后、失败只警告：归档出错不该让一次已经成功的发布报失败。只移动，不删除。
try {
    $listing = Get-RemoteListing
    $inHist = @(Get-Listing $histPath | ForEach-Object { $_.name })
    $keep = @('update.json', "$packageName.zip", "$packageName.zip.sha256")
    $candidates = @($listing | Where-Object { -not $_.is_dir -and $_.name -match '^Pan-Auto-v.*-portable\.zip(\.sha256)?$' -and ($keep -notcontains $_.name) } | ForEach-Object { $_.name })
    $dup = @($candidates | Where-Object { $inHist -contains $_ })
    if ($dup.Count) { Write-Warning "$Hist/ 里已有同名文件，跳过不覆盖：$($dup -join ', ')" }
    $old = @($candidates | Where-Object { $inHist -notcontains $_ })
    if ($old.Count) {
        $mv = Invoke-OpenListJson '/api/fs/move' @{ src_dir = $remotePath; dst_dir = $histPath; names = $old }
        if ($mv.code -ne 200) { throw "fs/move: $($mv.message)" }
        $null = Invoke-OpenListJson '/api/fs/list' @{ path = $remotePath; refresh = $true; page = 1; per_page = 1 }
        Write-Host "已归档到 ${Hist}/: $($old -join ', ')"
    } else { Write-Host '没有需要归档的旧版本' }
} catch {
    Write-Warning "发布已成功，但归档旧版本失败: $($_.Exception.Message)（下次发布会再补移，或手动在 OpenList 里移动）"
}
