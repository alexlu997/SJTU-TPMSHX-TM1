# compute-contracts Specification

> 历史范围：以下汇总 V2 拆分时的契约和验收要求。TM1 当前模块归属与入口见
> [架构说明](../../../docs/architecture.md)。原 `stages_2d`、`stages_3d`、
> `_stage_common` 转导出面已在消费者迁移后退役；下面的原拆分记录保留。

## Purpose
计算契约（`ComputeConfig` 族 / `ComputeResult`）的归属层与 import 方向约束：契约在 `domain/`，窗口采集在 `ui/window_config.py`，controllers 只留编排/状态。来自 openspec archive `2026-07-02-contracts-layer`（架构扫描批次 A）。
## Requirements
### Requirement: Contracts live below every consumer
计算契约（`ComputeConfig` 族 dataclass、`bc_to_dict` 等纯函数、`ComputeResult`）SHALL 位于 `domain/`（`compute_config.py` / `compute_result.py`），SHALL NOT import Qt、ui、controllers、pipelines 中任何一个。`controllers/`、`pipelines/`、`validation/`、`optimization/`、`ui/` SHALL 从 `domain` import 契约。

#### Scenario: Pipelines importable without controllers
- **WHEN** 在干净解释器中 `import pipelines.stages_2d` 与 `import pipelines.stages_3d`
- **THEN** 成功，且 `sys.modules` 不含 `controllers.*`

#### Scenario: Contracts are Qt-free
- **WHEN** 静态扫描 `domain/` 的 import
- **THEN** 无 PySide/PyQt/ui/controllers/pipelines 引用

### Requirement: Controllers keep only window-harvest logic, with no ui imports
`controllers/compute_config.py` SHALL 仅保留读取窗口控件、组装契约对象的采集函数；其对 `ui.zone_table.build_zone_config` 的依赖 SHALL 改为调用方注入（callable 参数），controllers SHALL NOT import ui。`theme_manager` SHALL 移入 `ui/`。

#### Scenario: No upward imports from controllers
- **WHEN** grep `controllers/` 的 import（含函数内）
- **THEN** 无 `from ui`/`import ui` 命中

### Requirement: Cycle-breaking deferred imports eliminated
拆分落地后，`pipelines/stages_2d.py`、`pipelines/stages_3d.py`、`controllers/compute_pipeline.py` 中仅为打破 controllers↔pipelines 环而放进函数体的 import SHALL 提升为模块顶层；保留的函数内 import SHALL 各带一行懒加载理由注释（重库/可选依赖）。

#### Scenario: Remaining deferred imports are annotated
- **WHEN** 审查上述三个模块的函数内 import
- **THEN** 每处要么已提升，要么紧邻注释说明懒加载理由

### Requirement: Behavior-preservation gates
本 change SHALL 通过：golden 2D 与 3D `--check` bit-identical（PYTHONHASHSEED=0）、全量 pytest 0 failed、CI 绿、离屏 UI 冒烟（runs/smokes）通过。SHALL 为单 commit 原子落地。

#### Scenario: Golden gates hold
- **WHEN** 搬移与 import 更新完成后运行两个 golden `--check`
- **THEN** 均 PASS (bit-identical)

### Requirement: Shared stage scaffolding single source
2D/3D 管线的非内核胶水 SHALL 单一来源于 `pipelines/_stage_common.py`：域尺寸单位滑移防火墙（`validate_domain_dims`，>10 m 抛 ValueError）、双侧代理训练域守卫（`surrogate_extrap_reasons`：ImportError → 跳过返回 []，ValueError 上抛）、headline 标量守卫（`safe_float`：None/非数 → nan）、props 槽几何三元组（`geometry_props`）。stages_2d 与 stages_3d SHALL NOT 各自持有这些逻辑的副本。数值内核 SHALL 保持每维独立（统一已被否决）。

#### Scenario: Unit-slip rejected identically in 2D and 3D
- **WHEN** L_dom_m=182.0（把 mm 值误填进米字段）进入任一维度的 parse
- **THEN** 抛 ValueError，消息含 "exceeds" 与 "unit slip"

#### Scenario: Broken extrap guard fails loudly (2D hush removed)
- **WHEN** 代理域检查内部抛 AttributeError
- **THEN** 异常向上传播（不再被 2D 静默吞掉禁用外推警告）

#### Scenario: None headline does not crash 2D finalize
- **WHEN** raw['Q_total'] 为显式 None
- **THEN** ComputeResult.Q_W == nan（而非 TypeError）

#### Scenario: Golden gates bit-identical
- **WHEN** `_golden_2d.py --check` / `_golden_3d.py --check`（PYTHONHASHSEED=0）在本变更前后各跑一次
- **THEN** 四次全部 PASS (bit-identical)

