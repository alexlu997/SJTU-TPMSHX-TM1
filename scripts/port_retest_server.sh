#!/usr/bin/env bash
# port_retest_server.sh — 在 pyfluent 服务器上并行跑端口维数复测四臂.
#
# 用法 (服务器上, 任意目录):
#   bash port_retest_server.sh            # clone/update + 四臂并行
#   bash port_retest_server.sh status     # 查看四臂进度
#
# 前置 (仅一次): 按 requirements-lock-server.txt 预置
# $PORT_WORKDIR/venv；本脚本不创建或安装环境。再把标定数据传上来:
#   scp -r data/raw_data  <user>@<server>:~/tpmshx-port/SJTU-TPMSHX-TM1/data/
#
# 四臂: ctrl4/ctrl6 × seed 7/123, SAAS, 无早停. 每臂独立算 45 点均匀扫掠
# (8 min, 避免臂间耦合). 预计墙钟 ~5-8 h (32 维臂 ~3-4 h, 72 维臂 ~5-7 h).

set -euo pipefail

WORKDIR="${PORT_WORKDIR:-$HOME/tpmshx-port}"
REPO="$WORKDIR/SJTU-TPMSHX-TM1"
BRANCH="main"
LOGD="$WORKDIR/logs/SJTU-TPMSHX-TM1"
PY="$WORKDIR/venv/bin/python"

if [ "${1:-}" = "status" ]; then
    for f in "$LOGD"/*.log; do
        [ -f "$f" ] || continue
        echo "== $(basename "$f") =="
        grep -E "\[PORT\]|\[qNEHVI\] iter|Traceback" "$f" | tail -3
    done
    exit 0
fi

mkdir -p "$WORKDIR" "$LOGD"

if [ ! -x "$PY" ]; then
    echo "FATAL: shared server Python not found: $PY"
    echo "Provision it from requirements-lock-server.txt before running this script."
    exit 1
fi

# 1. clone / update
if [ ! -d "$REPO/.git" ]; then
    git clone -b "$BRANCH" https://github.com/alexlu997/SJTU-TPMSHX-TM1.git "$REPO"
else
    git -C "$REPO" fetch origin "$BRANCH" && git -C "$REPO" checkout "$BRANCH" \
        && git -C "$REPO" pull --ff-only origin "$BRANCH"
fi

# 2. 预置环境验证（只读，不安装）
cd "$REPO"
"$PY" -m sjtu_tpmshx.runs.tools.check_locked_environment \
    requirements-lock-server.txt
"$PY" -m pip check
"$PY" -c 'import torch, botorch, gpytorch'

# 3. 标定数据在位检查 (worktree-rawdata 陷阱: 缺 raw_data 会静默回退 CSV 标定)
if [ ! -d "$REPO/data/raw_data" ]; then
    echo "FATAL: $REPO/data/raw_data 不存在 (gitignored)."
    echo "本地执行:  scp -r data/raw_data <user>@<server>:$REPO/data/"
    exit 1
fi

# 4. 四臂并行
# 注意 (2026-07-11 交接审计): 下面 export 的线程数只对 45 点均匀扫掠阶段有效.
# BO 阶段 (占墙钟绝大部分) 的 optimizer_qnehvi.py 会按 os.cpu_count() 重新切
# 内层线程 —— 它看到的是整机核数, 不知道有 4 个臂在跑 —— 并用显式的
# inner_max_num_threads 覆盖掉这里的 export, 导致四臂合计 ~4x 超订.
# TPMSHX_BO_CORE_BUDGET 是给它的显式每臂核预算; 不设时它退回整机核数(旧行为).
NCORE=$(nproc)
PER_ARM=$(( NCORE / 4 )); [ "$PER_ARM" -lt 1 ] && PER_ARM=1
THREADS=$PER_ARM; [ "$THREADS" -gt 8 ] && THREADS=8
export PYTHONHASHSEED=0
export PYTHONPATH="$REPO"
export OMP_NUM_THREADS=$THREADS MKL_NUM_THREADS=$THREADS OPENBLAS_NUM_THREADS=$THREADS NUMBA_NUM_THREADS=$THREADS
export TPMSHX_BO_CORE_BUDGET=$PER_ARM
echo "cores=$NCORE arms=4 -> 每臂预算 $PER_ARM 核, 每 worker $THREADS 线程"

launch() {  # launch <ctrl> <seed>
    local tag="c${1}s${2}"
    if [ -f "$LOGD/$tag.log" ] && grep -q "\[PORT\] DONE" "$LOGD/$tag.log"; then
        echo "skip $tag (already DONE)"; return
    fi
    nohup "$PY" -u -m sjtu_tpmshx.runs.run_port_dim_retest \
        --ctrl "$1" --seed "$2" --jobs 4 \
        > "$LOGD/$tag.log" 2>&1 &
    echo "launched $tag pid=$!"
}

launch 4 7
launch 4 123
launch 6 7
launch 6 123

echo "四臂已启动. 进度: bash $0 status"
echo "结果目录: $REPO/reports/port_dim_retest/"
