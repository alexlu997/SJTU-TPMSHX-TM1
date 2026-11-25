# 原生阶段接口

[中文](native-stages.zh-CN.md) | [English](native-stages.md)

## 现行 C ABI

Preparation ABI 3、Quick Design v2、二维保存态阶段 ABI 5、三维保存态阶段 ABI 3 与 Result ABI 3 定义了现行 C 阶段接口。
所有准备与保存态运行描述符均为扁平结构体，仅含顶层 `(abi_version, struct_size)` 字段头，不含嵌套 `values` 链。
所有阶段数值缓冲区均使用 `float64`，分区标签使用 `int32`。
各共享库不再导出这些阶段操作的旧版本入口。

| 阶段 | 现行 C 入口 |
| --- | --- |
| 二维准备（ABI 3） | `tpmshx_preparation_2d_{uniform,continuous,zoned,sigmoid}_{capacities,resolve_flow,prepare_case}_v1`、`tpmshx_preparation_2d_stripe_prepare_case_v1`、`tpmshx_query_inlet_properties_v2`、`tpmshx_preparation_sigmoid_lut_{create,release}_v7`、`tpmshx_preparation_df_experiment_scope_v1`、`tpmshx_preparation_collect_range_v1` |
| 三维准备（ABI 3） | `tpmshx_preparation_3d_{continuous,spatial}_{capacities,resolve_flow,prepare_case}_v1` |
| Quick Design 准备 | `tpmshx_prepare_quick_design_v2`、`tpmshx_quick_pressure_fractions_v2`、`tpmshx_quick_prepared_release_v2` |
| 二维阶段运行（保存态 ABI 5） | `tpmshx_stage_run_2d_abi_version`、`tpmshx_run_saved_case_2d_v5`、`tpmshx_stage_run_2d_{create,restore}_saved_v5`、`tpmshx_stage_run_2d_{advance_step,finish,phase,snapshot,take_result,release_run,release}_v1`、`tpmshx_stage_run_2d_{records,execution_view,get_capture,zone_temperatures,report}_v1`、`tpmshx_stage_borrow_mesh_v1`、`tpmshx_stage_port_windows_fit_2d_v1`、`tpmshx_stage_run_2d_check_experiment_v4` |
| 三维阶段运行（保存态 ABI 3，捕获 ABI 2） | `tpmshx_stage_run_3d_abi_version`、`tpmshx_stage_capture_3d_abi_version`、`tpmshx_run_saved_case_3d_v3`、`tpmshx_stage_run_3d_{create,restore}_saved_v3`、`tpmshx_stage_run_3d_{advance_step,finish,phase,snapshot,take_result,release_run,release}_v1`、`tpmshx_stage_run_3d_{records,execution_view,get_capture,report}_v1` |
| 阶段原始结果查询 | `tpmshx_full_{2,3}d_abi_version`、`tpmshx_full_2d_get_{energy_evidence,energy_update_scale,energy_effective_settings,model_enthalpy_evidence,last_closure_ranges,physical_heat_ledger,property_sampling,model_h_iterations,flow_methods}_v1`、`tpmshx_full_3d_get_{energy_evidence,energy_update_scale,energy_effective_settings,bootstrap_trace,model_enthalpy_evidence,last_closure_ranges,physical_heat_ledger,property_sampling,model_h_iterations,model_h_acceleration}_v1`、`tpmshx_run_state_release_v1` |
| 算法标识与默认值 | `tpmshx_temperature_algorithm_v1`、`tpmshx_model_h_algorithm_v1`、`tpmshx_energy_algorithm_version_v1`、`tpmshx_full_enthalpy_defaults_v1` |
| Quick Design 运行 | `tpmshx_solver_abi_version`、`tpmshx_run_quick_design_v2`、`tpmshx_quick_run_ranges_v2`、`tpmshx_quick_run_temperature_algorithm_v1`、`tpmshx_quick_run_release_v1` |
| 结果阶段（ABI 3） | `tpmshx_result_stage_query_v3`、`tpmshx_result_stage_{evaluate,applicability,physical_balance,qualification,release}_v1` |