### Requirement: No silent degradation in solver-side exception fallbacks
求解侧（solvers/pipelines/controllers/optimization 生产路径）的异常兜底 SHALL NOT 静默：物理量降级兜底（质量加权 → 朴素均值、ṁ→0、GP 未拟合继续）SHALL 发 warning；仅预期异常 SHALL 用窄类型捕获（如属性缺失 → AttributeError）；确属设计的 broad except（stdout tee、JIT warmup、LUT 缓存回退、UI 进度回调守卫）SHALL 带注释说明理由。UI 层 best-effort（会话恢复等）不在此约束内。

#### Scenario: Flux-weighting failure is loud
- **WHEN** `_face_flux_weights` 在 `_mass_weighted_T_out` 内抛异常
- **THEN** 返回朴素均值兜底且发 UserWarning（含失败原因与"T_out/Q degraded"）

#### Scenario: Production GP fit failure warns
- **WHEN** `fit_gpytorch_mll` 抛异常且 verbose=False
- **THEN** 发 warning（不再静默继续未拟合 GP）

#### Scenario: Golden unchanged
- **WHEN** 金档 2D/3D --check 在本变更后运行
- **THEN** PASS (bit-identical)

### Requirement: Central logging with GUI-capture-safe stdout handler
生产包（solvers/pipelines/controllers/df_surrogate/optimization/core/ui 库路径）的运行时输出 SHALL 走 `logutil.get_logger`（`tpmshx` 根 logger）。Handler SHALL 逐条解析当前 `sys.stdout`（非创建时绑定）——保证 `compute_orchestrator` 的 `redirect_stdout` 求解日志捕获不丢日志。默认渲染 SHALL 为裸消息（与旧 print 字节兼容）；`TPMSHX_LOG_TS=1` SHALL 加时间戳前缀；`TPMSHX_LOG_LEVEL` SHALL 控制级别（默认 INFO）。@njit 内与 CLI/`__main__` 路径的 print SHALL 保留。既有 `verbose` 门语义 SHALL 不变（logging 级别在其上叠加过滤，不替代）。

#### Scenario: Solve-log viewer still captures solver output
- **WHEN** GUI 跑一次 compute（orchestrator redirect_stdout 捕获）
- **THEN** 日志缓冲含转换后的 logger 输出（如 "[3D grid]" 行）

#### Scenario: Default output unchanged
- **WHEN** 未设任何 TPMSHX_LOG_* 环境变量跑一次求解
- **THEN** stdout 逐行字符串与转换前 print 输出一致

#### Scenario: Level filter works
- **WHEN** `TPMSHX_LOG_LEVEL=ERROR` 下跑求解
- **THEN** info 级求解 chatter 不出现

### Requirement: Pipelines module layout — cfg boundary vs engine
2D/3D 计算管线 SHALL 按职责分模块：`stages_2d`/`stages_3d` 只保留 cfg 边界（parse/build/run_cfg/finalize）并 SHALL 全量 re-export 迁出符号（外部 import 面零变更）；引擎与后处理住 `solve_2d`（2D 外循环 + Q/压力后处理）、`run_stack_3d`（3D 核心循环 `_run_3d_stack` + 守恒诊断 + 并行/剖析助手）、`flux_3d`（面通量加权 + 粗糙度施加）、`grid_3d`（轴映射/分区场/网格构建）。依赖方向 SHALL 保持 DAG：flux_3d/grid_3d ← run_stack_3d ← stages_3d；solve_2d ← stages_2d；引擎模块 SHALL NOT 反向 import stages_*。拆分 SHALL 为逐字搬移（浮点运算顺序不变）。

#### Scenario: External import surface unchanged
- **WHEN** 任一既有消费方执行 `from pipelines.stages_3d import _run_3d_stack`（或 tests 里的其余 ~15 个内部名）
- **THEN** import 成功且解析到迁移后的实现

#### Scenario: Golden bit-identical across the split
- **WHEN** 金档 2D/3D --check 在拆分后运行（PYTHONHASHSEED=0）
- **THEN** PASS (bit-identical)

#### Scenario: No cycles
- **WHEN** 运行 test_import_dag（或直接 import 各引擎模块）
- **THEN** 无循环 import 错误

### Requirement: Solver kernel modules split from driver layer
numba 内核 SHALL 与 Python 驱动层分模块：`solvers/_kernels_simple_2d.py`（2D SIMPLE 内核 + 压力泊松装配）、`solvers/_kernels_simple_3d.py`（3D SIMPLE 内核）、`solvers/_kernels_ltne_3d.py`（3D LTNE 内核，inline='always' 助手与调用者同模块）。原模块（simple_solver / simple_solver_3d / ltne_energy_3d）SHALL 保留求解器类、网格构建器、Python 驱动与 warmup，并全量 re-export 迁出内核名（外部 import 面零变更）。拆分 SHALL 为逐字搬移；ε-split 契约文本 SHALL NOT 有任何改动。

