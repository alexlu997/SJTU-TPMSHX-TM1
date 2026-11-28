# 从源码运行 TM1

[中文](first-run.md) · [English](first-run.en.md) · [返回首页](../README.md)

所有命令均在仓库根目录执行。先完成本机配置，再运行小算例。

<a id="first-run"></a>

## 安装锁定环境

这是 Python 源码项目，下载后需要安装锁定依赖。首次运行使用 macOS + Python 3.13，
或 Windows x64 + Python 3.12 / 3.13，与[平台 CI](../.github/workflows/ci.yml)一致。
先安装对应版本的 [Python](https://www.python.org/downloads/)。完整原生依赖的获取与校验需要 Git 工具。
也可在仓库页面选择 **Code → Download ZIP** 并解压。从解压后的源码根目录运行命令，
跳过下面的 `git clone` 和 `cd`。

以下环境创建和安装步骤仅用于首次配置。已有合规 `.venv-path` 时直接复用，
不要覆盖共享环境。所有命令均在包含 `pyproject.toml` 的仓库根目录逐条执行；
任一步报错或环境检查失败，先处理该错误再继续。

**macOS（Terminal，zsh / bash）**

```bash
git clone https://github.com/alexlu997/SJTU-TPMSHX-TM1.git
cd SJTU-TPMSHX-TM1
python3.13 -m venv .venv
printf '%s\n' "$PWD/.venv/bin/python" > .venv-path
PYTHON="$(head -n 1 .venv-path)"
"$PYTHON" -m pip install -r engineering/requirements/base.txt
"$PYTHON" -m tm1.development.runs.tools.check_locked_environment
"$PYTHON" -m pip check
```

**Windows（PowerShell）**

Python 3.12 和 3.13 使用相同的依赖锁。以下以 3.13 为例；选择 3.12 时，
将创建环境命令中的 `-3.13` 改为 `-3.12`，其余步骤相同。

```powershell
git clone https://github.com/alexlu997/SJTU-TPMSHX-TM1.git
cd SJTU-TPMSHX-TM1
py -3.13 -m venv .venv
$tm1Python = (Resolve-Path .venv\Scripts\python.exe).Path
[System.IO.File]::WriteAllText((Join-Path $PWD '.venv-path'), $tm1Python + [Environment]::NewLine)
$tm1Python = Get-Content .venv-path -TotalCount 1
& $tm1Python -m pip install -r engineering/requirements/base.txt
& $tm1Python -m tm1.development.runs.tools.check_locked_environment
& $tm1Python -m pip check
```

这里直接调用环境内解释器，无需激活脚本或修改 PowerShell 执行策略；这是
[Python venv 支持的用法](https://docs.python.org/3.13/library/venv.html#how-venvs-work)。
`.venv-path` 保存本机绝对路径，不随 Git 共享；新终端中重新读取该文件即可。

常规安装 wheel 时，h5py 和 PyYAML 随包安装，用于读写工况和结果文件。
`offline` 可选依赖组提供 Python 版 CoolProp，供 `preprocess.offline` 中的 sCO₂ CFD 读取器使用。
`test` 可选依赖组提供测试参考计算所需的 SymPy、scikit-image 和 Python 版 CoolProp。
源码开发使用的基础锁已包含上述依赖。

升级到当前依赖锁时，请创建独立的新环境并预热，保留原环境及其源码版本。
0.2 的基础锁删除 Numba、llvmlite 和 PyAMG，保留前后处理、优化及界面所需依赖。
原生压力求解仍使用其已移植的算法及许可声明，不加载 Python PyAMG。
BO 与桌面打包继续使用各自的完整锁。不要向其他工作树正在使用的共享环境安装新锁。
切换 `.venv-path` 后，先通过锁检查和 `pip check`，再运行计算或测试。
CO₂ 插值表按 CoolProp 版本隔离。Python 默认写入 `XDG_CACHE_HOME/coolprop/CoolProp-8.0.0`；
显式 `COOLPROP_ALTERNATIVE_TABLES_DIRECTORY` 和 C++ 表参数均作为缓存根目录，
内部追加 `CoolProp-8.0.0`。旧表保留，首次使用新版本时会在本机重新生成。

<a id="examples"></a>

## 运行二维和三维算例

仓库自带 [air_2d.json](../examples/three_module/air_2d.json) 和
[air_3d.json](../examples/three_module/air_3d.json)，使用随源码提供的模型资源，
不需要私有 `data/` 或 `.git`。首次运行前先构建本机 C++ 几何库、准备库、求解库与结果库：使用 macOS C++
工具链，或 Windows x64 的 MSVC 开发者终端。构建和物性表首次生成的耗时与求解耗时分开。

macOS：

```bash
PYTHON="$(head -n 1 .venv-path)"
export MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg"
"$PYTHON" engineering/scripts/build_native_dependencies.py fetch
"$PYTHON" engineering/scripts/build_native_dependencies.py publish
"$PYTHON" main.py run examples/three_module/air_2d.json .cache/first-run-2d --case-id first-run-2d
"$PYTHON" main.py run examples/three_module/air_3d.json .cache/first-run-3d --case-id first-run-3d
"$PYTHON" main.py
```

Windows：

```powershell
$tm1Python = Get-Content .venv-path -TotalCount 1
$env:MPLCONFIGDIR = Join-Path $PWD '.cache/matplotlib'
$env:XDG_CACHE_HOME = Join-Path $PWD '.cache/xdg'
& $tm1Python engineering/scripts/build_native_dependencies.py fetch
& $tm1Python engineering/scripts/build_native_dependencies.py publish
& $tm1Python main.py run examples/three_module/air_2d.json .cache/first-run-2d --case-id first-run-2d
& $tm1Python main.py run examples/three_module/air_3d.json .cache/first-run-3d --case-id first-run-3d
& $tm1Python main.py
```

前两条计算命令分别输出 `case.yaml`、伴随 `case.h5`、`results.h5` 和
`metrics.json`；最后一条启动图形界面。CLI 输入文件与 GUI 会话文件格式不同，
上述 JSON 用于命令行。打开对应 `metrics.json`，五项基本指标应为 `available`，
参考值如下（2026-10-02 当前实现复核，近似值用于核对运行结果；
二维修订前数值保留于[历史索引](history/README.md)）：

| 算例 | Q | Δp A / B（Pa） | 出口温度 A / B（K） |
| --- | --- | --- | --- |
| air_2d | 31131.52 W/m | 1626.03 / 1188.81 | 303.28 / 334.79 |
| air_3d | 338.33 W | 1944.17 / 3038.38 | 359.23 / 344.93 |

空气现按真实端口面的面积平均值校准入口绝压，误差低于0.01%才满足该项收敛条件；
压力和热量收敛定义见[架构说明](architecture.zh-CN.md)。
当前空气阻力系数、标定来源与适用范围见[模型资源](model-resources.md)；
阶段修复与实验对照报告从[历史索引](history/README.md)查阅。

完整计算的 `Q` 统一为主网格 A 侧原始边界焓流绝对值。`Q_A`、`Q_B` 保留
有符号的两侧换热量，二维 Richardson 外推值另列，不替代主指标。
两维度的压降统一按物理端口面压力、几何开口面积加权，定义版本为
`pressure_face_v1`。数值网格精度与实验预测误差分别评估，历史测量只代表
其记录的代码、工况与配置，见[历史索引](history/README.md)。
热量、温度及流量指标的定义版本为 `native_boundary_v1`；旧指标文件保留原定义，
旧原生结果可重新后处理。

输入中的网格数为请求值，前处理可能细化实际网格。两个算例用于安装和模块交接检查，
不代表实验精度验收；3D 示例显式允许相关式外推，原生警告会保留。
`run` 返回码 0 表示收敛且基本指标可用，2 表示未收敛或指标不可用，130 表示合作式取消；
其他输入／文件错误会报错退出。Mac 用 `echo $?`，PowerShell 用 `$LASTEXITCODE`
查看紧接着上一条命令的返回码。不要通过放宽阈值消除失败。

默认锁包含 GUI、文件交接和测试依赖，不包含 Torch / BoTorch / GPyTorch。
贝叶斯优化的 Windows CPU 环境另见 `engineering/requirements/bo-windows.txt`；macOS arm64 /
Python 3.13 使用 `engineering/requirements/bo-macos.txt`。已授权的 BO 任务使用独立环境，
随后用对应锁运行环境检查及 `pip check`；勿将可选依赖加到正在使用的共享基础环境。
上述小算例无需 BO。原始实验回归与重新拟合则需要[匹配版本的本地数据](verification.md#数据与历史证据)。

BoTorch 首次构造多目标 Log 采集函数时会尝试编译其可选 C++ 内核。
将 `TORCH_EXTENSIONS_DIR` 设为当前工作树的 `.cache/torch-extensions`，并在该次运行的
`PATH` 前放置 BO 环境的 `bin`（Windows 为 `Scripts`），使已锁定的 Ninja 可用。
编译还需要本机 C++ 工具链；无法编译时 BoTorch 会报告并使用其 Python 实现。
两种执行方式的性能证据需分别记录，首次编译不能计入暖态求解耗时。

<a id="native-libraries"></a>

## 构建、发布和查找原生库

本次交付保留 Python/Qt 主程序和源码，在项目内放置匹配的预编译 C++ 库，
不制作 `.app`。随附库面向本机 macOS 27 / arm64；其他系统、机器和旧版
macOS 尚未验收。继续复用 `.venv-path` 指定的现有锁定环境，环境检查同上。

在项目根目录运行：

```sh
"$(head -n 1 .venv-path)" main.py
```

`main.py` 加载 `native/lib/macos-arm64/libtpmshx_solver_shared.dylib`，并使用
`.cache/native-deps/tables`。库、表和本机 `.venv-path` 属于本地交付资源，
不随 Git 源码自动提供。计算开始时会报告缺少的库；`main.py` 不安装依赖，
也不编译库。T-SOU 使用带检查的 HEOS PT 物性，不创建 EOS 表；表目录选项保留给显式选择的历史运行库。公共 API、CLI 和直接模块调用默认使用 C++。

已有当前锁定原生依赖、pilot 构建目录已指向当前源码布局，且相关原生回归通过时，可显式发布求解库、几何库、准备库与结果库。旧布局项目须先按下文升级步骤准备新缓存。

```sh
"$PYTHON" engineering/scripts/build_native_dependencies.py publish
```

从旧的根目录 `native/` 布局升级时，先保留原 `native/lib/` 下的库、`build.json` 和 `previous/`。旧检查点仍须显式选择匹配的原库。保留仍有消费者的旧缓存及其绝对路径。旧 pilot 构建目录记录了原源码位置，不能直接用于新布局。

已有项目须选择一个尚未使用的缓存目录。以下以 `.cache/native-layout` 和基础环境锁为例；若 `.venv-path` 指向 BO 环境，将发布命令的锁换成对应的 `engineering/requirements/bo-macos.txt` 或 `engineering/requirements/bo-windows.txt`。

macOS：

```sh
"$PYTHON" engineering/scripts/build_native_dependencies.py fetch --cache .cache/native-layout
"$PYTHON" engineering/scripts/build_native_dependencies.py publish --cache .cache/native-layout --python-lock engineering/requirements/base.txt
```

Windows（PowerShell）：

```powershell
& $tm1Python engineering/scripts/build_native_dependencies.py fetch --cache .cache/native-layout
& $tm1Python engineering/scripts/build_native_dependencies.py publish --cache .cache/native-layout --python-lock engineering/requirements/base.txt
```

`publish` 包含构建和验证。后续显式执行 `build`、`verify` 或 `publish` 时，继续使用同一 `--cache` 目录。首次克隆的项目可使用上文默认缓存。

此命令离线构建并验证求解库、几何库、准备库与结果库，再以同一事务替换本平台的四个库。
缺少锁定依赖或验证失败时停止。改变库内容前，旧库及匹配记录保存在同目录的 `previous/`；
重复发布相同库保留已有回退副本。求解库使用 `build.json`，几何库使用 `geometry-build.json`，准备库使用 `preparation-build.json`，结果库使用 `result-build.json`，
分别记录构建配置、路径和可用的 Git 来源。替换失败恢复选定库及元数据。回滚失败保留暂存文件并报告恢复路径。
`native/lib/` 是 Git 忽略的本地交付目录。停止相关程序后，回退选定组件时，
从 `previous/` 恢复该库及对应记录，同时恢复匹配源码、Python 环境和物性版本。
发布检查不替代数值回归或桌面验收。日常启动不执行构建、安装或下载。

仅更新几何时，可使用锁定 CMake 工具与独立几何目标；环境锁仍须匹配当前解释器：

```sh
"$PYTHON" engineering/scripts/build_native_dependencies.py fetch-cmake
"$PYTHON" engineering/scripts/build_native_dependencies.py publish --component geometry --python-lock engineering/requirements/base.txt
```

Windows PowerShell 使用：

```powershell
& $tm1Python engineering/scripts/build_native_dependencies.py fetch-cmake
& $tm1Python engineering/scripts/build_native_dependencies.py publish --component geometry --python-lock engineering/requirements/base.txt
```

BO 环境仍须替换为对应 BO 锁。独立 `build`／`verify` 同样接受 `--component geometry`。
几何单独发布不构建或替换 solver/run_state；旧检查点仍须保留精确匹配的求解运行库。
运行时用 `TPMSHX_GEOMETRY_LIBRARY` 选择默认目录外的几何库；读取历史结果与独立后处理不加载几何库。
准备库也可独立更新。先在同一缓存构建锁定 CoolProp，再执行 `publish --component preparation`；
该命令不构建求解器或 run_state，只发布准备库及 `preparation-build.json`。命令见[准备核心](cpp-migration.zh-CN.md#native-preparation-core)。
运行时用 `TPMSHX_PREPARATION_LIBRARY` 选择准备库。读取历史结果与独立后处理不加载准备库。
结果库可用 `publish --component result` 独立发布，不构建求解器或模型库。使用当前解释器对应的精确锁。
完整 2D/3D 评估及三个独立结果查询需要包含当前结果阶段的库。
Quick Design 指标也由原生阶段根据 `float64` 操作数评估；纯 HDF/JSON 文件读取不加载原生库。
Linux x86_64 只支持独立结果评估，命令见[结果核心](cpp-migration.zh-CN.md#native-result-core)。
Python wheel 包含运行代码、已发布的开发／验证工具和模型资源，不包含测试或这四个本机原生库。
Git 和源码发行包保留完整测试树，包括原生测试桥；源码发行包还包含原生源码、构建文件、依赖锁和来源记录。
可用 `engineering/scripts/check_distributions.py` 检查源码包与 wheel 内容。
须通过 `--output-dir` 指定 `.cache/` 下的新目录。
原生构建仍是环境配置后的显式步骤。

GUI 不再提供后端切换；普通计算、快速设计和优化统一使用 C++。
启动时可指定库，或使用本机 macOS／Windows 交付目录中的匹配库；缺库时明确报错。
“计算线程数”的“自动”最多使用本机的 8 个逻辑 CPU。此选择属于当前窗口的运行设置，
不写入工况文件，也不改变已经生成的结果。

源码 GUI 和 CLI 共用默认查找：macOS 使用
`native/lib/macos-arm64/libtpmshx_solver_shared.dylib`，Windows 使用
`native/lib/windows-x64/tpmshx_solver_shared.dll`；默认表目录为
`.cache/native-deps/tables`。匹配库已发布到这些位置时无需指定后端。
显式库／表路径优先；API 可通过 `RunControl` 覆盖主机路径。

Windows x64 用户和没有已发布原生库的 macOS 用户，按
[项目文件夹运行说明](desktop.md#source-folder)显式传入原生库与可写表目录。

<a id="stage-api"></a>

## 三个模块

```text
应用输入 → preprocess → CaseData → solvers → FieldResult → postprocess → PerformanceResult
                         YAML/HDF5             HDF5/VTK                   JSON
```

前处理确定实际网格、边界、设计场、固定几何、模型资源和运行设置。求解消费准备好的
CaseData，温度相关物性和数值迭代在求解侧执行。后处理从 FieldResult 的原生场、通量、
压力和状态计算指标，缺数据时报告原因；不启动求解或读取 GUI、活动求解器对象。

```python
from tm1.preprocess.api import prepare_case
from tm1.solvers.api import run_case
from tm1.postprocess.api import evaluate

case = prepare_case(config, case_id="example")
result = run_case(case)
metrics = evaluate(result)
```

同进程不强制落盘。独立进程使用正式文件交接：

```bash
PYTHON="$(head -n 1 .venv-path)"
mkdir -p .cache/handoff
"$PYTHON" main.py prepare examples/three_module/air_2d.json .cache/handoff/case.yaml --case-id example
"$PYTHON" main.py solve .cache/handoff/case.yaml .cache/handoff/results.h5
"$PYTHON" main.py postprocess .cache/handoff/results.h5 .cache/handoff/metrics.json
```

PowerShell 使用相同参数，将 `"$PYTHON"` 改为 `& $tm1Python`，目录先用
`New-Item -ItemType Directory -Force .cache/handoff` 创建。
各阶段参数可用 `"$PYTHON" main.py prepare --help` 等查看，PowerShell 同样使用 `& $tm1Python`。

Case YAML 引用伴随 HDF5；result/VTK 导出和严格指标 JSON 的限制见
[schema](contracts/three_module_v1/README.zh-CN.md)。CLI 输出必须与本次输入文件及 Case 的伴随 HDF5
分开，路径重合会在执行阶段前拒绝；独立的既有输出仍可更新。
所有 CLI 阶段均拒绝向含 `run.json` 或 `checkpoint.h5` 的目录及其子目录写入；请选择新目录，以保留已保存的运行及原生库。
取消与失败不伪装成完成结果；已完成但未收敛的
结果保留原状态。指标有限不等于数值、能量或实验精度验收通过。

C++ 完整计算可以将迭代状态保存在新的运行目录：

```bash
"$PYTHON" main.py run examples/three_module/air_2d.json .cache/run-01 --case-id example --backend cpp --checkpoint-interval 60
"$PYTHON" main.py resume .cache/run-01/checkpoint.h5 .cache/run-02 --checkpoint-interval 60
```

CLI 保存间隔须显式指定；保存会等待下一个完整求解步骤结束。
启用保存后，Ctrl+C 请求暂停，进程在保存状态后返回退出码 3。
暂停不产生完成结果，取消仍返回退出码 130。
运行目录保留准备态输入、原生库、检查点与运行状态；完成后另有 `results.h5` 和 `metrics.json`。

硬链接可用时，重复保存共享固定原生库和已归档基准场；每个目录仍保留本地文件路径，其他文件系统使用独立副本。
共享快照应按只读文件使用；更新时通过 TM1 写入器整体替换，不直接原地改写内容。
已保存运行不会自动精简；任务证据遵守[存储保留原则](collaboration.zh-CN.md#storage-retention)。

续算读取已保存的准备态输入，写入新目录并保留原运行。移动时须一起移动整个运行目录。
续算要求相同的原生构建和平台；当前构建不同时，可用 `--native-library` 显式选择保留的库。
GUI 的载入菜单可以继续已保存的运行，沿用记录的保存间隔和输入来源。
新发起的 GUI C++ 完整计算每 60 秒请求保存，运行目录位于用户数据目录的 `development/runs/` 下。
计算详情显示保存位置；可用“保存并暂停”结束当前任务，再从载入菜单继续。
实际重算量还可能包含当前完整计算步和写盘时间。

## 已接线能力与边界

| 用途 | 公开入口 | 数量口径 |
| --- | --- | --- |
| 矩形全模型 2D/3D | `prepare_case`，随后 `run_case` / `evaluate` | 2D Q 为 W/m；3D Q 为 W |
| 连续场多工况优化 2D/3D | `run_multi_condition_optimization`，经完整 Case 求解及数值检查 | 默认模式比较换热改善与相对压降；芯体减重模式输出 kg，并约束逐工况换热和压降；2D 总量按明确厚度换算 |
| 快速设计 | `prepare_quick_design`，随后相同 API | 规定速度 LTNE 与解析入口压损，非完整 SIMPLE；Q 为 W |
| 参数扫描与有效场输入 | [公开示例](../examples/) | 不改求解器私有成员 |
| 离线清洗与 Nu 拟合 | `preprocess.offline` | 显式选择数据来源，不自动替换生产模型；旧 RBF 发布入口已退役 |

当前 GUI 连续场优化沿用完整算例的端口、流体和本维度求解设置，支持空气 A / 水 B 及含 CO₂/sCO₂ 的双流体组合，
默认搜索 L=4–8 mm、t=0.3–0.6 mm，各流体 Nu 的适用范围另行检查。
`optimization.json` 保存全部工况、控制向量、场定义、失败和原生批次路径；
它与 `batch.json` 均通过 `backend` 记录本轮选择，包括失败和取消，不记录本机库路径。
只有完整数值合格的批次才有目标值。model-h 保留原有能量检查；true-h 使用自身的
收敛、无焓裁剪、耦合及方程能量证据，不能用 model-h 证书代替。GUI 来源的 Pareto 回填保留完整场，
当前几何、端口或求解设置与来源不同则拒绝载入。任意外部 CLI 配置不等于 GUI 预设。
设计评估次数是搜索预算，不保证算法收敛或实验精度。

旧空气／空气优化筛选及其 2D、冻结 B 侧的 3D 求解入口已退役，见
[历史索引](history/retired-tools.md)。旧结果归档仍可读取，原配置对应的
Pareto CSV 仍可导出几何；旧筛选模式不能再执行或重新计算指标。

当前计算域仅支持 **矩形二维／长方体三维**，界面直接显示形状，不提供只有一个有效选项的下拉菜单。
六边形／八边形计算路线已退役，旧多边形配置在载入前明确拒绝，保留当前输入与结果；
多边形启动会话也不会恢复或转换成矩形。旧矩形文件仍可正常载入。
旧多边形代码通过[固定历史](history/retired-tools.md)保留，重新开放须完成
主线物理规则及独立模块交接的实现与验证。

`python/physical_models/`、`python/physical_models/df_surrogate/` 等是共享技术支撑，不是第四个业务模块。旧 Pipeline/应用
入口单向调用公开模块。具体边界见[架构说明](architecture.zh-CN.md)。

唯一数值后端为 C++。默认查找 macOS arm64 或 Windows x64 本机库，
也可用 `RunControl(native_library=...)` 或 CLI `--native-library` 指定路径。
Quick Design 和完整二维／三维求解的构建及能力边界见
[C++ 说明](cpp-migration.zh-CN.md#cpp-core-scope)。各批实现范围与交付记录集中在该文档。
可见桌面交付、完整性能与实验精度分别验收。

完整二维接口为 ABI 2，必须同步分发库、头文件和适配器。
Python 数值后端、混合 sweep 入口及 Python 专用研究入口均已退役。
旧结果仍可读取；旧研究 Case 不再执行，普通工况须通过当前 `ComputeConfig` 准备。
OpenFOAM、REFPROP 等提供器、扩展 h/f/PEC 定义与伴随能力继续按
M-B/原文限定追踪，不能据目录或接口声明为已实现。
