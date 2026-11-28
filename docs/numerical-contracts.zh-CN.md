# SJTU-TPMSHX-TM1 数值与运行契约

[中文](numerical-contracts.zh-CN.md) | [English](numerical-contracts.md)

本页收录从[架构说明](architecture.zh-CN.md)移出的详细数值、运行、界面与物理契约。
简明系统地图、包名映射与跨目录 C++ 依赖边见[架构说明](architecture.zh-CN.md)。

<a id="retained-python-responsibilities"></a>

## Python 保留职责

Python 在 [python](../python/) 下负责公共 API、配置、不可变 DTO、文件 I/O、缓存、警告格式化及应用工作流。
数值代码保持不依赖 Qt；GUI 代码仅位于 `python/applications/gui/ui/` 和 `python/applications/gui/controllers/`。
导入分层检查将源码路径映射到各自依赖所有者并强制上述边界。

- **公共计算入口**：`compute`（[python/compute.py](../python/compute.py)）编排 `prepare_case`、`run_case` 与 `evaluate`，管理进度、取消、阶段耗时与警告。`applications/result_adapter.compute_result` 与 `to_compute_result` 为 GUI、CLI 和验证工具映射 `FieldResult` 与 `PerformanceResult`。
- **输入规范化与缓存**：`python/cpp_interface/` 按需加载四个原生库，将实数输入规范化为 `float64`、标签规范化为 `int32`，并发出固定的 `RuntimeWarning` 诊断。`python/physical_models/preparation_cache.py` 拥有 32,768 项几何缓存和 4,096 项入口物性缓存；材料导热率与 chi 永不缓存。
- **配置、I/O 与模型资源**：`python/data_types/` 拥有 `ComputeConfig`、`CaseData`、`FieldResult`、`PerformanceResult` 与 `metric_spec`。`python/file_io/` 拥有 YAML、HDF5、JSON、VTK 与检查点读写。`python/physical_models/` 与 `python/model_configs/` 拥有模型查询、`zone_units.py` 与带版本资源。
- **后处理与账本辅助**：`python/postprocess/result_math.py` 保留原始压降查询与公共 `compute_phase2a` 守恒证书。`python/solvers/physical_ledger.py` 保留注入账本的 `ports_complete` 检查。
- **应用与研究工具**：`python/applications/` 拥有 GUI、CLI、Quick Design 尺寸搜索、多工况 BO 及运行恢复。`python/preprocess/offline/` 与 `python/development/` 拥有显式离线拟合、验证与诊断工具。
- **兼容别名解析器（`python/shared.py`）**：在当前 `tm1` 包根下以零重复方式将 `tm1.shared.*` 与 `tm1.solvers.backends.cpp.*` 别名路径解析至规范模块所有者；仍使用旧包根的本地 `.cache/` 脚本需更新导入或使用记录的原源码版本。
- **独立测试参考实现**：纯公式参考实现（如 `tests/python/water_nu_reference.py`、`geometry_reference.py`、`preparation_flow_reference.py`）保留在 [tests/python](../tests/python/) 下，不包含在运行 wheel 中。

缺少原生库、ABI 不匹配或缺少现行符号时显式报错，不提供数值回退。

<a id="native-grids-and-design-fields"></a>

## 原生网格与设计场

