# Python 源码和公开入口

[中文](README.md) | [English](README.en.md)

这个目录对应公开的 `tm1` 包。
命令均从仓库根目录执行，以确保导入当前检出代码。
首次配置、公开算例和启动步骤见[首次运行指南](../docs/first-run.md)。
完整模块边界和物理约束见[架构说明](../docs/architecture.zh-CN.md)。

## 四个计算入口

| 文件 | 公开入口 | 职责 |
| --- | --- | --- |
| [python/compute.py](compute.py) | `compute` | 校验配置并顺序组织三个计算阶段；返回 `CaseData`、`FieldResult` 和 `PerformanceResult`。 |
| [python/preprocess/api.py](preprocess/api.py) | `prepare_case` | 准备物理网格、端口、设计场、模型资源和可移植执行输入。 |
| [python/solvers/api.py](solvers/api.py) | `run_case` | 消费 `CaseData`，经 Python 绑定执行 C++ 保存态阶段，返回原生场和运行状态。 |
| [python/postprocess/api.py](postprocess/api.py) | `evaluate` | 从 `FieldResult` 评估工程指标、物理平衡、适用性与资格结论，不重跑求解。 |

```text
compute -> preprocess.api.prepare_case -> CaseData -> solvers.api.run_case -> FieldResult
                                                                       -> postprocess.api.evaluate -> PerformanceResult
```

`compute` 同时管理阶段进度、取消、耗时与警告。
当前正式计算支持矩形二维与长方体三维。
公开输入和文件交接见[示例](../examples/three_module/)与[数据契约](../docs/contracts/three_module_v1/README.zh-CN.md)。
近似模式和扩展状态见[能力范围](../docs/capabilities.md)。

### 现行原生阶段绑定

四个计算阶段直接调用收敛后的现行 C ABI，不回退到已退役的 Python 数值实现：

