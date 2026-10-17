# SJTU-TPMSHX-TM1

[中文](README.md) | [English](README.en.md)

TM1 将 TPMS 换热器的前处理、求解和后处理拆为独立维护的模块，供计算界面、
参数优化和快速设计通过公开接口调用。目标仓库为
[alexlu997/SJTU-TPMSHX-TM1](https://github.com/alexlu997/SJTU-TPMSHX-TM1)。
原 SJTU-TPMSHX/V2 是来源参考，本分支不合回原仓库。

**主体源码在 [sjtu_tpmshx/](sjtu_tpmshx/)**，前处理、求解和后处理都在这个包内。
其他根目录分别存放文档、示例、辅助工具和验证记录。

0.2 仅使用 C++ 数值后端，保留 Python/Qt 界面、CLI、前后处理、优化和快速设计。
完整 2D/3D 计算及快速设计仍通过相同的准备态和结果接口运行。
本轮维护平台为 macOS arm64 与 Windows x64；Linux 服务器部署暂不开展。

[v0.1.0](https://github.com/alexlu997/SJTU-TPMSHX-TM1/releases/tag/v0.1.0) 是首个 GitHub 源码发布版本，保留 Python 与 C++ 双后端。
0.1 发布包保留两套求解器源码。0.2 删除 Python 数值迭代器及其专用研究入口，
并删除外层物性 Anderson；固定物性松弛、热方程与流动加速保持原有规则。
`legacy_h_fou`、`temperature_fou` 和 `temperature_sou` 是保留的 C++ 能量算法，
不属于本次退役范围。运行 0.2 前须构建与源码匹配的本机原生库。

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
| 理解模块边界 | [架构说明](docs/architecture.zh-CN.md)、[三模块数据契约](schemas/three_module_v1/README.zh-CN.md) |
| 构建桌面软件 | [独立打包环境、用户文件与交付验证](docs/desktop.md) |
| 查找文档与其他目录 | [仓库目录与文档导航](docs/README.md) |
| 查阅旧版本资料 | [历史资料索引](docs/history/README.md) |

<a id="first-run"></a>

## 首次运行（macOS / Windows）

这是 Python 源码项目，下载后需要安装锁定依赖。首次运行使用 macOS + Python 3.13，
或 Windows x64 + Python 3.12 / 3.13，与[平台 CI](.github/workflows/ci.yml)一致。
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
"$PYTHON" -m pip install -r requirements/base.txt
"$PYTHON" -m sjtu_tpmshx.runs.tools.check_locked_environment
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
& $tm1Python -m pip install -r requirements/base.txt
& $tm1Python -m sjtu_tpmshx.runs.tools.check_locked_environment
& $tm1Python -m pip check
```

这里直接调用环境内解释器，无需激活脚本或修改 PowerShell 执行策略；这是
[Python venv 支持的用法](https://docs.python.org/3.13/library/venv.html#how-venvs-work)。
`.venv-path` 保存本机绝对路径，不随 Git 共享；新终端中重新读取该文件即可。

升级到当前依赖锁时，请创建独立的新环境并预热，保留原环境及其源码版本。
0.2 的基础锁删除 Numba、llvmlite 和 PyAMG，保留前后处理、优化及界面所需依赖。
原生压力求解仍使用其已移植的算法及许可声明，不加载 Python PyAMG。
BO 与桌面打包继续使用各自的完整锁。不要向其他工作树正在使用的共享环境安装新锁。
切换 `.venv-path` 后，先通过锁检查和 `pip check`，再运行计算或测试。
CO₂ 插值表按 CoolProp 版本隔离。Python 默认写入 `XDG_CACHE_HOME/coolprop/CoolProp-8.0.0`；
显式 `COOLPROP_ALTERNATIVE_TABLES_DIRECTORY` 和 C++ 表参数均作为缓存根目录，
内部追加 `CoolProp-8.0.0`。旧表保留，首次使用新版本时会在本机重新生成。

### 跑通小算例

仓库自带 [air_2d.json](examples/three_module/air_2d.json) 和
[air_3d.json](examples/three_module/air_3d.json)，使用随源码提供的模型资源，
不需要私有 `data/` 或 `.git`。首次运行前先构建本机 C++ 库：使用 macOS C++
工具链，或 Windows x64 的 MSVC 开发者终端。构建和物性表首次生成的耗时与求解耗时分开。

macOS：

```bash
PYTHON="$(head -n 1 .venv-path)"
export MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg"
"$PYTHON" scripts/build_native_dependencies.py fetch
"$PYTHON" scripts/build_native_dependencies.py publish
"$PYTHON" -m sjtu_tpmshx.cli run examples/three_module/air_2d.json .cache/first-run-2d --case-id first-run-2d
"$PYTHON" -m sjtu_tpmshx.cli run examples/three_module/air_3d.json .cache/first-run-3d --case-id first-run-3d
"$PYTHON" -m sjtu_tpmshx.main
```

Windows：

```powershell
$tm1Python = Get-Content .venv-path -TotalCount 1
$env:MPLCONFIGDIR = Join-Path $PWD '.cache/matplotlib'
$env:XDG_CACHE_HOME = Join-Path $PWD '.cache/xdg'
& $tm1Python scripts/build_native_dependencies.py fetch
& $tm1Python scripts/build_native_dependencies.py publish
& $tm1Python -m sjtu_tpmshx.cli run examples/three_module/air_2d.json .cache/first-run-2d --case-id first-run-2d
& $tm1Python -m sjtu_tpmshx.cli run examples/three_module/air_3d.json .cache/first-run-3d --case-id first-run-3d
& $tm1Python -m sjtu_tpmshx.main
```

前两条计算命令分别输出 `case.yaml`、伴随 `case.h5`、`results.h5` 和
`metrics.json`；最后一条启动图形界面。CLI 输入文件与 GUI 会话文件格式不同，
上述 JSON 用于命令行。打开对应 `metrics.json`，五项基本指标应为 `available`，
参考值如下（2026-10-02 当前实现复核，近似值用于核对运行结果；
二维修订前数值保留于[历史索引](docs/history/README.md)）：

| 算例 | Q | Δp A / B（Pa） | 出口温度 A / B（K） |
| --- | --- | --- | --- |
| air_2d | 31131.52 W/m | 1626.03 / 1188.81 | 303.28 / 334.79 |
| air_3d | 338.33 W | 1944.17 / 3038.38 | 359.23 / 344.93 |

空气现按真实端口面的面积平均值校准入口绝压，误差低于0.01%才满足该项收敛条件；
压力和热量收敛定义见[架构说明](docs/architecture.zh-CN.md)。
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
贝叶斯优化的 Windows CPU 环境另见 `requirements/bo-windows.txt`；macOS arm64 /
Python 3.13 使用 `requirements/bo-macos.txt`。已授权的 BO 任务使用独立环境，
随后用对应锁运行环境检查及 `pip check`；勿将可选依赖加到正在使用的共享基础环境。
上述小算例无需 BO。原始实验回归与重新拟合则需要匹配版本的本地数据，见文末。

BoTorch 首次构造多目标 Log 采集函数时会尝试编译其可选 C++ 内核。
将 `TORCH_EXTENSIONS_DIR` 设为当前工作树的 `.cache/torch-extensions`，并在该次运行的
`PATH` 前放置 BO 环境的 `bin`（Windows 为 `Scripts`），使已锁定的 Ninja 可用。
编译还需要本机 C++ 工具链；无法编译时 BoTorch 会报告并使用其 Python 实现。
两种执行方式的性能证据需分别记录，首次编译不能计入暖态求解耗时。

### macOS 项目文件夹中的 C++ 库

本次交付保留 Python/Qt 主程序和源码，在项目内放置匹配的预编译 C++ 库，
不制作 `.app`。随附库面向本机 macOS 27 / arm64；其他系统、机器和旧版
macOS 尚未验收。继续复用 `.venv-path` 指定的现有锁定环境，环境检查同上。

双击项目根目录的 `launch-macos.command`，或在终端运行：

```sh
./launch-macos.command
```

启动器进入自身所在项目目录，将缓存写入项目 `.cache/`，通过 `--backend cpp`
显式加载 `native/lib/macos-arm64/libtpmshx_solver_shared.dylib`，并传入
`.cache/native-deps/tables`。库、表和本机 `.venv-path` 属于本地交付资源，
不随 Git 源码自动提供。缺少解释器或库会直接报告原因；启动器不安装依赖、
或编译库。需要 CO₂ BICUBIC 表的既有 legacy 路线使用当前版本目录中的四表，
缺少时由该版本在本机生成；
保守温度算法不使用这些表。公共 API、CLI 和直接模块调用默认使用 C++。

已有当前锁定原生依赖且相关原生回归通过时，可显式发布启动器使用的库：

```sh
"$PYTHON" scripts/build_native_dependencies.py publish
```

此命令离线构建当前源码，运行独立 C/C++ 调用和错误路径检查，再替换本平台的库。
缺少锁定依赖或验证失败时停止。改变库内容前，旧库及记录保存在同目录的 `previous/`；
重复发布相同库保留已有回退副本。`build.json` 记录源码提交、未提交改动、构建配置及路径。
`native/lib/` 是 Git 忽略的本地交付目录。停止使用该库的程序后，可从 `previous/`
复制库和 `build.json` 回原目录；同时恢复对应源码、Python 环境和物性版本。
发布检查不替代数值回归或桌面验收。日常启动不执行构建、安装或下载。
GUI 不再提供后端切换；普通计算、快速设计和优化统一使用 C++。
启动时可指定库，或使用本机 macOS／Windows 交付目录中的匹配库；缺库时明确报错。
“计算线程数”的“自动”最多使用本机的 8 个逻辑 CPU。此选择属于当前窗口的运行设置，
不写入工况文件，也不改变已经生成的结果。

源码 GUI 和 CLI 共用默认查找：macOS 使用
`native/lib/macos-arm64/libtpmshx_solver_shared.dylib`，Windows 使用
`native/lib/windows-x64/tpmshx_solver_shared.dll`；默认表目录为
`.cache/native-deps/tables`。匹配库已发布到这些位置时无需指定后端。
显式库／表路径优先；API 可通过 `RunControl` 覆盖主机路径。

2026-10-05 的候选验收保留以下边界：Ceff43 为 19/43 通过、24/43 超时，
固定总体未通过；fixed230 执行和索引为 230/230，用时 93 分 18.5 秒，
保存态独立检查为 229/230 通过，首行因审计工具错误未评估且未重试。
这些局部检查不构成完整原生配置、迭代历史、F2 或实验准确度资格。
源码 GUI 已有两维显示和导出证据，取消、重算、菜单配置保存重载、重启恢复及
外循环次数显示的可见复核尚待解锁 Mac 后完成；当前不作为完整应用验收通过。
合入 PR #136 的 `298761d2` 基线已通过 macOS/Windows 原生 CI，见
[CI 记录](https://github.com/alexlu997/SJTU-TPMSHX-TM1/actions/runs/37713153292)。
早期数值比较失败仍属于其原版本记录。工程对照、严格局部回归、实验精度、
完整性能和可见桌面验收分别保留各自门槛。
文件夹可启动与限定回归通过不代表完整原生资格通过。

Windows x64 和不使用本地 macOS 启动器的用户，按
[项目文件夹运行说明](docs/desktop.md#source-folder)显式传入原生库与可写表目录。

<a id="gui-use"></a>

## GUI 常用流程

1. 启动 `sjtu_tpmshx.main`，用顶部“载入”选择预设。左侧“工况参数”分为
   “几何／边界／求解”三页，分别填写结构与维度、流体入口与开口、网格与求解选项。
   拖动参数栏与画布之间的分隔线调整宽度；点击栏标题的收起按钮或按 `Ctrl+\`
   收成图标栏，点击“展开”或对应分组返回参数，保留输入、滚动位置和栏宽。
   三维每侧入口可独立选择速度或总质量流量 kg/s。质量模式的速度只读，显示上次解析值；
   “自动填充”或下一次计算按当前温压、孔隙率和真实开口积分重新解析。改变几何仍保留
   输入的 kg/s。二维界面继续使用速度输入；优化工况表独立规定每个工况的总流量。
2. 点击参数栏底部“开始计算”（Ctrl+R）。画布下方的计算状态卡显示耗时，
   展开“详情”查看求解器实际发布的迭代和提示；卡片提供独立取消入口，
   收起参数栏后仍可取消。取消请求会等待当前计算步结束，三维粗网格初始化也会
   响应取消。求解模块导入时不再预编译所有路径，实际用到的核在首次调用时编译；
   若取消发生在编译中，仍需等待当前计算步返回，不能强行中断编译线程。状态卡不预测剩余时间；
   主界面不再显示实时残差曲线或无数据占位；收敛与守恒检查仍由求解器执行并记录在诊断中。
   结束后保留“计算完成／有提示／未收敛／失败／已取消”等状态；已捕获的完整日志
   此时才可通过“计算日志”打开。未收敛和三维视图不可用不会显示为正常成功。
3. 完成后进入“场图结果”，选择
   温度、速度或压力，以及流体 A/B（温度还可选择固体）。三维场图可移动
   z 切片滑块；“场图 / 三维”只切换显示方式，计算维度由工况参数决定。
   场图下方显示换热量、两侧压降、出口温度与收敛诊断；“摘要”可收起读数区，
   “更多 → 诊断详情”打开诊断。点击“专注”或按 `F` 收起参数与结果摘要，扩大当前
   画布；再次切换恢复原来的展开状态。编辑下一次配置不会改变当前结果的来源和单位。
   数值可显示不等于验收通过。
4. 用顶部“保存”保存配置；“导出”可保存结果或当前图像。
   二维结果保存 CSV，三维结果保存 CSV 与伴随的字段 NPZ。
   相位和切片选择只改变显示及图像导出。三维 NPZ 保存可用的完整 XYZ 温度场、
   A/B 侧三分量速度和速度模（m/s）、显示压力 `P_fA/P_fB`（Pa）、
   `L_mm/t_mm`（mm）及 `dx/dy/dz` 网格宽度（m）；保留 A 侧旧键 `vmag/P_kPa`。
   显示压力沿用当前结果的参考值；完整原生热状态和通量证据保存在 `results.h5`。
   GUI 会话保留界面状态；正式模块交接
   使用 `case.yaml` 与伴随 HDF5、`results.h5`，两者用途不同。
   命令面板的“Copy inputs as Python code”使用同一完整工况快照，包含温标、流体/边界、
   分区及模型参数；在已有窗口对象 `window` 的 Python 会话中执行即可恢复输入。
   这个片段不启动求解，也不是命令行 `ComputeConfig` 配置文件。

已有会话会恢复自定义流体、流动方向、网格和端口，不再被上海默认工况覆盖。
仅首次启动、没有保存会话的工作区，或明确重置／载入上海预设时使用上海默认值。
各工作区独立保存分区轴、分区表格和连续场控制点；旧会话缺少这些数据时清空并
禁用分区，若原文件启用了分区则提示重新设置，避免误用其他工作区的分区。
启动时温度输入统一显示为 K，通过单位换算保留原物理温度。

参数页切换、参数栏展开和计算详情展开使用约 200 ms 的轻淡入过渡，
文字全程保持清晰；连续点击会替换旧动效，期间仍可编辑输入。
窗口首次出现时也使用一次参数区淡入，提前完成效果初始化，减少首次切页的等待。
界面动效与三维预设视角使用独立的精确定时推进，支持高刷新率交互；
发生慢帧时按实际经过时间推进，不积压动画帧。三维实际帧率还取决于渲染负载。
三维旋转和视角过渡允许自适应降低体渲染采样精细度，停止后恢复原静态画质；
这只影响交互时的显示，计算场和完整结果导出不变。
设置环境变量 `QT_REDUCED_MOTION=1` 可关闭这些过渡及三维视角动画。

计算完成后优先绘制当前场图；其他场图首次打开或导出时生成并缓存。
切换流体或截面会更新可见图，新结果会清除旧图缓存。三维高清体渲染也按字段
首次生成，保留原始计算场、静止画质及共享色标。普通求解提示保留在状态卡和
“诊断详情”，不再通过同步弹窗阻塞结果显示。
“诊断详情”列出准备、求解、后处理和显示耗时；成功计算的总耗时为后台流程加
结果显示时间。比较终端与 GUI 速度时，应使用相同配置、线程数和缓存状态，
并区分原生构建、物性表初始化和后续计算。日常运行不重新编译求解器。

“更多”中可切换深色／浅色主题（重启生效）和 K／°C。界面使用系统无衬线字体：
macOS 为系统西文字体与苹方，Windows 为 Segoe UI 与微软雅黑，Linux 使用可用的
Noto Sans / 系统回退。正文与数值输入使用常规字重，标题和主操作强调层次。
图表与导出图片保留 Times New Roman 英文/数字、Microsoft YaHei 中文；
macOS 可使用已安装 Office 内的对应字体，只在当前进程注册，不复制或分发。
缺少图表字体时记录提示并使用可用字体，不影响界面系统字体。

日常计算在“求解 → 计算资源”中调整线程数，网格设置中选择常规或端口与壁面加密方案；
后者的输入格数包含全部加密单元。修改网格方案后需结合实际网格与收敛结果判断精度。
GUI 统一采用开口内均匀入口、开启局部密度热输运，不再提供历史入口平滑、六壁面
加密及局部密度开关。局部密度也参与限定空气/水工况的输运路径选择，并非 sCO₂
变物性的总开关。载入使用不同历史设置的 GUI 配置时会提示更新，随后保存当前设置。
允许入口 Nu 超范围仍只改变入口 Re 预检的拒绝/告警策略，不放宽物性或几何适用范围。
“计算线程数”随下一次计算传递，控制 C++ 逐点物性工作线程和二维双侧流场计算，设为 1 时串行执行。
小网格可使用更少线程；此值不限制整个应用或外部数学库的 CPU 占用，也不控制优化任务数量。
CLI 使用 `--cpu-threads N`，API 使用 `RunControl(cpu_threads=N)`；两者均要求正整数。
未指定时，C++ 库最多使用本机的 8 个逻辑 CPU。
线程数不写入 `CaseData`，也不改变物理模型、迭代预算或停止条件。
同一原生构建的续算可更换线程数。旧续算目录保留的库继续使用原入口；
若旧库不支持线程预算，则须省略该参数，GUI 中选“自动”。显式预算不会被静默忽略。

流体卡片优先显示入口条件；“自动填充”后展开物性预览，折叠不改变参数。
sCO₂ 传热选项随流体选择显示；已选择的实验模式会保留可见，便于核对或切回。
“使用现行有效系数”显式载入版本 `sco2-effective-nu-20260920-v1`；也可导入带
来源、版本和适用范围的自定义或历史参数。现行 `alpha_D=4.1064`、
`alpha_G=2.4824` 是各拓扑的总 Nu 幅度，只应用一次，不再叠加旧倍率。
通用 `cfd_smooth` 默认模式不变，打开旧保存输入也不会静默替换其中的参数。
选择方法、Gyroid 标定及 Diamond 迁移限制见[模型资源](docs/model-resources.md#sco2-有效-nu-系数)。

流体列表另有独立的 CO₂ 单相模型，可用于 A/B 侧的二维、三维均匀或连续场完整计算。
它使用 HEOS 物性和所给 CO₂ CFD 几何/Nu 资源，固定采用 `K=K0/2.5`、
`cF=2.5cF0`、`Nu=1.28Nu_base`。两个倍率在闭合中各应用一次，仅作用于 CO₂ 侧，
不随全局 D-F 模式切换；混合算例共用 CO₂ 对称几何。结果记录模型版本和实际倍率。
这是指定经验参数的应用，不是新的实验拟合结论。CO₂ 与 sCO₂ 不随温压自动互换；
单相状态、Nu/Re/Pr 和几何范围分别检查，不自动开启外推。两相、临界点、离散分区、
非零等值面偏移和 CO₂ 快速设计不在这条新增路径内。

“优化”页使用连续场搜索设置；原离散分区表仍用于单点计算。

内置上海预设默认选择 D-F“实验标定”。Gyroid 7/0.6 mm 空气侧采用
4 月 1 日直通实验的一维标定 `sF=2.649010286988306`，水侧保留原修正。
保存的完整配置保留所选模式，旧会话或预设未记录阻力模式时仍使用光滑 CFD；通用 API/CLI
默认值不变。实验修正有几何、工况和标定范围限制，不代表所有压降误差已消除。
现行系数与低流量外推规则见[模型资源](docs/model-resources.md)。
两批接法的历史二维/三维验证保留在[历史索引](docs/history/README.md)中。

“快速设计”从给定流体工况、换热需求与压损约束筛选尺寸，使用规定速度的近似模型。
界面的“自动搜索 / 固定胞元”“逆流 / 交叉流”分别对应原有 `auto/fixed`、
`counter/cross` 模式。工况文件使用 K、绝压 kPa、kg/s、kW；压降上限按比例填写
（例如 5% 填 `0.05`）。结果表将体积放在前列，便于比较候选尺寸。
选型或精修报错时立即停止，保留此前已完成候选；并行仅保证此前完整批次。
界面及 Excel 区分“失败中止”和“已取消”，最优标签仅针对已完成集合。
快速设计 CLI 在有已完成候选时将部分报告保存到指定 `--out`，随后仍抛出原错误、
以非零状态退出；首个候选失败时不覆盖旧报告。

“优化”页支持空气 A / 水 B，以及含 CO₂ 或 sCO₂ 的双流体组合，按当前维度进行连续场多工况搜索：二维为 L(x,y)/t(x,y)，
三维为 L(x,y,z)/t(x,y,z)。比较换热百分比改善与两侧等权相对压降，
换热目标始终是 B 侧吸热 `-Q_B`，基准必须为正；不同工况保持相同 A/B 流体模型。
保留 Pareto 方案的完整控制场。可选择 Sobol、qLogNEHVI 或 qLogNParEGO；
BO 需另配对应锁定环境。“优化设计 → 结果”内可切换 Pareto 前沿与尺寸/壁厚场，
点击 Pareto 方案即可查看连续场；几何布局画布保持独立。优化场图可单独复制或导出。
搜索空间可分别设置 X/Y/Z 控制点，默认每轴 3 点；1 点表示该轴恒定，2 点采用线性插值。
界面显示实际变量数，超过 Sobol 初始化支持的 21201 个变量时拒绝启动。
结果页的“导出 Pareto 数据”保存 CSV 或 XLSX，包含有效点、原设计编号、前沿标记和运行状态。
选择前沿方案后可“导出所选方案建模坐标”，生成 `geometry.csv`、原控制点 `controls.csv`、
`Lfield.csv`、`tfield.csv` 和来源记录。坐标与 L/t 均为 mm，按 x 最快、随后 y/z 排列。
建模采样包含域边界，单点轴取中面；最多 100 万采样点。导出使用方案的原始配置，
窗口中后续修改的几何和控制点不会改变它。API 原默认单元中心采样保持不变。
三维视图的 Range 按钮在 Full、Slice、Custom 间切换。Custom 的 Min/Max 按字段保存，
并随工作区会话恢复；范围同时用于体图、切片和新打开的切片弹窗及其图片。
超出范围的值使用端点颜色，输入范围不改变原始数据；Max 必须大于 Min，且两者有限。
三维设计还可切换到“三维尺寸 / 壁厚场”，旋转和缩放完整XYZ参数场，切换L/t、
透明度及XY/YZ/XZ切片位置。体视图按连续设计场采样显示，不需要重新求解；
它表示晶胞尺寸和壁厚的空间分布，不是TPMS实体曲面的CAD预览。
GUI 的温度、压力、速度、尺寸/壁厚与敏感性热图统一使用 `ui.theme.FIELD_CMAP`
定义的 `turbo` 色图，二维、三维及切片弹窗一致；各物理量保留自己的单位与数值范围。
默认16个初始设计、8轮每轮1个新设计；一个设计在多个工况下评价后才形成一条聚合样本。
导入的工况 JSON 仅含 `conditions` 列表，每行含
`condition_id` 与 A/B 各自的 `T_in_A_K`、`P_in_A_Pa`、`mass_flow_A_kg_s`
（B 侧将 A 换为 B）；未导入时明确使用当前单工况。二维需填写实际换算厚度。
Shanghai Gyroid 7/.6 的冻结整机修正可用于显式连续场趋势探索，
搜索结果仍需全工况和网格复核，不等同于渐变结构的实验验证。
命令面板中的 `Sensitivity sweep` 是 A 侧两个参数的局部趋势热图，仅在 A 侧选择空气时运行，
使用固定 40 K 温差估算和未加实验修正的 CFD 压降基线；B 侧流体不参与该估算。
它不是当前完整工况的重新求解，也不替代最终计算。用于本估算的固定温度、压力及未扫描参数必须有效；
A 侧压力留空时与计算页一致使用 101325 Pa，非空非法值会拒绝运行。
固定输入改变后需重新扫描，旧热图不能回填。

输入文件分三类：CLI 配置（`air_2d.json` / `air_3d.json`）、GUI 会话/预设、
快速设计的 `DesignCase`。字段与单位不同，不能互相当作输入；
最小 DesignCase 和扩展示例见[工具说明](docs/tools.md#公开模块扩展示例)。

GUI 导入没有 `config_format` 包装的 `line_edits` JSON 或旧式平铺参数文件时，
只更新文件提供的字段。未提供的温标、阻力模式、网格、模型参数、连续场及优化工况保持当前值。
文件明确切换 K/°C 时，未提供的新温度值会按当前物理温度换算显示；不会把原文本改贴单位。
正式完整配置、预设库及启动会话仍按各自的恢复规则处理。

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
[schema](schemas/three_module_v1/README.zh-CN.md)。CLI 输出必须与本次输入文件及 Case 的伴随 HDF5
分开，路径重合会在执行阶段前拒绝；独立的既有输出仍可更新。
取消与失败不伪装成完成结果；已完成但未收敛的
结果保留原状态。指标有限不等于数值、能量或实验精度验收通过。

C++ 完整计算可以将迭代状态保存在新的运行目录：

```bash
"$PYTHON" -m sjtu_tpmshx.cli run examples/three_module/air_2d.json .cache/run-01 --case-id example --backend cpp --checkpoint-interval 60
"$PYTHON" -m sjtu_tpmshx.cli resume .cache/run-01/checkpoint.h5 .cache/run-02 --checkpoint-interval 60
```

CLI 保存间隔须显式指定；保存会等待下一个完整求解步骤结束。
启用保存后，Ctrl+C 请求暂停，进程在保存状态后返回退出码 3。
暂停不产生完成结果，取消仍返回退出码 130。
运行目录保留准备态输入、原生库、检查点与运行状态；完成后另有 `results.h5` 和 `metrics.json`。

续算读取已保存的准备态输入，写入新目录并保留原运行。移动时须一起移动整个运行目录。
续算要求相同的原生构建和平台；当前构建不同时，可用 `--native-library` 显式选择保留的库。
GUI 的载入菜单可以继续已保存的运行，沿用记录的保存间隔和输入来源。
新发起的 GUI C++ 完整计算每 60 秒请求保存，运行目录位于用户数据目录的 `runs/` 下。
计算详情显示保存位置；可用“保存并暂停”结束当前任务，再从载入菜单继续。
实际重算量还可能包含当前完整计算步和写盘时间。

## 已接线能力与边界

| 用途 | 公开入口 | 数量口径 |
| --- | --- | --- |
| 矩形全模型 2D/3D | `prepare_case`，随后 `run_case` / `evaluate` | 2D Q 为 W/m；3D Q 为 W |
| 连续场多工况优化 2D/3D | `run_multi_condition_optimization`，经完整 Case 求解及数值检查 | 换热百分比改善与两侧相对压降；2D 总流量按明确厚度换算 |
| 快速设计 | `prepare_quick_design`，随后相同 API | 规定速度 LTNE 与解析入口压损，非完整 SIMPLE；Q 为 W |
| 参数扫描与有效场输入 | [公开示例](examples/) | 不改求解器私有成员 |
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
[历史索引](docs/history/retired-tools.md)。旧结果归档仍可读取，原配置对应的
Pareto CSV 仍可导出几何；旧筛选模式不能再执行或重新计算指标。

当前计算域仅支持 **矩形二维／长方体三维**，界面直接显示形状，不提供只有一个有效选项的下拉菜单。
六边形／八边形计算路线已退役，旧多边形配置在载入前明确拒绝，保留当前输入与结果；
多边形启动会话也不会恢复或转换成矩形。旧矩形文件仍可正常载入。
旧多边形代码通过[固定历史](docs/history/retired-tools.md)保留，重新开放须完成
主线物理规则及独立模块交接的实现与验证。

`models/`、`df_surrogate/` 等是共享技术支撑，不是第四个业务模块。旧 Pipeline/应用
入口单向调用公开模块。具体边界见[架构说明](docs/architecture.zh-CN.md)。

唯一数值后端为 C++。默认查找 macOS arm64 或 Windows x64 本机库，
也可用 `RunControl(native_library=...)` 或 CLI `--native-library` 指定路径。
Quick Design 和完整二维／三维求解的构建及能力边界见
[C++ 迁移说明](docs/cpp-migration.zh-CN.md)。原生构建、独立调用及数值对照已通过
macOS/Python 3.13 与 Windows/Python 3.12、3.13 的必需 CI；
可见桌面交付与完整性能验收仍各自保留。
完整二维接口为 ABI 2，必须同步分发库、头文件和适配器。
Python 数值后端、混合 sweep 入口及 Python 专用研究入口均已退役。
旧结果仍可读取；旧研究 Case 不再执行，普通工况须通过当前 `ComputeConfig` 准备。
OpenFOAM、REFPROP 等提供器、扩展 h/f/PEC 定义与伴随能力继续按
M-B/原文限定追踪，不能据目录或接口声明为已实现。

## 环境与检查

本地项目执行使用 `.venv-path` 第一行的绝对解释器。任务环境缺失或检查失败时，
先停止依赖该环境的工作，再按[环境恢复流程](docs/collaboration.zh-CN.md#环境恢复)
自主恢复。修改前说明影响并保留恢复方式，通过检查后再切换指针和继续工作。
恢复使用当前适用锁；依赖版本变更须同时更新依赖声明和精确锁。
共享 venv 只安装锁定依赖，不把当前项目 editable 安装进去，不修改使用中的环境。
命令从当前仓库根运行。

```bash
PYTHON="$(head -n 1 .venv-path)"
"$PYTHON" -m sjtu_tpmshx.runs.tools.check_locked_environment
"$PYTHON" -m pip check
export MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg"
export QT_QPA_PLATFORM=offscreen PYTHONHASHSEED=0
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
"$PYTHON" -m mypy --config-file pyproject.toml
"$PYTHON" -m pytest sjtu_tpmshx/tests -q -ra -m "not slow and not heavy" --ignore=sjtu_tpmshx/tests/integration_tm1 -n 2 --dist worksteal --timeout=600 --timeout-method=thread --durations=30 --junitxml=.cache/ci/fast.xml
"$PYTHON" -m pytest sjtu_tpmshx/tests/integration_tm1 -q -ra --timeout=600 --timeout-method=thread --durations=30 --junitxml=.cache/ci/integration.xml
# 完整本地验收：没有 -m 过滤；按本机 CPU/内存可将 auto 换为固定 worker 数。
"$PYTHON" -m pytest sjtu_tpmshx/tests -q -n auto --dist loadscope --timeout=600 --timeout-method=thread
```

PowerShell 使用同样的 pytest 参数，以 `$env:变量名=值` 设置上述环境变量，
并以 `& $tm1Python` 调用解释器。测试前必须提供匹配的原生库。
CI 快测按完整模块分到两个独立 runner，每片固定两个 worker，使用 `worksteal` 平衡剩余测试。
每个 worker 的 BLAS/OMP 单线程。`fast-1` 的两个 worker 结束后，同一作业串行执行完整 integration。
集成测试使用独立 pytest 进程、manifest 和 JUnit 报告；快测失败后仍执行，取消工作流时停止。
三个平台/Python 组合分别复用各自环境，减少三个作业及其重复安装。
CI 在独立 Qt 进程中渲染真实 3D 体场，检查字段切换、PNG 解码、缩放图像、应用导出及关闭。
macOS 使用 Cocoa；Windows 使用固定版本的 Mesa OpenGL 软件渲染。
快测 artifact 保留 PNG 和渲染报告；实体 Windows 显示器的桌面验收仍单独记录。

现有测试辅助脚本继续保留；`run_tests_fast.ps1` 只提供开发反馈，
其 `not heavy` 子集与 CI 快测不同。两份 PowerShell 脚本默认严格检查基础锁。
已有 Windows BO 环境时，显式使用
`./scripts/run_tests_server.ps1 -LockFile requirements/bo-windows.txt`，或向
`run_tests_fast.ps1` 传同一参数；所选锁与 `pip check` 都通过后才启动测试。
脚本不安装依赖，也不因为选择了服务器锁而放行锁外包。

GitHub workflow 使用 checkout v7、setup-python v7、upload-artifact v7，
分片门使用 download-artifact v8。这些 Action 的运行时不改变求解器的 Python 环境；
`ci` 内的 `minimal-postprocess` 验证完整环境到最小后处理环境的真实文件交接。
`ci` 的基础和独立 BO 作业均覆盖 macOS / Python 3.13，以及 Windows / Python
3.12、3.13；BO 作业分别安装对应平台的 BO 锁，严格检查环境后
显式导入 Torch / BoTorch / GPyTorch，并运行多工况优化器测试（含两种真实 Log
采集函数）。基础作业仍使用不含 BO 的锁，覆盖可选依赖缺失时的行为。
BO 作业上传 JUnit 与完整收集 manifest，保留 7 天，不上传求解数据或虚拟环境。

PR 按 [明确的路径清单](scripts/ci_scope.py) 选择检查层级：

- `docs`：仅根目录 README、AGENTS 和 `docs/` 下的 Markdown。检查本地链接、锚点和具体项目模块命令。
- `application`：仅指定界面显示、布局模块、图标及对应测试，可包含文档。保留两平台构建、应用、集成、BO 与真实文件后处理检查。
- `full`：求解器、模型、公共接口、依赖、工作流和所有未列出的路径。运行完整矩阵。

main 和手动触发始终使用 `full`。重命名同时检查旧、新路径；未知或空的变更集合使用完整矩阵。
完整矩阵有 29 个作业。较轻 PR 层级不能作为完整 CI 耗时或数值研究验收。
物理变更仍须完成其要求的扩展数值研究；常规 CI 不替代该证据。

`pyproject.toml` 的 `[tool.mypy].files` 显式列出 19 个类型检查文件：覆盖配置、控制器、CLI、统一工作流、当前
envelope 实现、三模块数据契约与公共 API、后处理指标入口；已删除的转发模块不再列入。
`pyproject.toml` 还对四个边界实现模块启用无注解函数体检查；这不等于全求解器严格类型覆盖。
`test_type_gate.py` 在 pytest 快测中执行同一清单，并确认错误类型不能传入三个公共 API 及两个工作流入口；
上面的 mypy 命令用于本地单独检查，CI 不另加重复步骤。

第一条 pytest 排除了 slow/heavy 和 `integration_tm1`，第二条单独完整执行该集成目录，
避免重复执行其中的快测成员；两者不能代替第三条完整本地验收。
本地上述命令仍执行未分片的完整子集。CI 中的原生资格测试只在原生组执行，
共同模块清单为 `sjtu_tpmshx/tests/native/_ci_suite.txt`。原生 pytest 使用 `@<清单路径>` 读取它。
应用快测仍记录原完整收集集合，再通过 `--ci-covered-modules=<清单路径>` 移交这些模块。
清单外的新模块自动保留在应用快测中，不会按目录整体排除。
复现应用分片时，在第一条 pytest 命令追加
`-p sjtu_tpmshx.tests.ci_shard --ci-shard=0 --ci-manifest=.cache/ci/fast-0
--ci-covered-modules=sjtu_tpmshx/tests/native/_ci_suite.txt`。
另一片改为 `--ci-shard=1` 并使用独立 manifest 目录。
分片 0 的模块列在 `sjtu_tpmshx/tests/_ci_shard0.txt`，其余应用模块自动进入分片 1。
移交和分片在原 heavy 标记及 pytest 过滤之后执行，所有原生断言保持不变。

汇总门先验证原生分片完整、互斥且成功，再与应用分片合并核对原完整快测集合。
跨组重复、漏测、缺失 worker 或失败记录均阻止通过。下载相同平台/Python 的全部 manifest 后运行：

```bash
"$PYTHON" scripts/check_ci_shards.py .cache/ci/fast-0 .cache/ci/fast-1 --covered-by .cache/ci/native-*/native-manifest
```

原生分片必须按编号顺序传入。若本地不使用 `--ci-covered-modules`，仍可单独核对两个完整快测分片。

原生资格检查在 macOS 分为三片，在每个 Windows/Python 组合分为五片。
每片使用两个 worker 和 `loadscope`，将同一模块或类保留在同一 worker。
分组依据完整矩阵的实测用例耗时。保守能量测试按共享 fixture 参数分组，
同组的收敛、物性、能量账本和真实回放检查保持在同片。其他模块保留共享 fixture；
独立工程用例与二维检查点用例可按完整 node ID 分组。
分组清单位于 `sjtu_tpmshx/tests/native/`：macOS 使用 `_ci_macos_shard0.txt` 至 `_ci_macos_shard1.txt`，
Windows 使用 `_ci_windows_shard0.txt` 至 `_ci_windows_shard3.txt`。
按编号顺序将每份清单通过 `--ci-shard-modules=<清单路径>` 重复传入。
未列出的用例自动进入最后一片，即 macOS 分片 2 或 Windows 分片 4。
按编号向同一集合校验器传入全部 manifest，核对其完整且互斥；每片必须有 `gw0`、`gw1` 两份记录。
`--serial` 仅用于本地串行测试的 `controller` 记录。
三个平台/Python 组合保持不变。原生工程用例保留逐侧物理模型、收敛及能量门槛。
原生组同时设置 `TPMSHX_REQUIRE_CPP_TESTS=1` 和 `TPMSHX_REQUIRE_NATIVE_DEPS_TESTS=1`；
缺少编译器或原生库必须失败。原有线程并发、进程恢复和结果所有权测试仍在原生组执行。
Python 数值对照迁移为独立公式／离散账本、制造解、组件重放及固定历史参考；
不保留已退役迭代器作为第二套求解实现。

每个平台调用 [原生工作流](.github/workflows/native.yml)，用 Python 3.13 构建一次原生库并运行独立 C/C++ 调用程序。
原生库不链接 Python 运行时。macOS 使用 Python 3.13 测试；Windows 保留 Python 3.12 和 3.13 两套测试。
分片在本平台构建完成后启动，不等待其他平台。原生、快测和集成测试共同使用本轮工作流及源码产生的
`native-build-<平台>` artifact。归档保留可执行权限，包含运行库、调用程序和许可声明。
CoolProp 精确缓存键绑定平台、架构、Python 3.13、托管工具链镜像版本、原生依赖锁和构建脚本。
项目 C++ 和模型系数每轮重新构建；缓存命中仍须完成独立调用验证。
构建日志单独保存在 `native-build-logs-<平台>`。
每片上传 `native-dependencies-<平台>-py<版本>-shard-<编号>`，macOS 编号为 0–2，Windows 为 0–4，
包含 JUnit 和 `native-manifest`。以上 artifact 均保留 7 天。
原生日志保留最慢 20 项和 skip 原因。

快测和集成日志保留最慢 30 项和 skip 原因。各测试组将 JUnit 与 collection manifest 分别保存为
`test-reports-<平台>-py<版本>-<fast-0|fast-1|integration>` artifact，保留 7 天。
manifest 附带各 pytest 进程的独立 RSS 峰值；
进程峰值不能相加当作同期总峰值，统计不覆盖普通子进程。
三个原名 `tests (<平台>, <版本>)` 必需检查核对所选层级的预期作业名称及结果。
`docs` 只允许明确跳过运行时作业；文档检查必须成功。其他层级要求构建、应用、集成、BO 和后处理成功。
`full` 必须通过完整原生覆盖；`application` 只允许省略原生模块清单中的精确路径，其他遗漏均失败。
各平台/Python 汇总还要求对应 BO 和集成报告、成功收集记录及完整测试计数。
BO 不允许跳过测试；集成允许已记录的单项跳过，但全跳过必须失败。
未预期的失败、取消、跳过、缺失报告或覆盖缺口均不能放行。
`minimal-postprocess` 继续作为独立必需检查；在 `docs` 层级只核对预期作业结果。
比较速度时区分快测、集成和整个 job，并使用相同平台的基准，不据本地耗时承诺 CI 提速。
完整验收的 skip 须保留具体原因，不能当作被跳过能力已经通过。最小后处理 CI 使用独立的
`requirements/postprocess.txt` 环境，并消费另一完整环境生成的真实 2D/3D
结果文件。macOS 集成步骤将公开算例的两个结果及指标通过 `real-file-handoff`
传给 Linux 最小环境，保留 7 天。该交接不包含私有数据。配置不等于实际 CI 通过。

## 协作与合并

Codex 与 Claude 共用 [AGENTS.md](AGENTS.md) 中的项目规则。任务归属、独立工作树、
环境选择、同步与交接使用[协作流程](docs/collaboration.zh-CN.md)。

公开契约的修改需要检查下游消费者：前处理的配置/单位/网格由求解侧复核；求解的
原生场/边界证据/状态由后处理侧复核；指标定义及文件关联由应用/文件消费者复核。
GUI 和调度留在 `ui/`、`controllers/`，模型资源保持共享。每个 PR 写明受影响的
接口、验证证据和参与复核者。当前仓库维护者为 `alexlu997`；师兄加入后再分配具名
模块责任人，当前不建立虚构的 CODEOWNERS 或把模型自查写成人工独立批准。

2026-09-13 已回读核验 main 保护：通过 PR 更新，要求分支与 main 同步，并通过
`tests (macos-14, 3.13)`、`tests (windows-2022, 3.12)`、`minimal-postprocess`
三项 GitHub Actions 检查；管理员同样受约束，禁止强推和删除。多人正式参与后
再启用至少一位非作者批准；目前平台所需批准人数为 0。实际状态以 GitHub 为准。

Windows 同时支持 Python 3.12 和 3.13：main 保护保留上述三项，并新增
`tests (windows-2022, 3.13)`，共四项必需检查；其他保护保持不变。
工作流更新不会自动修改 GitHub 保护设置，合并前须核实必需检查已同步。

现行能力与待完成事项见[能力范围](docs/capabilities.md)，
测量工具和复现边界见[工具说明](docs/tools.md)。

## 数据与历史证据

原始实验/CFD 数据位于本地 `data/raw_data/`，不提交。匹配版本见
[data-revision.txt](data-revision.txt)。清洗、拟合和本地输出规则见
[离线模型说明](docs/model-resources.md)。
目录按实验、CFD 结果和工况计划分类；Excel 的新旧名称、用途及读取约束见
[数据目录与文件名对照](docs/data-catalog.md)。移动数据时须同步加载器和压力口径识别。

优化研究脚本、逐工况结果和探索报告保留在忽略的 `.cache/` 中，不提交或上传到
代码仓库；长期需要的研究证据应另外做私有归档，不能把 Git 忽略规则当作备份。
本地虚拟环境和 `.venv-path` 同样不提交，由版本化的依赖声明与锁文件重建。
生产优化模块、回归测试、CI 工作流、锁文件及使用/架构文档随代码提交。

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
