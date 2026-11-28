<a id="sjtu-tpmshx-tm1-architecture"></a>

# SJTU-TPMSHX-TM1 架构

[中文](architecture.zh-CN.md) | [English](architecture.md)

## 系统总览与三个公开阶段

0.2 版本仅使用 C++ 作为数值求解后端。
完整二维、完整三维和 Quick Design 支持 macOS arm64 与 Windows x64。
Linux x86_64 仅支持独立结果评估。
生产计算域形状限定为矩形二维与长方体三维。
完整运行经由三个公开阶段衔接：

```text
applications -> preprocess.api -> CaseData -> solvers.api -> FieldResult
                                                          -> postprocess.api -> PerformanceResult
                         data_types / physical_models / model_configs / file_io / run_control
```

Quick Design、保存态工况运行、离线评估和运行恢复分别从对应阶段进入。
缺少原生库、ABI 不匹配或缺少现行符号时显式报错，不提供数值回退。

## 四个原生共享库

四个独立的 C++ 共享库承担全部生产数值计算：

| 共享库 | 源码目录 | 现行 ABI 与职责 |
| --- | --- | --- |
| `tpmshx_geometry_shared` | [native/geometry/](../native/geometry/) | geometry ABI 2 与 field ABI 3：TPMS 单元几何、chi/Kss、网格、端口、样条、sigmoid 场、LUT 与分区。 |
| `tpmshx_preparation_shared` | [native/preprocess/](../native/preprocess/) | preparation ABI 5 与 Quick Design 准备 v3。负责物性、Nu、固定 D-F、二维／三维准备、入口查询及共享的入口、sigmoid 表、标量几何与 EOS 缓存。 |
| `tpmshx_solver_shared` | [native/solver/](../native/solver/) | 二维保存态 ABI 5、三维保存态 ABI 3（捕获 ABI 2）与 Quick Design 运行 v2：SIMPLE 流动、model-h、温度与 T-SOU 保守能量。 |
| `tpmshx_result_shared` | [native/postprocess/](../native/postprocess/) | result ABI 3（`float64` 数组与 `int32` 分区标签）：工程指标、物理平衡、适用性检查、分区统计与资格判断。 |

