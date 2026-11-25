# C++ 数值后端与原生集成

[中文](cpp-migration.zh-CN.md) | [English](cpp-migration.md)

## 架构与后端边界

TM1 采用三阶段计算主线：

```text
application -> preprocess.api -> CaseData -> solvers.api -> FieldResult
                                                           -> postprocess.api -> PerformanceResult
```

0.2 版本仅使用 C++ 作为数值求解后端。
Python 保留公共应用接口、配置、数据对象、文件读写、缓存、优化、GUI 和 CLI。
完整二维、完整三维和 Quick Design 支持 macOS arm64 与 Windows x64。
Linux x86_64 仅支持独立结果评估。
公共 `RunControl` 与 CLI 默认使用 `backend="cpp"`。
原生库路径属于宿主控制项，不写入 `CaseData`。
缺少原生库、ABI 不匹配或缺少必需符号时显式报错，不回退到其他数值路线。
0.1 至 0.2 求解器迁移阶段、已退役 `v1`–`v11` ABI 及历史资格检查记录见[C++ 迁移与 ABI 演进历史](history/cpp-migration-history.zh-CN.md)。

<a id="cpp-core-scope"></a>

## C++ 核心范围

四个独立的 C++ 共享库拥有全部生产数值计算：

| 共享库 | 源码目录 | 现行 ABI 与职责 |
| --- | --- | --- |
| 几何库 | [geometry](../geometry/) | Geometry ABI 2 与 Field ABI 3：单元几何、chi/Kss、网格、端口、样条、sigmoid、LUT 与分区。 |
| 准备库 | [preprocess](../preprocess/) | Preparation ABI 3 与 Quick Design 准备 v2：物性、Nu 闭合、固定 D-F、二维／三维及 Quick 准备。 |
| 求解库 | [solver](../solver/) | 二维保存态 ABI 5、三维保存态 ABI 3、捕获 ABI 2 及 Quick Design 运行 v2。 |
| 结果库 | [postprocess](../postprocess/) | Result ABI 3（`float64` + `int32` 标签）：工程指标、物理平衡、适用性、分区统计与资格判断。 |