每个准备族同时导出对应的 `*_flow_release_v1` 与 `*_case_release_v1` 释放函数。
缺少必需现行入口的共享库属于部署错误；Python 不会选择归档运行库或回退路线。
保存态阶段入口定义现行 C SDK，供 Python 及 C／C++ 调用方使用。
阶段原始结果查询读取阶段结果所借用的 `raw` 结果；只释放阶段结果。
求解库不导出直接完整求解、续算或单驱动 C 入口。
已退役的 `v1`–`v11` ABI 记录见[C++ 迁移与 ABI 演进历史](history/cpp-migration-history.zh-CN.md)。

## 阶段主线、所有权与单位

`include/tpmshx/stages.hpp` 中的 C++ 调用顺序为 `prepare_case`、`run_case` 与 `evaluate`。
准备库计算物理网格、端口、场与模型证据；求解库运行准备态；结果库独立评估已记录证据。

调用 `saved_case`、`SavedCase2D` 或 `SavedPreparedCase3D` 前，先用变量保存准备所有者。
用 `const auto saved = saved_case(prepared);` 保存完整的描述符。
创建或恢复 `Run2D` 或 `Run3D` 时，传入 `saved`。
将原始 C 结构体或 C++ 基类 `SavedCase3D` 按值复制后，副本仍然借用完整描述符的存储。
如果外部适配器返回其内部描述符的引用，使用副本期间须保持该适配器存活。
在成功取出结果或释放运行对象前，须保持准备所有者和原描述符存活且不变。
回调函数及其上下文须一直有效，直到运行对象释放。
一次性调用 `run_case` 可以直接接收临时准备所有者或临时描述符。
例如，`run_case(prepare_case(input, options), control)` 会在临时准备所有者销毁前转移结果。

`RunControl`（二维）和 `RunControl3D` 默认将 `cpu_threads` 设为主机报告的逻辑 CPU 数量，最多 8 个。
如果主机报告 0，默认使用 1 个线程。
启动或恢复运行时，可以将 `cpu_threads` 设为正整数，包括大于 8 的值。

- **单位**：设计输入（`cell_length_mm`、`wall_thickness_mm`）使用 mm；保存的物理设计场使用 m。构建输运与闭合比例时保留既有 mm-to-m-to-mm 转换顺序。换热量在二维为 W/m、三维为 W；质量流量为 kg/s；温度为 K；压力为 Pa(abs)。
- **数组布局**：请求网格数与实际网格数分开保存。二维物理场为 `(nx, ny)` C 序，三维物理场为 `(nx, ny, nz)` C 序，各侧流场为 `(cross, stream)` 序。
- **单一所有者释放**：每个拥有动态存储的输出仅有一个外层 `owner` 指针，嵌套视图的 `owner` 为空。最后一次使用后须通过创建该对象的库释放。纯标量查询（`tpmshx_query_inlet_properties_v2`、`tpmshx_quick_pressure_fractions_v2`）按值返回，无需释放。
- **互斥缓冲区**：输出、失败、诊断与错误缓冲区不得与输入、回调或任何存活结果的视图重叠。重叠调用返回无效状态，且不修改结果与诊断缓冲区。
- **库边界**：准备库与求解库各自链接锁定的 CoolProp 静态库；结果库不链接准备库、求解库、CoolProp 或 Qt。
- **Result ABI 3 查询**：`tpmshx_result_stage_query_v3` 接收扁平的 `tpmshx_stage_input_v3`，包含借用的 `float64` 数组、`int32` 标签以及原始 C 字符串模式／单位标签。接口返回前同步传递浮点事件，Python 适配器对除零、溢出和无效值发出 `RuntimeWarning`。

二维或三维阶段运行完成后，在释放结果前复制以下视图：

- `tpmshx_stage_run_{2d,3d}_records_v1`：物性采样、末次闭合范围、温度模型记录、能量关系、SIMPLE 停止原因及三维阻力汇总。
- `tpmshx_stage_run_{2d,3d}_execution_view_v1`：实际热学控制、能量证据、更新尺度、model-h 记录及 sCO2 运行通知。
- `tpmshx_stage_run_{2d,3d}_report_v1`：标量执行报告，包含解析网格、流体、执行状态、物性采样与 model-h 平衡。

