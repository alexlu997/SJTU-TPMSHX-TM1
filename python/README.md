# Python 源码和公开入口

[中文](README.md) | [English](README.en.md)

这个目录对应公开的 `sjtu_tpmshx` 包，已有脚本沿用原导入名。首次配置、公开算例和启动步骤见[首次运行指南](../docs/first-run.md)。
命令均从仓库根目录执行。完整模块边界和物理约束见[架构说明](../docs/architecture.zh-CN.md)。

## 四个计算入口

| 文件 | 公开入口 | 职责 |
| --- | --- | --- |
| [python/compute.py](compute.py) | `compute` | 主计算入口，校验配置并统一组织三个阶段；返回 CaseData、FieldResult 和 PerformanceResult |
| [python/preprocess/api.py](preprocess/api.py) | `prepare_case` | 准备实际网格、边界、设计场、模型资源和可移植运行输入 |
| [python/solvers/api.py](solvers/api.py) | `run_case` | 消费 CaseData，经 Python 绑定执行 C++ 数值求解，返回原生场和运行状态 |
| [python/postprocess/api.py](postprocess/api.py) | `evaluate` | 从 FieldResult 组织指标评估与资格结论，不重跑求解 |

```text
compute -> preprocess.api.prepare_case -> CaseData -> solvers.api.run_case -> FieldResult
                                                                       -> postprocess.api.evaluate -> PerformanceResult
```

`compute` 同时处理阶段进度、取消、耗时与警告。`python/postprocess/api.py` 将完整 2D/3D、Quick Design 评估及独立查询交给原生结果阶段。
`python/cpp_interface/_native_result_stage.py` 适配 `float64`/`int32` 证据、固定 `RuntimeWarning` 诊断与返回对象；`python/postprocess/export.py` 负责导出。
当前正式计算支持矩形二维与长方体三维。公开输入和文件交接见[示例](../examples/three_module/)与[数据契约](../docs/contracts/three_module_v1/README.zh-CN.md)。
近似模式和扩展状态见[能力范围](../docs/capabilities.md)。

[原生阶段 SDK](../docs/native-stages.zh-CN.md)提供独立的 C++ 调用流程。
首条完整路径支持规定入口速度的均匀、对称二维 air/air。
准备 v2 为规定速度、均匀对称二维几何增加 air/water/sCO2/CO2 的全部 16 个有序配对。
准备 v3 为均匀二维总质量流量增加独立容量查询、入口流量解析和完整准备，复用物理入口网格，
并将前段记录与最终准备证据分开。
run v2 支持均匀四流体准备态，包括已解析的总质量流量。准备 v4 提供连续 XY 物理场和完整局部阻力，供 run v3 使用。run v1 保留原 air/air CFD 范围。
准备 v5 增加规定速度、CFD 阻力和零 delta 下的原始 air/air 条带与矩形。
它的独立热几何与行阻力保留原离散规则。
准备 v6 增加原始 air/air sigmoid 控制，以及支持生产分辨率冷构建、可复用的原生 LUT。
它保留独立热几何和行阻力，不使用离散平滑。

准备 v8 为这些 air/air 空间输入增加容量查询、流量解析和完整固定流量准备。
它保留物理网格和几何，在换热计算前解析速度，并拥有复制后的区域、控制点与 LUT。
域长／端口类型输入与独立的前段证据仍明确保留。
准备 v9 通过带类型的宿主缓存钩子连接对称空间几何的 Python 准备、容量查询与解析。
`python/cpp_interface/preparation_host.py` 共享缓存与证据传输，未命中时由原生阶段计算。
Python 保留 LUT 存储，缺表时原生代码在原几何检查点构建。

准备 v10 增加规定速度下既有非零 delta 的均匀 air/water 和 air/air 空间模式。
它单独携带名义热侧元组，保留既有分流和 N128 几何计算，与设计场及逐单元热几何分开。
连续场、CO2/sCO2、实验模型和总质量流量的既有限制不变；此前 C 布局及范围均保留。
Python 连续 XY 和条带的完整准备优先使用 v11，由准备库返回流体孔隙率和逐条带 A 侧水力半径。受支持的旧准备库仍通过几何库取得相应字段。
均匀、矩形和 sigmoid 的完整准备使用 v10。均匀及连续 XY 的容量查询和流量解析使用 v7，结果分别为 v3 和 v4。
空间容量和解析使用 v10，沿用 v9 结果视图和释放函数。
公共 ZoneConfig 与 sigmoid 组合查询在单独迁移通过前仍保留独立调用消费者。
它们保留调用方提供的物性及自定义 sigmoid 控制。
`python/cpp_interface/native_preparation.py` 为原生适配器，被替代的 Python 准备流程及行 D-F 投影已退役。
独立准备参考保留在 `tests/python`；`python/physical_models/zone_units.py` 负责保存分区数据的单位转换。
CaseData 与保存文件契约不变，原生失败直接传播，不选择其他准备路线。

