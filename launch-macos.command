#!/bin/zsh
set -eu
cd -- "${0:A:h}"

if [[ ! -f .venv-path || ! -r .venv-path ]]; then
    print -u2 -- '缺少或无法读取 .venv-path；请填写已配置 Python 解释器的绝对路径。'
    exit 1
fi
tm1_python="$(head -n 1 .venv-path)"
if [[ "$tm1_python" != /* || ! -f "$tm1_python" || ! -x "$tm1_python" ]]; then
    print -u2 -- ".venv-path 第一行必须是存在且可执行的 Python 绝对路径：$tm1_python"
    exit 1
fi
tm1_library="$PWD/native/lib/macos-arm64/libtpmshx_solver_shared.dylib"
if [[ ! -f "$tm1_library" ]]; then
    print -u2 -- "缺少随附匹配的 C++ 候选库：$tm1_library"
    exit 1
fi

export MPLCONFIGDIR="$PWD/.cache/matplotlib"
export XDG_CACHE_HOME="$PWD/.cache/xdg"
export NUMBA_CACHE_DIR="$PWD/.cache/numba"
mkdir -p -- "$MPLCONFIGDIR" "$XDG_CACHE_HOME" "$NUMBA_CACHE_DIR"
exec "$tm1_python" -m sjtu_tpmshx.main --backend cpp \
    --native-library "$tm1_library" \
    --native-table-directory "$PWD/.cache/native-deps/tables"