Python 按原顺序去重合并算例通知与运行期 `nu-evidence` 警告，写入 `scope_notes`。
独立结果阶段决定指标可用性与资格结论。

## 入口物性查询

`stages.hpp` 中的 `InletPropertyQuery` 与 `query_inlet_properties` 通过 `preparation_case_c_api.h` 的 `tpmshx_query_inlet_properties_v2` 暴露标量入口物性组合。
调用方提供拓扑、mm 单位的 `L` 与 `t`、入口速度、温度、压力、m 单位的水力直径、单侧孔隙率及可选 sCO2 Nu 配置。
该查询不计算几何、网格、端口或求解场。
它按生产顺序计算四流体物性、Nu 与固定 CFD 阻力；`exact_co2_drag` 独立于传入几何选择固定 CO2 阻力因子。

| 序号 | 物理量 | 单位 |
| --- | --- | --- |
| 0 | `rho` | kg/m³ |
| 1 | `mu` | Pa·s |
| 2 | `k_f` | W/(m·K) |
| 3 | `cp` | J/(kg·K) |
| 4 | `Pr` | 无量纲 |
| 5 | `Re` | 无量纲 |
| 6 | `Nu` | 无量纲 |
| 7 | `K_df` | m² |
| 8 | `cF_df` | 1/m |
| 9 | `dP_per_L` | Pa/m |
| 10 | `H_sf` | W/(m²·K) |
| 11 | `K_ff` | W/(m·K) |

`tpmshx_preparation_inlet_query_result_v1`（`abi_version = 1`、`struct_size = sizeof(tpmshx_preparation_inlet_query_result_v1)`）返回 12 个纯 `float64` 标量（`double values[12]`）。
该查询不创建所有者，无需释放调用。
可传入将缓存钩子置空且 `validate_grid_stage = 0` 的 `tpmshx_preparation_callbacks_v1`，以同步接收范围、通知和浮点事件。
独立 Python `tpms_calc.compute` 通过 `python/cpp_interface/inlet_properties.py` 调用此入口，并保留几何选择、共享缓存、逐次 `K_ss` 查询与警告策略。

## 空间几何总质量流量

Preparation ABI 3 为全部四个二维几何族（`uniform`、`continuous`、`zoned`、`sigmoid`）提供 `capacities`、`resolve_flow` 与 `prepare_case` 入口，并为条带提供返回逐条带 A 侧水力半径的 `tpmshx_preparation_2d_stripe_prepare_case_v1`：

- **均匀几何（`FlowInput2D`）**：支持两种拓扑与全部 16 组空气／水／sCO2／CO2 有序流体配对，以及 CFD 或符合条件的实验 D-F。
- **连续 XY 场（`ContinuousInput2D`）**：样条控制（`n_ctrl_x`、`n_ctrl_y`、1–3 阶、`symmetric_y`、边界及 mm 单位的 `L`/`t` 决策向量）在物理单元中心采样，返回孔隙率、比表面积、水力直径、流体导热率及完整局部 `(cross, stream)` K/cF 场。CFD 模式支持全部 16 组流体；实验模式支持 CO2/CO2 固定因子及上海 Gyroid 空气 A／水 B 连续迁移。
- **离散分区（`ZonedFlowInput2D`）**：支持 CFD 阻力下的空气／空气条带（`axis = 0` 或 `1`，按区间排序）与矩形（`axis = 2`，保留输入顺序）。先按横向物理宽度投影原始 `L`/`t` 再预测行 D-F；对设计孔隙率、固体导热率、流体导热率与体积换热场施加高斯滤波（`sigma = 2`、`radius = 8`、反射边界），原始热学几何不做平滑。
- **Sigmoid 场（`SigmoidFlowInput2D`）**：支持 CFD 阻力下的空气／空气 36 项交错 `L`/`t` 控制及进出口过渡参数，不做高斯滤波。`build_sigmoid_lut`（`tpmshx_preparation_sigmoid_lut_create_v7` / `release_v7`）从原始几何构建可复用的 41×31 原生 LUT（体素分辨率 256）。