独立的三维准备 v1 接收规定速度的原始对称均匀输入，覆盖全部 16 个有序流体配对，
保留物理网格、带类型的端口、六个流向、单元数上限和原有 CFD／实验限制。
两侧孔隙率已拆分，K/cF 基础场与逐侧应用因子分开保存。
独立的三维流量 v2 增加容量查询、总流量解析和完整准备，只计算一次几何。
连续三维 v3 从原始 XY 挤出或 XYZ 控制点完成准备，并支持容量查询及总流量解析。
spatial v4 增加 XY 网格矩形和现有全局偏置规则，分别保留侧孔隙率及热几何。
原生三维运行／捕获将这些准备家族及保存视图接到同一 `Full3DRun` 生命周期。
结果在准备态及运行释放后拥有完整原始场与评估证据。
Python 完整三维执行通过 `full_3d_stage.py` 使用该保存输入生命周期。
`full_3d_stage.py` 发布现行结果，`full_3d_capture.py` 解码早期结果。
原生捕获提供应用归约量和可选审计出口权重。
Python 三维准备使用 host v5 和共享的带类型缓存回调。
空气场每侧最多选择八个标量观测值，完整原始数组记录仍保留全部单元。
`python/preprocess/three_d/preparation.py` 从拥有独立存储的原生结果组装不可变 CaseData。
被替代的 `shared/models/grid_3d.py` 和 `asym_split.py` 助手已退役。
`tests/python/preparation_3d_reference.py` 保留独立数值参考。
接近单元上限的内存使用及真实三维 BO 需要单独验收。

二维执行使用所选库的完整保存输入原生生命周期，包括检查点与完整结果捕获。
保存输入描述符 v2 增加名义侧几何并接收离散与 sigmoid 场；saved v1 保持不变。
Python 优先选择 v2，其次为对称均匀或连续输入选择 v1；不具备适用协议的归档库继续使用原接口。

当前公共保存态 2D/3D 运行在原生结果释放前复制适用性分组和必需记录。
`python/solvers/applicability_evidence.py` 按原生顺序保留保存的入口字段和标量类型，并在 C 提供 constraint 时采用该值。
公共 API 发布这些分组，不重复分类。
Python 将完整 case notices 与运行期 `nu-evidence` 警告记录合并为 `scope_notes`；独立 C++ 阶段保留原生通知。
直接完整求解路径保留 `capture_applicability`；捕获失败不选择该路径。
求解结束时，[execution_report.cpp](../solver/execution_report.cpp) 从 C++ 求解记录生成物性采样、热学方法和守恒收支。
Python 将标量报告和单独传递的场数组写入结果。只有缺少报告接口的运行库还需要逐项解码原始执行视图。
`python/data_types/field_result.py` 将这些记录与物性采样、算例资源索引写入场结果。
缺少执行视图的旧库由 `python/solvers/execution_record.py` 从返回字段重建记录。
原生结果阶段判断资格。

