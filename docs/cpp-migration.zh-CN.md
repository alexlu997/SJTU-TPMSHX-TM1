<a id="c-solver-migration-under-the-v03-architecture"></a>

# V0.3 架构下的 C++ 求解器迁移

[中文](cpp-migration.zh-CN.md) | [English](cpp-migration.md)

<a id="status-and-architecture-decision"></a>

## 状态与架构决定

所提供的《TPMS 均质化换热器求解软件总体框架说明 V0.3》（2026-09-08）描述目标架构，不代表已交付能力。三个业务模块与现有 TM1 公共流程一致：

```text
application -> preprocess.api -> CaseData -> solvers.api -> FieldResult
                                                           -> postprocess.api
```

0.2 保留这些模块边界，统一使用 C++ 数值后端。Python 保留应用、前处理、优化和后处理接口，以及模型资源。0.1 保留两套求解实现；0.2 撤销 Python 数值后端及其额外研究入口。共享温度 sweep 与能量审计继续使用。既有守恒 EOS 路线默认使用 T-SOU；H-FOU、T-FOU 与冻结 H sweep 的 C 导出已退役。历史结果及匹配的归档运行库保留原算法身份。外层物性 Anderson 已退役；固定物性松弛和热方程 Anderson 保留原规则。

完整二维／三维和 Quick Design 使用 macOS arm64 或 Windows x64 匹配库。公共 `RunControl` 和 CLI 默认使用 C++。库路径属于主机控制，不写入 `CaseData`；缺库时明确失败。交付保留 Python/Qt 入口和项目文件夹内匹配的求解库、几何库、准备库和结果库。必需 CI、可见桌面、完整性能和实验精度保持独立验收。

当前数值检查采用独立公式、离散账本、制造解、原生组件重放及固定历史参考。原 Python/C++ 比较保留为[0.1 记录构建的证据](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/v0.1.0/docs/cpp-migration.zh-CN.md)，0.2 不保留 Python 求解器重跑这些对照。

<a id="cpp-core-scope"></a>

## 2026-11 C++ 核心范围