共享系数、范围与默认值统一来自 [model_parameters_v1.json](../python/model_configs/model_parameters_v1.json) 与 [preparation_df_v1.json](../python/model_configs/preparation_df_v1.json)。
`engineering/scripts/generate_native_model_coefficients.py` 仅用 Python 标准库由上述文件生成 C++ 头文件。
另见 [native/include/tpmshx/](../native/include/tpmshx/)、[tests/cpp/](../tests/cpp/)、[C++ 接入说明](cpp-migration.zh-CN.md#cpp-core-scope)、[原生阶段 SDK](native-stages.zh-CN.md)与[C++ 迁移与 ABI 演进历史](history/cpp-migration-history.zh-CN.md)。

## 源码、导入名与原生库路径映射

| 名称或路径 | 职责与使用方 |
| --- | --- |
| 源码目录 [python/](../python/) | 存放 Python 源码树；[pyproject.toml](../pyproject.toml) 中的 `[tool.setuptools.package-dir]` 将 `tm1` 映射到 `python`。 |
| 导入名 `tm1` | 仓库内全部导入与 CLI 模块命令使用的公开包名。 |
| 应用启动入口 [main.py](../main.py) | 唯一的应用启动入口，也是冻结包入口；在任何路由导入 Qt、VTK、Matplotlib 或 Torch 之前分派 `gui`（默认）、CLI 阶段、`summary`、`design` 与 `optimize`。命令行模式以 UTF-8 写入标准输出和标准错误。 |
| 检出加载器 [tm1.py](../tm1.py) | 从仓库根目录执行命令时，将 `python/__init__.py` 作为 `tm1` 加载；源码检出中的 `main.py`、`tm1` 工具的模块命令和 pytest 使用它。 |
| 安装态 wheel 布局 `tm1/` | 打包 Python 模块及 `pyproject.toml` 声明的 JSON、CSV 与图标资源，不含原生库。[check_types.py](../engineering/scripts/check_types.py) 通过 [python_source.py](../engineering/packaging/python_source.py) 构建相同目录树供 `mypy` 检查。 |
| 现行原生库目录 `native/lib/<host>/` | 被 Git 忽略的目录，由 [build_native_dependencies.py](../engineering/scripts/build_native_dependencies.py) 为源码运行发布四个原生库。`provenance.py` 定义 `PUBLISHED_LIBRARY_DIR`，`module_ports.py`、`stage_libraries.py` 与 `_native_geometry.py` 读取该目录；冻结桌面包从 `native/` 加载。使用 `.venv-path` 解释器运行 `build_native_dependencies.py verify-published` 执行[已发布原生库检查](verification.md#published-native-images)；该命令将已发布导出符号与几何、准备、求解和结果库的 `.exports` 清单比对，并输出各库构建记录（`build.json` 与 `*-build.json`）。 |

<a id="directory-owners"></a>

## 目录所有者

下表列出各目录的内容。各分层之间不重复关联式或物理常数。
Python 目录的职责见 [Python 分层所有者](#python-分层所有者)表。

| 路径 | 内容 |
| --- | --- |
| [native/preprocess/](../native/preprocess/)、[native/solver/](../native/solver/)、[native/postprocess/](../native/postprocess/) | C++ 前处理、求解与评估。 |
| [native/geometry/](../native/geometry/) | C++ 几何。 |
| [native/numerics/](../native/numerics/) | 通用数值函数。 |
| [native/include/tpmshx/](../native/include/tpmshx/) | C 与 C++ 头文件。 |
| [tests/cpp/](../tests/cpp/) | 原生调用方测试。 |
| [python/applications/](../python/applications/) | 应用工作流。GUI 组件位于 `gui/ui/`，控制器位于 `gui/controllers/`。 |
| [python/preprocess/](../python/preprocess/) | Python 前处理阶段，生成新的 `CaseData`。 |
| [python/solvers/](../python/solvers/) | Python 求解阶段，生成新的 `FieldResult`。 |
| [python/postprocess/](../python/postprocess/) | Python 评估阶段，生成新的 `PerformanceResult` 与 `MetricValue`。 |
| [python/data_types/](../python/data_types/) | 可移植类型，包括各阶段数据类型。 |
| [python/physical_models/](../python/physical_models/)、[python/model_configs/](../python/model_configs/) | 独立模型查询、sigmoid NPZ 文件与模型资源。 |
| [python/file_io/](../python/file_io/)、[python/run_control/](../python/run_control/) | 文件 I/O 与运行控制。 |
| [python/cpp_interface/](../python/cpp_interface/) | 原生调用。 |
| [tests/python/](../tests/python/) | Python 测试。 |
| [python/development/](../python/development/) | 验证与工具。 |
| [engineering/](../engineering/) | 构建脚本、打包与依赖锁。 |

<a id="binding-import-limits"></a>

## 绑定层导入限制

`python/cpp_interface/` 中的绑定遵守以下导入限制。
`python -m tm1.development.runs.tools.audit_import_graph --fail-on-violations` 检查这些限制。
该审计也拒绝 `ui` 归属和 `solvers` 归属内各模块之间的导入环。

- 绑定可以导入 `run_control`、`model_configs` 和 `data_types` 模块，但不导入各阶段数据类型所在的模块。
- 阶段数据类型为 `CaseData`、`ModelRef`、`FieldResult`、`MetricSpec`、`MetricValue` 和 `PerformanceResult`。
  绑定不构建这些类型，仅在 `TYPE_CHECKING` 下导入它们。
- 例外是 `python/cpp_interface/preparation_host.py`，它导入 `ModelRef` 以检查已保存的模型引用。
- 绑定不导入阶段、应用、物理模型、文件 I/O、`compute` 或开发模块。

<a id="retained-python-responsibilities"></a>

## Python 分层所有者

Python 在 [python/](../python/) 下负责公共 API、配置、不可变 DTO、文件 I/O、警告格式化与应用工作流。
Python 校验与写入 sigmoid NPZ 文件。准备库与独立查询共用入口、sigmoid 表、标量几何及 CO₂／sCO₂ 物性缓存。
数值代码保持不依赖 Qt。在 GUI 之外，只有离屏 GUI 冒烟工具 `python/development/runs/_smoke_boot.py` 和 `python/development/runs/smokes/` 导入 Qt。
GUI 代码位于 `python/applications/gui/ui/`（`Main_Menu` 位于 `main_window.py`）和 `python/applications/gui/controllers/`。根目录 [main.py](../main.py) 是唯一的应用启动入口：先调用 `freeze_support()`，再在任何路由导入 Qt、VTK、Matplotlib 或 Torch 之前分派 `gui`（默认）、CLI 阶段、`summary`、`design` 与 `optimize`。GUI 路由调用 `python/applications/gui/main.py`。
主窗口组装 `SingleRun`、`OptimizationPage` 和 `QuickDesignPage`。每个任务所有者负责启动、取消和线程退出。`Workbench` 选择视图，`FieldResults` 发布结果，`ResultExport` 导出数据与图表，`CaseFiles` 读写算例、预设和工作区会话。优化输入和工况解码位于无 Qt 依赖的 `applications/optimization/optimization_job.py`。
`preprocess/preflight.py` 根据已捕获的 `ComputeConfig` 返回网格与几何预检结果。`applications/design/sensitivity.py` 计算仅适用于空气的筛选估算中的一行。GUI 显示预检报告，每行结束后处理事件，并负责热图显示和单元格选择。

| 分层 | 所有者路径 | 职责 |
| --- | --- | --- |
| 公共入口与应用 | [compute.py](../python/compute.py)、[applications/](../python/applications/) | 运行三个计算阶段；拥有 GUI、CLI、Quick Design 尺寸搜索、灵敏度筛选、多工况 BO、`result_adapter` 与运行恢复。 |
| 阶段 API | [preprocess/](../python/preprocess/)、[solvers/](../python/solvers/)、[postprocess/](../python/postprocess/) | 定义 `prepare_case`、`run_case` 与 `evaluate`，以及预检、离线拟合、`physical_ledger`、`result_math`、`result_display` 与导出。 |
| 原生绑定 | [cpp_interface/](../python/cpp_interface/) | 按需加载四个原生库，将实数规范化为 `float64`、标签规范化为 `int32`，并发出固定 `RuntimeWarning` 诊断。 |
| 模型与资源 | [physical_models/](../python/physical_models/)、[model_configs/](../python/model_configs/) | 拥有模型查询、`zone_units.py` 与带版本 JSON／CSV 模型资源。 |
| 数据、I/O 与控制 | [data_types/](../python/data_types/)、[file_io/](../python/file_io/)、[run_control/](../python/run_control/) | 拥有 `ComputeConfig`、`CaseData`、`FieldResult`、`PerformanceResult`、`metric_spec`、文件 I/O、取消与来源记录。 |
| 验证与参考实现 | [development/](../python/development/)、[tests/python/](../tests/python/) | 拥有验证与运行工具；纯公式测试参考实现留在运行 wheel 之外。 |

缓存容量与边界细则见[Python 保留职责](numerical-contracts.zh-CN.md#retained-python-responsibilities)，模块入口见[Python 源码地图](../python/README.md)。

## 跨目录 C++ 依赖边

交付的四个共享库之间不存在共享库链接环。
每个 CMake 作用域独立构建库文件。
仅 `native/preprocess/` 与 `native/solver/` 链接各自隔离的 CoolProp 静态归档；`native/geometry/` 与 `native/postprocess/` 不链接 CoolProp。
以下六类编译期源码与头文件边跨目录存在：

| 依赖边 | 源码或头文件位置 | 原因 |
| --- | --- | --- |
| `native/preprocess/` <-> `native/numerics/` | `native/preprocess/preparation_properties.hpp` 包含 `../numerics/property_kernels.hpp`。`native/numerics/df_summary.cpp` 包含 `tpmshx/preparation_df.hpp`。 | `native/preprocess/preparation_property_points.cpp` 定义六个前处理适配函数。`native/numerics/fluid_properties.cpp` 定义共用的物性内核。前处理和求解器的构建都使用同一个 D-F 汇总函数。 |
| `native/solver/` -> `native/postprocess/` | `native/solver/CMakeLists.txt` 将 `native/postprocess/result_{core,arithmetic,metrics,balance}.cpp` 编译进隐藏静态目标 `tpmshx_capture_math`；`native/solver/stage_capture_2d.cpp` 包含 `../postprocess/result_zone_capture.hpp`。 | 在求解捕获阶段复用精确结果算术，同时保持 `tpmshx_result_shared` 独立部署而不依赖求解库。 |
| `native/solver/` -> `native/preprocess/` | `native/solver/CMakeLists.txt` 编译 `native/preprocess/preparation_{df_corrections,flow}.cpp`；`native/solver/stage_saved_models.hpp` 包含 `../preprocess/preparation_nu.hpp`；`native/solver/quick_design_run.cpp` 包含 `../preprocess/preparation_c_boundary.hpp`。 | 复用 D-F 修正、`closure_geometry_ratio`、Nu 路线与 C 边界规则，无需链接 `tpmshx_preparation_shared`，使静态 CoolProp 注册表保持隔离。 |
| `native/preprocess/`、`native/solver/` -> `native/geometry/` | 两个 CMake 工程均以子目录方式引入 `native/geometry/`；`native/preprocess/preparation_case.cpp` 包含 `../geometry/field_{continuous,lut,sigmoid}.hpp`；五个前处理与求解文件包含 `../geometry/field_c_boundary.hpp`。 | 将网格、端口、设计场与 C 边界辅助代码静态编入各自隔离的阶段构建。 |
| `native/geometry/` <-> `native/numerics/` | `native/include/tpmshx/geometry.hpp` 为 `Topology` 包含 `tpmshx/fluid_properties.hpp`；`native/geometry/{grid,zones}.cpp` 包含 `../numerics/contiguous_sum.hpp`；`native/include/tpmshx/pressure_reference.hpp` 包含 `tpmshx/ports.hpp`，`pressure-reference.cmake` 直接链接 `tpmshx_grid`，`models.cmake` 传递链接 `tpmshx_grid`。 | 在几何与压力基准目标之间共享拓扑枚举、确定性求和辅助函数与物理端口分数计算。 |
| 各阶段 -> `native/numerics/` 与共享 Quick 头文件 | `native/preprocess/` 与 `native/solver/` 包含 `../numerics/contiguous_sum.hpp` 并编译 `native/numerics/df_summary.cpp`；`native/preprocess/` 与 `native/postprocess/` 包含 `../numerics/scalar_range_samples.hpp`；`native/solver/` 与 `native/postprocess/` 编译 `native/numerics/recorded_report.cpp`；`native/include/tpmshx/quick_design_stage_c_api.h` 包含前处理、求解与结果 C 头文件。 | 在各阶段间共享确定性求和、范围采样、报告编码及统一的 Quick Design 阶段 C 接口。 |

## 详细契约索引

详细数值、运行、界面与物理契约均位于[数值与运行契约](numerical-contracts.zh-CN.md)：

- <a id="native-grids-and-design-fields"></a>**网格、设计场与几何 ABI**：[原生网格与设计场](numerical-contracts.zh-CN.md#native-grids-and-design-fields)（FITPACK、样条、ABI 2/3 状态码、CO2 因子、规定总质量流量）。
- <a id="native-preparation-solver-and-evaluation-stages"></a><a id="原生准备求解与评估阶段"></a>**前处理、求解路线与执行记录**：[原生准备、求解与评估阶段](numerical-contracts.zh-CN.md#原生准备求解与评估阶段)（SIMPLE F2、Anderson 设置、T-SOU、model-h、fullCC、Quick Design、`full_execution_v1`）。
- <a id="result-qualification-by-route"></a>**结果资格与物理平衡**：[各路线的结果资格](numerical-contracts.zh-CN.md#result-qualification-by-route)与[物理平衡证据](numerical-contracts.zh-CN.md#物理平衡证据)。
- <a id="captured-parameter-limits"></a><a id="捕获的参数范围"></a>**适用范围与公共结论**：[捕获的参数范围](numerical-contracts.zh-CN.md#捕获的参数范围)（`[0.9 * L, 1.1 * U]` 策略）与[公共结果结论](numerical-contracts.zh-CN.md#公共结果结论)。
- <a id="native-3d-continuation"></a>**持久化接口、续算与优化**：[持久化接口与物理状态](numerical-contracts.zh-CN.md#persistent-interfaces-and-physical-state)和[原生二维与三维续算、取消与 BO](numerical-contracts.zh-CN.md#native-3d-continuation)。
- <a id="ui-structure"></a>**桌面界面与结果缓存**：[UI 结构](numerical-contracts.zh-CN.md#ui-structure)（用户存储、预检、工作台模块、`ResultCache`、导出）。
- <a id="physical-invariants"></a>**物理约束与 `sF` 窗口**：[物理不变量](numerical-contracts.zh-CN.md#physical-invariants)（12 条核心不变量、冻结 `sF` 常量与标定速度窗）。
- <a id="local-data"></a>**本地原始数据目录**：[本地数据](numerical-contracts.zh-CN.md#local-data)与[数据目录](data-catalog.md)。

配套文档：[三模块数据契约](contracts/three_module_v1/README.zh-CN.md)、[能力范围](capabilities.md)、[模型资源](model-resources.md)与[验证指南](verification.md)。

<a id="extension-points"></a>

## 扩展位置

请查阅[贡献者扩展指南](extending.zh-CN.md)，按顺序定位规则所有者、公开接口、下游使用方与现有测试。
该指南提供流体、Nu 闭合及 GUI 面板或对话框的完整路线，以及简明的拓扑路线。
每个维度保持一条生产路径，不为单一实现引入多余包装层。
