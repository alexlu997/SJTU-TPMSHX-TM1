# SJTU-TPMSHX-TM1

TM1 将 TPMS 换热器的前处理、求解和后处理拆为独立维护的模块，供计算界面、
参数优化和快速设计通过公开接口调用。目标仓库为
[alexlu997/SJTU-TPMSHX-TM1](https://github.com/alexlu997/SJTU-TPMSHX-TM1)。
原 SJTU-TPMSHX/V2 是来源参考，本分支不合回原仓库。

**主体源码在 [sjtu_tpmshx/](sjtu_tpmshx/)**，前处理、求解和后处理都在这个包内。
其他根目录分别存放文档、示例、辅助工具和验证记录。

矩形 2D/3D 三模块主线的 M-A 合并验收已记录；M-B 扩展能力继续单独追踪。
历史 B40 失败与物理适用范围仍须保留。当前结论见
[架构验收](docs/plans/three-module-graph/acceptance_architecture.md) 与
[能力追踪](docs/plans/three-module-graph/acceptance_document.md)；
原计划、接管过程与各节点证据从[Graph 索引](docs/plans/three-module-graph/README.md)查阅。

## 从这里开始

| 你要做什么 | 入口 |
| --- | --- |
| 在本机运行 | [macOS / Windows 首次运行](#first-run)，含命令行算例和 GUI 启动 |
| 从界面开始使用 | [GUI 常用流程](#gui-use) |
| 阅读或修改源码 | [主体源码与模块地图](sjtu_tpmshx/README.md) |
| 理解模块边界 | [架构说明](docs/architecture.md)、[三模块数据契约](schemas/three_module_v1/) |
| 查找文档与其他目录 | [仓库目录与文档导航](docs/README.md) |
| 查阅旧版本资料 | [历史资料索引](docs/history/README.md) |

<a id="first-run"></a>

## 首次运行（macOS / Windows）

这是 Python 源码项目，下载后需要安装锁定依赖。首次运行使用 macOS + Python 3.13，
或 Windows x64 + Python 3.12，与[平台 CI](.github/workflows/ci.yml)一致。
先安装对应版本的 [Python](https://www.python.org/downloads/)，克隆方式还需要 Git。
也可在仓库页面选择 **Code → Download ZIP** 并解压；ZIP 用户直接进入解压后的
仓库根目录，跳过下面的 `git clone` / `cd`，其余命令相同。

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
"$PYTHON" -m pip install -r requirements-lock.txt
"$PYTHON" -m sjtu_tpmshx.runs.tools.check_locked_environment
"$PYTHON" -m pip check
```

**Windows（PowerShell）**

```powershell
git clone https://github.com/alexlu997/SJTU-TPMSHX-TM1.git
cd SJTU-TPMSHX-TM1
py -3.12 -m venv .venv
$tm1Python = (Resolve-Path .venv\Scripts\python.exe).Path
[System.IO.File]::WriteAllText((Join-Path $PWD '.venv-path'), $tm1Python + [Environment]::NewLine)
$tm1Python = Get-Content .venv-path -TotalCount 1
& $tm1Python -m pip install -r requirements-lock.txt
& $tm1Python -m sjtu_tpmshx.runs.tools.check_locked_environment
& $tm1Python -m pip check
```

这里直接调用环境内解释器，无需激活脚本或修改 PowerShell 执行策略；这是
[Python venv 支持的用法](https://docs.python.org/3.13/library/venv.html#how-venvs-work)。
`.venv-path` 保存本机绝对路径，不随 Git 共享；新终端中重新读取该文件即可。

### 跑通小算例

仓库自带 [air_2d.json](examples/three_module/air_2d.json) 和
[air_3d.json](examples/three_module/air_3d.json)，使用随源码提供的模型资源，
不需要私有 `data/` 或 `.git`。首次求解包含 Numba 编译，可能需要数分钟。

macOS：

```bash
PYTHON="$(head -n 1 .venv-path)"
export MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg"
export NUMBA_CACHE_DIR="$PWD/.cache/numba"
"$PYTHON" -m sjtu_tpmshx.cli run examples/three_module/air_2d.json .cache/first-run-2d --case-id first-run-2d
"$PYTHON" -m sjtu_tpmshx.cli run examples/three_module/air_3d.json .cache/first-run-3d --case-id first-run-3d
"$PYTHON" -m sjtu_tpmshx.main
```

Windows：

```powershell
$tm1Python = Get-Content .venv-path -TotalCount 1
$env:MPLCONFIGDIR = Join-Path $PWD '.cache/matplotlib'
$env:XDG_CACHE_HOME = Join-Path $PWD '.cache/xdg'
$env:NUMBA_CACHE_DIR = Join-Path $PWD '.cache/numba'
& $tm1Python -m sjtu_tpmshx.cli run examples/three_module/air_2d.json .cache/first-run-2d --case-id first-run-2d
& $tm1Python -m sjtu_tpmshx.cli run examples/three_module/air_3d.json .cache/first-run-3d --case-id first-run-3d
& $tm1Python -m sjtu_tpmshx.main
```

前两条计算命令分别输出 `case.yaml`、伴随 `case.h5`、`results.h5` 和
`metrics.json`；最后一条启动图形界面。CLI 输入文件与 GUI 会话文件格式不同，
上述 JSON 用于命令行。打开对应 `metrics.json`，五项基本指标应为 `available`，
参考值如下（近似值用于核对运行结果）：

| 算例 | Q | Δp A / B（Pa） | 出口温度 A / B（K） |
| --- | --- | --- | --- |
| air_2d | 31032.26 W/m | 1665.93 / 1212.49 | 304.24 / 334.70 |
| air_3d | 338.49 W | 1945.25 / 3044.93 | 359.20 / 344.94 |

完整计算的 `Q` 统一为主网格 A 侧原始边界焓流绝对值。`Q_A`、`Q_B` 保留
有符号的两侧换热量，二维 Richardson 外推值另列，不替代主指标。
指标定义版本为 `native_boundary_v1`；旧指标文件保留原定义，旧原生结果可重新后处理。

输入中的网格数为请求值，前处理可能细化实际网格。两个算例用于安装和模块交接检查，
不代表实验精度验收；3D 示例显式允许相关式外推，原生警告会保留。
`run` 返回码 0 表示收敛且基本指标可用，2 表示未收敛或指标不可用，130 表示合作式取消；
其他输入／文件错误会报错退出。Mac 用 `echo $?`，PowerShell 用 `$LASTEXITCODE`
查看紧接着上一条命令的返回码。不要通过放宽阈值消除失败。

默认锁包含 GUI、文件交接和测试依赖，不包含 Torch / BoTorch / GPyTorch。
贝叶斯优化的 Windows CPU 环境另见 `requirements-lock-server.txt`；上述小算例
无需 BO。原始实验回归与重新拟合则需要匹配版本的本地数据，见文末。

<a id="gui-use"></a>

## GUI 常用流程

1. 启动 `sjtu_tpmshx.main`，载入算例预设或填写左侧“几何与结构”“流体”。
   在“网格与求解器”“边界细节与高级”中核对维度、网格和开口。
2. 点击底部“计算”（Ctrl+R）。完成后进入“结果”，选择温度、压力或速度；
   右侧查看收敛、能量闭合、适用域警告和“诊断详情”。数值可显示不等于验收通过。
3. 用保存/导出菜单保存配置、结果或图像。GUI 会话保留界面状态；正式模块交接
   使用 `case.yaml` 与伴随 HDF5、`results.h5`，两者用途不同。

二维边界中的“开口内均匀”控制入口速度分布；上海预设的水侧默认启用，
开口位置和总流量不变。未启用时保留历史边缘平滑分布。预设会保存该选择；
旧预设缺少此项时沿用历史分布。三维入口已使用均匀分布，不受此项影响。

“快速设计”从给定流体工况、换热需求与压损约束筛选尺寸，使用规定速度的近似模型。
“优化”页进行空气/空气连续场筛选与 Pareto 比较，BO 需另配对应锁定环境。
命令面板中的 `Sensitivity sweep` 是两个参数的局部趋势热图，使用空气、固定 40 K
温差估算；它不是当前完整工况的重新求解，也不替代最终计算。

输入文件分三类：CLI 配置（`air_2d.json` / `air_3d.json`）、GUI 会话/预设、
快速设计的 `DesignCase`。字段与单位不同，不能互相当作输入；
最小 DesignCase 和扩展示例见[工具说明](docs/tools.md#公开模块扩展示例)。

## 三个模块

```text
应用输入 → preprocess → CaseData → solvers → FieldResult → postprocess → PerformanceResult
                         YAML/HDF5             HDF5/VTK                   JSON
```

前处理确定实际网格、边界、设计场、固定几何、模型资源和运行设置。求解消费准备好的
CaseData，温度相关物性和数值迭代在求解侧执行。后处理从 FieldResult 的原生场、通量、
压力和状态计算指标，缺数据时报告原因；不启动求解或读取 GUI、活动求解器对象。

```python
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.postprocess.api import evaluate

case = prepare_case(config, case_id="example")
result = run_case(case)
metrics = evaluate(result)
```

同进程不强制落盘。独立进程使用正式文件交接：

```bash
PYTHON="$(head -n 1 .venv-path)"
mkdir -p .cache/handoff
"$PYTHON" -m sjtu_tpmshx.cli prepare examples/three_module/air_2d.json .cache/handoff/case.yaml --case-id example
"$PYTHON" -m sjtu_tpmshx.cli solve .cache/handoff/case.yaml .cache/handoff/results.h5
"$PYTHON" -m sjtu_tpmshx.cli postprocess .cache/handoff/results.h5 .cache/handoff/metrics.json
```

PowerShell 使用相同参数，将 `"$PYTHON"` 改为 `& $tm1Python`，目录先用
`New-Item -ItemType Directory -Force .cache/handoff` 创建。
各阶段参数可用 `"$PYTHON" -m sjtu_tpmshx.cli prepare --help` 等查看，PowerShell 同样使用 `& $tm1Python`。

Case YAML 引用伴随 HDF5；result/VTK 导出和严格指标 JSON 的限制见
[schema](schemas/three_module_v1/)。取消与失败不伪装成完成结果；已完成但未收敛的
结果保留原状态。指标有限不等于数值、能量或实验精度验收通过。

## 已接线能力与边界

| 用途 | 公开入口 | 数量口径 |
| --- | --- | --- |
| 矩形全模型 2D/3D | `prepare_case`，随后 `run_case` / `evaluate` | 2D Q 为 W/m；3D Q 为 W |
| 优化筛选 2D/3D | `prepare_screening_2d/3d`，随后相同求解和后处理 API | 核心 3D 为总量；优化目标在应用层按真实 Lz 归一 |
| 快速设计 | `prepare_quick_design`，随后相同 API | 规定速度 LTNE 与解析入口压损，非完整 SIMPLE；Q 为 W |
| 参数扫描与有效场输入 | [公开示例](examples/) | 不改求解器私有成员 |
| 离线清洗与 Nu 拟合 | `preprocess.offline` | 显式选择数据来源，不自动替换生产模型；旧 RBF 发布入口已退役 |

连续场优化目前限于空气/空气、A 沿 +x、B 沿 −y 的交叉流筛选；其他流体或
流向会明确拒绝。GUI 优化使用整面开口；2D API 可显式给出 `ports_A/B`，
3D 筛选仅支持整面开口。优化搜索的几何范围为 L=4–8 mm、t=0.3–0.6 mm，
各流体 Nu 的适用范围另行检查。每次优化保存完整 `config.json`；结果的场预览
和 nTop 导出使用原配置。Pareto 点回填普通计算框只提供平均 L/t，不能重建梯度场。

当前计算域仅支持 **Rectangle（矩形）2D/3D**。Hexagon / Octagon 计算路线已退役，
旧多边形配置仍可查看、保存，但点击计算会明确拒绝，也不会自动改成矩形。
旧多边形代码通过[固定历史](docs/history/retired-tools.md)保留，重新开放须完成
主线物理规则及独立模块交接的实现与验证。

`models/`、`df_surrogate/` 等是共享技术支撑，不是第四个业务模块。旧 Pipeline/应用
入口单向调用公开模块。具体边界见[架构说明](docs/architecture.md)。

实际后端为 Python/Numba。C++、OpenFOAM、REFPROP 等提供器、扩展 h/f/PEC 定义与
伴随能力继续按 M-B/原文限定追踪，不能据目录或接口声明为已实现。

## 环境与检查

本地 Python 必须使用 `.venv-path` 第一行的绝对解释器。缺失时先配置合规环境；
代理不自动创建、升级或重装共享环境。依赖声明与精确锁同时维护，共享 venv
只安装锁定依赖，不把当前项目 editable 安装进去。命令从当前仓库根运行。

```bash
PYTHON="$(head -n 1 .venv-path)"
"$PYTHON" -m sjtu_tpmshx.runs.tools.check_locked_environment
"$PYTHON" -m pip check
export MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg"
export QT_QPA_PLATFORM=offscreen PYTHONHASHSEED=0
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export NUMBA_NUM_THREADS=2
"$PYTHON" -m pytest sjtu_tpmshx/tests -q -m "not slow and not heavy" --timeout=600 --timeout-method=thread
"$PYTHON" -m pytest sjtu_tpmshx/tests/integration_tm1 -q --timeout=600 --timeout-method=thread
# 完整本地验收：没有 -m 过滤；按本机 CPU/内存可将 auto 换为固定 worker 数。
"$PYTHON" -m pytest sjtu_tpmshx/tests -q -n auto --dist loadscope --timeout=600 --timeout-method=thread
```

PowerShell 使用同样的 pytest 参数，并以 `$env:NUMBA_NUM_THREADS='2'` 等设置
上述环境变量，以 `& $tm1Python` 调用解释器。Numba 上限至少为 2，因为焓输运测试
显式运行双线程检查。固定 128 核服务器的并行预算见 `scripts/run_tests_server.ps1`；
`run_tests_fast.ps1` 只提供开发反馈，其 `not heavy` 子集与 CI 快测不同。

第一条 pytest 排除了 slow/heavy，不能代替真实集成或第三条完整本地验收。
完整验收的 skip 须保留具体原因，不能当作被跳过能力已经通过。最小后处理 CI 使用独立的
`requirements-lock-postprocess.txt` 环境，并消费另一完整环境生成的真实 2D/3D
结果文件；文件留在 CI 作业本地，不上传结果 artifact。配置不等于实际 CI 通过。

## 协作与合并

公开契约的修改需要检查下游消费者：前处理的配置/单位/网格由求解侧复核；求解的
原生场/边界证据/状态由后处理侧复核；指标定义及文件关联由应用/文件消费者复核。
GUI 和调度留在 `ui/`、`controllers/`，模型资源保持共享。每个 PR 写明受影响的
接口、验证证据和参与复核者。当前仓库维护者为 `alexlu997`；师兄加入后再分配具名
模块责任人，当前不建立虚构的 CODEOWNERS 或把模型自查写成人工独立批准。

2026-09-13 已回读核验 main 保护：通过 PR 更新，要求分支与 main 同步，并通过
`tests (macos-14, 3.13)`、`tests (windows-2022, 3.12)`、`minimal-postprocess`
三项 GitHub Actions 检查；管理员同样受约束，禁止强推和删除。多人正式参与后
再启用至少一位非作者批准；目前平台所需批准人数为 0。实际状态以 GitHub 为准。

本阶段主计算可靠性与性能任务的范围和验收见
[现行计划](docs/plans/main-compute-20260913.md)。

## 数据与历史证据

原始实验/CFD 数据位于本地 `data/raw_data/`，不提交。匹配版本见
[data-revision.txt](data-revision.txt)。清洗、拟合和本地输出规则见
[离线模型说明](docs/plans/three-module-graph/decisions/offline_models.md)。
目录按实验、CFD 结果和工况计划分类；Excel 的新旧名称、用途及读取约束见
[数据目录与文件名对照](docs/data-catalog.md)。移动数据时须同步加载器和压力口径识别。

旧 γ/RBF、SmoothDF、水发展段及旧 sCO2 阻力模型已退役，代码和结果见
[固定历史索引](docs/history/legacy-models.md)。当前联合 K/cF、原水 Nu 和实验修正继续使用。
当前水 CFD 工作簿缺失时不以旧版文件替代。

原 README 的历史精度与物理说明原样保存在
[V2 README 存档](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/docs/history/v2-readme.md)，旧图片链接固定到历史提交。
已移出当前文件树的图片、优化输出、探索记录与 Atlas 快照见
[历史资料索引](docs/history/README.md)。
这些数字不是 TM1 或当前默认 CFD 模式的新验收。B40 原锁定测试 4/4 失败、
3D 筛选未收敛及其他原生失败证据继续保留；不改阈值或物理范围迎合结果。