总质量流量目标单位为 kg/s，且要求正的物理深度（m）；二维求解场仍保持单位深度基准。
`capacities` 积分入口设计孔隙率、开口分布、物理宽度、入口密度与物理深度，不评估过时速度或 Nu。
`resolve_flow` 用目标流量除以容量并校验解析后的速度；无目标时仅复制输入，不执行物理准备。
`prepare_case` 仅构造一次物理网格与几何，在换热计算前解析速度，并将前段流量证据（`flow.evidence`）与最终准备证据（`prepared`）分开保存。
`tpmshx_preparation_df_experiment_scope_v1` 为二维与三维准备共用，检查实验 D-F 布局资格与 HX 实验域匹配。
调用方必须为 `topology` 传入 0（Diamond）或 1（Gyroid）。
接口仅对这两个代码规定返回值的含义。

## 空间几何宿主缓存接口

所有二维与三维准备入口共用同一扁平回调结构 `tpmshx_preparation_callbacks_v1`（`stages.hpp` 中的 `PreparationCallbacks`）。
初始化时须设置 `abi_version = TPMSHX_PREPARATION_CASE_ABI_VERSION`（1）与 `struct_size = sizeof(tpmshx_preparation_callbacks_v1)`。

- **事件与观测钩子**：`event`、`observe_range` 与 `observe_notice` 在调用线程上同步报告诊断、范围记录及通知（含几何外推原因）。
- **宿主校验钩子**：`validate_host_input` 与 `validate_grid_stage`（`0` 或 `1`）保留 Python 对象检查顺序，不提供数值输出。`validate_grid_stage = 1` 要求 `validate_host_input` 非空。
- **缓存钩子（`action = 0` 查询，`action = 1` 发布）**：`geometry_cache`、`inlet_cache`、`geometry_cache_at`、`inlet_cache_at` 与 `sigmoid_lut_cache` 在宿主缓存间交换已完成值。命中（`hit = 1`）时宿主返回在阶段返回前保持有效的只读视图；未命中（`hit = 0`）时由 C++ 计算并在回调中发布只读视图，宿主须在回调返回前完成复制。
- **按准备族划分的钩子规则**：无键钩子（`geometry_cache`、`inlet_cache`）与带键钩子（`geometry_cache_at`、`inlet_cache_at`、`sigmoid_lut_cache`）不得混用。二维均匀与连续操作仅接受无键钩子；二维分区、sigmoid 与条带操作仅接受带键钩子。三维操作仅接受 `geometry_cache_at` 与 `inlet_cache_at`，并拒绝 `sigmoid_lut_cache` 与 `validate_grid_stage != 0`。
- **隔离规则**：回调不得执行数值准备，返回视图不得与输出、失败或错误缓冲区重叠。回调返回非零值立即中止阶段，便于 Python 重新抛出原异常。

`python/cpp_interface/preparation_host.py` 与 `native_preparation.py` 将这些钩子连接到 `python/physical_models/preparation_cache.py` 中 32,768 项几何缓存和 4,096 项入口物性缓存。
Python 保留 LUT 的内存与磁盘存储；缺表时 C++ 在体素分辨率 256 下构建 41×31 原生表。
[空间缓存示例](../examples/cpp/prepare_spatial_cache_2d.cpp)在 Python 之外测试了这组带类型回调。

## 既有偏移几何

非零水平集偏移（`delta_levelset != 0`）支持规定入口速度下的均匀空气／水配对，以及空气／空气均匀、条带、矩形与 sigmoid 模式。
连续场、CO2/sCO2 流体、实验 D-F 模型、容量查询和规定总质量流量均拒绝非零 `delta_levelset`。

当 `delta_levelset != 0` 时，N128 非对称几何核心计算 `split_a`，并填充 `thermal.have_side_geometry = 1` 与两组四元 `side_geometry` 元组：侧比表面积、侧水力直径及对应名义参考值。
名义热侧几何与设计孔隙率、固体导热率及单元热学场分开保存；阶段不会按分区分别计算新偏移模型。
[偏移几何示例](../examples/cpp/offset_2d.cpp)端到端准备、运行并评估均匀、条带、矩形和 sigmoid 偏移算例。

