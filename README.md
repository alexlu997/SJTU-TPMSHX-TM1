# SJTU-TPMSHX-TM1

TM1 将 TPMS 换热器的前处理、求解和后处理拆为独立维护的模块，供计算界面、
参数优化和快速设计通过公开接口调用。目标仓库为
[alexlu997/SJTU-TPMSHX-TM1](https://github.com/alexlu997/SJTU-TPMSHX-TM1)。
原 SJTU-TPMSHX/V2 是来源参考，本分支不合回原仓库。

**主体源码在 [sjtu_tpmshx/](sjtu_tpmshx/)**，前处理、求解和后处理都在这个包内。
其他根目录分别存放文档、示例、辅助工具和验证记录。

矩形 2D/3D 三模块主线的 M-A 合并验收已记录；M-B 扩展能力继续单独追踪。
历史 B40 失败与物理适用范围仍须保留。当前结论见
[能力范围与未完成事项](docs/capabilities.md)；
原计划、接管过程与各节点证据从[固定历史索引](docs/history/README.md)查阅。

## 从这里开始

| 你要做什么 | 入口 |
| --- | --- |
| 在本机运行 | [macOS / Windows 首次运行](#first-run)，含命令行算例和 GUI 启动 |
| 从界面开始使用 | [GUI 常用流程](#gui-use) |
| 阅读或修改源码 | [主体源码与模块地图](sjtu_tpmshx/README.md) |
| 理解模块边界 | [架构说明](docs/architecture.md)、[三模块数据契约](schemas/three_module_v1/) |
| 构建桌面软件 | [独立打包环境、用户文件与交付验证](docs/desktop.md) |
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
| air_2d | 31124.61 W/m | 1626.34 / 1188.97 | 303.34 / 334.79 |
| air_3d | 338.33 W | 1944.01 / 3038.07 | 359.23 / 344.93 |

空气现按真实端口面的面积平均值校准入口绝压，误差低于0.01%才满足该项收敛条件；
压力和热量收敛定义见[架构说明](docs/architecture.md)。
当前空气阻力系数、标定来源与适用范围见[模型资源](docs/model-resources.md)；
阶段修复与实验对照报告从[历史索引](docs/history/README.md)查阅。

完整计算的 `Q` 统一为主网格 A 侧原始边界焓流绝对值。`Q_A`、`Q_B` 保留
有符号的两侧换热量，二维 Richardson 外推值另列，不替代主指标。
两维度的压降统一按物理端口面压力、几何开口面积加权，定义版本为
`pressure_face_v1`。数值网格精度与实验预测误差分别评估，历史测量只代表
其记录的代码、工况与配置，见[历史索引](docs/history/README.md)。
热量、温度及流量指标的定义版本为 `native_boundary_v1`；旧指标文件保留原定义，
旧原生结果可重新后处理。

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

1. 启动 `sjtu_tpmshx.main`，用顶部“载入”选择预设。左侧“工况参数”分为
   “几何／边界／求解”三页，分别填写结构与维度、流体入口与开口、网格与求解选项。
   拖动参数栏与画布之间的分隔线调整宽度；点击栏标题的收起按钮或按 `Ctrl+\`
   收成图标栏，点击“展开”或对应分组返回参数，保留输入、滚动位置和栏宽。
2. 点击参数栏底部“开始计算”（Ctrl+R）。画布下方的计算状态卡显示耗时，
   展开“详情”查看求解器实际发布的迭代和 A/B 残差；卡片提供独立取消入口，
   收起参数栏后仍可取消。取消请求会等待当前计算步结束。状态卡不预测剩余时间；
   三维路径目前只发布外迭代信息，未提供实时残差时明确显示暂无数据。
   结束后保留“计算完成／有提示／未收敛／失败／已取消”等状态；已捕获的完整日志
   此时才可通过“计算日志”打开。未收敛和三维视图不可用不会显示为正常成功。
3. 完成后进入“场图结果”，选择
   温度、速度或压力，以及流体 A/B（温度还可选择固体）。三维场图可移动
   z 切片滑块；“场图 / 三维”只切换显示方式，计算维度由工况参数决定。
   场图下方显示换热量、两侧压降、出口温度与收敛诊断；“摘要”可收起读数区，
   “更多 → 诊断详情”打开诊断。点击“专注”或按 `F` 收起参数与结果摘要，扩大当前
   画布；再次切换恢复原来的展开状态。编辑下一次配置不会改变当前结果的来源和单位。
   数值可显示不等于验收通过。
4. 用顶部“保存”保存配置；“导出”可保存完整 CSV + NPZ 结果或当前图像。
   相位和切片选择只改变显示及图像导出，完整结果仍保留全部原始场。
   GUI 会话保留界面状态；正式模块交接
   使用 `case.yaml` 与伴随 HDF5、`results.h5`，两者用途不同。

参数页切换、参数栏展开和计算详情展开使用约 200 ms 的轻淡入过渡，
文字全程保持清晰；连续点击会替换旧动效，期间仍可编辑输入。
窗口首次出现时也使用一次参数区淡入，提前完成效果初始化，减少首次切页的等待。
界面动效与三维预设视角使用独立的精确定时推进，支持高刷新率交互；
发生慢帧时按实际经过时间推进，不积压动画帧。三维实际帧率还取决于渲染负载。
三维旋转和视角过渡允许自适应降低体渲染采样精细度，停止后恢复原静态画质；
这只影响交互时的显示，计算场和完整结果导出不变。
设置环境变量 `QT_REDUCED_MOTION=1` 可关闭这些过渡及三维视角动画。

“更多”中可切换深色／浅色主题（重启生效）和 K／°C。界面使用系统无衬线字体：
macOS 为系统西文字体与苹方，Windows 为 Segoe UI 与微软雅黑，Linux 使用可用的
Noto Sans / 系统回退。正文与数值输入使用常规字重，标题和主操作强调层次。
图表与导出图片保留 Times New Roman 英文/数字、Microsoft YaHei 中文；
macOS 可使用已安装 Office 内的对应字体，只在当前进程注册，不复制或分发。
缺少图表字体时记录提示并使用可用字体，不影响界面系统字体。

日常计算在“求解 → 计算资源”中调整线程数；原高级数值选项移入
“边界 → 专家设置”，默认收起。折叠不改变当前配置、预设值或适用范围告警。
专家选项具有不同用途，不能作为统一的精度增强开关：
允许入口 Nu 超范围只改变入口 Re 预检的拒绝/告警策略；六壁面加密与端口/壁面加密
是互斥的网格方案，前者在三轴各追加 16 格，后者的输入格数已含加密单元。
局部密度热输运默认开启，也参与限定空气/水工况的输运路径选择，
并非 sCO₂ 变物性的总开关。修改网格方案后需结合实际网格与收敛结果判断精度。
“计算线程数”在启动普通计算时传给工作线程，控制其中的 Numba 并行核；
小网格可使用串行核，优化任务使用独立并行策略，此值不是整个应用的 CPU 占用上限。

流体卡片优先显示入口条件；“自动填充”后展开物性预览，折叠不改变参数。
sCO₂ 传热选项随流体选择显示；已选择的实验模式会保留可见，便于核对或切回。
“使用现行有效系数”显式载入版本 `sco2-effective-nu-20260920-v1`；也可导入带
来源、版本和适用范围的自定义或历史参数。现行 `alpha_D=4.1064`、
`alpha_G=2.4824` 是各拓扑的总 Nu 幅度，只应用一次，不再叠加旧倍率。
通用 `cfd_smooth` 默认模式不变，打开旧保存输入也不会静默替换其中的参数。
选择方法、Gyroid 标定及 Diamond 迁移限制见[模型资源](docs/model-resources.md#sco2-有效-nu-系数)。
“优化”页将搜索设置与单点计算分区分开，分区仍只服务于单点计算。

二维边界中的“开口内均匀”控制入口速度分布；上海预设的水侧默认启用，
开口位置和总流量不变。未启用时保留历史边缘平滑分布。预设会保存该选择；
旧预设缺少此项时沿用历史分布。三维入口已使用均匀分布，不受此项影响。

内置上海预设默认选择 D-F“实验标定”。Gyroid 7/0.6 mm 空气侧采用
4 月 1 日直通实验的一维标定 `sF=2.649010286988306`，水侧保留原修正。
保存的配置保留所选模式，旧文件未记录阻力模式时仍使用光滑 CFD；通用 API/CLI
默认值不变。实验修正有几何、工况和标定范围限制，不代表所有压降误差已消除。
现行系数与低流量外推规则见[模型资源](docs/model-resources.md)。
两批接法的历史二维/三维验证保留在[历史索引](docs/history/README.md)中。

“快速设计”从给定流体工况、换热需求与压损约束筛选尺寸，使用规定速度的近似模型。
界面的“自动搜索 / 固定胞元”“逆流 / 交叉流”分别对应原有 `auto/fixed`、
`counter/cross` 模式。工况文件使用 K、绝压 kPa、kg/s、kW；压降上限按比例填写
（例如 5% 填 `0.05`）。结果表将体积放在前列，便于比较候选尺寸。
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
"$PYTHON" -m mypy @mypy-core-files.txt --config-file pyproject.toml
"$PYTHON" -m pytest sjtu_tpmshx/tests -q -ra -m "not slow and not heavy" --ignore=sjtu_tpmshx/tests/integration_tm1 -n 2 --dist loadscope --timeout=600 --timeout-method=thread --durations=30 --junitxml=.cache/ci/fast.xml
NUMBA_NUM_THREADS=1 "$PYTHON" -m pytest sjtu_tpmshx/tests/integration_tm1 -q -ra --timeout=600 --timeout-method=thread --durations=30 --junitxml=.cache/ci/integration.xml
# 完整本地验收：没有 -m 过滤；按本机 CPU/内存可将 auto 换为固定 worker 数。
"$PYTHON" -m pytest sjtu_tpmshx/tests -q -n auto --dist loadscope --timeout=600 --timeout-method=thread
```

PowerShell 使用同样的 pytest 参数，并以 `$env:NUMBA_NUM_THREADS='2'` 等设置
上述环境变量，以 `& $tm1Python` 调用解释器。Numba 上限至少为 2，因为焓输运测试
显式运行双线程检查；独立集成步骤使用 1，运行全量前恢复为 2。
CI 快测固定两个 worker，每个 worker 的 BLAS/OMP 单线程、Numba 上限为 2。
固定 128 核服务器的并行预算见 `scripts/run_tests_server.ps1`；
`run_tests_fast.ps1` 只提供开发反馈，其 `not heavy` 子集与 CI 快测不同。

`mypy-core-files.txt` 显式列出 18 个类型检查文件：保留既有配置、控制器、CLI
及兼容入口，并覆盖当前 envelope 实现、三模块数据契约与公共 API、后处理指标入口。
`pyproject.toml` 还对四个边界实现模块启用无注解函数体检查；这不等于全求解器严格类型覆盖。
`test_type_gate.py` 在 pytest 快测中执行同一清单，并确认错误类型不能传入三个公共 API；
上面的 mypy 命令用于本地单独检查，CI 不另加重复步骤。

第一条 pytest 排除了 slow/heavy 和 `integration_tm1`，第二条单独完整执行该集成目录，
避免重复执行其中的快测成员；两者不能代替第三条完整本地验收。
CI 日志保留最慢 30 项和 skip 原因，并将两份 JUnit 测试状态/逐项耗时 XML 保存为
`test-reports-<平台>-py<版本>` artifact，保留 7 天；上传范围只包含这两份测试报告。
比较速度时区分快测、集成和整个 job，并使用相同平台的基准，不据本地耗时承诺 CI 提速。
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

现行能力与待完成事项见[能力范围](docs/capabilities.md)，
测量工具和复现边界见[工具说明](docs/tools.md)。

## 数据与历史证据

原始实验/CFD 数据位于本地 `data/raw_data/`，不提交。匹配版本见
[data-revision.txt](data-revision.txt)。清洗、拟合和本地输出规则见
[离线模型说明](docs/model-resources.md)。
目录按实验、CFD 结果和工况计划分类；Excel 的新旧名称、用途及读取约束见
[数据目录与文件名对照](docs/data-catalog.md)。移动数据时须同步加载器和压力口径识别。

旧 γ/RBF、SmoothDF、水发展段及旧 sCO2 阻力模型已退役，代码和结果见
[固定历史索引](docs/history/legacy-models.md)。当前联合 K/cF、原水 Nu 和 D-F
实验修正继续使用；sCO₂ Nu 的旧锚定 γ 及专属报告工具已由
[现行有效系数](docs/model-resources.md#sco2-有效-nu-系数)替代。历史实验误差不改写。
当前水 CFD 工作簿缺失时不以旧版文件替代。

原 README 的历史精度与物理说明原样保存在
[V2 README 存档](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/docs/history/v2-readme.md)，旧图片链接固定到历史提交。
已移出当前文件树的图片、优化输出、探索记录与 Atlas 快照见
[历史资料索引](docs/history/README.md)。
这些数字不是 TM1 或当前默认 CFD 模式的新验收。B40 原锁定测试 4/4 失败、
3D 筛选未收敛及其他原生失败证据继续保留；不改阈值或物理范围迎合结果。