本次六批范围已落实：模型数据归集、几何／设计场、准备、结果核心及消费者／退休收口，保留原算法、功能、物理门与文件接口。
各批变更记录：[数据来源 PR275](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/275)、[几何 PR276](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/276)、[网格与场 PR277](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/277)、[准备 PR278](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/278)、[结果 PR279](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/279)。
消费者收口移除了过期 GUI 插值预热；显式对象协议、配置、I/O、GUI／搜索／研究、注入 ledger 和审计／导出摘要保持已声明边界。
[源码地图](../sjtu_tpmshx/README.md)列出 C++ 修改位置；具体保留范围见[Python 职责](architecture.zh-CN.md#retained-python-responsibilities)。
这六批与文末历史求解器迁移的 0–4 阶段不同。
PR CI、合并后 main CI、可见桌面交付、性能与实验精度仍分别验收。

<a id="native-geometry-core"></a>

## 原生几何核心

独立几何核心负责标准、CO2、非对称几何与 chi/Kss。
Sigmoid LUT 节点和派生几何也使用该核心。
同一核心还负责网格、端口、六方向轴映射、连续 XY/XYZ 场、sigmoid、线性 LUT、分区和 Gaussian 平滑。
这些计算使用同一 `tpmshx_geometry_shared` 文件，不新增运行库或数值框架。
数值源码仍在 `sjtu_tpmshx/solvers/native/`。
`shared/models/_native_geometry.py` 在几何查询需要时，通过 ctypes 加载独立几何 ABI 1 库。
Python 保留公共类型、缓存及逐次调用的 chi 显式值／环境值／拟合选择。
缺库、ABI 不符或符号缺失时明确失败，不使用数值 fallback，也不在运行时构建。

独立 CMake 项目为 `sjtu_tpmshx/solvers/native/geometry/`。
`tpmshx_geometry_shared` 目标使用 C++ 标准库、marching-cubes 移植与受限 C17 FITPACK 子集，
不需要 CoolProp、SuperLU、AMGCL、Eigen 或求解运行库；完整 dependency pilot 包含同一目标。
准备与结果计算使用下述独立核心；本次实施与退休范围见[范围说明](#cpp-core-scope)。

[架构说明](architecture.zh-CN.md#native-grids-and-design-fields)定义数值所有权、类型及缓冲区生命周期。
[设计场来源说明](../sjtu_tpmshx/solvers/native/geometry/fields-sources.md)记录固定来源、本地修改及 BSD 声明。
XY 保留首次拟合的 `s=0` 双变量路线；XYZ 和含单点轴的 XY 保留逐轴拟合并采样。
标量带状求解不声明与 LAPACK／BLAS 逐位一致，原始数值与物理多项式门槛保持不变。
XY 与 Apple-arm64 Gaussian 的局部融合设置不启用全局 fast-math；Windows 和完整工况资格仍须分别建立。

Geometry、grid 和 zones 调用保留几何 ABI 1，状态 2 表示算术域错误。
设计场调用在同一文件增加 field ABI 2，状态 2 表示分配失败；ctypes 适配使用不同错误映射。
既有几何签名不变。调用按显式长度借用缓冲区，失败时不修改调用方输出。
XY 句柄持有创建库直至释放；LUT 对象保留捕获的轴、表及创建绑定。
Python 持有返回数组、配置、DTO、I/O、缓存及 GUI／BO 编排。
已替换的 Python 数值体已退役，独立参考保留在 `development/tests/`。

macOS arm64 使用 `libtpmshx_geometry_shared.dylib`，Windows x64 使用 `tpmshx_geometry_shared.dll`。
源码默认目录为 `sjtu_tpmshx/solvers/native/lib/<host>/`，冻结程序使用自身的 `native/`。
如需选择其他几何库，将 `TPMSHX_GEOMETRY_LIBRARY` 设为预构建文件的绝对路径。
历史结果读取和独立后处理不加载该库。
修改 C++ 函数或编入库的模型参数后，须重新构建并重启进程；共享 JSON 资源仍是权威来源。
贯通、扫描、Richardson 和目标 C 研究改用
`sjtu_tpmshx/development/runs/tools/asym_geometry_research.py`，shared 不保留转发别名。

仅构建几何时，`fetch-cmake` 只获取锁定构建工具。
`build`、`verify` 与 `publish --component geometry` 仍检查配置的 Python 解释器及选定环境锁。
下面的基础锁仅适用于基础环境；BO 解释器须选择对应 BO 锁。

```sh
tm1_python="$(sed -n '1p' .venv-path)"
tm1_lock=engineering/requirements/base.txt
"$tm1_python" engineering/scripts/build_native_dependencies.py fetch-cmake
"$tm1_python" engineering/scripts/build_native_dependencies.py publish --component geometry --python-lock "$tm1_lock"
```

Windows PowerShell：

```powershell
$tm1Python = Get-Content .venv-path -TotalCount 1
$tm1Lock = 'engineering/requirements/base.txt'
& $tm1Python engineering/scripts/build_native_dependencies.py fetch-cmake
& $tm1Python engineering/scripts/build_native_dependencies.py publish --component geometry --python-lock $tm1Lock
```

`publish` 包含构建与验证；如需分开，使用同一锁和缓存执行 `build --component geometry` 与 `verify --component geometry`。
独立产物默认位于 `.cache/native-deps/build/geometry-<host>`，验证执行静态／动态 C 调用方及几何 kernel smoke。
几何单独发布写入 `geometry-build.json`，不触及 solver 或 run_state。
内容不同的旧几何库及匹配记录保存在 `previous/`。
默认完整发布先构建并验证求解库、几何库、准备库和结果库，再以同一事务替换四个库。
求解库保留 `build.json`，几何库使用 `geometry-build.json`，
准备库使用 `preparation-build.json`，结果库使用 `result-build.json`。
Git 检出的 `source_commit` 记录完整提交号，`source_changes` 逐行记录已跟踪文件的变更。
空 `source_changes` 列表表示没有已跟踪文件变更。源码归档的两个字段均为 `null`。
替换失败时恢复选定文件及元数据；回滚失败时保留暂存文件并报告恢复路径。
旧求解检查点仍须使用精确保留的运行库、准备态输入和控制量。

application 与 full CI tier 均保留完整 native pilot 构建和既有求解器覆盖。
产物显式包含求解库、几何库、准备库和结果库。
原生与 BO 消费者从同一平台产物中恢复所需运行库。
完整计算仍限于 macOS arm64 与 Windows x64；独立 Linux 结果评估范围见下文。
Python wheel 包含代码和模型资源，不包含原生库。
桌面打包要求四个预构建输入，详见[桌面交付](desktop.md#可选冻结打包)。

<a id="native-preparation-core"></a>

## 原生准备核心

独立准备核心负责物性、Nu 闭合、固定 DF、实验修正、投影和准备数值。
独立 CMake 项目为 `sjtu_tpmshx/solvers/native/preparation/`。
目标为 `tpmshx_preparation`、`tpmshx_preparation_c` 和 `tpmshx_preparation_shared`。
它们复用几何／网格和共享模型实现，链接锁定的 CoolProp 静态库，
不构建完整求解器或 run_state，也不需要 SuperLU 或 AMG。
完整构建脚本分别构建 pilot 和 preparation 工程，共用一套物性和 DF 数值实现。
二维准备将 v7 域长／端口标量类型描述符与适用的版本载荷配合使用。
共享网格和端口核心保留整数与窄浮点混合运算。
原始空间准备 v8 为 air/air 条带、矩形和 sigmoid 场增加容量、解析及完整固定流量入口。
这些入口保留 CFD 阻力与零 delta，在 Nu 和换热计算前解析速度，并复用物理网格。
流量 owner 保存复制后的区域、控制点及 LUT，前段证据与最终准备证据分开。
v7 网格描述符与 v8 深度／目标类型保留标量算术。
准备 v9 将对称空间几何的 Python 准备、容量查询与流量解析切换到这些原生所有者。
带类型的缓存钩子通过既有宿主缓存保留实际键、可选 Nu 选择、发布顺序与证据。
Python 保留 LUT 内存／磁盘读写，缺表时原生代码在原几何检查点构建。
v9 模型保留空间导热系数实际值、类型，以及独立的几何外推／默认 LUT 标志。
公共配置保留原拓扑和导热系数比较规则，包括窄标量的相等比较。
空间计算使用被接受的空间数值，名义计算继续使用原值。
准备 v10 增加规定速度下既有非零 delta 的均匀 air/water 和 air/air 空间模式。
完整结果携带名义非对称热侧元组，与设计场和逐单元热场保持分开。
既有分流计算、标量转换顺序和 N128 几何索引不变。
Python 均匀及空间准备使用 v10；均匀容量和解析仍使用 v7/v3，连续入口仍使用 v7/v4。
空间容量和解析使用 v10，沿用 v9 结果视图与释放函数。
容量和规定总流量准备仍按原校验顺序拒绝非零 delta。
连续场、CO2/sCO2 和实验模型保留既有限制；此前 C 布局及范围继续可用。
保存运行描述符 v2 携带名义侧元组，通过既有完整二维生命周期接收离散及 sigmoid 场。
它保留 saved v1、结果所有权与同构建恢复，不重新准备保存算例。
公共分区与 sigmoid 组合查询在单独迁移前仍保留独立调用消费者。
`preprocess/two_d/preparation.py` 为原生适配器；被替代的 Python 二维准备流程及行 D-F 投影已退役。
冻结测试参考保留原流程与投影；既有三维准备路径仍单独保留。
回调与所有权合同见[空间宿主接口](native-stages.zh-CN.md#空间几何宿主缓存接口)。
v10 范围见[偏移几何](native-stages.zh-CN.md#既有偏移几何)，输入借用规则见[运行续算](native-stages.zh-CN.md#运行续算)。
已保存的准备工况继续使用记录的网格，适配器不重建历史网格。
Python 前处理入口调用独立结果库采集范围记录。准备库本身不链接结果库。

`shared/models/_native_preparation.py` 在需要时通过 ctypes 加载 preparation ABI 1。
具名物性、DF 和流量适配器保留现有 Python 公共接口。
Preparation 状态 0 表示成功，1 表示无效输入，2 表示分配失败，3 表示运行时错误；
状态 10、11、12 分别表示水、CO2、sCO2 状态错误。
几何 ABI 1 与 field ABI 2 不变，继续使用各自错误映射。
调用按显式元素数借用对齐缓冲区，失败不修改数值输出；
上下文在最后一次调用后必须由创建库释放。
缺库、ABI 不符或符号缺失时明确失败，不提供运行时构建或数值 fallback。

原始经验 getter、带检查的 EOS 调用和 Nu 闭合保留不同校验、下限与警告规则。
DF 插值保留原 bracket 容差、NaN 传播及端点行为。
投影在 C-order 打包前保留每个输入的归约顺序，包括加权和单轴字段。
float16 加权归约保留原中间舍入。
实验修正将来源标定、应用和运行窗口分别记录。
Python 保留配置、DTO、shape／类型适配、I/O、缓存、警告记录和 GUI／BO 策略。
离线拟合仍在 Python；冻结的开发参考提供独立 expected。
每段被替换的生产数值体在同批退役，调用方在同批完成迁移。
JSON 和固定 CSV 权威见[模型资源](model-resources.md#当前资源与研究输出)。

准备库单独发布要求同一缓存中已有锁定源码、锁定 CMake 工具和已构建的 CoolProp 静态库。
使用配置解释器及其精确环境锁；缺少 CoolProp 时，先完成 `fetch` 和 `build --component coolprop`。
这些输入就绪后执行：

```sh
tm1_python="$(sed -n '1p' .venv-path)"
tm1_lock=engineering/requirements/base.txt
"$tm1_python" engineering/scripts/build_native_dependencies.py publish --component preparation --python-lock "$tm1_lock"
```

Windows PowerShell 使用：

```powershell
$tm1Python = Get-Content .venv-path -TotalCount 1
$tm1Lock = 'engineering/requirements/base.txt'
& $tm1Python engineering/scripts/build_native_dependencies.py publish --component preparation --python-lock $tm1Lock
```

BO 解释器须选择对应 BO 锁，各步骤保留同一 `--cache`。
独立 `build` 和 `verify` 也接受 `--component preparation`。
默认构建目录为 `.cache/native-deps/build/preparation-<host>`。
完整求解器构建于 `pilot-<host>`。构建脚本分别使用两个 CMake 项目。
macOS 准备库链接使用 `-Os` 构建的 `coolprop-preparation-macos-arm64/libCoolProp.a`。
求解器保留 `coolprop-macos-arm64/libCoolProp.a` 的原构建设置。
这两种设置分别保留原 Python 物性查询和原 C++ 求解器的结果。
Windows 准备库使用原锁定的 Windows 静态归档。
每个归档的 `coolprop-build.json` 记录实际编译参数片段和工具链信息。
缓存将该记录与归档一起保留；发布时，各库元数据包含其实际采用的记录。
验证检查独立 C 静态／动态调用方、几何调用方及编入库的 CoolProp 版本／提交。
此验证不替代完整工况、物理、双库并发、平台 CI 或桌面验收。
源码发行包提供原生源码、构建文件、依赖锁、许可、来源记录和完整测试树。
wheel 提供 Python 接口、已发布的开发／验证工具与显式声明的资源，排除测试包及其子包。
原生构建仍是显式步骤。CI 在源码树外安装并检查两种构建得到的 wheel。
最小环境仅使用独立结果库，评估真实二维和三维文件。
`engineering/scripts/check_distributions.py` 实际构建并检查源码包及其 wheel。
须通过 `--output-dir` 指定 `.cache/` 下的新目录。
`publish --component preparation` 只发布准备库及 `preparation-build.json`，不替换求解库、几何库、结果库或 run_state 文件。
内容不同的旧库和匹配记录保存在 `previous/`，替换失败使用同一事务回滚。

macOS arm64 运行库为 `libtpmshx_preparation_shared.dylib`，Windows x64 为 `tpmshx_preparation_shared.dll`。
源码默认目录为 `sjtu_tpmshx/solvers/native/lib/<host>/`，冻结程序使用自身的 `native/`。
`TPMSHX_PREPARATION_LIBRARY` 选择其他预构建运行库。
桌面打包从 `TPMSHX_NATIVE_PREPARATION_LIBRARY` 接收它，同时要求求解库、几何库和结果库输入。
Python wheel 包含代码和模型资源，不包含原生库。
历史结果回读和独立后处理不加载准备库或几何库。

修改 C++ 函数或编入库的数据后，须重建受影响的库并重启进程。
求解、几何、准备和结果的构建记录与按版本隔离的物性表缓存保持独立。
求解库重新链接会产生新的构建身份；旧检查点仍须精确保留的求解库、准备态输入与控制量。
当前／previous 运行库和运行记录仍有消费者时必须保留。
Linux x86_64 支持独立结果评估。完整求解器与桌面支持仍限 macOS arm64 和 Windows x64。
实现范围与交付记录见[范围说明](#cpp-core-scope)。

<a id="native-result-core"></a>

## 原生结果核心

独立 result ABI 2 负责指标、有符号物理平衡、分区统计及数值资格检查。
结果阶段选择已记录证据，负责完整 2D/3D 指标定义、状态和资格。
Python 保留公开 DTO 和文件接口、原对象身份及 NumPy 事件处理。
三个独立结果查询使用同一原生阶段；Quick Design 指标运算也由同一阶段负责，固定具名宿主操作保留既有 Python 对象、任意精度整数和转换协议。
带版本的宿主查询保留延迟输入错误和回调异常，不改变已发布的 v1 C 布局。
独立 `solvers/native/result/` 项目只使用 C++17 和系统库，
不加载求解器、准备库、几何库、CoolProp 或模型资源。

纯导入和 HDF/JSON 读取不加载原生库；实际指标运算需要预构建结果库。
`TPMSHX_RESULT_LIBRARY` 可指定其他文件的绝对路径；默认目录是包内 `solvers/native/lib/<host>/`。
三种库名分别为 `libtpmshx_result_shared.dylib`、`tpmshx_result_shared.dll`、`libtpmshx_result_shared.so`。
Linux x86_64 只支持独立结果评估。
Linux 仅允许 `fetch-cmake`、`build`、`verify` 和 `publish`，且必须指定 `--component result`。
此流程不获取或校验模型源码、不生成模型系数，也不构建完整求解器。

若 `.venv-path` 已记录既有最小环境：

```sh
tm1_python="$(sed -n '1p' .venv-path)"
"$tm1_python" engineering/scripts/build_native_dependencies.py fetch-cmake --component result
"$tm1_python" engineering/scripts/build_native_dependencies.py publish --component result --python-lock engineering/requirements/postprocess.txt
```

使用基础或 BO 环境时选择其精确锁。Windows 在 MSVC 开发终端使用相同参数。
独立 `build --component result` 与 `verify --component result` 使用同一锁和缓存。
默认构建目录为 `.cache/native-deps/build/result-<host>`。
验证运行独立 C 静态、C 动态和 C++ 核心调用方，并检查精确 C 导出及系统运行库依赖。
独立结果发布不构建求解状态，`result-build.json` 保留实际编译器、选项、产物和 SDK 元数据。
其依赖记录为空，不包含 CoolProp 构建记录。
macOS／Windows 完整发布以同一事务部署四个库，并保留各自匹配的前一版本。
CI 保留完整 macOS／Windows 构建，并增加独立 Ubuntu `result-build` 作业。
该作业向 `minimal-postprocess` 提供 `result-build-linux-x86_64`，后者还接收独立的 macOS `real-file-handoff` 输入。
最小作业检查独立结果参考和真实保存的 2D/3D 文件，不构建求解器或模型库。
[来源与接口说明](../sjtu_tpmshx/solvers/native/result/sources.md)定义类型、缓冲区、错误及许可声明。
不提供数值回退、运行时编译器或通用数值回调。

<a id="complete-quick-design-capability"></a>

## 完整 Quick Design 能力

[Quick Design 阶段](native-stages.zh-CN.md#quick-design-阶段)为 native double 调用者增加
原始工况准备和具有独立所有权的结果证据。独立的版本 1 C 合同保留下述既有驱动 ABI。
Python 生产接入仍需单独完成类型与事件验收。

`quick_design_driver.hpp` 负责完整准备态 const/mean 物性阶段计算。它包含原有经验空气／水或 HEOS sCO2 物性、既有 Nu、一次或两次温度计算、全场热启动、逐阶段液态水检查、迭代预算、进度和取消。准备好的入口状态解析压降比例保持固定。这是既有给定流量尺寸设计近似，`physical_validation=not_established`。

`solver_c_api.h` 提供独立、带版本的 C 入口和具名配置／结果结构。接口借用九个显式长度数组。错误区分非法输入、水入口／物性状态、水温度场、算术失败和其他原生异常。取消有独立结果状态。失败场不能发布为已接受结果。构建流程分别对静态库和动态库运行同一个独立 C 调用方。

薄 Python 适配器复用共享准备态输入校验和 `FieldResult` 映射。原生阶段证据提供场、物性和原警告记录，不调用 Python 数值核或物性函数。主机库位置属于执行控制，不在 `CaseData` 中：

```python
from sjtu_tpmshx.shared.domain.module_ports import RunControl
from sjtu_tpmshx.solvers.api import run_case

result = run_case(prepared_case, RunControl(
    backend="cpp", native_library="/absolute/path/to/libtpmshx_solver_shared.dylib"))
```

Windows 使用 `tpmshx_solver_shared.dll`。路径必须指向该主机上已构建的库。库缺失、ABI 不符或能力不支持时明确失败。公开结果保存、加载和离线评估使用既有接口。macOS/Windows 原生 CI 包括新进程保存态 Case 重放，且禁止 Numba/Python 求解核；另检查回调失败、取消、恢复和并发运行。这些运行覆盖所测 C ABI 和命令行路径；可见桌面交付仍需独立验收。

<a id="complete-full-2d-capability"></a>

## 完整 full 2D 能力

`full_2d.hpp` 和 `full_2d_c_api.h` 提供完整矩形双流体二维驱动。驱动负责既有 SIMPLE 流动更新、入口压力参考与气体压力射击、物性／闭合更新、外循环耦合、所选 temperature/model-h/true-h 求解、Richardson 转移，以及最终场和能量证据。局部端口、空间 L/t 场、真实边界通量，以及区分的最终流动／热压力状态都保留准备态契约。

主热量指标仍为 W/m；总质量流量优化仍要求显式物理深度。执行完成与收敛保持区分，包括预算耗尽、证据检查失败和取消。

full 2D 使用 **ABI 2**。第 29 个准备态数组保留原闭合输入中的无量纲比值 `(D_h_m * 1000) / L_mm`。从舍入后的 SI 长度重建比值可能改变梯度场换热系数的末位。C 符号和结构采用 `v2`；适配器在数值调用前拒绝 ABI 1 库。必须一起分发匹配的库、头文件和适配器。已保存 FieldResult 仍由既有可移植读取器加载，无需原生库。

上述公共调用也接受 full 2D `CaseData`。CLI、桌面和设计调用方传递同一个 `RunControl`。源码 CLI 示例：

```bash
"$PYTHON" -m sjtu_tpmshx.cli solve case.h5 results.h5 --backend cpp \
  --native-library /absolute/path/to/libtpmshx_solver_shared.dylib
```

绑定校验准备态输入，传递借用的输入视图，在释放前复制结果所有者持有的数组，并映射到既有 `FieldResult`。主机库和表目录不序列化到工况或结果。新进程 CLI 求解、保存回读和离线评估不加载 Numba 或 Python 数值驱动。当前资格检查通过独立审计和原生组件重放检查完整场、状态、预算、压力与能量。历史 Python 比较保留原容差和结论。macOS 运行成功不证明 Windows 验收。

<a id="complete-full-3d-capability"></a>

## 完整 full 3D 能力

`full_3d.hpp` 和 `full_3d_c_api.h` 通过 ABI 2 提供矩形双流体三维外循环驱动。它消费相同准备态 XYZ 场和局部端口几何，执行带压力参考的 SIMPLE 及所选 temperature/model-h/true-h 耦合，并返回原有最终状态证据、警告和场位置。可选粗网格初始化保留细网格压力边界值。原生结果不由 Python 数值核提供。

完整 3D ABI 2 删除外层物性 Anderson 控制项和结果字段。头文件、原生库和绑定必须匹配。Python 绑定在数值调用前拒绝 ABI 1。固定物性松弛与热方程 Anderson 保留。旧结果仍可读取；检查点仍要求构建身份匹配。

初始化诊断通过独立于完整结果的查询提供。`tpmshx_full_3d_get_bootstrap_trace_v1(result, side, trace)` 为 side 0/1 提供独立只读视图。字符串和层数组由结果所有者持有，仅在调用 `tpmshx_full_3d_release_v1` 前有效。查询不执行数值工作，也不分配内存。C 调用方必须使用 ABI 2 结果布局。当前 Python 绑定要求新查询符号；旧库缺少该能力时明确报错，不虚构轨迹或代用 Python 求解。

轨迹记录显式启停、实际粗网格形状与深度、逐层上限、进入的迭代数和停止原因。它保留原递归 `count > 2000`、子层上限 200、最小轴长及停止规则。`started_cap_sum` 是实际进入迭代的各层上限之和，不是共享全局初始化预算。未开始即取消的父层贡献零迭代，且不计入该上限和。绑定在释放前复制轨迹，写入 `diagnostics.coarse_bootstrap_trace`。不含此可选键的旧结果仍可读取。

合作式取消结果仍持有部分诊断视图，C 调用方可在释放前查询。Python 绑定抛出 `CancelledError`，在 `coarse_bootstrap_trace` 附带独立副本，不发布部分 FieldResult。硬 C API 错误仍保持调用方结果不变，也不发布所有者，因此此时不能通过查询取得完整轨迹。原算法捕获的初始化局部失败仍被记录，不能声称种子已应用，也不能用配置上限替代实际计费工作。

共享物理端口压力归约保留参考掩码数组顺序和连续成对求和，同时用于加权压力与开口面积。这也固定压力射击的入口锚点。改变求和顺序，即使初始压力只差舍入量，也可能改变后续 SIMPLE 停止迭代。完整场检查因此必须保留原迭代预算和比较容差。

相同公共 `run_case` 和 CLI 命令可选择 full 3D CaseData。数值资格检查包含原 24³ 工况及完整场、压力和热证据，预算与比较门槛不变。该限预算工况的历史 Python／原生对照均为 `converged=False`；相符不等于收敛。full 3D model-h 热量仍为 W。原 temperature 路线缺少完整焓证据时，仍保留热量不可用边界。优化继续使用独立的 model-h 物理边界与能量检查。

<a id="fixed-flow-conservative-temperature-candidates"></a>

## 固定流动的守恒温度候选算法

`enthalpy_driver.hpp` 中的 C++ `solve_enthalpy` 使用 `EnthalpyAlgorithm::temperature_sou`。两个直接 C 入口均使用 T-SOU：v1 固定 1e-8 K 更新门，v2 接受正 K 容差；两者保留严格归一化焓更新及边界不平衡门。该算法覆盖张量网格上的两个求解流体，包括单位深度二维拉伸。输入包括有符号质量面、局部绝对压力、有效固体导热率和体积换热系数。方向 0–5 将流入限定在声明面；方向 -1 将标量入口状态用于全部外边界流入。完整驱动保留声明端口检查。外部导热边界绝热。此入口不准备质量流量、不求解 SIMPLE，也不评估 Nu。

每次非线性更新冻结独立的真实 h、T 和 cp 数组，然后交替执行正序／逆序的 A、B 和固体 sweep。流体对流采用线性化 `h* + cp*(T-T*)`，扩散采用温度。SOU 在物理坐标上直接根据真实焓冻结 minmod 修正，包括出口面，并对固体使用完全松弛。

SOU 在真实状态更新前，将完成的三相块增量乘以 0.6。这抑制了拉伸 full 2D 网格上已复现的限制器振荡，不改变稳态方程。随后，带检查的 HEOS PT 更新以真实状态替代线性化焓，再评估残差与热负荷。不使用 BICUBIC 表、H→T 反演、裁剪或恢复回退。

SOU recipe 2 在该阻尼普通映射上使用六样本 Anderson 候选。选择前以真实 HEOS PT 物性和原能量审计校验每个候选。候选必须严格降低按原容差归一化的方程比和耦合比中的最大值。无效或非有限候选保留普通更新。接受候选后继续迭代。首次／最终块以及普通温度更新较小时，都使用完整普通 PT／审计块；只有该块可以判收敛。`picard_relaxation=0.6` 描述普通映射，不描述每个 Anderson 增量。

同一个已加载库的 `tpmshx_energy_algorithm_version_v1` 根据实际返回算法报告 SOU recipe 2。Python 将该身份记录在主／外循环证据、有效设置和边界捕获中。缺少查询的旧库在守恒流动执行前失败。已保存 FOU recipe 1 和 SOU recipe 1/2 边界证据仍可读取，不重放 EOS 或推断版本。算法 recipe 版本独立于 C ABI。

完整驱动要求正的耦合、方程容差，以及以 K 为单位的正 `temperature_update_tolerance`。三项检查必须在同一真实状态上同时满足。`EnthalpyResult::algorithm` 标识实际算法；`temperature_update` 仅存在于这些路线。既有 `residual` 仍记录归一化真实焓更新。SOU 最终证据重新构造实际面修正，并一致用于边界热负荷和局部残差。达到迭代上限时保留真实证据；取消使部分场无效并清除该证据。

`conservative_energy_smoke` 检查独立冻结平衡、六方向非均匀面通量、焓参考不变性和非法输入。`conservative_energy_driver_smoke` 检查真实 EOS 状态、冷／热启动一致性、独立出口热负荷、取消、迭代上限和物理域失败。依赖组件验证运行两者。其范围是固定流动数值资格；完整流动／闭合验收、已保存的历史对照及实验适用性保持独立。

<a id="explicit-full-flow-candidate-selection"></a>

### 显式选择完整流动候选

在 `prepare_case` 前，使用默认 `solver.enthalpy_algorithm=temperature_sou`，并将 `solver.enthalpy_temperature_tol_K` 设为所需正 K 容差。随后使用 `backend='cpp'` 和匹配原生库执行已保存工况。默认 K 容差为 1e-8。T-SOU 用于既有双流体 true-h 路线；model-h、其他温度内核及 Quick Design 保留原物理路线。对不兼容路线显式设置 EOS 控制时，在流动执行前失败。该选择不扩大流体、沸腾、冷凝或 Nu/Darcy-Forchheimer 适用范围。GUI 尚未提供此算法选择。

完整三维候选也支持 `port_wall_refine` 生成的非均匀张量网格，覆盖完整和部分开口。计算使用实际单元宽度及端口面质量流量。model-h 的端口能量标志不改变此 true-h 路径。此支持不改变已保存算法、默认值或验收门。

完整驱动保留原 SIMPLE、压力、物性、外耦合和最终验收门。full 3D 保留热学和质量准备，不执行温度预测扫描。T-SOU recipe 每个非线性步使用五次 sweep，流体松弛为 .2，固体松弛为 1。full 3D 在准备态 Case 中保存已解析控制量；二维未设置控制量时采用对应算法版本的 recipe。默认设置下，T-SOU 保留完整驱动原迭代预算，并要求真实耦合／方程能量比不大于 .001，同时满足声明的温度更新容差。原生结果记录实际整块 Picard 松弛 0.6；它与流体及固体行松弛分开。

`tpmshx_solve_full_2d_v3` 和 `tpmshx_solve_full_3d_v2` 接受共享 `tpmshx_energy_options_v1`，保留旧结果 POD 和释放函数。对应 `get_energy_evidence_v1` 查询借用同一所有者，不执行求解。它提供实际算法／温度更新、最终 epsilon×HEOS 导热率、六个向外有符号焓功率面，以及逐外步标量身份。旧入口仍可用，默认执行 T-SOU。当前库在流动前拒绝显式旧算法标识；旧检查点须使用匹配的归档运行库和原控制参数。

显式控制使用 `tpmshx_solve_full_2d_v4` 或 `tpmshx_solve_full_3d_v3`。
两者接受同一组已持久化的 EOS 迭代、扫掠、松弛与收敛设置。
二维 v4 控制块还包含 `tpmshx_energy_options_v2`。
它覆盖 `config_v2` 中的两个热控制值，其他值保持原含义。
现有实际执行设置查询记录每次热调用使用的控制参数。
积分 model-h 路线在流场执行前拒绝这些 EOS 专用设置。

Python 绑定在释放前复制查询视图，并在 `backend_version` 中记录实际调用的入口。当前运行库使用含 CPU 线程限制的 `full_2d_v6` 或 `full_3d_v5`。保留的旧运行库在支持所请求控制量时，可以使用较早的能量或迭代控制入口。候选结果采用可移植 `thermal_mode=conservative_energy`。`boundary_fluxes.true_h` 包含既有真实 h、入口 h、质量数组，以及算法／版本、六面 `boundary_power`、W/m 或 W 单位和完整性标志。各侧热负荷为 `-sum(boundary_power)`。

SOU 在出口面重构物理焓，因此旧 FOU 单元焓归约不能提供该热量。面证据缺失或无效时指标不可用，不进行替代重构。最终流动更新后的压力和速度，与已接受或限预算的最后热状态保持区分。二维候选保留 true-h 单位深度约定，不生成 Richardson 证据。

<a id="first-implemented-slice"></a>

## 首个实现单元

冻结 H-FOU sweep、其裁剪规则及低层 C 导出已退役，Git 历史保留原实现。`enthalpy_sweeps.hpp/.cpp` 中共享 `FluidView`、审计类型与 `thermal_energy_audit` 仍由守恒温度内核及真实状态审计使用。`conservative_energy_smoke` 保留独立冻结平衡、压力偏移、导热线、六方向面功率和非法输入检查。

<a id="second-implemented-slice-actual-state-energy-audit"></a>

## 第二个实现单元：真实状态能量审计

同一库在 `sjtu_tpmshx/solvers/native/src/enthalpy_sweeps.cpp` 中提供 `thermal_energy_audit`，执行真实状态能量审计：

- 真实状态 A/B 单元残差为 Fourier 导热＋固体交换－有符号迎风焓散度。调用方提供真实 EOS 温度和有效流体导热率，不使用 sweep 的冻结线性化状态。
- 计算绝热固体单元残差和六面有符号边界焓热负荷。入口／回流面使用给定入口焓，流出使用单元焓。
- 保留既有耦合比与方程比，包括不变的分母 `max(abs(Q_A), abs(Q_B), 1)`、流体残差绝对值和／最大值及固体和。三维输出为逐单元 W，既有单位深度二维拉伸为 W/m。

算子不应用验收阈值，也不评估 EOS、校验物理适用范围、平衡质量、统计此前裁剪或判定收敛。这些驱动检查仍然必需。非法输入在写残差前拒绝。算术溢出报错，并使全部输出缓冲区无效；状态／系数数组保持只读。

资格检查比较真实残差场和能量预算，不只比较最终比值。独立检查包括六个有符号流向、单单元 20 W 交换、内面抵消、等温压力相关焓，以及故意不平衡的局部温度场。最后一种场的全局／耦合预算为零，但方程残差为正。

<a id="shared-finite-volume-temperature-consumers"></a>

## 共享有限体积温度算子的使用方

集成 fullCC 候选通过严格 model-h 驱动和真实热状态质量面，输运既有空气／水积分焓 h(T)。它替代早期可变 cp 的 m*cp*T 提案。早期物理契约失败保留为历史，不描述当前实现。此前数值和资源资格仍归属于各自构建；最终库和应用验收保持独立。固定 cp Quick Design 是另一种近似，不代表可变 cp 积分焓。

私有 `energy_fv_rows.hpp` 提供共享输运、Fourier 导热、LTNE 交换和物理源项行。它不选择流体模型、不准备 SIMPLE/MAC 面、不持有 EOS，也不授予调用方收敛规则。CMake 对所有实例化共享行的源码应用相同的禁止浮点收缩策略，包括直接核 smoke。这样可避免链接顺序选择同一模板的不同舍入副本。该策略仅作用于相关源码；保留的旧热核维持原编译选项。

实际调用边界如下：

| 使用方 | 驱动与保留契约 |
| --- | --- |
| Quick Design const/mean 与独立 CC | `temperature_driver.cpp` 的 `solve_temperature`；每阶段固定系数、热容输运、冷／热启动、有限预算和取消。 |
| 空气／水 full2D temperature 主／细网格，以及 full3D CC Nz=1 | 严格 `solve_model_h_2d`；既有空气／水 h(T)、A-SOU/B-FOU、准备态 mass/K/h_v，以及原调用预算。 |
| 空气／水 full3D CC Nz>1 | 严格 `solve_model_h_3d`；两侧 SOU、准备态 mass/K/h_v、给定 B、非对称几何，以及仅严格模式支持的水／水。 |
| 既有产品 model-h | 默认非严格 model-h 驱动及原资格／停止规则；fullCC 复用不授予优化资格。 |
| full3D true-h 准备 | `true_h_preparation` 保留 CC 输入校验；交错准备保留投影。两者都不更新温度。EOS 驱动保留算法及物理门。 |
| 交错／MAC temperature | 既有投影／缓存及热容面准备；保留的非守恒平流研究修正不具备 fullCC 积分焓资格。 |
| true-h | 默认 T-SOU；EOS 物理关系及独立物理门仍由焓驱动负责。 |

full3D true-h 在每次外层焓求解前不执行温度扫描。首次调用使用流体入口温度和配置的固体初温；未指定固体初温时，使用两入口温度均值。后续调用使用上一轮热场。热系数、入口热容通量、面通量平衡／投影及输入校验保留。焓驱动校验初始 PT 状态，并提供最终热结论。

私有 G4 迭代器和交错预热专用行已退役。CC 校验函数保留原输入校验，不改变热场。交错准备仍以零温度预算运行并记录投影证据。准备完成后的第一个热学检查点属于 EOS 驱动。旧检查点需要匹配的存档运行库；历史结果记录仍可读取。full2D true-h 不使用此 full3D 准备路径。

单 A 侧 sCO2 执行已退役。原生输入边界在数值计算前拒绝 A 为 sCO2 且 B 关闭的输入。空气／水关闭 B 的验证及暂停恢复覆盖保留。带 `legacy_frozen_cp_single_a_cc_v1` 的历史结果仍标记缺少完整 h(P,T) 输运证据，不能获得 model-h 账本。旧单 A 侧 sCO2 检查点需要匹配的存档运行库。


fullCC 使用已接受的热状态 SIMPLE 质量面，不乘 cp，不从单元速度重建质量，也不重复乘孔隙率／开口。model-h 驱动在重构面温度上评估既有 h(T)，并使用原准备态 Fourier 导热率和交换系数。full2D 行与功率使用单位深度、W/m。full3D Nz=1 要求活动 z 面质量为零；将真实质量除以深度后交给二维求解，再将残差、源／储库和边界功率乘以深度一次，返回 W。温度不变。

严格 fullCC 保留热负荷／场稳定条件，并额外要求新计算的完整边界账本。各相绝对单元残差和中的最大值，以及耦合边界／源不平衡中的较大者，必须不超过界面交换尺度的 1e-7，尺度下限为一个原生功率单位。检查失败时在原预算内继续。物理流入不完整时不能收敛。严格 SOU 使用真实入口距离和单侧流出重构。严格入口 Fourier 导热在行和审计中都使用热阻／矩规则。非严格产品 model-h 边界不变。fullCC 仍不支持非零制造体源。给定 B 是外部温度储库，不参与更新、Anderson 或求解方程，也不虚构 B 证据。

以下受控线迭代仅描述固定系数 QD／独立 CC 驱动，不描述严格 fullCC model-h 适配器。独立 CC 从给定单元场重构唯一有符号热容面。显式热容输入已包含孔隙率／面积／深度因子，并优先于该重构。每个内面使用一个 T-minmod 修正。流入完整、二阶输运活动且不采用红黑排序时，每块包含至多四次点 sweep 和一次带检查的线 Newton 试探。

只有真实状态物理误差严格下降时才接受试探。两个比较状态都采用相同的 0.6 块阻尼；拒绝后保留阻尼点状态。A 和 SOU B 的点 sweep 使用 min(caller alpha,0.2)；FOU B 与线试探使用调用方 alpha。退化或红黑工况使用点块。预算统计每个请求步；取消不能证明收敛。

该固定系数驱动的完整边界收敛要求 Q／场稳定，以及新计算的最大相残差／耦合边界源平衡不大于 1e-7。归一化使用较大界面功率，下限为 1 W 或 W/m。直接热容调用存在未标识外流入时不能收敛。独立重构热容调用在边界不完整时保留历史稳定状态，同时明确暴露缺失边界证据。此固定系数驱动不查询 EOS。CC 仍拒绝非零制造体源；交错／model-h 保留既有源能力。给定 B 是外部温度储库，不提供已求解 B 残差证据。

只读查询区分实际固定系数受控线、交错和 model-h recipe。fullCC 空间契约标识为二维／Nz=1 的 `model_h_tface_sou_fou_strict_v3`，或 Nz>1 的 `model_h_tface_sou_sou_strict_v3`。增量 full2D/full3D `get_model_enthalpy_evidence_v1` 保留既有求解结果布局，返回 `tpmshx_model_enthalpy_evidence_v1`，不使用旧热容账本布局。

每个求解流体记录既有二次 cp(T) 的 [c0,c1,c2,Tbase,Tref] 及积分基准 h(Tref)=0。还记录求解相标志、物理残差、源／储库功率，以及向外 m*h(T_face)／Fourier 平面。视图借用结果所有者；绑定在释放前复制。二维主／细网格阶段保留独立实际身份。请求的热模式仍为 `temperature`，可移植证据声明 `model_enthalpy_temperature_v1`。离线后处理校验并归约已捕获功率，不运行求解器、EOS 或新面重构。可用性不等于收敛，这些记录也不赋予产品 model-h 优化资格。新账本字段缺少声明时无效；不含新字段的历史文件保留原规则。

当前资格范围有限。六十个严格入口热阻／矩 smoke 配置覆盖六方向和十类系数／边界，检查局部行与账本，不是完整 PDE 网格阶数结果。定义的 N3 分层协议另通过独立算子／K=0 解析检查、来自 20 个独立行的 84 个接受轴向阶数区段、共 42 项指标，以及六组实际 64³ 制造解的原绝对误差门。它不证明任意三维流动全局二阶；32→64 阶数仍作为趋势报告。原六组 MMS 总体为 0/6 通过，原轴向总体为 4/6 通过、2/6 失败；后续协议不改写这些历史结果。

N5 的十二个刻意限预算请求成功返回，并通过十四个已记录热阶段的算术审计，但产品请求收敛为 0/12，热阶段收敛为 2/14。独立正常预算总体通过三个完整稳态使用方：二维主／细网格、三维 Nz=1、三维 Nz>1；四个热阶段审计也全部通过。此前稳态候选的 2/3 结果及失败的二维主／细网格检查保留为历史。

这些固定总体不证明实验精度或 N6 性能／内存验收。旧固定热容组件计时不是相同 h(T) 算子的完整驱动成本比较。新原生算法要求独立矩阵、解析、网格序列、真实状态平衡和生命周期资格。旧 Python 轨迹测试只保留为同算法历史证据，不能证明改变后的原生方法等价。原生成功退出、完整物理账本、收敛和实验精度是不同事实。原生默认值不扩大物理适用范围。

<a id="build-and-run-the-qualification-checks"></a>

## 构建并执行资格检查

已有 POSIX C++17 编译器和 `make` 时，从仓库根执行：

```sh
make -f sjtu_tpmshx/solvers/native/Makefile CXX=c++
make -f sjtu_tpmshx/solvers/native/Makefile check
```

这生成 `.cache/native/libtpmshx_thermal.a`。C++ 调用方包含 `sjtu_tpmshx/solvers/native/include` 并链接该归档。温度线求解器构建要求既有锁定 Eigen 头文件，并启用 `EIGEN_MPL2_ONLY`。`TPMSHX_EIGEN_INCLUDE` 默认指向锁定 Eigen 源码 `.cache/native-deps/src/Eigen-5.0.1`。隔离源码树可显式设置该变量。目录缺失时构建失败，不下载依赖。

低层归档不链接 Python、Qt、NumPy、CoolProp/EOS、OpenMP 或绑定库运行时。完整依赖组件库另有 EOS／压力依赖。`check` 构建并运行独立 C++ 温度及守恒能量调用方。原纯热 shared 目标仅导出已退役 H sweep，因此一并移除。完整依赖构建继续在两个目标平台覆盖直接 T-SOU、完整二维／三维、model-h、温度与流动接口的 C 静态／动态调用。该低层库不随 Python wheel 或桌面应用打包，不自动发现，也不在运行中构建。

Windows 已有 x64 Visual Studio 开发者命令提示符时运行：

```bat
nmake /f sjtu_tpmshx\solvers\native\Makefile.msvc check
```

这在 `.cache/native` 下生成 `tpmshx_thermal.lib`，再运行相同 C++ 调用方。这些命令不安装编译器。完整求解器 C ABI 保留显式 Windows 导出／导入和 `cdecl`；ctypes 通过 `CDLL` 加载其 DLL。

`thermal_c_api.h` 保留共享导出和调用约定宏，冻结 H sweep 导出已退役。完整 C 接口保留有界错误、缓冲区及物理校验；异常不跨越 C 边界。能量审计测试保留仅供测试的桥接。

通过常规环境检查后，使用 `.venv-path` 解释器：

```sh
tm1_python="$(head -n 1 .venv-path)"
"$tm1_python" -m sjtu_tpmshx.development.runs.tools.check_locked_environment
"$tm1_python" -m pip check
MPLCONFIGDIR="$PWD/.cache/matplotlib" \
XDG_CACHE_HOME="$PWD/.cache/xdg" \
TPMSHX_REQUIRE_CPP_TESTS=1 TPMSHX_REQUIRE_NATIVE_DEPS_TESTS=1 \
"$tm1_python" -m pytest -q sjtu_tpmshx/development/tests/native
```

所有显式 `TPMSHX_TRUE_H_KERNEL` 覆盖均已退役，包括 `numba` 和 `cpp_sweeps_v1`。已保存准备态请求在流动执行前被拒绝；删除覆盖后使用原生执行。环境快照保留该键仅为明确拒绝。新 Case 不再捕获 `TPMSHX_THERMAL_LIBRARY`，原生库选择属于 `RunControl`。旧结果可在不加载求解库时读取，历史 Python `sweep_kernel` 和 `energy_audit` 记录保留原含义。

必需标志使缺少编译器或依赖组件成为资格检查失败。可选本地组件测试可以跳过缺失组件，但跳过不代表原生验收。macOS 3.13 和 Windows 3.12/3.13 CI 要求原生资格；本机通过不证明 Windows 分发验收。测试不安装编译器或 Python 依赖。

原生焓 sweep 测试保留固定随机字段、有符号／零面流量、非均匀网格、六方向、单单元轴、零对角元、裁剪与修改前拒绝。独立检查覆盖等温压力相关焓、指数冷却、一阶网格收敛以及边界／源能量平衡。零变化参考保留 `atol=2e-8 J/kg` 和 `atol=2e-11 K`；裁剪次数不超过计费 sweep 预算。原生构建不启用 fast-math。这些检查验证数值算子，不证明 sCO2 实验预测或应用加速。

能量审计固定比较容差为 `rtol=2e-12`，逐单元 `atol=1e-9 W`，归约预算 `atol=1e-8 W`，无量纲比 `atol=1e-12`。二维使用相同来源单位归一化。独立 NumPy 审计算术检查真实残差场和预算；这些比较不改变生产验收门。性能检查须计入校验与绑定开销，并区分 EOS 初始化、原生构建、核执行和完整求解。历史 Numba 计时归属于 0.1 及对应算法路线。

公共执行测试保留物理场、有符号边界通量、压力、指标、文件交接、取消与真实原生错误检查。原生工程用例继续执行原 F2、收敛和能量门。

<a id="isolated-eos-and-pressure-dependency-qualification"></a>

## 隔离 EOS 与压力依赖资格

依赖组件构建为显式步骤，与生产后端选择分开。`sjtu_tpmshx/solvers/native/dependency-pilot/` 是包含几何目标的完整求解器构建项目；[独立几何构建](#native-geometry-core) 只需要锁定 CMake 工具与生成的模型数据。输入锁定在 [sjtu_tpmshx/solvers/native/dependencies-lock.toml](../sjtu_tpmshx/solvers/native/dependencies-lock.toml)：CoolProp 8.0.0 及九个固定提交的 CPM 头文件依赖、SuperLU 7.0.1 及选定的三项 SciPy 1.18.1 double-LU 修正、AMGCL 1.5.0 和可移植 CMake 4.4.4。SuperLU 源码不等同于 SciPy 内附修订。源码、二进制、日志和 EOS 表都保存在本工作树 `.cache/native-deps`。[第三方说明](../sjtu_tpmshx/solvers/native/THIRD_PARTY_NOTICES.md)记录链接组件和原始许可声明。

`engineering/scripts/generate_native_model_coefficients.py` 读取共享
`model_parameters_v1.json`、`preparation_df_v1.json`、固定 DF CSV 与既有 CO2 资源。
资源读取器仅使用 Python 标准库，生成器不导入数值模型实现。
构建在所选缓存的 `generated/` 目录下生成 `tpmshx/model_coefficients.hpp` 和 `tpmshx/preparation_df_data.hpp`，默认目录为 `.cache/native-deps/generated/`。
C++ 使用生成的常量，运行时不解析 JSON，也不调用 Python。
几何、准备和求解代码使用已声明的模型资源；既有模型身份、单位、拟合系数和实验结论不变。
本次实施与退休范围见[范围说明](#cpp-core-scope)，数据来源见[模型资源](model-resources.md#当前资源与研究输出)。

Python wheel 包含代码、JSON 和 CSV 资源，不包含原生库；原生求解库仍须单独显式构建。
系数未变不表示旧检查点能使用新构建的求解库。
恢复必须使用精确匹配的已保留运行库、已保存准备态输入和控制量。
构建替代库时，保留每个已保存运行所需的匹配库。

获得原生依赖准备的明确授权后，使用配置解释器和既有锁检查。`fetch` 是完整依赖的联网步骤；`fetch-eigen` 仅获取无 EOS 热库所需的固定 Eigen 5.0.1 头文件。`build` 离线运行，不安装 Python 包或改变共享环境。CoolProp 构建使用显式本地 CPM 路径并关闭 FetchContent 联网，不获取可选测试或包装模块：

```sh
"$tm1_python" engineering/scripts/build_native_dependencies.py fetch
"$tm1_python" engineering/scripts/build_native_dependencies.py build
"$tm1_python" engineering/scripts/build_native_dependencies.py verify
TPMSHX_REQUIRE_NATIVE_DEPS_TESTS=1 \
MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg" \
"$tm1_python" -m pytest -q -ra \
  sjtu_tpmshx/development/tests/native/test_native_eos.py \
  sjtu_tpmshx/development/tests/native/test_native_pressure.py \
  sjtu_tpmshx/development/tests/native/test_superlu_error_boundary.py \
  sjtu_tpmshx/development/tests/native/test_fluid_properties.py \
  sjtu_tpmshx/development/tests/native/test_quick_design_driver.py \
  sjtu_tpmshx/development/tests/native/test_cpp_quick_design.py
```

EOS 调用方以与 Python 参考相同的具名后端评估 CO2 和 Water，即 HEOS 或 BICUBIC&HEOS。检查正向物性、焓反演、既有 CO2 范围、稳定液态水约束和独立可变状态。它不以 CoolProp 数值替代项目经验空气／水输运函数。每个进程使用显式表目录，不改变父 Python EOS 设置。`test_native_eos.py` 固定物性比较容差；它与 PDE 验收以及 BICUBIC 相对 HEOS 的插值误差分别管理。

压力调用方消费规范 32 位 CSR，保留原零 Dirichlet 行，并报告原 `Ax-b` 残差和固定点误差。不超过 2000 单元的二维／三维系统使用 SuperLU/COLAMD。较大三维系统使用原 PyAMG 5.3 的经典强度、分裂、修正插值、Galerkin 顺序和对称 Gauss–Seidel 循环，同时保留原 SciPy BiCGStab 停止及 breakdown 规则。

200 次预算、已解析相对容差，以及复用预条件器时使用当前矩阵乘法的规则不变。仅原 breakdown 路径以 L2 缩放右端重试；资格检查报告未缩放方程残差。最初 AMGCL 压力候选未通过完整工况比较，已被替换。AMGCL 仍用于独立交错温度投影。构建排除 MC64/ILU，并使用三项锁定的 SciPy double-LU 数值修正。

SuperLU 调用采用纯 C 错误边界和线程局部分配账本。分配失败和 ABORT 在清理后返回有界错误，跳转不跨 C++ 栈帧。macOS 资格在每个观测到的分配序号注入失败，并在 release 和 ASan/UBSan 构建中检查同进程恢复、长 ABORT 消息、奇异 info 和独立并发线程。Windows 必需 CI 也通过 release 分配、ABORT 和恢复检查；这不将 sanitizer 证据扩展到 Windows。非法输入和未知后端错误不静默回退 LU。这些压力测试本身不能建立完整原生 SIMPLE 或外耦合资格。

完整固定流动 true-h、二维／三维 model-h 和二维／三维 SIMPLE 均已有独立 C++ 实现、带版本 C 接口，以及 `solvers/backends/cpp/` 下的显式 Python 绑定。热绑定返回既有能量和原始边界元数据。原生 model-h 在 C 调用方释放结果前持有审计数组；Python 绑定释放前复制视图。回调异常和取消丢弃部分状态。

SIMPLE 接口持有逐实例压力缓存，并保留原 F2、出口、热启动状态和原始质量证据。这些可独立调用驱动也支撑上述完整二维／三维外耦合后端。macOS SuperLU 构建使用锁定 SciPy 参考所用的系统 Accelerate BLAS，并为二维 SIMPLE 保留原 CSR／转置 LU 运算顺序。Windows 使用锁定可移植 CBLAS 源码，由必需原生 CI 执行。动量串行循环不表示 BLAS 单线程；线程策略和测得性能须分别记录。

`native-dependencies` CI 在 macOS/Python 3.13 和 Windows/Python 3.12/3.13 构建并执行这些调用方与必需测试。可执行文件缺失会使必需作业失败。可选本地组件测试可以跳过未构建组件，但不能据此声明原生资格。两平台均有真实必需 CI 通过记录；证据仅覆盖其构建与工况。
这些记录只证明所记录构建与工况的结果。

<a id="remaining-stages-and-acceptance-gates"></a>

<a id="migration-stages-and-remaining-acceptance-gates"></a>

## 迁移阶段与剩余验收门

下表记录原迁移阶段及其验收要求。0.2 已退役 Python 数值执行，所有公开求解路线使用 C++。
历史对照保留原结果；当前执行与恢复能力见[架构说明](architecture.zh-CN.md)。
平台 CI、可见桌面、性能和实验精度仍分别验收。

| 阶段 | 实现边界 | 继续推进所需证据 |
| --- | --- | --- |
| 0：热算子 | 独立原生 sweep 和能量审计算子；Python/C++ 混合选择项已退役。 | 算子检查，以及公共场／通量／指标、交接、取消和错误比较。 |
| 1：完整热驱动 | 按相同顺序迁移 Picard 状态、物性刷新、EOS 反演、残差、热启动与合作取消。流体物性和 Nu/hv 闭合评估分开。 | 固定入口／压力／网格输入；A/B/固体方程和边界能量门不变；裁剪／无效／取消保留原含义；比较独立原生场与通量。 |
| 2：流动与耦合 | 迁移 SIMPLE/Brinkman–Forchheimer、压力与质量修正，再迁移所声明矩形子集的原外耦合顺序。 | 动量及新密度局部／全局质量 F2 门；物理入口压力、出口／回流和能量检查；方向与网格测试；相同准备态几何／闭合，不重调系数。 |
| 3：实际 C++ 后端 | 使用最小求解侧适配器消费 CaseData，生成完整 FieldResult，只声明已接受能力。 | 不依赖 Python 求解核；分进程工况／结果交接；状态、单位、场位置和模型来源；缺失或不支持能力明确拒绝。 |
| 4：应用与发布 | 通过既有公共求解 API 选择已合格后端，保留 GUI／设计／优化与离线后处理。 | 仅在支持范围内使用固定二维／三维工况；按预定容差比较跨后端 Q、压力、温度和通量；各支持平台的构建及交付证据。 |

阶段 1 前必须明确原生物性库交付、许可和构建策略。当前 Python CoolProp 安装不能证明已有完整可移植 C++ 开发／运行包。不得静默以拟合代替 HEOS，也不得用 sCO2 标定吸收迁移误差。跨语言共享闭合必须保留生产版本、来源和有效范围，不另行重拟合系数。

2026-09-21 检查的本地 CoolProp 7.2.0 wheel 包含 C++ 头文件和 MIT 许可，但二进制为 CPython Mach-O bundle，不是可独立链接的 `libCoolProp`。独立 C++ 链接以不支持的 Mach-O 类型失败；该环境未发现独立 archive/dylib。检查时未下载源码或安装依赖。之后获准的隔离构建见上文。当前完整驱动须在各目标平台验证 HEOS PT 状态、实际能量与恢复，包括真实 Windows 执行。历史 BICUBIC 记录保留原含义。

每个阶段比较前，先冻结代表工况和比较容差，并保留失败工况及原分母。解析、网格、守恒资格与实验验证分别执行。原 83 工况记录保持历史身份，原生迁移不继承其实验结论。性能测量须区分编译、EOS、流动、热 sweep 和总时间，以相同预热状态和收敛门比较。

OpenFOAM、完整外部求解器 ABI、通用非结构网格、额外物理模型和抽象工厂框架都不是此次迁移的前提。只有具体且独立通过资格检查的能力需要时，才加入对应功能。
