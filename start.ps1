# bookswich 一键启动脚本
# 用法: .\start.ps1            # 启动前后端并打开浏览器
#       .\start.ps1 -NoBrowser # 只启动不打开浏览器
#       .\start.ps1 -Restart   # 先停旧服务再启动
#
# 说明: 后端/前端以后台隐藏窗口进程启动（输出不落盘，排查用前台命令手动起）。
#       注意: 不能给 Start-Process 传 -RedirectStandardOutput/-RedirectStandardError
#       （PS 5.1 句柄继承会让本脚本挂起等子进程退出），也不要包 cmd /c 重定向（同样挂起）。
param(
    [switch]$NoBrowser,
    [switch]$Restart
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-Port([int]$port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

if ($Restart) {
    Write-Host "⏹ 停止旧服务..."
    & (Join-Path $root "stop.ps1")
}

$python = Join-Path $root "backend\.venv\Scripts\python.exe"

# ── 后端 ──
if (-not (Test-Port 8000)) {
    Write-Host "▶ 启动后端 (uvicorn @ 8000)..."
    Start-Process -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory (Join-Path $root "backend") -WindowStyle Hidden
} else {
    Write-Host "· 后端已在运行 (8000)"
}

# ── 前端 ──
if (-not (Test-Port 5173)) {
    Write-Host "▶ 启动前端 (vite @ 5173)..."
    Start-Process -FilePath "npm.cmd" `
        -ArgumentList @("run", "dev") `
        -WorkingDirectory (Join-Path $root "frontend") -WindowStyle Hidden
} else {
    Write-Host "· 前端已在运行 (5173)"
}

# ── 等待就绪 ──
Write-Host "⏳ 等待后端就绪..."
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    try {
        $h = Invoke-RestMethod "http://127.0.0.1:8000/api/health" -TimeoutSec 2
        if ($h.status -eq "ok") { $ready = $true; break }
    } catch { }
}
if ($ready) {
    Write-Host "✅ 后端就绪: http://127.0.0.1:8000"
} else {
    Write-Host "⚠ 后端未就绪（排查: cd backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000）"
}

Start-Sleep -Seconds 2
try {
    $r = Invoke-WebRequest "http://localhost:5173" -UseBasicParsing -TimeoutSec 5
    if ($r.StatusCode -eq 200) { Write-Host "✅ 前端就绪: http://localhost:5173" }
} catch {
    Write-Host "⚠ 前端可能未就绪（排查: cd frontend; npm run dev）"
}

if (-not $NoBrowser) {
    Start-Process "http://localhost:5173"
}
Write-Host "`n✔ 完成。停止服务: .\stop.ps1 | 重启: .\start.ps1 -Restart"
