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

# ── 1. 项目根 (Codes/) 和 DATA_DIR ──
# 全部由 data_dir.py 解析：FEAT_ROOT 向上查找 .workspace/fix/ 标记，
# 即使脚本在子 worktree 中运行也能正确定位到 Codes/ feat 根。
Write-Host "[INFO] 解析 Codes 根和 DATA_DIR (via data_dir.py) ..."
# conda run 在多层嵌套（Start-Process → conda run → python -c）时无法处理
# 含换行符的 -c 参数，改用临时 .py 文件解决。
$TempPy = Join-Path $env:TEMP "defender_resolve_paths.py"
$ScriptPath = $MyInvocation.MyCommand.Path
@"
import sys, os
script = os.path.normpath(r"$ScriptPath")
sys.path.insert(0, os.path.dirname(os.path.dirname(script)))
from scripts.data_dir import FEAT_ROOT, DATA_DIR
print(FEAT_ROOT)
print(DATA_DIR)
"@ | Out-File -FilePath $TempPy -Encoding UTF8

$PyOut = conda run -n GTHT python "$TempPy" 2>&1
Remove-Item $TempPy -ErrorAction SilentlyContinue

if ($LASTEXITCODE -ne 0 -or -not $PyOut) {
    Write-Host "[ERROR] 无法运行 data_dir.py: $PyOut" -ForegroundColor Red
    Write-Host "[ERROR] 请确认 GTHT 环境已配置" -ForegroundColor Red
    exit 1
}
$lines = $PyOut -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
$CodesDir = $lines[0]
$DataDir = $lines[1]
Write-Host "[INFO] Codes (feat 根): $CodesDir"
Write-Host "[INFO] DATA_DIR: $DataDir"
# 确保 DATA_DIR 是绝对路径
$DataDir = [System.IO.Path]::GetFullPath($DataDir)

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