## 均匀三维准备

`preparation_case_3d_c_api.h` 提供两个扁平三维准备族，覆盖全部受支持的三维几何：

- **空间与均匀三维（`SpatialInput3D`、`tpmshx_preparation_3d_spatial_{capacities,resolve_flow,prepare_case}_v1`）**：`geometry_mode = 0` 准备均匀三维算例（两种拓扑、全部 16 组流体配对、CFD 或符合条件的实验 D-F）；`geometry_mode = 2` 准备带可选全局非零 `delta_levelset` 的 XY 网格矩形（空气／水 CFD 范围）。矩形使用域比例坐标，后项覆盖前项，未覆盖单元采用名义 `L`/`t`，在网格索引单位下对 `L`/`t` 施加高斯滤波后沿 z 延伸。
- **连续三维（`ContinuousInput3D`、`tpmshx_preparation_3d_continuous_{capacities,resolve_flow,prepare_case}_v1`）**：`have_ctrl_z = 0` 准备 XY 挤出控制；`have_ctrl_z = 1` 准备真 XYZ 控制（先全部 `L` 后全部 `t`，z 轴最快），在最终物理单元中心采样并支持可选 y 对称。

`CaseInput3D` 要求三个正物理长度、三个网格数（`Nz >= 2`）、两侧均含有效端口以及显式单元上限（C++ 默认 2,000,000 单元；接近该上限的内存检查与真实三维 BO 仍为独立验收门槛）。
宿主在调用 C++ 前解析配置与环境上限。
接口支持全部六个流向（`±x`、`±y`、`±z`）、全开口、局部端口、可选第二横向窗口、均匀网格与 `port_wall_refine` 网格。
物理场形状为 `(nx, ny, nz)` C 序，开口掩码为 `(cross1, cross2)` 序，每侧记录轴排列与反向标志而不翻转物理单元宽度。

准备输出的各侧孔隙率已完成拆分，调用方不得再次减半。
非零 `delta_levelset` 时，局部总孔隙率乘以各侧全局分流比，名义热侧／参考元组单独保存。
返回的 K/cF 场保持未缩放的 CFD 基准值，CO2 或实验应用因子单独记入侧证据。
容量查询按各侧实际入口孔隙率、开口面积与密度积分；完整定流量准备仅构造一次几何，解析速度后再执行速度与模型检查。
空气场标量范围观测每侧最多保留 8 个样本（原始通知、极值与末次采样），完整原始数组记录保留全部单元。
`python/preprocess/three_d/preparation.py` 从原生视图组装不可变 `CaseData`，再经 `preparation_host.py` 释放原生所有者。

## 运行续算

`stage_run_c_api.h` 将扁平的 `SavedCase2D`（`tpmshx_stage_saved_case_2d_v5`，ABI 5）与 `RunRequest2D`（`tpmshx_stage_run_request_2d_v4`）接入 `Full2DRun`。
调用任何二维保存态阶段入口前，先校验 `tpmshx_stage_run_2d_abi_version() == 5`。
`SavedCase2D` 借用已校验的准备视图、流场网格、设计场、模型引用、名义热侧元组和实验设置，不重复执行前处理。

- **一次性运行**：`tpmshx_run_saved_case_2d_v5` 在 C++ 内推进至结束并转移拥有的 `tpmshx_stage_run_result_2d_v1`（使用 `tpmshx_stage_run_2d_release_v1` 释放）。
- **分步与检查点生命周期**：`tpmshx_stage_run_2d_create_saved_v5`、`restore_saved_v5`、`advance_step_v1`、`finish_v1`、`phase_v1`、`snapshot_v1`、`take_result_v1` 与 `release_run_v1`。快照（`tpmshx_run_state_v1`，使用 `tpmshx_run_state_release_v1` 释放）拥有独立存储。恢复要求完全相同的构建、准备输入与数值控制；仅正值 `cpu_threads` 允许调整。
- **校验与捕获辅助**：`tpmshx_stage_borrow_mesh_v1` 校验并借用对齐的 `float64` 宽度与热学几何；`tpmshx_stage_port_windows_fit_2d_v1` 检查横向端口窗口；`tpmshx_stage_run_2d_check_experiment_v4` 检查实验 D-F 适用性；`tpmshx_stage_run_2d_get_capture_v1`（`capture_summary`）返回复制后的热学、Nu、热负荷与压力截断标量；`tpmshx_stage_run_2d_zone_temperatures_v1` 在不加载结果库的情况下汇总主网格分区温度。

