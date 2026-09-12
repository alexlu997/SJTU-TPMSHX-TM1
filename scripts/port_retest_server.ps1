# port_retest_server.ps1 — Windows Server 2022 上并行跑端口维数复测四臂.
#
# 用法 (PowerShell, 任意目录):
#   powershell -ExecutionPolicy Bypass -File port_retest_server.ps1          # clone/update + 四臂并行
#   powershell -ExecutionPolicy Bypass -File port_retest_server.ps1 status   # 查看四臂进度 + 存活/退出状态
#   powershell -ExecutionPolicy Bypass -File port_retest_server.ps1 stop     # 停掉本脚本启动的所有臂
#
# 前置: git + 按 requirements-lock-server.txt 预置的 $PORT_WORKDIR\venv;
#       gh auth 或 https 凭据可拉私有仓. 本脚本不创建环境、不安装或升级依赖.
# (标定数据在私有仓 SJTU-TPMSHX-data, 脚本自动 clone 并拼进 data/raw_data).
#
# 四臂: ctrl4/ctrl6 x seed 7/123, SAAS, 无早停. 预计墙钟 ~4-7 h (瓶颈是 ctrl6
# 臂的 144 点 Sobol init, 只有 2 个 BO worker, 与 --jobs 无关).
#
# ── 2026-07-11 交接审计后的修复 (https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/d3ba040de0d43fce8e9b485396a5b660c2d87c5f/docs/atlas/HANDOFF-windows-server.md) ──
# P0  缺 raw_data 会让 DF 代理回退到 committed CSV 标定 (surrogate_v3.py:156
#     的 XLSX.exists() 分支会告警但继续) → 产出不同数字.
#     原脚本没有 .sh:52-56 那个 FATAL 检查, 且 Copy-Item -Recurse 二次执行可能
#     把目录嵌套成 data\raw_data\raw_data. 现在: 先删后拷 + 拷完硬校验.
# P1  线程超订: optimizer_qnehvi.py 的 BO 阶段按 os.cpu_count() 切内层线程,
#     它看到的是整机核数, 不知道有 4 个臂 → 四臂各占满整机 ≈ 4x 超订.
#     现在: 探测核数, 按 arm 数均分, 用 TPMSHX_BO_CORE_BUDGET 显式告知每个臂.
# P1  原脚本 -NoNewWindow 让子进程挂在父控制台上 (关窗口/logoff 会杀光所有臂),
#     且 PID 只 Write-Host 不落盘 (断线重连后无法找回或停掉它们).
#     现在: PID 落盘 + 独立控制台 (关父窗口不再杀子进程) + stop 子命令.
# P2  --jobs 只影响 45 点均匀扫掠 (~8 min), BO 阶段的 n_jobs 写死 min(q_batch,2)=2.
#     保留该 flag 但不再假装它控制总并行度.

param([string]$Mode = "run")

$ErrorActionPreference = "Stop"
$WorkDir  = if ($env:PORT_WORKDIR) { $env:PORT_WORKDIR } else { Join-Path $HOME "tpmshx-port" }
$Repo     = Join-Path $WorkDir "SJTU-TPMSHX-TM1"
$DataRepo = Join-Path $WorkDir "SJTU-TPMSHX-data"
$LogD     = Join-Path $WorkDir "logs/SJTU-TPMSHX-TM1"
$PidD     = Join-Path $WorkDir "pids/SJTU-TPMSHX-TM1"
$Branch   = if ($env:PORT_BRANCH) { $env:PORT_BRANCH } else { "main" }
$Py       = Join-Path $WorkDir "venv\Scripts\python.exe"

# 四臂定义 (单一来源: run / status / stop 都用它)
$Arms = @(
    @{ Ctrl = 4; Seed = 7   },
    @{ Ctrl = 4; Seed = 123 },
    @{ Ctrl = 6; Seed = 7   },
    @{ Ctrl = 6; Seed = 123 }
)
function Tag($a) { "c$($a.Ctrl)s$($a.Seed)" }

# ── status: 进度 + 存活/退出状态 (原脚本只 grep 日志, 分不清"跑着"和"死了") ──
if ($Mode -eq "status") {
    foreach ($a in $Arms) {
        $tag     = Tag $a
        $log     = Join-Path $LogD "$tag.log"
        $pidFile = Join-Path $PidD "$tag.pid"

        $state = "not started"
        if (Test-Path $log) {
            if (Select-String -Path $log -Pattern "\[PORT\] DONE" -Quiet) {
                $state = "DONE"
            } elseif (Test-Path $pidFile) {
                $armPid = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
                $proc = Get-Process -Id $armPid -ErrorAction SilentlyContinue
                if ($proc) { $state = "RUNNING (pid $armPid)" }
                else       { $state = "DEAD (pid $armPid gone, no DONE marker — crashed or killed)" }
            } else {
                $state = "UNKNOWN (log exists, no pid file)"
            }
        }
        Write-Host "== $tag : $state =="
        if (Test-Path $log) {
            Select-String -Path $log -Pattern "\[PORT\]|\[qNEHVI\] iter|Traceback" |
                Select-Object -Last 3 | ForEach-Object { Write-Host "   $($_.Line)" }
        }
        $errLog = Join-Path $LogD "$tag.err.log"
        if ((Test-Path $errLog) -and (Get-Item $errLog).Length -gt 0) {
            Write-Host "   [stderr non-empty] $errLog"
        }
    }
    exit 0
}