几何库（`tpmshx_geometry_shared`）负责网格生成、物理端口、水平集单元几何与空间设计场。
构建路径与发布见[几何构建与交付](cpp-migration.zh-CN.md#native-geometry-core)，固定源码与 BSD 声明见 [fields-sources.md](../geometry/fields-sources.md)。

| 所有者 | 数值契约 |
| --- | --- |
| `grid.cpp`、`ports.cpp` | 均匀、对齐、壁面与端口宽度；GUI 自适应格数与三维建议；六方向轴映射；物理端口重叠与分布。 |
| `field_continuous.cpp`、`continuous/xy_fitpack.c` | 非退化 XY 样条，采用受限 SciPy 1.18.1 FITPACK 首次拟合（`s = 0`）路线。 |
| `continuous/tensor_spline.cpp` | XYZ 样条与单点 XY 轴，按 x、y、z 顺序执行一维拟合与采样。 |
| `field_sigmoid.cpp`、`field_lut.cpp` | 有序 sigmoid 混合、末段截断与线性 LUT 插值（不属于样条路线）。 |
| `zones.cpp` | 有序离散分区赋值，以及网格索引单位下的 `sigma = 2`、`radius = 8` 反射高斯滤波。 |

几何库导出 geometry ABI 2 与 field ABI 3，两者状态码各自独立：

| 协议 | 状态 1 | 状态 2 | 状态 3 |
| --- | --- | --- | --- |
| 几何、网格与分区（ABI 2） | 输入无效 | 定义域错误（`ZeroDivisionError`） | 运行时错误 |
| 连续样条、sigmoid 与 LUT（ABI 3） | 输入无效 | 分配失败（`MemoryError`） | 数值或运行时错误 |

- **水平集计数索引**：`geometry.cpp` 与 `asym_geometry.cpp` 构建精确的有序 `|phi|` 体素与暴露面计数索引（缓存两组拓扑／分辨率；`N = 128` 时占 32 MiB 索引加 16 MiB `phi` 网格）。标准对称场对 `L`/`t` 数组批量应用与标量相同的公式。固体导热率每次调用按显式 `chi`、`TPMSHX_CHI_S`、原生拟合的顺序解析。
- **连续场（`zones.axis = "continuous"`）**：接受 `x_decision`（先 `L` 控制点后 `t` 控制点，单位 mm）、`n_ctrl_x`、`n_ctrl_y`、可选 `n_ctrl_z`（仅三维；三维仅给 XY 时沿 z 挤出）、`symmetric_y`、`spline_order`（1–3）及位于 `L = 4..8 mm`、`t = 0.3..0.6 mm` 内的 `L_bounds` 与 `t_bounds`。样条在最终物理单元中心采样，不做高斯滤波。连续场要求对称通道（`delta = 0`）。双侧流体在 SIMPLE 坐标系下消费完整局部 K/cF 数组。
- **离散分区（`x`、`y`、`grid`）**：条带区间须为有限数并无间隙无重叠覆盖 `[0, 1]`（容差 `1e-9`）。二维条带与矩形先按横向宽度投影原始 `L`/`t` 再预测行 D-F，并对设计场做高斯滤波而保留原始热学几何。三维 XY 网格矩形分别平滑 `L` 与 `t` 后沿 z 延伸。
- **CO2 模型**：任一侧为 CO2 时由 `co2_segment2_v1.json` 为两侧提供公共对称几何。仅 CO2 侧施加固定因子 `K = K0 / 2.5`、`cF = 2.5 * cF0` 及 Nu 因子 `1.28`（含 Nu 下限），且不依赖 `df_mode`。独立入口计算对流体注册表解析为 `co2` 的所有名称使用相同的 CO2 几何和阻力因子。
- **规定总质量流量**：`preprocess.api.prepare_fixed_mass_flow_case` 与 `prepare_inlet_mass_capacities` 在物理开口上积分局部单侧孔隙率与归一化入口速度分布，乘以入口密度后用规定 `mass_flow_kg_s` 除以容量求入口速度。二维总流量输入需提供显式物理深度（m），求解场保持单位深度基准。

## 原生准备、求解与评估阶段

### 前处理与入口查询

`preprocess/preparation_case.cpp` 负责二维／三维工况准备（`tpmshx_preparation_2d_*_v1`、`tpmshx_preparation_3d_*_v1`）与标量入口查询（`tpmshx_query_inlet_properties_v2`）。
`python/cpp_interface/preparation_host.py` 在二维与三维间共享统一的 `tpmshx_preparation_callbacks_v1` 缓存传输、范围记录解码与 D-F 应用解码。
`tpmshx_preparation_df_experiment_scope_v1` 在二维／三维准备与静态 Python 预检间共享实验 D-F 布局与 HX 实验域检查。
详见[原生准备核心](cpp-migration.zh-CN.md#native-preparation-core)和[入口物性查询](native-stages.zh-CN.md#入口物性查询)。

### 完整二维、完整三维与 Quick Design 执行

Python 仅绑定保存态阶段生命周期：`full_2d_stage.py`（二维保存态 ABI 5）、`full_3d_stage.py`（三维保存态 ABI 3，捕获 ABI 2）和 `quick_design.py`（Quick Design 运行 v2）。
两个完整绑定均校验并借用对齐的 `float64` 工况数组（`tpmshx_stage_borrow_mesh_v1`），将未设置容差保持缺省由 C++ 从 `model_parameters_v1.json` 解析，并在原生释放前复制场、记录、执行视图与标量报告。

- **SIMPLE 流动（`Simple2DSolver`、`Simple3DSolver`）**：全部流体使用原生 F2 监控（连续动量、新密度局部／全局质量与零出口回流检查），显式 `convergence_mode = "legacy"` 被拒绝。动量面采用连续性方程的有符号质量通量；横向黏性面采用半格串联热阻式黏性通量。可选 `SolverConfig.simple_velocity_relaxation` 范围为 `(0, 1]`，默认二维 `0.7`、三维 `0.5`。
- **二维定密度 Anderson**：完整二维定密度侧使用 `simple_2d_fixed_density_anderson_v1`。提议计入原步数预算，仅当动量残差不增、两项质量门槛均通过且出口零回流时接受。
- **三维返回证书与粗网格引导**：三维在最后一次密度更新后重新闭合出口通量并复测全部四项 F2 门槛（末步不通过时记为 `post_closure`）。正式三维默认关闭粗网格引导；显式启用时由 `tpmshx_full_3d_get_bootstrap_trace_v1` 将逐层尺寸、上限与计费步数发布到 `diagnostics.coarse_bootstrap_trace`。
- **三维内部运行时所有者**：`full_3d.cpp` 划分 `FlowRun`、`ThermalRun`、`TransportProperties`、`RangeRecorder` 与 `SidePhysics`。入口压力下的原始输运物性仅在单元温度未变时复用（每采样侧每单元 48 字节）。
- **热学路线**：

| 路线 | 实现与适用范围 |
| --- | --- |
| 真焓（T-SOU） | 任一侧含 CO2 或 sCO2 的均匀／连续几何默认采用 `temperature_sou`。使用受保护 HEOS PT 更新、`0.6` 整块 Picard 阻尼与 SOU 配方 2 六样本 Anderson 提议。默认值：二维 `12000`（含水）／`5000`（其他）步，三维 `1500` 步，`5` 次扫描，`omega = 0.2`，`1e-8 K` 温度更新门，`0.001` 耦合与方程门。空气／水侧用积分 `h(T)`，CO2/sCO2 侧用 HEOS `h(T,P)`。完整三维每次 EOS 求解前执行零次温度扫描。 |
| 模型焓（model-h） | 空气／水积分 `h(T)` 输运，双侧采用有符号质量面、minmod SOU 与 `MODEL_H_RELAXATION = 0.2`。二维含无分区对称水／水；三维（`Nz > 1`）支持全部空气／水有序配对（水／水与非对称几何走严格边界契约）。两维共享加速块所有者（严格三维：5 扫描／块、16 Anderson 样本；其他调用：25 扫描／块、6 样本）。可选 `SolverConfig` 覆盖项（`model_h_max_iterations`、`model_h_temperature_tol_K`、`model_h_q_relative_tol`）同时作用于主／细网格调用。 |
| 严格 fullCC 温度 | 空气／水完整二维与完整三维 `Nz = 1`（`model_h_tface_sou_fou_strict_v3`）及完整三维 `Nz > 1`（`model_h_tface_sou_sou_strict_v3`）复用严格 model-h 驱动（完整边界账本比例 `<= 1e-7`）。见[共享有限体积使用方](cpp-migration.zh-CN.md#shared-finite-volume-temperature-consumers)。 |
| Quick Design | 规定流量 LTNE 尺寸近似（`quick_design_prepare_v2.cpp`、`quick_design_run.cpp`），保留固定解析入口压降分数、定物性单次或均物性两次扫描及每次扫描后的液态水检查。长度搜索（`solve_Lx`）仅接受冷启动收敛的可行候选。 |

- **结果评估（`postprocess/result_stage.cpp`）**：`python/postprocess/api.py` 将完整二维／三维与 Quick Design 的评估、适用性、物理平衡和资格查询全部路由至 `tpmshx_result_stage_query_v3`。后处理仅读取已记录证据，永不重跑求解器。

<a id="completed-execution-records"></a>

### 完整执行记录

已完成的完整求解写入 `metadata.execution_record`（`full_execution_v1`）、`input_resolution`（`prepared_input_v1`）、`property_sampling`（`full_sampling_v1`）、`model_h_iterations`（`model_h_iterations_v1`）与 `enthalpy_update_normalization`。
记录将各侧流动／换热资源与其能量关系（`eos_h_TP`、`integral_cp_T`、`capacity_temperature` 或 `prescribed_temperature`）分开，并区分末次热学状态标签与后更新最终流场状态标签。
`enthalpy_update_normalization` 按 `max(cp_in * abs(dT_in), 1 J/kg)` 独立归一化各流体焓更新，与焓零点无关。
历史结果文件保留其原始元数据，不被改写。

<a id="result-qualification-by-route"></a>

## 各路线的结果资格

执行完成、求解收敛、指标可用与优化准入是四个独立事实。
`run_case` 记录原生收敛结论；`evaluate` 判断已记录证据是否足以计算各指标。

| 路线 | 原生收敛与最终证据 | 额外使用方要求 |
| --- | --- | --- |
| 二维 model-h | SIMPLE、外耦合、主／细网格热学收敛与能量证书、Richardson 资格及压力包线。 | 多工况批次须同时具备物理边界账本及主／细门槛。`Q` 单位 W/m；总流量研究须提供显式深度。 |
| 三维 model-h | 最终 SIMPLE 检查、热学／外循环收敛、有限场及压力包线；无源热学过程还须通过严格能量门。 | 多工况批次独立复核 `compute_phase2a` 全局／单元、源项及边界证书。 |
| 二维／三维 true-h | 原生 T-SOU 求解，满足 `0.001` 方程／边界门、Kelvin 门与物性检查。热学证据与失败的末步流场后更新保持分离。 | 须检查 `true_h_balance` 与收敛细节；不属于空气／水 model-h 优化器契约。 |
| 原生完整计算 CC | 接受热学质量面上的严格 model-h，含积分 `h(T_face)` 对流与傅里叶功率，完整边界比例 `<= 1e-7`。 | `model_enthalpy_temperature_v1` 支持二维 W/m 或三维 W 捕获换热量；与生产 model-h 优化资格分开。 |
| 其他温度与研究路线 | 各自特定的停止规则、系数采样与记录状态。 | 定系数热容输运与交错／MAC 研究不继承 fullCC 积分焓资格。 |
| Quick Design | 显式规定流量尺寸近似模式。 | 其指标与可行性检查不证明完整 SIMPLE 求解有效。 |

二维 model-h 在换热量和温度变化稳定后触发非线性 A/B/固体单元平衡；各相最大单元残差相对平均单元换热量（下限 `1 W/m`）不得超过 `1%`。
无源三维 model-h 在稳定后触发严格证书（全局／单元最大残差与 LTNE 源不平衡相对 `max(abs(Q_sA), abs(Q_sB), 1 W)` 均不超过 `1%`）。
水侧首次 model-h 扫描至多 250 步即交还流动更新，若离开液态区则减半试步区间重试。
末次热学扫描未收敛时，外层场变化稳定不能判定外循环收敛。
独立物理适用范围见[能力范围](capabilities.md)、[模型适用性](model-resources.md)和[数据来源](data-catalog.md)。

## 物理平衡证据

完整结果在 `boundary_fluxes.energy`（`physical_heat_ledger_v1`）、`boundary_fluxes.temperature` 与 `boundary_fluxes.fine`（二维细网格）下保存物理热量审计。
记录保存外法向有符号对流与导热、源项积分、相残差（`RHS - diag * state`）、求解相标志及给定 B 侧热库功率（二维 W/m，三维 W）。
`postprocess.api.evaluate_physical_balance` 在不调用求解器或 EOS 的前提下计算质量入流／出流／散度、相残差范数、有符号外部功率及残差和与外部功率之差。
缺失或取消的证据保持不可用，读取器永不伪造零平衡。

<a id="captured-parameter-limits"></a>

## 捕获的参数范围

准备态工况在 `applicability_inputs` 中保存原始模型范围和入口样本；已完成的完整求解保存 `applicability_evidence_v1`。
保存态二维／三维运行在释放前复制原生适用性分组与必需记录，并将算例通知与运行期 `nu-evidence` 警告合并为 `scope_notes`。
三维空气场标量观测每侧最多保留 8 个样本（原始通知、极值与末次采样），完整原始数组记录保留全部单元。

`postprocess.api.evaluate_applicability(result)` 在不调用求解器或 EOS 的前提下检查入口与末次局部关联式输入（含下限截断前的 `Re`）：

- 对正原始范围 `[L, U]`，允许的参数区间为 `[0.9 * L, 1.1 * U]`。
- 任一样本超出该区间即判定范围检查失败（不按单元比例豁免）。
- 几何范围保持固定；水侧 HX 标定下限 `0.10 m/s` 允许至 `0.09 m/s`。
- 缺少必需证据返回 `unverified`；无证据旧文件返回 `unavailable`。

## 公共结果结论

`postprocess.api.evaluate` 将 `result_qualification_v1` 写入 `PerformanceResult.qualification`；`evaluate_qualification(result, metrics)` 可从保存证据独立复现。
执行、收敛（含主网格 `Ta`/`Tb`/`Ts` 及已记录细网格温度的有限性检查）、物理平衡、参数范围、指标可用性与设计准入各自独立记录状态。
`design` 结论要求全部已记录门槛通过；未解决的 sCO2 联合 P/T/Pr 与壁面加热／冷却覆盖缺口使 `model_scope` 与 `design` 保持 `unverified`。
独立的 `optimization` 结论允许在所有执行、收敛、物理、参数范围与指标门槛均通过时，仅延后已知的 sCO2 模型范围缺口。

<a id="persistent-interfaces-and-physical-state"></a>

## 持久化接口与物理状态

- **`CaseData`、`FieldResult`、`PerformanceResult`**：跨阶段契约的数组保持分离且只读；仅更新元数据时可共享连续只读字节缓冲并创建独立数组头。`data_types.metric_spec` 在 JSON、GUI 与多工况聚合间强制指标族、单位与定义版本一致。
- **显示契约（`postprocess.result_display`）**：无 Qt 依赖的数据模块，拥有场单位、坐标轴、二维显示别名、分区统计、外推水印格式化以及 `RESULT_FIELD_SPECS`（规范标量键、物理量、相、符号、存储／显示单位及默认色阶：温度 `coolwarm`、速度与压力 `viridis`、几何设计 `turbo`）。温度与压力别名保留原始单元值；三维显示别名共享不可变缓冲。绝对压力场在 GUI 显示边界由 Pa 换算为 kPa，同时保持 ΔP、原始数组与导出键不变。
- **公共热学与压降定义**：完整热学指标采用 `native_boundary_v1`（`Q` 为主网格 `abs(Q_A)`，`Q_A`/`Q_B` 为有符号放热量，出口温度按质量通量加权，二维 Richardson 换热量另记为 `Q_richardson_A/B`）。完整压降采用 `pressure_face_v1`（最终 SIMPLE 压力外推至物理进出口面并按几何开口面积加权）。
- **空气入口压力打靶（`numerics/pressure_reference.cpp`）**：以有界 `P^2` 更新迭代出口单元基准，直至物理入口开口面积平均压力与 `P_in` 相对误差不超过 `1e-4`。显式 `p_in_shooting = False` / `TPMSHX_P_IN_SHOOT = 0` 仅为诊断开关，不能证明收敛。不可压路线直接将物理入口面开口面积平均锚定到 `P_in`。
- **二维入口分布（`PartialBCConfig.uniform_inlet_2d`）**：采用无历史四格过渡的几何重叠分布。桌面端固定为 `True`；脚本 API 设为 `False` 时保留历史过渡分布。

<a id="native-3d-continuation"></a>

## 原生二维与三维续算

`Full2DRun.advance_step` 与 `Full3DRun.advance_step` 经由 `full_run_state.cpp` 的共享带类型归档（原生状态格式 2）暴露 SIMPLE、热学与控制器内层安全边界。
快照覆盖初始与后更新 SIMPLE 调用、model-h 选择（含 Anderson 历史与水启动重试）、温度块、EOS Picard 迭代及二维细化网格。
恢复按原输入重建派生矩阵与视图而不重复已计费迭代，要求完全相同的原生构建、平台、准备输入与数值控制。

- **CPU 线程上限（`RunControl.cpu_threads`）**：仅作用于运行期的可选上限（原生默认最多 8 逻辑 CPU），恢复时允许更改。供 T-SOU 并行 EOS 计算与双流体扫描、三维 model-h 波前线扫描及成对二维 SIMPLE 工作线程使用（设为 `1` 时串行化），并记录于 `runtime_resources`。
- **检查点与恢复**：`SolverCheckpoint`（`full_2d_continuation_v1` / `full_3d_continuation_v1`）通过 `python/file_io/solver_checkpoint_io.py` 原子写入。`applications.execution.recovery` 管理运行目录、固定快照硬链接共享（`file_io.file_snapshot`）、`PausedRun`（CLI Ctrl+C 退出码 3；GUI 60 秒间隔）及后处理失败时的 `failed-result.h5` 保留。

<a id="cooperative-cancellation"></a>

### 合作式取消

完整原生入口在打包输入或加载原生库前先检查取消状态（`run_control.cancellation.CancelledError`）。
二维在每步 SIMPLE 与 LTNE 块（含 Richardson）轮询；三维在每步 SIMPLE、动量／压力子步与 LTNE 块轮询；T-SOU 在每次 Picard 迭代轮询。
进行中的线性求解或计算块完成后返回；不强制终止线程，取消的运行不发布结果。

### 多工况批次与贝叶斯优化

`applications.optimization.multi_condition` 通过 `compute_prepared_run`（60 秒检查点）评估有序工况批次，并由 `resume_condition_batch` 恢复至新目录。
优化器使用 `evaluate_compact_condition_batch`：返回紧凑摘要，并在原目录内继续已保存的批次；复用已完成成员，保留失败成员且不重新运行。
默认 `workers = None` 最多启动 4 个原生工作进程，每进程至少分配 2 个 CPU 槽位，平分总 CPU 上限并保持输入顺序与单管理进程暂停／取消控制。
正常并行求解期间，若工作进程意外退出，父进程会把批次记为失败，并抛出 `BrokenProcessPool`。
最近一次完整写入的检查点仍可读取。若进程池拒绝某个工况的提交请求，父进程会把该工况记为 `failed`。
在新批次中，父进程始终未选中的工况保持 `not_run`。
在原目录内续算时，若父进程始终未选中已保存为 `paused` 的工况，该工况保持 `paused`。
批次只使用 1 个工作进程时（例如只有 1 个 CPU 槽位时），调用进程按输入顺序逐个运行工况，不创建管理进程。
`run_multi_condition_optimization` 支持 `qLogNEHVI`、`qLogNParEGO` 与 `Sobol` 基于完整合格批次最大化 `(heat_gain_percent, -pressure_ratio)`，或使用 `qLogNEI` 与 `Sobol` 结合 `mass_requirements`（含可选逐工况 `T_out`/`P_out` 限制与 `allow_nu_re_extrapolation`）执行约束最小芯体质量优化。
`resume_multi_condition_optimization` 将原归档复制到新目录并校验 `optimization-input.json`、Sobol 序列与已保存提议后继续。
nTop CSV 导出写出 XY 或 XYZ 坐标及完整控制点来源。

<a id="ui-structure"></a>

## UI 结构

- **用户存储与启动**：`python/applications/gui/controllers/user_storage.py` 使用临时文件原子替换在平台用户目录保存偏好、会话与历史。`python/applications/gui/main.py` 在导入 Matplotlib 前配置可写缓存。已有会话恢复完整输入快照；上海默认配置仅用于新建工作区。
- **预检与退役设置**：点击计算前先捕获一份 `ComputeConfig` 供网格预检、速度建议、三维规模确认与后台工作线程共用。预检与前处理共享 `python/physical_models/grid.py`。已退役的 `wall_refine_3d`（额外六壁面加层）在开启时拒绝新前处理；`ComputeConfig.from_dict(..., prepared_grid=True)` 用于重放、续算与几何导出（见[退役记录](history/README.md#six-wall-grid-retirement)）。已保存的多边形预设被拒绝。
- **预设与局部导入**：复制为 Python、可复现链接、菜单载入与拖放共用同一预设解码器。未包装的 `line_edits` 与旧扁平配置仅将提供字段合入当前捕获输入后再做跨字段校验。
- **工作台模块**：`builders_canvas.py` 组装工作台；`workbench.py` 负责标签页路由；`panel_vis_3d.py`（配合 `volume_toolbar.py` 与 `volume_overlays.py`）负责 PyVista 三维渲染（单元中心加边界点、默认外表面、三正交截面、体渲染不透明度、悬浮色标卡与端口标签，以及供 `result_export.py` 复制与保存共用的单一合成捕获）；`background_tasks.py` 在工作台拥有的单个 QThread 中准备三维模块，同时将控件／Matplotlib／OpenGL 保留在 GUI 线程；`field_factory.py` 负责数值标签；`fmt.py` 格式化资格原因；`typography.py` 选择系统无衬线 Qt 字体与出版级 Matplotlib/VTK 字体。
- **结果缓存与导出**：`ResultCache` 为当前维度持有一份已发布的 `ComputeResult`；失败或取消的尝试保留先前已接受结果。三维 NPZ 导出包含温度（K）、速度分量与幅值（m/s）、显示压力 `P_fA`/`P_fB`（Pa）、`L_mm`/`t_mm`（mm）、`dx`/`dy`/`dz`（m）及历史别名 `vmag`/`P_kPa`。
- **可恢复验证 CLI**：`development.validation.cases.validate_sco2_exp_q` 冻结所选成员，每成员完成后原子发布 `partial.csv` 与 `state.json`，支持基于一致已验证输入的 `--resume-run`，取消时返回退出码 130。

<a id="physical-invariants"></a>

## 物理不变量

仅在明确修订物理模型并完成直接验证时才可修改以下约束：

1. **可压空气**：空气走理想气体密度路径，不得替换为定密度或等温近似。
2. **孔隙率只拆分一次**：对称调用传入总孔隙率，由求解器形成双半孔隙率通道。非零 `delta_levelset` 时由 `preprocess/preparation_case.cpp` 计算总和等于总孔隙率的 `eps_A` 与 `eps_B`，内核不得再次减半。流体有效导热率为 `K_ff_i = eps_i * k_i`（对称时为 `eps_total/2 * k_i`，偏移因子 `2 * split_i` 只乘一次）。
3. **质量通量入口**：二维与三维可压空气均采用质量通量入口；求解速度均为孔隙内速度而非表观速度。
4. **Darcy-Forchheimer 归属**：`physical_models.df_surrogate.predict.predict_K_cF()` 保持纯几何基准（水+sCO2 CFD 在 `4..8 mm` × `0.3..0.6 mm` 的双线性插值，不依赖 Re 或流体）。生产模式仅暴露 **CFD 光滑壁**（通用默认）与 **实验标定**（SIMPLE 前每侧施加一次已评审固定因子）。显式选择已退役的 `gamma_df` 与 `rbf` 模式直接报错（见[历史模型索引](history/legacy-models.md)）。
5. **Nusselt 归属**：完整计算在 [fluid_nusselt_ratio](../numerics/fluid_properties.cpp#L171) 与 [nu_point](../numerics/fluid_properties.cpp#L364) 计算 Nu，由 [nu_correlations.py](../python/physical_models/nu_correlations.py) 封装。`python/model_configs/sco2_effective_nu.json`（`sco2_effective_nu_config()`）是 sCO2 有效 Nu 的唯一资源（`alpha_D`/`alpha_G` 作为总 `Ceff` 在 Nu 下限前应用一次，见[模型资源](model-resources.md#sco2-有效-nu-系数)）。[二维](../solver/full_2d.cpp#L539)与[三维](../solver/full_3d.cpp#L877)求解器均按单元中心孔隙速度幅值 `sqrt(uc^2 + vc^2 [+ wc^2])` 计算局部 Re 与 Nu。
6. **可压包线**：`python/physical_models/envelope.py` 拒绝非有限状态、压力 `<= 1000 Pa` 与 `Mach >= 1`。正压亚声速场还须满足入口压力门方可收敛。
7. **压力基准**：理想气体侧由 `P_ref_abs` 锚定出口单元，局部绝对压力为 `P_ref_abs + P`。入口压力修正与诊断统一采用物理端口面的几何开口面积平均。
8. **单位**：准备契约统一使用 K、Pa 与 m；接受 mm 的闭合调用在边界显式换算，不改变持久化 SI 场。
9. **端口边界**：二维支持 `±x`/`±y`，三维增加 `±z`。非开口外表面为静止无滑移壁面并施加半格黏性壁面通量（三维含 `z±`）。主网格与交错开口分数直接由实际网格上的原始矩形重叠计算。
10. **真焓归属**：任一侧含 CO2 或 sCO2 的配对均走保守 T-SOU，使用有符号交错面质量通量与边界焓热负荷。sCO2 在入口和局部状态均受 **280–700 K、7.9–16 MPa 绝对压力**约束。默认关闭的研究开关 `TPMSHX_SCO2_COMPRESSIBLE` 仅在三维 A 侧启用局部压力物性更新，不构成双侧可压模型验收。
11. **当前 TM1 限制**：CO2 与 sCO2 拒绝离散分区与非零 `delta_levelset`，支持对称连续场。`Nz > 1` 时端部单元在入口开口面施加 `T_in` 与半格导热，在出口施加零梯度。
12. **实验修正适用范围**：空气芯体试件标定覆盖 `L = 6..8 mm`、`t = 0.3..0.5 mm`。整机 HX 有效修正（`7/0.6 mm`、`0.182 x 0.042 x 0.042 m`、`delta = 0`、固定 `K = K0`）使用冻结 `sF`：sCO2 为 `6.313005350332494`（D）／`7.608907691857889`（G）；水为 `4.8928`（D，RMSRE 6.84%）／`4.1989`（G，RMSRE 0.93%，`u >= 0.10 m/s` 拟合）；空气为 `1.8024228153853061`（D）／`2.649010286988306`（G，实验批次 `shanghai-air-straight-20260401-v1`，运行期标定窗 `8.027855328062564..22.446874107951544 m/s`）。批准应用速度窗（`hx_application_velocity_bounds()`，D/G，m/s）：水 `0.0139648..0.254055`／`0.0162341..0.225876`；空气 `3.88324..22.7599`／`3.91282..24.5467`；sCO2 `0.434925..2.53961`／`0.381408..2.47046`。超出标定窗时发出运行期外推通知。详见[模型资源](model-resources.md)。

<a id="local-data"></a>

## 本地数据

原始实验与 CFD 数据置于 Git 之外的 `data/raw_data/`：

```text
data/raw_data/
├── experiments/{air,water_air,sco2}/
├── cfd/
│   ├── water/
│   └── sco2/{Diamond,Gyroid}/
├── archive/{co2,water_air,sco2}/
└── plans/water/
```

不得在不更新对应加载器注册表与调用测试的情况下重命名数据目录或工作簿。
文件名映射与水压降约定见[数据目录](data-catalog.md)。