所有现行 C++ 阶段接口均将数值缓冲区规范化为 `float64`，分区标签规范化为 `int32`。
按职责查找 C++ 修改入口见[源码地图](../python/README.md)。
Python 保留边界（包括 `python/shared.py`）见[架构说明中的保留职责](architecture.zh-CN.md#retained-python-responsibilities)。
纯公式测试参考实现保留在 `tests/python/` 中，作为独立回归校验基准。
PR CI、合并主分支 CI、桌面交付、单元上限附近内存检查、真实三维 BO、性能验收和实验验证保持为独立门槛。

<a id="native-geometry-core"></a>

## 原生几何核心

[geometry](../geometry/) 中的独立几何核心负责标准、CO2 与非对称单元几何，以及 chi 和固体导热率计算。
同一核心还负责网格、端口、六方向轴映射、连续 XY/XYZ 样条、sigmoid 场、线性 LUT、离散分区与高斯滤波。
单个共享库文件（`tpmshx_geometry_shared`）提供以上全部计算。
它仅依赖 C++ 标准库、marching-cubes 移植代码与受限的 C17 FITPACK 子集。
它不链接 CoolProp、SuperLU、AMGCL、Eigen 或求解器运行库。
网格与设计场归属见[架构说明](architecture.zh-CN.md#native-grids-and-design-fields)，固定源码与 BSD 声明见 [fields-sources.md](../geometry/fields-sources.md)。

`python/cpp_interface/_native_geometry.py` 通过 ctypes 按需加载 `tpmshx_geometry_shared`。
几何、网格与分区接口使用 geometry ABI 2，状态 2 表示定义域错误。
连续场、sigmoid 与 LUT 接口使用 field ABI 3，状态 2 表示内存分配失败。
调用缓冲区均按显式元素计数借用，调用失败时保持调用方输出不变。
XY 样条句柄与 LUT 对象在释放前保留对其创建库的引用。

macOS arm64 使用 `libtpmshx_geometry_shared.dylib`，Windows x64 使用 `tpmshx_geometry_shared.dll`。
源码检出默认读取 `sjtu_tpmshx/solvers/native/lib/<host>/`，冻结桌面包读取 `native/`。
可通过 `TPMSHX_GEOMETRY_LIBRARY` 指定绝对预构建路径以切换几何库。
历史结果读取与离线后处理不加载该库。
修改 C++ 函数或编入库的模型数据后，必须重新构建受影响的库并重启进程。

在 macOS 上获取锁定 CMake 并单独发布几何库：

```sh
tm1_python="$(sed -n '1p' .venv-path)"
tm1_lock=engineering/requirements/base.txt
"$tm1_python" engineering/scripts/build_native_dependencies.py fetch-cmake
"$tm1_python" engineering/scripts/build_native_dependencies.py publish --component geometry --python-lock "$tm1_lock"
```

在 Windows PowerShell 中：

```powershell
$tm1Python = Get-Content .venv-path -TotalCount 1
$tm1Lock = 'engineering/requirements/base.txt'
& $tm1Python engineering/scripts/build_native_dependencies.py fetch-cmake
& $tm1Python engineering/scripts/build_native_dependencies.py publish --component geometry --python-lock $tm1Lock
```

若 `.venv-path` 指向 BO 环境，请改用 `bo-macos.txt` 或 `bo-windows.txt`。
如需分步执行，可使用同一 `--cache` 运行 `build --component geometry` 和 `verify --component geometry`。
独立几何构建默认输出至 `.cache/native-deps/build/geometry-<host>`。
单独发布几何库仅更新 `geometry-build.json`，并将先前不同版本的库保留在 `previous/` 下。
默认完整发布在构建并验证全部四个库后，以单次事务同步发布。
每个库写入各自的构建记录（`build.json`、`geometry-build.json`、`preparation-build.json`、`result-build.json`），记录 `source_commit` 与 `source_changes`。
替换失败时自动回滚暂存文件并报告恢复路径。
旧求解检查点仍要求精确匹配的保留求解库、准备输入与控制项。

完整与应用级 CI 均构建全部四个库，并作为制品供后续原生和 BO 任务使用。
Python wheel 仅包含 Python 模块与模型资源，不含原生库。
桌面打包需要全部四个预构建库，见[桌面部署](desktop.md#可选冻结打包)。

<a id="native-preparation-core"></a>

## 原生准备核心

[preprocess](../preprocess/) 中的独立准备核心计算流体物性、Nu 闭合、固定 D-F 表、实验修正、行投影及完整二维／三维／Quick 准备。
其 CMake 目标（`tpmshx_preparation`、`tpmshx_preparation_c`、`tpmshx_preparation_shared`）复用几何核心、共享物性实现与锁定的 CoolProp 静态库。
该工程不依赖求解器运行库、`run_state`、SuperLU 或 AMG。

`python/cpp_interface/stage_libraries.py` 按需独立加载 preparation ABI 3。
Preparation ABI 3 采用扁平的 `(abi_version, struct_size)` 输入结构、统一的 `tpmshx_preparation_callbacks_v1` 以及简洁的 `v1` 族入口名称。
其状态码定义为：0 成功、1 输入无效、2 分配失败、3 运行时错误，10/11/12 分别表示水／CO2／sCO2 状态错误。
所有现行二维、三维、入口查询和 Quick Design 准备入口见[原生阶段接口](native-stages.zh-CN.md)：

- [入口物性查询](native-stages.zh-CN.md#入口物性查询)：`tpmshx_query_inlet_properties_v2` 返回 12 个 `float64` 标量，无需网格或求解器。
- [空间几何总质量流量](native-stages.zh-CN.md#空间几何总质量流量)：均匀、连续 XY、离散分区与 sigmoid 输入的容量查询、流量解析和完整二维准备。
- [空间几何宿主缓存接口](native-stages.zh-CN.md#空间几何宿主缓存接口)：`preparation_host.py` 与 `tpmshx_preparation_callbacks_v1` 传输缓存值，不在宿主回调中执行数值计算。
- [既有偏移几何](native-stages.zh-CN.md#既有偏移几何)：非零 `delta_levelset` 的名义热侧几何与分流规则。
- [均匀三维准备](native-stages.zh-CN.md#均匀三维准备)：基于 `preparation_case_3d_c_api.h` 的均匀、连续 XY/XYZ 与 XY 网格矩形三维准备。
- [Quick Design 阶段](native-stages.zh-CN.md#quick-design-阶段)：`tpmshx_prepare_quick_design_v2`、`tpmshx_quick_pressure_fractions_v2` 及 `tpmshx_quick_callbacks_v2`。

共享 JSON 与 CSV 权威来源见[模型资源](model-resources.md#当前资源与研究输出)。
二维与三维准备共用 `tpmshx_preparation_df_experiment_scope_v1` 执行布局与 HX 实验域检查。
私有 `scalar_range_samples.hpp` 每侧最多保留 8 个空气场标量观测值（原始通知、极值与末次采样），完整数组记录仍覆盖全部单元。

单独发布准备库需要同一缓存中的锁定源码、锁定 CMake 与已构建的 CoolProp 静态库。
若缺少 CoolProp，先运行 `fetch` 与 `build --component coolprop`。
随后在 macOS 上运行：

```sh
tm1_python="$(sed -n '1p' .venv-path)"
tm1_lock=engineering/requirements/base.txt
"$tm1_python" engineering/scripts/build_native_dependencies.py publish --component preparation --python-lock "$tm1_lock"
```

在 Windows PowerShell 中：

```powershell
$tm1Python = Get-Content .venv-path -TotalCount 1
$tm1Lock = 'engineering/requirements/base.txt'
& $tm1Python engineering/scripts/build_native_dependencies.py publish --component preparation --python-lock $tm1Lock
```

在 macOS 上，准备库链接以 `-Os` 编译的 `coolprop-preparation-macos-arm64/libCoolProp.a`，而求解库链接 `coolprop-macos-arm64/libCoolProp.a`。
Windows 两个角色共用同一个锁定的 `Release/CoolProp.lib`。
每个静态库保留 `coolprop-build.json` 记录，并在发布时写入对应库的构建元数据。
运行库文件在 macOS arm64 上为 `libtpmshx_preparation_shared.dylib`，在 Windows x64 上为 `tpmshx_preparation_shared.dll`。
可通过 `TPMSHX_PREPARATION_LIBRARY` 指定替代路径，桌面打包使用 `TPMSHX_NATIVE_PREPARATION_LIBRARY`。
使用 `engineering/scripts/check_distributions.py --output-dir .cache/<dir>` 构建并校验源码分发包和 wheel。

<a id="native-result-core"></a>

## 原生结果核心

[postprocess](../postprocess/) 中的独立结果核心实现 Result ABI 3。
它以 `float64` 数值与 `int32` 分区标签计算工程指标、有符号物理平衡、分区统计、适用性检查和资格结论。
独立的 `postprocess/` 工程仅依赖 C++17 与系统库。
它不链接求解库、准备库、几何库、CoolProp、Qt 或模型资源文件。
缓冲区布局、错误码与通知规则见 [postprocess/sources.md](../postprocess/sources.md)。

`python/cpp_interface/result_evaluation.py` 中的查询通过 `_native_result.py` 按需加载结果库。
纯 Python 导入和 HDF5/JSON 读取不依赖原生库。
`tpmshx_result_stage_query_v3` 接收扁平的 `tpmshx_stage_input_v3`，包含借用的 `float64` 数组、`int32` 标签以及原始 C 字符串模式／单位标签。
浮点事件会针对除零、溢出和无效值发出固定的 `RuntimeWarning` 诊断。

运行库镜像在 macOS 为 `libtpmshx_result_shared.dylib`，Windows 为 `tpmshx_result_shared.dll`，Linux x86_64 为 `libtpmshx_result_shared.so`。
可通过 `TPMSHX_RESULT_LIBRARY` 指定绝对替代路径。
Linux x86_64 仅允许带 `--component result` 的 `fetch-cmake`、`build`、`verify` 与 `publish`。
在 `.venv-path` 指向最小后处理环境时运行：

```sh
tm1_python="$(sed -n '1p' .venv-path)"
"$tm1_python" engineering/scripts/build_native_dependencies.py fetch-cmake --component result
"$tm1_python" engineering/scripts/build_native_dependencies.py publish --component result --python-lock engineering/requirements/postprocess.txt
```

CI 除完整 macOS/Windows 构建外，还在 Ubuntu 24.04 与 26.04 上构建并验证结果库。
`minimal-postprocess` 任务在 Ubuntu 24.04 上使用 `result-build-linux-x86_64-ubuntu-24.04` 及来自 macOS 的真实二维／三维保存文件执行测试。

## 求解核心与执行接口

[solver](../solver/) 中的求解库实现完整二维、完整三维、Quick Design、SIMPLE 流动、model-h、温度及 T-SOU 保守能量驱动。
保存态阶段运行生命周期是 Python 及 C／C++ 调用方唯一的求解执行接口。
原生绑定位于 `python/cpp_interface/` 下的 `full_2d_stage.py`、`full_3d_stage.py` 和 `quick_design.py`。
求解宿主 `python/solvers/full_2d.py`、`python/solvers/full_3d.py` 与 `python/solvers/quick_design.py` 校验保存工况并组装公共 `FieldResult`。

- **完整二维（`full_2d.hpp`、`stage_run_c_api.h`）**：保存态 ABI 5（`tpmshx_run_saved_case_2d_v5`、`create_saved_v5`、`restore_saved_v5`）。拥有定密度 Anderson 的 SIMPLE、入口压力打靶、物性／热学耦合、Richardson 细化及最终证书，主换热量单位为 W/m。
- **完整三维（`full_3d.hpp`、`stage_run_3d_c_api.h`）**：保存态 ABI 3（`tpmshx_run_saved_case_3d_v3`、`create_saved_v3`、`restore_saved_v3`）与捕获 ABI 2。拥有 XYZ SIMPLE、可选粗网格引导（`tpmshx_full_3d_get_bootstrap_trace_v1`）、热学优先外耦合及最终证书，主换热量单位为 W。
- **Quick Design（`quick_design_driver.hpp`、`quick_design_stage_c_api.h`）**：`tpmshx_run_quick_design_v2` 在保存的准备场上执行定物性或平均物性扫描，保留固定解析压降分数与 `physical_validation=not_established`。
- **原始结果查询（`full_2d_c_api.h`、`full_3d_c_api.h`）**：`tpmshx_full_{2,3}d_get_*_v1` 读取阶段结果所借用的 `raw` 结果；只释放阶段结果。已退役的直接求解与单驱动 C 入口记录于 [C++ 迁移与 ABI 演进历史](history/cpp-migration-history.zh-CN.md)。
- **执行报告（`execution_report.cpp`）**：`tpmshx_stage_run_2d_report_v1` 与 `tpmshx_stage_run_3d_report_v1` 发布解析网格、流体、状态、物性采样与 model-h 平衡。

所有权、检查点恢复与默认控制见[运行续算](native-stages.zh-CN.md#运行续算)和[原生三维执行](native-stages.zh-CN.md#原生三维执行)。

公共 Python 执行通过 `RunControl` 传递库路径：

```python
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.solvers.api import run_case

result = run_case(prepared_case, RunControl(
    backend="cpp", native_library="/absolute/path/to/libtpmshx_solver_shared.dylib"))
```

源码 CLI 执行方式：

```bash
"$PYTHON" -m sjtu_tpmshx.cli solve case.h5 results.h5 --backend cpp \
  --native-library /absolute/path/to/libtpmshx_solver_shared.dylib
```

### T-SOU 保守能量与真实态审计

`enthalpy_driver.hpp` 中的 `solve_enthalpy` 在双流体 true-h 路线上执行 `EnthalpyAlgorithm::temperature_sou`（T-SOU）。
每步非线性迭代冻结真实 `h`、`T` 和 `cp` 数组，以 minmod 焓面重构执行交替的 A、B 与固体扫描，并对整块增量施加 `0.6` 阻尼。
随后通过受保护的 HEOS PT 更新刷新真实焓值再检查残差与边界热负荷，不使用 BICUBIC 表、H-to-T 反演或焓截断。
SOU 配方 2 采用六样本 Anderson 提议，仅当提议严格降低归一化耦合与方程残差最大值时才接受。
只有完整的常规 PT／审计块能够判定收敛。
`tpmshx_energy_algorithm_version_v1` 独立于 C ABI 报告实际执行的配方版本。

`solver/enthalpy_sweeps.cpp` 中的 `thermal_energy_audit` 计算真实态 A/B/固体单元残差及六个外法向有符号边界焓热负荷。
耦合与方程比例采用 `max(abs(Q_A), abs(Q_B), 1)` 作为分母，单位为 W/m（二维）或 W（三维）。
该算子本身不施加验收阈值；由驱动强制执行 `0.001` 的耦合／方程门槛与 Kelvin 更新门槛。
可移植候选结果标记 `thermal_mode=conservative_energy` 并记录 `boundary_fluxes.true_h.boundary_power`；单侧换热量为 `-sum(boundary_power)`，不做回退重构。

<a id="shared-finite-volume-temperature-consumers"></a>

## 共享有限体积温度使用方

私有 `energy_fv_rows.hpp` 提供共享的有限体积输运、傅里叶导热、LTNE 换热与物理源项行组装。
各调用方各自拥有流体模型、面准备、EOS 更新、迭代预算与收敛策略。
CMake 对实例化该共享行的每个源文件施加文件级禁止浮点收缩选项。

| 使用方 | 驱动与保留契约 |
| --- | --- |
| Quick Design 定／均物性与独立 CC | `temperature_driver.cpp` 中的 `solve_temperature`：单次扫描固定系数、热容输运、受保护线迭代（最多 4 次点扫描 + `0.6` 块阻尼线牛顿试步）及 `<= 1e-7` 完整边界比例。 |
| 空气／水完整二维温度与三维 CC（`Nz = 1`） | 严格 `solve_model_h_2d`：积分 `h(T)`、A-SOU/B-FOU（`model_h_tface_sou_fou_strict_v3`）、准备态质量／K／`h_v`、三维 `Nz = 1` 物理厚度缩放及 `<= 1e-7` 完整边界账本。 |
| 空气／水完整三维 CC（`Nz > 1`） | 严格 `solve_model_h_3d`：积分 `h(T)`、双侧 SOU（`model_h_tface_sou_sou_strict_v3`）、给定 B 侧热源支持、非对称几何、严格水／水及 `<= 1e-7` 完整边界账本。 |
| 生产 model-h | 非严格 `solve_model_h_2d` / `solve_model_h_3d`，保持既有资格与停止规则。 |
| 完整三维 true-h 准备 | `true_h_preparation` 校验 CC 输入并投影交错面，在 EOS 求解前执行零次温度扫描。 |
| 交错／MAC 研究 | 保留既有投影、缓存与热容面准备，不继承 fullCC 积分焓资格。 |
| True-h | `enthalpy_driver.cpp` 默认 T-SOU，保持独立 EOS 关系与物理门槛。 |

FullCC 在后续流场更新前通过 `tpmshx_full_{2d,3d}_get_model_enthalpy_evidence_v1` 捕获 `model_enthalpy_temperature_v1`。
每个求解流体记录二次 `cp(T)` 的 `[c0, c1, c2, Tbase, Tref]`、求解相标志、残差、源／热库功率以及外法向 `m*h(T_face)` 和傅里叶平面。
非零 fullCC 制造体积源仍不受支持；给定 B 侧保留热库功率，不伪造已解 B 残差证书。
历史 N3、N5 与 N3 之前资格记录见[C++ 迁移与 ABI 演进历史](history/cpp-migration-history.zh-CN.md)。

## 构建与运行原生资格检查

锁定的原生依赖清单位于 [dependencies-lock.toml](../engineering/native_build/dependencies-lock.toml)：CoolProp 8.0.0 及其九个固定提交的 CPM 头文件依赖、包含三项 SciPy 1.18.1 双精度 LU 修复的 SuperLU 7.0.1、AMGCL 1.5.0、Eigen 5.0.1 与 CMake 4.4.4。
第三方许可声明见 [THIRD_PARTY_NOTICES.md](../engineering/native_build/licenses/THIRD_PARTY_NOTICES.md)。
`engineering/scripts/generate_native_model_coefficients.py` 仅使用 Python 标准库在 `.cache/native-deps/generated/` 下生成 `tpmshx/model_coefficients.hpp` 与 `tpmshx/preparation_df_data.hpp`。

### 独立无 EOS 热学静态库检查

在具备 POSIX C++17 编译器、`make` 及 `.cache/native-deps/src/Eigen-5.0.1` 锁定 Eigen 头文件（`fetch-eigen`）时运行：

```sh
make -f engineering/native_build/Makefile CXX=c++
make -f engineering/native_build/Makefile check
```

在 Windows x64 Visual Studio 开发者命令行中：

```bat
nmake /f engineering\native_build\Makefile.msvc check
```

上述命令以 `EIGEN_MPL2_ONLY` 构建 `.cache/native/libtpmshx_thermal.a`（或 `tpmshx_thermal.lib`），并在不依赖 Python、CoolProp 或 Qt 的情况下运行独立 C++ 温度与保守能量测试。

### 完整依赖构建与原生 pytest 套件

直接配置原生组件时，`TPMSHX_BUILD_QUALIFICATION` 默认为 `ON`。
它启用该组件的测试程序。求解器还会构建 Python 测试库，并生成记录 model-h 迭代历史的测试目标。
原生依赖构建启用资格测试。顶层 SDK 为每个组件关闭资格测试，复用已经配置过的构建目录时也会关闭。
`check-stages` 在所选缓存的 `build/stages-<host>/` 下使用独立的 SDK 组件构建目录。

通过环境检查后，使用 `.venv-path` 指定的解释器运行：

```sh
tm1_python="$(head -n 1 .venv-path)"
"$tm1_python" -m sjtu_tpmshx.development.runs.tools.check_locked_environment
"$tm1_python" -m pip check
"$tm1_python" engineering/scripts/build_native_dependencies.py fetch
"$tm1_python" engineering/scripts/build_native_dependencies.py build
"$tm1_python" engineering/scripts/build_native_dependencies.py verify
MPLCONFIGDIR="$PWD/.cache/matplotlib" \
XDG_CACHE_HOME="$PWD/.cache/xdg" \
TPMSHX_REQUIRE_NATIVE_DEPS_TESTS=1 \
"$tm1_python" -m pytest -q tests/python/native
```

`fetch` 下载锁定归档；`build` 与 `verify` 离线运行且不安装 Python 包。
SuperLU 调用位于纯 C 错误边界与线程局部分配账本之后，内存分配失败或 `ABORT` 在清理后返回有界错误。
macOS SuperLU 链接系统 Accelerate BLAS，Windows 链接锁定的可移植 CBLAS 源码。
单元数不超过 2,000 的压力方程使用 SuperLU/COLAMD；更大三维规模使用经典代数多重网格配合 BiCGStab（200 步预算，数值崩溃时按 L2 缩放重试）。
所有 `TPMSHX_TRUE_H_KERNEL` 覆盖（`numba`、`cpp_sweeps_v1`）均已退役，在流动求解前显式报错。
设置 `TPMSHX_REQUIRE_NATIVE_DEPS_TESTS=1` 后，缺少原生库或调用程序会导致测试失败。
本地 macOS 通过不代表 Windows 编译、运行或桌面验收通过。