独立的 `physical_models.tpms_calc.compute` 与完整准备使用同一原生入口物性组合。
Python 保留几何选择、共享缓存、可变结果副本、逐次 K_ss 查询、对象转换和警告策略。
`python/cpp_interface/inlet_properties.py` 传输十二个带类型的查询值，并与准备适配器共享范围观测。
[入口物性查询](../docs/native-stages.zh-CN.md#入口物性查询) 向 C 和 C++ 调用者提供同一计算，不需要网格或求解器。

Quick Design 准备 v2 接受带类型的原始输入，并提供不创建热网格或设计场数组的独立压降查询。
Python 通过 `_native_quick_prepare.py` 执行固定宿主协议，将原生输出复制到 CaseData。
被替代的 `shared/models/quick_design.py` 已删除；默认值统一来自 `python/model_configs/model_parameters_v1.json` 及生成的 C++ 常量。
native-double v1 契约与既有 LTNE 模型继续可用。
Python 执行通过保存的准备态调用原生 run 阶段；原生结果阶段负责 Quick Design 指标。
准备宿主操作保留既有 Python 类型、缓存、警告和事件协议；结果评估将 Quick Design 操作数规范化为 `float64`，并发出固定 `RuntimeWarning` 诊断。
上述 Python 入口保留全部现有模式。

## 修改数值函数

修改数值规则时，从下表找到 C++ 所有者。
公开输入／输出契约位于 `python/data_types/`；Python 绑定负责类型与数组传递。

| 修改内容 | C++ 文件与代表函数 |
| --- | --- |
| 单元几何、chi 与固体导热率 | [geometry.cpp](../geometry/geometry.cpp): `standard_geometry`, `solid_conductivity`; [asym_geometry.cpp](../geometry/asym_geometry.cpp) |
| 网格与物理端口 | [grid.cpp](../geometry/grid.cpp): `uniform`, `wall`; [ports.cpp](../geometry/ports.cpp): `port_overlap_1d`, `port_fractions_1d` |
| 连续场、sigmoid、LUT 与分区 | [field_continuous.cpp](../geometry/field_continuous.cpp); [field_sigmoid.cpp](../geometry/field_sigmoid.cpp); [field_lut.cpp](../geometry/field_lut.cpp); [zones.cpp](../geometry/zones.cpp) |
| 物性与 Nu 闭合 | [fluid_properties.cpp](../numerics/fluid_properties.cpp): `PropertyEvaluator::evaluate`, `fluid_nusselt`; [preparation_properties.cpp](../preprocess/preparation_properties.cpp) |
| 标量入口物性组合 | [preparation_case.cpp](../preprocess/preparation_case.cpp): `query_inlet_properties`, `inlet_property_values`; [preparation_case_c_api.cpp](../preprocess/preparation_case_c_api.cpp): `tpmshx_query_inlet_properties_v1` |
| 固定 DF、修正、投影与规定流量 | [preparation_df.cpp](../preprocess/preparation_df.cpp): `fixed_df`; [preparation_df_corrections.cpp](../preprocess/preparation_df_corrections.cpp); [preparation_df_projection.cpp](../preprocess/preparation_df_projection.cpp); [preparation_flow.cpp](../preprocess/preparation_flow.cpp): `inlet_capacity_2d`, `inlet_speed` |
| 完整二维／三维与 Quick Design | [full_2d.cpp](../solver/full_2d.cpp): `solve_full_2d`; [full_3d.cpp](../solver/full_3d.cpp): `solve_full_3d`; [quick_design_driver.cpp](../solver/quick_design_driver.cpp): `solve_quick_design` |
| 指标、物理平衡、分区统计与检查 | [result_metrics.cpp](../postprocess/result_metrics.cpp): `pressure_face`, `boundary_enthalpy_duty`; [result_balance.cpp](../postprocess/result_balance.cpp): `mass`, `energy`, `zone_std`; [result_checks.cpp](../postprocess/result_checks.cpp): `collect_range`, `strict_certificate` |
| 完整阶段准备与执行 | [preparation_case.cpp](../preprocess/preparation_case.cpp): `prepare_case_2d`, `prepare_zoned_flow_case_2d`, `prepare_thermal_sides`, `prepare_case_3d`; [stage_run.cpp](../solver/stage_run.cpp): `tpmshx_run_saved_case_2d_v4`, `tpmshx_stage_run_2d_create_saved_v4/restore_saved_v4`; [stage_capture_2d.cpp](../solver/stage_capture_2d.cpp)：`tpmshx_stage_run_2d_get_capture_v1`, `tpmshx_stage_run_2d_records_v1`; [stage_run_3d.cpp](../solver/stage_run_3d.cpp): `tpmshx_run_saved_case_3d_v2`, `tpmshx_stage_run_3d_create_saved_v2/restore_saved_v2`; [stage_capture_3d.cpp](../solver/stage_capture_3d.cpp): `capture_3d`, `tpmshx_stage_run_3d_get_capture_v1`, `tpmshx_stage_run_3d_records_v1` |
| Quick Design 阶段准备与执行 | [quick_design_prepare_v2.cpp](../preprocess/quick_design_prepare_v2.cpp): `tpmshx_prepare_quick_design_v2`, `tpmshx_quick_pressure_fractions_v2`; [quick_design_run.cpp](../solver/quick_design_run.cpp): `tpmshx_run_quick_design_v2` |
| 阶段评估与资格判断 | [result_stage.cpp](../postprocess/result_stage.cpp): `evaluate`, `evaluate_applicability`, `evaluate_physical_balance`, `evaluate_qualification` |

几何库使用 geometry ABI 1／field ABI 2；准备库保留 ABI 1 加载入口，并增加带版本的 Quick 准备 v2 契约；结果库使用 result ABI 3。
求解器的算法细节从上表 driver 进入对应 SIMPLE、压力和能量实现；[C++ 说明](../docs/cpp-migration.zh-CN.md)给出接口边界。
Python 保留配置、DTO、I/O、缓存、固定 `RuntimeWarning` 诊断、GUI／搜索和离线研究。
原生结果阶段负责完整评估与资格；Python 保留来源数据和宿主通知，并解释执行记录。
具体保留边界见[架构](../docs/architecture.zh-CN.md#retained-python-responsibilities)。

### 修改后重新构建

修改 C++ 函数或编入库的模型数据后，先通过[当前环境检查](../docs/verification.md)。
从仓库根目录重新构建并发布四库，最后重启进程。
下列命令使用基础锁；若 `.venv-path` 指向 BO 环境，换成 `engineering/requirements/` 中对应的 `bo-macos.txt` 或 `bo-windows.txt`。
首次使用构建缓存时，先执行[首次运行](../docs/first-run.md#examples)中的 `fetch` 命令，再用同一缓存执行下列命令。

macOS:

```sh
PYTHON="$(head -n 1 .venv-path)"
"$PYTHON" engineering/scripts/build_native_dependencies.py publish --python-lock engineering/requirements/base.txt
```

Windows (PowerShell):

```powershell
$tm1Python = Get-Content .venv-path -TotalCount 1
& $tm1Python engineering/scripts/build_native_dependencies.py publish --python-lock engineering/requirements/base.txt
```

组件单独发布和旧检查点运行库保留规则见[C++ 构建说明](../docs/cpp-migration.zh-CN.md#native-geometry-core)。

<a id="三模块主线"></a>
<a id="支撑模块与应用入口"></a>

## Python 目录

| 目录 | 职责与边界 |
| --- | --- |
| [preprocess/](preprocess/) | 前处理与显式离线模型准备 |
| [solvers/](solvers/) | 求解 API、准备态适配和 Python C++ 绑定。原生求解实现见[根目录 solver/](../solver/) |
| [postprocess/](postprocess/) | 已记录结果的指标、物理审计、资格结论和导出 |
| [data_types/](data_types/) | 配置、准备好的工况、场与性能结果的数据定义 |
| [file_io/](file_io/) | 工况、结果、指标和检查点的文件读写 |
| [run_control/](run_control/) | 取消、进度、告警、环境与运行库选择 |
| [physical_models/](physical_models/) 和 [model_configs/](model_configs/) | 物理模型查询及带版本的模型参数 |
| [cpp_interface/](cpp_interface/) | Python 调用原生库的接口。[solver_library/](cpp_interface/solver_library/) 同时服务底层调用与保存态运行 |
| [applications/](applications/) | [GUI](applications/gui/)、[CLI](applications/cli/)、[快速设计](applications/design/)、[BO 优化](applications/optimization/)和[历史运行恢复](applications/execution/recovery.py) |
| [development/](development/) | 数值与实验验证、演示、诊断工具。自动测试在 [tests/python/](../tests/python/) |

GUI 实现在 [python/applications/gui/main.py](applications/gui/main.py)，CLI 实现在 [python/applications/cli/main.py](applications/cli/main.py)。
包顶 [python/main.py](main.py)、[python/cli.py](cli.py) 和 [python/desktop.py](desktop.py) 保留短启动入口。
使用 `python -m sjtu_tpmshx.main` 或 `python -m sjtu_tpmshx.cli`；计算代码直接调用上面的四个入口。

根 [engineering/](../engineering/) 保存 `scripts/` 构建与检查脚本、`packaging/` 打包配置和 `requirements/` 依赖锁。
[docs/contracts/](../docs/contracts/) 保存公共文件契约，`.github/workflows/` 保存 CI 配置。
其他根目录职责见[仓库导航](../docs/README.md)。
