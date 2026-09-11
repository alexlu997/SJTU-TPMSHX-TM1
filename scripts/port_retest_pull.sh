#!/usr/bin/env bash
# port_retest_pull.sh — 从 pyfluent 服务器拉回端口复测结果 (本地执行).
#
# 用法 (TM1 仓库根目录): bash scripts/port_retest_pull.sh <user>@<server>
# 可选:  PORT_WORKDIR=~/tpmshx-port (与服务器脚本一致时不用改)

set -euo pipefail
HOST="${1:?用法: bash scripts/port_retest_pull.sh <user>@<server>}"
REMOTE="${PORT_WORKDIR:-~/tpmshx-port}/SJTU-TPMSHX-TM1/reports/port_dim_retest"
PYTHON="$(head -n 1 .venv-path)"
if [ ! -x "$PYTHON" ]; then
    echo "FATAL: .venv-path interpreter not found: $PYTHON" >&2
    exit 1
fi
"$PYTHON" -m sjtu_tpmshx.runs.tools.check_locked_environment
"$PYTHON" -m pip check

mkdir -p reports
scp -r "$HOST:$REMOTE" reports/
echo "== 四臂判决 =="
for j in reports/port_dim_retest/*/port_metrics.json; do
    "$PYTHON" - "$j" <<'EOF'
import json, sys
m = json.load(open(sys.argv[1]))
print(f"{sys.argv[1].split('/')[-2]:>16}: D={m['decision_dim']:>2}  "
      f"HV gain {m['hv_gain_pct']:+6.2f}%  dominated {m['uniform_dominated_frac']*100:3.0f}%  "
      f"({m['budget']['graded']} evals, {m['wall_seconds']/3600:.1f} h)")
EOF
done