`RunRequest2D` 中 `energy` 为空时默认选择 T-SOU 配方（`temperature_sou`，`1e-8 K`，来自 `model_parameters_v1.json`）。
可选能量控制不得与 `explicit_energy` 或启用的 `model_h` 控制同时设置。
取消返回状态 6 且不发布成功阶段结果；状态 4 表示求解器包线失败。

## 原生三维执行

`stage_run_3d_c_api.h` 将扁平的 `SavedCase3D`（`tpmshx_stage_saved_case_3d_v3`，ABI 3）与 `RunRequest3D`（`tpmshx_stage_run_request_3d_v1`）接入 `Full3DRun`。
调用任何三维保存态阶段入口前，先校验 `tpmshx_stage_run_3d_abi_version() == 3` 与 `tpmshx_stage_capture_3d_abi_version() == 2`。
`SavedCase3D` 在首步迭代前校验物理域长、轴映射、端口掩码、模型资源与单元设计场，不调用原始准备流程。

- **一次性运行**：`tpmshx_run_saved_case_3d_v3` 在 C++ 内推进至结束并转移拥有的 `tpmshx_stage_run_result_3d_v1`（使用 `tpmshx_stage_run_3d_release_v1` 释放）。
- **分步与检查点生命周期**：`tpmshx_stage_run_3d_create_saved_v3`、`restore_saved_v3`、`advance_step_v1`、`finish_v1`、`phase_v1`、`snapshot_v1`、`take_result_v1` 与 `release_run_v1`。安全检查点阶段为热学优先顺序中的 1、2、6、7、8、9、10。恢复要求同一构建、准备输入与数值控制；仅正值 `cpu_threads` 允许调整。
- **默认控制**：初次与热启动 SIMPLE 预算默认为 2,000 与 600，热学预算默认为 20,000。显式提供 SIMPLE 预算会同时覆盖两项流动预算（例如完整验证使用的 50,000）。Model-h 与 EOS 控制冲突在流动前被拒绝。
- **结果所有权与评估**：转移后的结果拥有 `raw`、通用 `evidence` 与 `evaluation`（`tpmshx_stage_input_v3`），可直接传入 `tpmshx_result_stage_query_v3`。最终 SIMPLE 场提供压力与显示，最后一次完成的热学状态提供质量、热学压力与能量（单位 W 与 kg/s）。`tpmshx_stage_run_3d_get_capture_v1`（`capture_summary(result, include_audit)`）返回单元数、热源和、压力截断数、Nu 统计及可选审计出口数组。
  显式传入 `include_audit` 时，请使用三维结果左值，并在使用 `audit_outlet` 数组视图期间保留结果的存储空间。
  临时三维结果须用单参数调用 `capture_summary(result)` 取得标量，即使显式传入 `false` 也会编译失败。

C 状态码含义为：0（结果已转移，不代表收敛）、1（输入无效）、2（水状态错误）、3（算术错误）与 4（原生失败）。
取消的结果保留 `raw.stop = 2` 的原始诊断，不包含完成的评估证据。
Python 完整三维执行通过 `python/cpp_interface/full_3d_stage.py` 独占绑定该生命周期。

## Quick Design 阶段

`quick_design_stage_c_api.h` 提供扁平 `float64` 布局的 Quick Design 准备 v2 与运行 v2 接口。
Quick Design 属于规定流量 LTNE 尺寸近似模式（`physical_validation=not_established`），并非 SIMPLE 求解。

### 准备 v2 与压降查询