#### Scenario: Kernel import surface unchanged
- **WHEN** 测试执行 `from solvers.simple_solver import _sweep_u_jit_df`（或其余内核直连 import）
- **THEN** import 成功且行为与拆分前一致

#### Scenario: Golden bit-identical across the kernel split
- **WHEN** 金档 2D/3D --check 在拆分后运行（PYTHONHASHSEED=0）
- **THEN** PASS (bit-identical)

#### Scenario: Warmup still compiles cross-module
- **WHEN** `import solvers.ltne_energy_3d`（模块级 _warmup_jit() 触发）
- **THEN** 无异常（跨模块 JIT 编译成立）

### Requirement: Finite-positive input gates at every boundary
非有限（NaN/inf）或非正的物理标量 SHALL 在三个咽喉被拒：窗口 strict 校验（`_validate_required_widgets`，temp 类字段原文可为负 °C、只查有限性）、字段 blur 校验（"Must be finite"）、`ComputeConfig.validate()`（`from_dict`/`from_json` 必经；直接构造保持宽松供测试用）。`validate_geometry` SHALL 接入 `_preflight_grid` 运行路径（硬错弹窗阻断、软警合并进预检报告）。

#### Scenario: NaN rejected at the script boundary
- **WHEN** `ComputeConfig.from_json` 读入含 `NaN` 的 JSON
- **THEN** 抛 ValueError（不再静默进入求解器）

#### Scenario: Negative Celsius still accepted
- **WHEN** °C 模式下 T_in 原文为 "-10"
- **THEN** 窗口 strict 校验通过（开尔文正性由 validate() 把关）

### Requirement: First-class convergence verdict
`ComputeResult` SHALL 携带 `converged: bool`：2D = 外耦合收敛且无 SIMPLE 停滞；3D = 无 SIMPLE 停滞且最后一轮 LTNE 达标（早期外迭代打满帽不算失败）。False 时 UI SHALL 前置用户警告并在诊断摘要标注"否（结果仅供参考）"。

#### Scenario: Diverged solve is visibly flagged
- **WHEN** raw['solver_converged']=False 的结果进入 write_result
- **THEN** result.warnings 首条为未收敛提示，诊断摘要含"收敛: 否"

### Requirement: 3D cell cap on every path
`_run_3d_stack` SHALL 在网格单元数超过上限（默认 2,000,000；`TPMSHX_MAX_CELLS_3D` 或 `cfg['max_cells_3d']` 显式放宽）时抛 ValueError（含 RAM 估算），使脚本/优化器路径与 UI 同受保护；UI 大网格对话框 SHALL 显示工作内存估算。

#### Scenario: Script path blocked before allocation
- **WHEN** cap=1000 下以 2000 单元 cfg 调 `_run_3d_stack`
- **THEN** 求解前抛 ValueError（消息含 "cell cap"）

### Requirement: Corrupt persistence quarantined
损坏的会话/预设 JSON SHALL 被重命名为 `<name>.corrupt-<ts>`（best-effort）而非静默回退默认并被下次保存覆盖。

#### Scenario: Corrupt session recoverable
- **WHEN** `.last_session.json` 内容非法 JSON 且调用 load_session
- **THEN** 返回 None 且目录中出现 `.corrupt-*` 隔离文件

### Requirement: First-wave performance levers stay bit-identical
以下性能改动 SHALL 保持金档 2D/3D 位相同：几何缓存扩容（`_compute_raw` lru ≥2048、`compute_geometry` lru ≥4096——纯缓存容量，命中值不变）；`_build_hv_local_2d` 均匀路径向量化（逐元素镜像 3D perf-B1 变换：Re 预下限 1.0、Nu 后下限、ε_f=ε/2）；2D A/B 两股 SIMPLE 求解并行（独立求解器、无共享写状态，仅墙钟变化）；BO loky worker 线程数 = cores//n_jobs（默认路径 n_jobs=1 不受影响）。会改变迭代轨迹或浮点次序的深层优化（2D 温启动、PP-AMG、并行门默认值、3D 外迭代重解并行、RB 2D 能量）SHALL 记录为显式的重基线决策，不混入本批。

#### Scenario: Golden bit-identical after wave 1
- **WHEN** 金档 2D/3D --check 在本变更后运行（PYTHONHASHSEED=0）
- **THEN** PASS (bit-identical)

#### Scenario: Threaded 2D A/B produces the sequential result
- **WHEN** 同一 cfg 在并行 A/B 下求解
- **THEN** 全部输出场与串行版本位相同（金档即证）

#### Scenario: Cache growth changes no values
- **WHEN** 相同 (tpms, L, t) 查询命中扩容后的缓存
- **THEN** 返回值与未缓存计算一致（lru 语义）
