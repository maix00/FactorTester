# ═══════════════════════════════════════════════════════════════════════
# Windows Defender 实时扫描排除脚本
# ═══════════════════════════════════════════════════════════════════════
#
# 用途: 排除 FactorTester 项目目录和 Python/Conda 安装目录，
#       减少 Defender 实时扫描对 .parquet 文件读取和 .pyd C 扩展加载的影响。
#
# 用法: 以管理员身份运行 PowerShell，然后执行此脚本:
#   powershell -ExecutionPolicy Bypass -File scripts\windows_defender_exclusion.ps1
#
# 或手动逐条执行下方命令。
# ═══════════════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"

# 检查管理员权限
if (-NOT ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "[ERROR] 请以管理员身份运行此脚本。" -ForegroundColor Red
    Write-Host "  右键 PowerShell → 以管理员身份运行，然后重新执行。" -ForegroundColor Yellow
    exit 1
}

Write-Host "══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Windows Defender 排除路径配置" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════════" -ForegroundColor Cyan

$exclusions = @(
    "$env:USERPROFILE\Documents\GTHT\FactorTester",
    "$env:USERPROFILE\scoop\apps\miniconda3"
)

foreach ($path in $exclusions) {
    if (Test-Path $path) {
        try {
            Add-MpPreference -ExclusionPath $path -ErrorAction Stop
            Write-Host "[OK] 已添加排除: $path" -ForegroundColor Green
        } catch {
            Write-Host "[WARN] 添加失败: $path — $_" -ForegroundColor Yellow
        }
    } else {
        Write-Host "[SKIP] 路径不存在: $path" -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  当前所有 Defender 排除路径:" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════════" -ForegroundColor Cyan

$current = (Get-MpPreference).ExclusionPath
if ($current) {
    $current | ForEach-Object { Write-Host "  • $_" }
} else {
    Write-Host "  (无)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "完成。建议重启 VS Code/Flask 服务器以使排除生效。" -ForegroundColor Cyan