`tpmshx_prepare_quick_design_v2` 与 `tpmshx_quick_pressure_fractions_v2` 接受 `tpmshx_quick_input_v2`（`abi_version = 2` 与精确 `struct_size`），包含 13 个 `float64` 标量槽位（`TPMSHX_QUICK_VALUE_COUNT`）：胞元尺寸（mm）、壁厚（mm）、宽度（m）、长度（m）、高度（m）、固体导热率（W/(m·K)）、容差、两路质量流量（kg/s）、两路温度（K）与两路压力（Pa(abs)）。
设置 `have_height = 0` 时以宽度替代高度。
文本字段（`topology`、`arrangement`、`property_mode`、`fluids[2]`）均带显式字节长度。
默认网格数（叉流 `(60, 40, 1)`、逆流 `(60, 1, 2)`）、导热率（`16 W/(m·K)`）、容差（`1e-5`）与几何分辨率（`128`）统一来自 `model_parameters_v1.json` 及生成的 C++ 常量。
未设置的逆流 `q_relative_tolerance` 与 `chunk_iterations` 保持缺省标记（C 中为 `0`，`CaseData` 中为 `None`）。

- 完整准备按原顺序执行热启动检查、标签检查、正数检查、形状、几何／材料、网格、入口物性、截面积、解析 D-F 压降分数与 SI 设计场生成。使用 `tpmshx_quick_prepared_release_v2` 释放 `tpmshx_quick_prepared_v2`。
- `tpmshx_quick_pressure_fractions_v2` 跳过热学网格与设计场数组，仅在该查询内将所有非 `cross` 布置按逆流截面处理，并按值返回 `tpmshx_quick_pressure_v2`（无需释放）。
- 两类输出均按计算顺序记录 `floating_events[4]`（A 物性、A 普朗特数、B 物性、B 普朗特数）及经验物性拟合 `ranges`。
- 可选的 `tpmshx_quick_callbacks_v2` 仅提供 `geometry_cache` 与 `eos_cache` 两个钩子（查询 `action = 0`，发布 `action = 1`；返回非零以状态 20 中止）。回调仅传输已完成值，不执行数值计算。

### 准备态执行与评估

`tpmshx_run_quick_design_v2` 在传入的准备场上执行定物性（一次扫描）或平均物性（两次扫描）热学迭代，并保持解析压降分数不变。
返回的 `tpmshx_quick_run_result_v1`（使用 `tpmshx_quick_run_release_v1` 释放）拥有全部 15 个场、物理网格宽度、压降证据、末次扫描标量及扫描范围记录（`tpmshx_quick_run_ranges_v2`）。
`tpmshx_quick_run_temperature_algorithm_v1` 返回实际执行的温度配方名。
取消返回状态 6 且不发布结果。
Python 在 `python/cpp_interface/_native_quick_prepare.py` 绑定准备，在 `python/cpp_interface/quick_design.py` 绑定运行，并通过 Result ABI 3（`tpmshx_result_stage_query_v3`）计算 Quick Design 指标。

## 安装的公共头文件

所有组件组合均安装下表中的头文件。默认安装位置为 `include/tpmshx/`。
可链接的库由所选组件决定。
若需目录内容与清单完全一致，请使用空的安装目录。重复使用同一目录时，CMake 会保留以前安装的文件。

<a id="sdk-public-headers"></a>

| 接口 | 头文件 |
| --- | --- |
| 阶段调用与运行状态 | `stages.hpp`、`stage_run_c_api.h`、`stage_run_3d_c_api.h`、`quick_design_stage_c_api.h`、`run_state_c_api.h` |
| 几何与网格 | `geometry_c_api.h`、`grid_c_api.h`、`zones_c_api.h`、`field_continuous_c_api.h`、`field_lut_c_api.h`、`field_sigmoid_c_api.h` |
| 工况准备与物性 | `preparation_c_api.h`、`preparation_case_c_api.h`、`preparation_case_3d_c_api.h`、`preparation_df_c_api.h`、`preparation_flow_c_api.h`、`property_c_api.h` |
| 求解器与流动 | `solver_c_api.h`、`full_2d_c_api.h`、`full_2d_run_c_api.h`、`full_3d_c_api.h`、`full_3d_run_c_api.h`、`simple_c_api_types.h`、`simple_2d_c_api.h`、`simple_3d_c_api.h` |
| 热学模型 | `thermal_c_api.h`、`enthalpy_driver_c_api.h`、`model_h_c_api.h`、`temperature_driver_c_api.h` |
| 物理与数值证据 | `closure_evidence_c_api.h`、`physical_ledger_c_api.h`、`property_sampling_c_api.h`、`temperature_evidence_c_api.h` |
| 结果评估 | `result_c_api.h`、`result_balance_c_api.h`、`result_checks_c_api.h`、`result_metrics_c_api.h`、`result_stage_c_api.h` |

