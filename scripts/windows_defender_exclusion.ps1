# ═══════════════════════════════════════════════════════════════════════
# Windows Defender 实时扫描排除脚本
# ═══════════════════════════════════════════════════════════════════════
#
# 用途: 排除 Codes（项目根）、DATA_DIR（parquet 数据）和 Conda 安装目录，
#       减少 Defender 实时扫描对 .parquet 文件读取和 .pyd C 扩展加载的影响。
#
# 路径来源: DATA_DIR 由 scripts/data_dir.py 动态解析（优先 .settings → feat root → 回退）。
#
# 用法: 以管理员身份运行 PowerShell，cd 到项目目录后执行:
#   powershell -ExecutionPolicy Bypass -File scripts\windows_defender_exclusion.ps1
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

# ── 1. 项目根目录 (Codes/) ──
# 脚本位于 <Codes>/scripts/，故 Codes = 脚本所在目录的上一级
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CodesDir = Split-Path -Parent $ScriptDir
Write-Host "[INFO] Codes (项目根): $CodesDir"

# ── 2. DATA_DIR ──
# 通过 data_dir.py 解析（兼容 .settings 配置和 worktree 隔离）
Write-Host "[INFO] 解析 DATA_DIR ..."
$PyCmd = @"
import sys, os
sys.path.insert(0, os.path.normpath(r"$CodesDir"))
from scripts.data_dir import DATA_DIR
print(DATA_DIR)
"@
$DataDir = conda run -n GTHT python -c $PyCmd 2>$null
if (-not $DataDir -or $LASTEXITCODE -ne 0) {
    Write-Host "[WARN] 无法通过 data_dir.py 解析 DATA_DIR，尝试回退路径" -ForegroundColor Yellow
    $DataDir = Join-Path $CodesDir "..\data"
}
$DataDir = [System.IO.Path]::GetFullPath($DataDir)
Write-Host "[INFO] DATA_DIR: $DataDir"

# ── 3. Conda 安装目录 ──
# 通过 conda info --base 获取
$CondaBase = conda info --base 2>$null
if ($CondaBase) {
    $CondaBase = $CondaBase.Trim()
} else {
    $CondaBase = "$env:USERPROFILE\scoop\apps\miniconda3"
}
Write-Host "[INFO] Conda base: $CondaBase"

# ── 组装排除列表 ──
$exclusions = @(
    $CodesDir,
    $DataDir,
    $CondaBase
)

Write-Host ""
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