# ── stop: 停掉本脚本启动的臂 (原脚本无此能力 — PID 从不落盘) ──
if ($Mode -eq "stop") {
    foreach ($a in $Arms) {
        $tag     = Tag $a
        $pidFile = Join-Path $PidD "$tag.pid"
        if (-not (Test-Path $pidFile)) { Write-Host "no pid file for $tag"; continue }
        $armPid = (Get-Content $pidFile | Select-Object -First 1)
        $proc = Get-Process -Id $armPid -ErrorAction SilentlyContinue
        if ($proc) {
            Stop-Process -Id $armPid -Force
            Write-Host "stopped $tag (pid $armPid)"
        } else {
            Write-Host "$tag (pid $armPid) already gone"
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
    exit 0
}

New-Item -ItemType Directory -Force $WorkDir, $LogD, $PidD | Out-Null
if (-not (Test-Path $Py -PathType Leaf)) {
    throw "Pre-provisioned Python not found at $Py; create it from requirements-lock-server.txt while attended"
}

# ── 1. clone / update — 主仓 (public) + 数据仓 (private) ──
if (-not (Test-Path (Join-Path $Repo ".git"))) {
    git clone -b $Branch https://github.com/alexlu997/SJTU-TPMSHX-TM1.git $Repo
} else {
    git -C $Repo fetch origin $Branch
    git -C $Repo checkout $Branch
    git -C $Repo pull --ff-only origin $Branch
}
$DataCommit = (Get-Content (Join-Path $Repo "data-revision.txt") -Raw).Trim()
if (-not (Test-Path (Join-Path $DataRepo ".git"))) {
    git clone https://github.com/alexlu997/SJTU-TPMSHX-data.git $DataRepo
} else {
    git -C $DataRepo fetch origin
}
git -C $DataRepo checkout --detach $DataCommit
$actualDataCommit = (git -C $DataRepo rev-parse HEAD)
if ($actualDataCommit -ne $DataCommit) {
    throw "Data revision mismatch: expected $DataCommit, got $actualDataCommit"
}
Write-Host "data repo @ $actualDataCommit"

# ── 2. 拼装标定数据 (P0) ──
# 主仓 data/ 是 gitignored 的. 缺 raw_data 时 DF 代理会告警并回退到
# committed CSV 标定 (df_surrogate/surrogate_v3.py:156), 但四臂仍会继续运行，
# 产出与 Excel 标定不同的数字，结果不可比.
$SrcRaw = Join-Path $DataRepo "raw_data"
$DstRaw = Join-Path $Repo "data\raw_data"
if (-not (Test-Path $SrcRaw)) {
    Write-Host "FATAL: 数据仓里没有 raw_data/ ($SrcRaw)" -ForegroundColor Red
    exit 1
}
New-Item -ItemType Directory -Force (Join-Path $Repo "data") | Out-Null
# 先删后拷: Copy-Item -Recurse 在目标已存在时会把源目录嵌套进去
# (data\raw_data\raw_data), 二次执行即触发 → 上面的 XLSX 路径失配 → 静默回退.
if (Test-Path $DstRaw) { Remove-Item -Recurse -Force $DstRaw }
Copy-Item -Recurse -Force $SrcRaw $DstRaw

# 拷完硬校验: 生产推理路径唯一真正需要的是这个文件 (gamma_df 的 γ 锚点经
# SurrogateV3 读它). 缺它 = 静默回退, 宁可现在 FATAL.
$KeyXlsx = Join-Path $DstRaw "experiments/air/air_DG_specimen_experiment_summary.xlsx"
if (-not (Test-Path $KeyXlsx)) {
    Write-Host "FATAL: 标定数据未就位 — 缺 $KeyXlsx" -ForegroundColor Red
    Write-Host "       (缺它 DF 代理会静默回退 CSV 标定, 产出不可比的数字)" -ForegroundColor Red
    exit 1
}
Write-Host "标定数据就位: $KeyXlsx"

# ── 3. 预置环境验证（只读，不安装） ──
Set-Location $Repo
& $Py -m sjtu_tpmshx.runs.tools.check_locked_environment requirements-lock-server.txt
if ($LASTEXITCODE -ne 0) { throw "Pre-provisioned environment differs from requirements-lock-server.txt" }
& $Py -m pip check
if ($LASTEXITCODE -ne 0) { throw "Pre-provisioned environment failed pip check" }
& $Py -c "import torch, botorch, gpytorch"
if ($LASTEXITCODE -ne 0) { throw "Pre-provisioned environment is missing server BO dependencies" }

# ── 4. 四臂并行 ──
$env:PYTHONHASHSEED = "0"
$env:PYTHONPATH     = $Repo

# 线程预算 (P1): 探测逻辑处理器数, 按 arm 数均分. 原脚本硬编码 8 且注释假设
# "64 核", 既不探测也不区分物理核/逻辑核; 更要命的是 BO 阶段的
# optimizer_qnehvi.py 会用 os.cpu_count()//2 覆盖掉它 (它看到整机核数, 不知道
# 有 4 个臂) → 四臂合计 ≈ 4x 超订. TPMSHX_BO_CORE_BUDGET 是给它的显式预算.
$NCore = [int]$env:NUMBER_OF_PROCESSORS      # 逻辑处理器 (含超线程)
if ($NCore -lt 1) { $NCore = 4 }
$PerArm = [Math]::Max(1, [Math]::Floor($NCore / $Arms.Count))
$Threads = [Math]::Max(1, [Math]::Min(8, $PerArm))   # 单 worker 的线程上限
Write-Host "cores=$NCore (逻辑处理器) arms=$($Arms.Count) → 每臂预算 $PerArm 核, 每 worker $Threads 线程"

$env:OMP_NUM_THREADS       = "$Threads"
$env:MKL_NUM_THREADS       = "$Threads"
$env:OPENBLAS_NUM_THREADS  = "$Threads"
$env:NUMBA_NUM_THREADS     = "$Threads"
$env:TPMSHX_BO_CORE_BUDGET = "$PerArm"   # BO 阶段按这个切内层线程, 不再用整机核数

# --jobs 只作用于 45 点均匀扫掠 (~8 min); BO 阶段 n_jobs 写死 min(q_batch,2)=2,
# 不受它影响 (交接审计 Q6). 给它每臂预算内的一个合理值即可.
$Jobs = [Math]::Max(1, [Math]::Min(8, $PerArm))

function Launch($a) {
    $tag     = Tag $a
    $log     = Join-Path $LogD "$tag.log"
    $errLog  = Join-Path $LogD "$tag.err.log"
    $pidFile = Join-Path $PidD "$tag.pid"

    if ((Test-Path $log) -and (Select-String -Path $log -Pattern "\[PORT\] DONE" -Quiet)) {
        Write-Host "skip $tag (already DONE)"; return
    }
    # 幂等 (P1): 原脚本没有锁 — 臂还在跑时重复执行会再起一套, 新旧进程写同一个
    # 输出目录, 结果互相覆盖. 有活着的 PID 就跳过.
    if (Test-Path $pidFile) {
        $oldPid = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
            Write-Host "skip $tag (已在运行, pid $oldPid — 先跑 'stop' 再重启)"; return
        }
    }

    # 独立控制台 (P1): 原脚本用 -NoNewWindow, 子进程挂在父 PowerShell 的控制台
    # 上 — 关掉那个窗口 / logoff 会把四个臂一起杀掉. 不带 -NoNewWindow 时
    # Start-Process 给子进程新控制台, 父窗口关闭不再波及它.
    $p = Start-Process -FilePath $Py -PassThru -WindowStyle Hidden `
        -ArgumentList "-u", "-m", "sjtu_tpmshx.runs.run_port_dim_retest",
                      "--ctrl", "$($a.Ctrl)", "--seed", "$($a.Seed)", "--jobs", "$Jobs" `
        -RedirectStandardOutput $log -RedirectStandardError $errLog
    Set-Content -Path $pidFile -Value $p.Id
    Write-Host "launched $tag pid=$($p.Id) → $log"
}

foreach ($a in $Arms) { Launch $a }

Write-Host ""
Write-Host "四臂已启动 (PID 落盘在 $PidD)."
Write-Host "  进度: powershell -File $PSCommandPath status"
Write-Host "  停止: powershell -File $PSCommandPath stop"
Write-Host "  结果: $Repo\reports\port_dim_retest\"
Write-Host ""
Write-Host "注意: 服务器重启不会自动拉起这些臂, 且崩溃的臂无法断点续跑" -ForegroundColor Yellow
Write-Host "      (optimizer 每 5 轮写的 pareto_iter*.csv 只是快照, 无 --resume)." -ForegroundColor Yellow