## 构建、安装与 SDK 示例

根目录 CMake 工程使用已准备的本地依赖构建并安装阶段 SDK，不下载源码也不替换已发布的 Python 运行库。
先使用 `.venv-path` 中的解释器生成两份模型头文件：

```sh
"$PYTHON" -m engineering.scripts.generate_native_model_coefficients \
  --output .cache/stages-sdk/generated/tpmshx/model_coefficients.hpp \
  --df-output .cache/stages-sdk/generated/tpmshx/preparation_df_data.hpp
```

在 macOS 上使用锁定 CMake 配置、构建并安装（Windows 使用 `-A x64`，两个 CoolProp 参数均指向锁定的 `Release/CoolProp.lib`）：

```sh
"$CMAKE" -S . -B .cache/stages-sdk/build \
  -DTPMSHX_NATIVE_DEPS_ROOT="$PWD/.cache/native-deps" \
  -DTPMSHX_MODEL_INCLUDE_DIR="$PWD/.cache/stages-sdk/generated" \
  -DTPMSHX_PREPARATION_COOLPROP_LIBRARY="$PWD/.cache/native-deps/build/coolprop-preparation-macos-arm64/libCoolProp.a" \
  -DTPMSHX_SOLVER_COOLPROP_LIBRARY="$PWD/.cache/native-deps/build/coolprop-macos-arm64/libCoolProp.a" \
  -DCMAKE_INSTALL_PREFIX="$PWD/.cache/stages-sdk/install"
"$CMAKE" --build .cache/stages-sdk/build --config Release --parallel 1
"$CMAKE" --install .cache/stages-sdk/build --config Release
```

指定 `-DTPMSHX_COMPONENTS=result` 可单独构建结果 SDK（Linux x86_64 仅支持此组件）。
外部 C++ 工程通过 CMake 引入已安装包：

```cmake
find_package(tpmshx CONFIG REQUIRED COMPONENTS result)
target_link_libraries(my_program PRIVATE tpmshx::result)
```

构建并运行 `examples/cpp/` 下的安装后 SDK 示例（`air_2d.cpp`、`uniform_2d.cpp`、`continuous_2d.cpp`、`offset_2d.cpp`、`resume_2d.cpp`、`prepare_spatial_cache_2d.cpp`、`run_3d.cpp`、`prepare_continuous_3d.cpp`、`prepare_spatial_3d.cpp`、`quick_design.cpp`、`prepare_quick_design.cpp`、`result_client.cpp`）：

```sh
"$CMAKE" -S examples/cpp -B .cache/stages-sdk/examples \
  -DCMAKE_PREFIX_PATH="$PWD/.cache/stages-sdk/install"
"$CMAKE" --build .cache/stages-sdk/examples --config Release
"$CTEST" --test-dir .cache/stages-sdk/examples -C Release --output-on-failure --no-tests=error
```

完成依赖构建后，可运行自动化的源码树外 SDK 检查：

```sh
"$PYTHON" engineering/scripts/build_native_dependencies.py check-stages
```

BO 环境需附带对应的 `--python-lock`；Linux 需加上 `--component result --python-lock engineering/requirements/postprocess.txt`。
SDK 检查仅校验安装后的 C/C++ 接口；Python 集成、检查点恢复、单元上限附近内存检查、真实三维 BO 和桌面验收仍为独立门槛。
