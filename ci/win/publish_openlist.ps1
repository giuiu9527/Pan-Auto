<#
发布到 OpenList：上传 zip + .sha256 -> 刷新目录缓存 -> 轮询公开链接 -> 最后写 update.json -> 自检

用法（项目根目录，先跑 ci\win\package.ps1）：
  .\ci\win\publish_openlist.ps1
  .\ci\win\publish_openlist.ps1 -Notes "本次更新说明"      # 否则取 RELEASE_NOTES.md 最上面一节

约束（软件包更新方式.md 第 2、5 节）：
  - 远端目录写死 /Pan-Auto。★不要读 OPENLIST_UPDATE_PATH（那是 IMM 投屏的目录）。
  - 账号密码只从用户环境变量 OPENLIST_USERNAME / OPENLIST_PASSWORD 读，不打印、不落盘。
  - 公开分享链接只写在 app/update_client.py 的 UPDATE_PUBLIC_BASE，这里解析同一个值做自检，不另存一份。
  - 顺序不能调换：包 -> .sha256 -> refresh -> 轮询公开链接 200 -> update.json。
  - 每次上传都校验 code==200 并用认证 API fs/list 确认文件真的落盘，否则重传一次。
#>
[CmdletBinding()]
param(
    [string]$Notes = ''
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $root

$baseUrl = 'http://209.146.116.186:5244'
$remotePath = '/Pan-Auto'   # 写死，见文件头

foreach ($name in 'OPENLIST_USERNAME', 'OPENLIST_PASSWORD') {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        throw "缺少环境变量 $name（在用户环境变量里设置，新开终端生效）"
    }
}
$username = [Environment]::GetEnvironmentVariable('OPENLIST_USERNAME')
$password = [Environment]::GetEnvironmentVariable('OPENLIST_PASSWORD')

function Read-Utf8($path) {
    return [IO.File]::ReadAllText($path, (New-Object System.Text.UTF8Encoding($false)))
}

# 公开分享链接：从客户端源码解析，保证发布自检和客户端下载的是同一个地址
$clientSrc = Read-Utf8 (Join-Path $root 'app\update_client.py')
$m = [regex]::Match($clientSrc, 'UPDATE_PUBLIC_BASE\s*=\s*"([^"]*)"')
$publicBase = if ($m.Success) { $m.Groups[1].Value.Trim() } else { '' }
if (-not $publicBase) {
    throw "app/update_client.py 里 UPDATE_PUBLIC_BASE 还是空的：先在 OpenList 网页给 $remotePath 开公开只读分享，把链接填进去再发布。"
}
$publicBase = $publicBase.TrimEnd('/')

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

# ---- 登录 ----
$login = Invoke-RestMethod -Uri "$baseUrl/api/auth/login" -Method Post -ContentType 'application/json' `
    -Body (@{ username = $username; password = $password } | ConvertTo-Json -Compress)
if ($login.code -ne 200 -or [string]::IsNullOrWhiteSpace($login.data.token)) { throw "OpenList 登录失败：$($login.message)" }
$token = $login.data.token
$headers = @{ Authorization = $token }

function Get-RemoteListing {
    $r = Invoke-RestMethod -Uri "$baseUrl/api/fs/list" -Method Post -Headers $headers -ContentType 'application/json' `
        -Body (@{ path = $remotePath; refresh = $true; page = 1; per_page = 500 } | ConvertTo-Json -Compress)
    if ($r.code -ne 200) { throw "fs/list 失败：$($r.message)" }
    return @($r.data.content)
}

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

# ---- 3. 刷新目录缓存 ----
$null = Get-RemoteListing

# ---- 4. 轮询公开链接，直到 .sha256 能 200 下载 ----
$publicChecksum = "$publicBase/$packageName.zip.sha256"
$visible = $false
foreach ($attempt in 1..20) {
    $code = & curl.exe -sS -o NUL -w '%{http_code}' $publicChecksum
    if ($code -eq '200') { $visible = $true; break }
    Write-Host "公开链接还没就绪（HTTP $code），$attempt/20，15 秒后重试"
    Start-Sleep -Seconds 15
}
if (-not $visible) {
    throw "包已上传但公开链接 5 分钟内仍不可达，update.json 未写入。等分享缓存追上后重跑本脚本即可。"
}

# ---- 5. 最后才写 update.json ----
$manifestPath = Join-Path ([IO.Path]::GetTempPath()) "Pan-Auto-update-$version.json"
try {
    $manifest = [ordered]@{
        version      = $version
        versionCode  = [int]($version.Split('.')[0]) * 10000 + [int]($version.Split('.')[1]) * 100 + [int]($version.Split('.')[2])
        archive      = "$packageName.zip"
        notes        = $Notes
        published_at = (Get-Date).ToUniversalTime().ToString('o')
    } | ConvertTo-Json -Compress
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

# ---- 6. 自检：脚本报成功 ≠ 客户端能更新 ----
Write-Host "==> 自检公开链接" -ForegroundColor Cyan
$pubManifest = & curl.exe -sS "$publicBase/update.json" | ConvertFrom-Json
if ($pubManifest.version -ne $version -or $pubManifest.archive -ne "$packageName.zip") {
    throw "公开链接上的 update.json 不对：version=$($pubManifest.version) archive=$($pubManifest.archive)"
}
$zipCode = & curl.exe -sS -o NUL -w '%{http_code}' "$publicBase/$packageName.zip"
if ($zipCode -ne '200') { throw "公开链接下载包返回 HTTP $zipCode" }
$pubHash = ((& curl.exe -sS $publicChecksum) -split '\s+')[0].ToLowerInvariant()
if ($pubHash -ne $localHash) { throw "公开 .sha256 ($pubHash) 与本地包 ($localHash) 不一致" }

Write-Host "已发布 v$version -> $publicBase/update.json（包 $packageName.zip，SHA256 一致）" -ForegroundColor Green