- **前处理准备（`preprocess/`，ABI 3）**：`python/cpp_interface/native_preparation.py` 与 `python/cpp_interface/preparation_host.py` 绑定扁平二维和三维 `v1` 族入口及统一的 `tpmshx_preparation_callbacks_v1`。`python/preprocess/two_d/preparation.py` 使用绑定在释放前复制的数组与元数据构造不可变的二维 `CaseData`。`python/preprocess/three_d/preparation.py` 使用绑定在释放前复制的数组与元数据构造不可变的三维 `CaseData`。`python/physical_models/zone_units.py` 负责保存分区数据的单位转换。
- **入口物性查询**：`python/cpp_interface/inlet_properties.py` 为独立的 `physical_models.tpms_calc.compute` 绑定 `tpmshx_query_inlet_properties_v2`。Python 保留几何选择、共享缓存、逐次 `K_ss` 查询和警告策略。见[入口物性查询](../docs/native-stages.zh-CN.md#入口物性查询)。
- **完整二维与三维执行（`solver/`，二维保存态 ABI 5／三维保存态 ABI 3、捕获 ABI 2）**：求解宿主 `python/solvers/full_2d.py` 与 `python/solvers/full_3d.py` 校验保存工况、选择模型与运行控制、重放警告并组装 `FieldResult`。`python/cpp_interface/full_2d_stage.py` 与 `python/cpp_interface/full_3d_stage.py` 仅绑定保存态阶段生命周期（`tpmshx_run_saved_case_2d_v5`、`tpmshx_run_saved_case_3d_v3` 及经由 `python/cpp_interface/run_state.py` 使用宿主错误映射的检查点创建／恢复入口），并在释放前复制原生输出。两者均要求库提供 `execution_view_v1`、`records_v1`、`report_v1` 和 `get_capture_v1`；缺少这些入口的库按部署错误直接失败。
- **执行与适用性记录**：保存态二维／三维运行在原生结果释放前复制适用性分组与必需记录。`python/cpp_interface/solver_library/stage_capture.py` 复制原生捕获视图、闭合记录、账本与适用性选择，`python/solvers/stage_execution.py` 将原生报告关联到可移植模型角色，`python/data_types/field_result.py` 发布 `execution_record`（`full_execution_v1`）及带 `scope_notes` 的 `applicability_evidence`。`python/solvers/execution_record.py` 仅在非阶段或测试构造的 `FieldResult` 缺少该字段时补充组装 `full_execution_v1`。
- **Quick Design（`quick_design_prepare_v2.cpp`、`quick_design_run.cpp`）**：准备宿主 `python/preprocess/quick_design.py` 组装 `CaseData` 并提供定尺所用的压降分数查询。绑定 `python/cpp_interface/quick_preparation.py` 通过 `tpmshx_quick_callbacks_v2` 调用 `tpmshx_prepare_quick_design_v2` 和 `tpmshx_quick_pressure_fractions_v2`。求解宿主 `python/solvers/quick_design.py` 读取已保存的准备算例并组装 `FieldResult`。绑定 `python/cpp_interface/quick_design.py` 调用 `tpmshx_run_quick_design_v2`，在释放原生结果前复制输出。默认值统一来自 `python/model_configs/model_parameters_v1.json` 及生成的 C++ 常量。
- **结果评估（`postprocess/`，Result ABI 3）**通过 `python/postprocess/api.py` 处理完整二维、完整三维和 Quick Design 结果。`python/cpp_interface/result_evaluation.py` 将 `float64` 证据和 `int32` 标签传给 `tpmshx_result_stage_query_v3`，发出原生 `RuntimeWarning` 诊断，并在释放前复制输出。`python/postprocess/evaluation.py` 组装指标和公开报告。`python/postprocess/export.py` 负责导出。

Python 之外的 C/C++ 调用流程见[原生阶段 SDK](../docs/native-stages.zh-CN.md)。
已退役的 `v1`–`v11` 入口和直接 Python 驱动见[C++ 迁移与 ABI 演进历史](../docs/history/cpp-migration-history.zh-CN.md)。

## 修改数值函数

修改数值规则时，按职责在下表查找 C++ 所有者。
`python/data_types/` 定义公开输入／输出契约，`python/cpp_interface/` 负责类型与数组传递。

| 修改内容 | C++ 文件与代表函数 |
| --- | --- |
| 单元几何、chi 与固体导热率 | [geometry.cpp](../geometry/geometry.cpp): `standard_geometry`, `solid_conductivity`; [asym_geometry.cpp](../geometry/asym_geometry.cpp) |
| 网格与物理端口 | [grid.cpp](../geometry/grid.cpp): `uniform`, `wall`; [ports.cpp](../geometry/ports.cpp): `port_overlap_1d`, `port_fractions_1d` |
| 连续场、sigmoid、LUT 与分区 | [field_continuous.cpp](../geometry/field_continuous.cpp); [field_sigmoid.cpp](../geometry/field_sigmoid.cpp); [field_lut.cpp](../geometry/field_lut.cpp); [zones.cpp](../geometry/zones.cpp) |
| 物性与 Nu 闭合 | [fluid_properties.cpp](../numerics/fluid_properties.cpp): `PropertyEvaluator::evaluate`, `fluid_nusselt`; [preparation_properties.cpp](../preprocess/preparation_properties.cpp) |
| 标量入口物性组合 | [preparation_case.cpp](../preprocess/preparation_case.cpp): `query_inlet_properties`, `inlet_property_values`; [preparation_case_c_api.cpp](../preprocess/preparation_case_c_api.cpp): `tpmshx_query_inlet_properties_v2` |
| 固定 D-F、修正、投影与规定流量 | [preparation_df.cpp](../preprocess/preparation_df.cpp): `fixed_df`; [preparation_df_corrections.cpp](../preprocess/preparation_df_corrections.cpp); [preparation_df_projection.cpp](../preprocess/preparation_df_projection.cpp); [preparation_flow.cpp](../preprocess/preparation_flow.cpp): `inlet_capacity_2d`, `inlet_speed` |
| 完整二维／三维与 Quick Design | [full_2d.cpp](../solver/full_2d.cpp): `solve_full_2d`; [full_3d.cpp](../solver/full_3d.cpp): `solve_full_3d`; [quick_design_driver.cpp](../solver/quick_design_driver.cpp): `solve_quick_design` |
| 指标、物理平衡、分区统计与检查 | [result_metrics.cpp](../postprocess/result_metrics.cpp): `pressure_face`, `boundary_enthalpy_duty`; [result_balance.cpp](../postprocess/result_balance.cpp): `mass`, `energy`, `zone_std`; [result_checks.cpp](../postprocess/result_checks.cpp): `collect_range`, `strict_certificate` |
| 完整阶段准备与执行 | [preparation_case.cpp](../preprocess/preparation_case.cpp): `prepare_case_2d`, `prepare_zoned_flow_case_2d`, `prepare_thermal_sides`, `prepare_case_3d`; [stage_run.cpp](../solver/stage_run.cpp): `tpmshx_run_saved_case_2d_v5`, `tpmshx_stage_run_2d_create_saved_v5/restore_saved_v5`; [stage_capture_2d.cpp](../solver/stage_capture_2d.cpp): `tpmshx_stage_run_2d_get_capture_v1`, `tpmshx_stage_run_2d_records_v1`; [stage_run_3d.cpp](../solver/stage_run_3d.cpp): `tpmshx_run_saved_case_3d_v3`, `tpmshx_stage_run_3d_create_saved_v3/restore_saved_v3`; [stage_capture_3d.cpp](../solver/stage_capture_3d.cpp): `capture_3d`, `tpmshx_stage_run_3d_get_capture_v1`, `tpmshx_stage_run_3d_records_v1` |
| Quick Design 阶段准备与执行 | [quick_design_prepare_v2.cpp](../preprocess/quick_design_prepare_v2.cpp): `tpmshx_prepare_quick_design_v2`, `tpmshx_quick_pressure_fractions_v2`; [quick_design_run.cpp](../solver/quick_design_run.cpp): `tpmshx_run_quick_design_v2` |
| 阶段评估与资格判断 | [result_stage.cpp](../postprocess/result_stage.cpp): `evaluate`, `evaluate_applicability`, `evaluate_physical_balance`, `evaluate_qualification` |

几何库使用 geometry ABI 2 和 field ABI 3。
准备库使用 preparation ABI 3 和 Quick Design 准备 v2。
结果库使用 result ABI 3。
求解器内部边界见[C++ 接入说明](../docs/cpp-migration.zh-CN.md)，Python 保留职责见[架构说明](../docs/architecture.zh-CN.md#retained-python-responsibilities)。

### 修改后重新构建

修改 C++ 函数或编入库的模型数据后，先通过[当前环境检查](../docs/verification.md)。
从仓库根目录重新构建并发布四个库，然后重启进程。
若 `.venv-path` 指向 BO 环境，将 `base.txt` 替换为 `engineering/requirements/` 中的 `bo-macos.txt` 或 `bo-windows.txt`。
首次使用构建缓存时，先执行[首次运行](../docs/first-run.md#examples)中的 `fetch` 命令，再复用同一缓存执行下列命令。

macOS：

```sh
PYTHON="$(head -n 1 .venv-path)"
"$PYTHON" engineering/scripts/build_native_dependencies.py publish --python-lock engineering/requirements/base.txt
```

Windows (PowerShell)：

```powershell
$tm1Python = Get-Content .venv-path -TotalCount 1
& $tm1Python engineering/scripts/build_native_dependencies.py publish --python-lock engineering/requirements/base.txt
```

单独发布组件和旧检查点运行库保留规则见[C++ 构建说明](../docs/cpp-migration.zh-CN.md#native-geometry-core)。

<a id="三模块主线"></a>
<a id="支撑模块与应用入口"></a>

## Python 目录

| 目录 | 职责与边界 |
| --- | --- |
| [preprocess/](preprocess/) | 前处理与显式离线模型准备。 |
| [solvers/](solvers/) | 求解 API、二维／三维与 Quick Design 求解宿主及执行与账本辅助模块。C++ 实现在 [solver/](../solver/)。 |
| [postprocess/](postprocess/) | 已记录结果的指标、物理审计、资格结论和导出。 |
| [data_types/](data_types/) | 配置、准备好的工况、场与性能结果的数据定义。 |
| [file_io/](file_io/) | 工况、结果、指标和检查点的文件读写。 |
| [run_control/](run_control/) | 取消、进度、告警、环境与运行库选择。 |
| [physical_models/](physical_models/) 和 [model_configs/](model_configs/) | 物理模型查询及带版本的模型参数。 |
| [cpp_interface/](cpp_interface/) | 原生 ctypes 绑定。[solver_library/](cpp_interface/solver_library/) 包含保存态原生运行的 ctypes 布局与解码函数。 |
| [applications/](applications/) | [GUI](applications/gui/)、[CLI](applications/cli/)、[快速设计](applications/design/)、[BO 优化](applications/optimization/)和[历史运行恢复](applications/execution/recovery.py)。 |
| [development/](development/) | 数值与实验验证、诊断和开发工具。自动测试位于 [tests/python/](../tests/python/)。 |

[网格与几何预检](preprocess/preflight.py)读取已捕获的 `ComputeConfig`。[灵敏度筛选](applications/design/sensitivity.py)逐行估算 A 侧为空气时的指标。
GUI 显示预检警告、扫描进度和热图。

仍使用已退役模块路径的本地脚本需更新导入，或使用记录的原源码版本。
使用根目录 [main.py](../main.py) 启动应用。它将 GUI 分派到 [applications/gui/main.py](applications/gui/main.py)，文件阶段分派到 [applications/cli/stages.py](applications/cli/stages.py)，`summary` 分派到 [applications/cli/main.py](applications/cli/main.py)，`design` 分派到 [applications/design/cli.py](applications/design/cli.py)，`optimize` 分派到 [applications/optimization/cli.py](applications/optimization/cli.py)。
计算代码直接调用上述四个入口。
根 [engineering/](../engineering/) 保存构建与检查脚本、打包配置和依赖锁。
[docs/contracts/](../docs/contracts/) 保存公共文件契约，`.github/workflows/` 保存 CI 配置，其他根目录职责见[仓库导航](../docs/README.md)。
