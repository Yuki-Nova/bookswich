# bookswich 一键停止脚本（只停 bookswich 占用端口 8000/5173 的进程）
$ErrorActionPreference = "SilentlyContinue"
$stopped = $false
foreach ($port in @(8000, 5173)) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen
    foreach ($c in $conns) {
        $p = Get-Process -Id $c.OwningProcess
        Stop-Process -Id $c.OwningProcess -Force
        Write-Host "⏹ 已停止 PID $($c.OwningProcess) (端口 $port, $($p.ProcessName))"
        $stopped = $true
    }
}
if (-not $stopped) { Write-Host "· 没有 bookswich 服务在运行" }
