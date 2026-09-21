# 退役工程、试验与工具索引

各节注明各自的历史提交与现行承接。

2026-09-12 按用户确认将已结束的工程、M1/M2 固定试验及历史资料移出当前树。
原文件固定保存在已合并提交 [b1af7ed](https://github.com/alexlu997/SJTU-TPMSHX-TM1/commit/b1af7edcea5796aa955aa8fae1785be3c1b57e1d)，
原数值、失败、被否原因及未实施事项不改写。常规设计/优化与现行验证继续保留。

第一批移出 141 个文件；D76 现行 Nu 验证另迁入
[validation/cases/validate_sco2_d76.py](../../sjtu_tpmshx/validation/cases/validate_sco2_d76.py)，
保留六个工况、表头校验、15% 门槛和原退出语义。原工程脚本中的旧
`SCO2_CF_SCALE=3.39` 不移入现行计算链。

| 原路径 | 文件数 | 固定历史入口 |
| --- | ---: | --- |
| `projects/703-sCO2-D76/` | 9 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/projects/703-sCO2-D76/) |
| `projects/704-Aircooler-10kW/` | 3 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/projects/704-Aircooler-10kW/) |
| `projects/624-Retrodict/` | 2 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/projects/624-Retrodict/) |
| `reports/m1_uniform_vs_graded/` | 98 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/reports/m1_uniform_vs_graded/) |
| `openspec/changes/df-coeffs-cfd-refit/` | 3 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/openspec/changes/df-coeffs-cfd-refit/) |
| `openspec/changes/a2-3d-physical-g/` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/openspec/changes/a2-3d-physical-g/) |
| `openspec/changes/evaluator-envelope-authority/` | 3 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/openspec/changes/evaluator-envelope-authority/) |
| `reports/shanghai-validation/` | 2 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/reports/shanghai-validation/) |
| `reports/solver-efficiency-r1-r4/` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/reports/solver-efficiency-r1-r4/) |
| `benchmarks/archive/benchmark_a.py` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/benchmarks/archive/benchmark_a.py) |
| `benchmarks/benchmark_snapshot_a.md` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/benchmarks/benchmark_snapshot_a.md) |
| `benchmarks/benchmark_snapshot_b.md` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/benchmarks/benchmark_snapshot_b.md) |
| `constraints-devbox-2026-07-11.txt` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/constraints-devbox-2026-07-11.txt) |
| `docs/ARCHITECTURE-AUDIT-2026-07.md` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/docs/ARCHITECTURE-AUDIT-2026-07.md) |
| `docs/DF-CALIBRATION-AUDIT-2026-07.md` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/docs/DF-CALIBRATION-AUDIT-2026-07.md) |
| `docs/history/PROJECT_MANUAL.md` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/docs/history/PROJECT_MANUAL.md) |
| `docs/history/devlog.md` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/docs/history/devlog.md) |
| `docs/history/upgrade-2026-07.md` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/docs/history/upgrade-2026-07.md) |
| `docs/history/v2-readme.md` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/docs/history/v2-readme.md) |
| `poc/poc_1d_ltne_strict_conservation.py` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/poc/poc_1d_ltne_strict_conservation.py) |
| `scripts/port_retest_pull.sh` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/scripts/port_retest_pull.sh) |
| `scripts/port_retest_server.ps1` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/scripts/port_retest_server.ps1) |
| `scripts/port_retest_server.sh` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/scripts/port_retest_server.sh) |
| `sjtu_tpmshx/runs/run_m1_uniform_vs_graded.py` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/runs/run_m1_uniform_vs_graded.py) |
| `sjtu_tpmshx/runs/run_m2_rerank_m1.py` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/runs/run_m2_rerank_m1.py) |
| `sjtu_tpmshx/runs/run_port_dim_retest.py` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/runs/run_port_dim_retest.py) |
| `sjtu_tpmshx/runs/tools/plot_grid_convergence.py` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/runs/tools/plot_grid_convergence.py) |
| `sjtu_tpmshx/tests/test_port_result_pull.py` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/tests/test_port_result_pull.py) |

M1/M2 的三个固定 Pareto 输入与消费者、端口维数复测试验一同退役。
普通 qNEHVI、快速设计和通用测试服务器入口仍在当前树。
A1/benchmark A 的旧输入原已缺失，历史代码不代表可在当前目录完整重跑。
原 validation 与 reports 索引也可在上述提交的同名路径查阅。

当前模型及数据约定见[架构](../architecture.md)和[数据目录](../data-catalog.md)；
旧 RBF/γ 模型与更早的资料见[模型退役索引](legacy-models.md)和[历史总索引](README.md)。

## 多边形计算退役

公开 Compute 已拒绝 Hexagon/Octagon；旧计算实现、三角剖分和已无消费者的
`unstructured_mesh.hexagon/octagon` 均已退役。旧矩形工况仍可导入；多边形
文件在修改当前输入前被拒绝，不再作为可用计算形状展示。

| 原路径 | 固定历史入口 |
| --- | --- |
| `sjtu_tpmshx/ui/polygon_calc.py` | [原实现](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/ui/polygon_calc.py) |
| `sjtu_tpmshx/solvers/polygon_fvm.py` | [原实现](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/solvers/polygon_fvm.py) |
| `sjtu_tpmshx/solvers/unstructured_mesh.py` | [原实现](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/solvers/unstructured_mesh.py) |

## B 侧局部开口实验修正退役（2026-09-22）

按用户确认，移除 M4 有效参与面积缩放、逐单元 χB 热源/导热缩放、χB 阈值
冻结温度，以及 H2 出口低导热诊断。它们是附加实验修正，不是进出口的真实几何
边界。当前端口位置、尺寸、方向及质量/能量守恒检查继续保留。

原实现和 H2/H6/H8 调查可从 [87dcfbab 的求解运行时](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/87dcfbab5bf3e7dcc32e6a0d4e77fe58c5625fcc/sjtu_tpmshx/solvers/backends/python/three_d/runtime.py)
及[守恒审计](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/87dcfbab5bf3e7dcc32e6a0d4e77fe58c5625fcc/sjtu_tpmshx/validation/cases/audit_3d_conservation.py)查阅。
历史结果及失败记录保留原模型含义，不改写为现行结果。

- 配置/原始研究字典/准备后的执行输入中的 `partial_B_closure`、`m4_*`、
  `chi_B_*`、`audit_h2_*`、`audit_zero_K_ffB_at_outlet` 均显式拒绝；即使值为
  `none`、0 或 False，也需移除该旧实验设置。移除后是现行模型的新计算。
- 守恒工具保留 T1–T6 的整面、局部、偏置、隔离和等温工况，删除专用 H2/H6/H8
  入口。当前 GCI 的偏置开口工况名为 **T4**，不再使用 T4_H8，不能与旧 H8 的
  数字直接合并。当前偏置端口测试仍要求原有热力学、能量和亚声速门槛。
- `TPMSHX_SCO2_COMPRESSIBLE` 属于另一项 A 侧物性研究，未在此组退役。
  非对称 CFD 工单、导入和研究求值也继续保留。

## 无消费者代码与参考实现整理（2026-09-22）

移除闲置的 GUI 时间滑条/窗口场缓存/主题镜像、画布和预热辅助函数，以及
未接入的后处理报告/绘图帮助器。仍在使用的菜单操作改为直接连接现有处理函数。
旧矩形工况导入、实际场图、导出和取消功能继续保留。

`solvers.envelope`、`solvers.roughness` 纯转发模块及 `df_projection` 的模型转发
已退役，仓内调用者改从 models 导入；活动压力归约仍留在 solvers。
历史水 Nu 对照和完整端面二维焓参考实现移至 tests，继续做比较，不再作为生产
求解入口。永久跳过、只有 pass 的旧二维上海测试占位删除，其[历史说明](README.md)
及现行三维/集总验证的原门槛保留。

## SIMPLER 试验退役

2D 默认 SIMPLE 保留；删除 SIMPLER 选择参数、伪速度核和专属 benchmark/test/spec。
旧 `coupling` / `simpler_relax_p` 参数不再接受，传入会报错。
原比较的两个网格上加速比为 0.46×、0.59×，没有性能收益；原结论和数值保留如下。

| 原路径 | 固定历史入口 |
| --- | --- |
| `openspec/specs/simpler-coupling-2d/spec.md` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/openspec/specs/simpler-coupling-2d/spec.md) |
| `reports/simpler-coupling-2d/CONCLUSIONS.md` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/reports/simpler-coupling-2d/CONCLUSIONS.md) |
| `reports/simpler-coupling-2d/benchmark_simple_vs_simpler_2d.csv` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/reports/simpler-coupling-2d/benchmark_simple_vs_simpler_2d.csv) |
| `sjtu_tpmshx/runs/benchmark_simpler_2d.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/runs/benchmark_simpler_2d.py) |
| `sjtu_tpmshx/tests/test_simpler_coupling_2d.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/tests/test_simpler_coupling_2d.py) |

## RBF 退役后的依赖

基础依赖不再需要 `scikit-learn` 和 `threadpoolctl`，已从基础锁移除。
常规 BO 的 [GPyTorch 1.15.2](https://pypi.org/pypi/gpytorch/1.15.2/json)
仍依赖 scikit-learn，因此两个原版本保留在 `requirements-lock-server.txt`。
`joblib` 仍用于常规设计/优化并行计算，几何与现行 K/cF 的预热也继续保留。

## 旧可变物性方向性测试退役

2026-09-13 经用户明确同意，退役
`test_partial_bc_ghost_b.py::test_variable_rho_cp_off_override`，并移除其耗时测试清单条目。
[原测试与断言](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/29aac9c3649fd640283d02ec0d303e585f743d1b/sjtu_tpmshx/tests/test_partial_bc_ghost_b.py#L240)
固定保留在本轮修改前的提交 `29aac9c3649fd640283d02ec0d303e585f743d1b`。

原断言要求关闭可变物性后的有效度满足 `ε_off > ε_on + 0.1`。修改前的隔离源码
和本轮代码均得到 `ε_on=0.1759099320`、`ε_off=0.1374915884`，原测试均失败
（退出码 1）。这项旧方向性假设不再用作开关是否有效的验收条件；没有调整求解公式、
关联式、冻结参考数值或其他测试容差。基线失败及退役前全量失败日志保留在本任务
`.cache/consistency-maintenance-20260913/` 的 `baseline-legacy-override.log`
与 `full-suite-corrected.log`。

现行覆盖继续保留：

- [test_3d_property_frame.py](../../sjtu_tpmshx/tests/test_3d_property_frame.py)：
  显式 ON/OFF 下的物性字段、流体与流向接线。
- [test_3d_model_enthalpy_transport.py](../../sjtu_tpmshx/tests/test_3d_model_enthalpy_transport.py)：
  开关控制内核路径、平衡前质量通量，以及关闭路径的温度/焓报告约定。
- [test_partial_bc_ghost_b.py](../../sjtu_tpmshx/tests/test_partial_bc_ghost_b.py)：
  默认与显式开启时的有效度上限、固体及两侧能量平衡、出口速度和场边界检查。

## 旧规范与状态原稿归档（2026-09-13）

以下 5 份原稿移出当前树，全文固定在文档整理前的已合并提交
`5c517b415be0adbfc7bbfd205a3dba07fe8792a8`。原数值、失败、未实施事项与
历史重基线决定保留；本轮不重算参考、不放宽物理校验，也不删除对应有效测试或 CSV。

| 原路径与固定原文 | 现行约束承接 |
| --- | --- |
| [arch-b-c-e/spec.md](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/5c517b415be0adbfc7bbfd205a3dba07fe8792a8/openspec/specs/arch-b-c-e/spec.md) | [架构](../architecture.md)：共享模型、数值/GUI 归属；`solvers/_solve_common.py` 统一 F2；LowReExit 于下述 2026-09-14 整理中退役 |
| [compute-contracts/spec.md](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/5c517b415be0adbfc7bbfd205a3dba07fe8792a8/openspec/specs/compute-contracts/spec.md) | [正式数据契约](../../schemas/three_module_v1/)与架构：Qt-free domain、实际准备输入、原生状态、严格文件交接；输入、质量/能量、日志、收敛与持久化检查保留 |
| [collaboration-project-layout/spec.md](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/5c517b415be0adbfc7bbfd205a3dba07fe8792a8/openspec/specs/collaboration-project-layout/spec.md) | 已结束工程按本页索引归档；共享模型、求解器与有效验证仍归主体包，不恢复旧项目目录 |
| [solver-efficiency-r1-r4/spec.md](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/5c517b415be0adbfc7bbfd205a3dba07fe8792a8/openspec/specs/solver-efficiency-r1-r4/spec.md) | 历史性能结论见本页原工程索引；旧早退测试迁为 F2，守恒和 SOU 检查继续保留，原重基线步骤不作为新任务指令 |
| [_CSV_STATUS.md](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/5c517b415be0adbfc7bbfd205a3dba07fe8792a8/sjtu_tpmshx/validation/_CSV_STATUS.md) | [验证导航](../../sjtu_tpmshx/validation/README.md)、[数据记录](../data-catalog.md)：当前入口与来源限制；原 CSV 数字不改写成新验收 |

保留的 OpenSpec 说明当前 GUI、孔隙率分配与 CI 行为；原 Graph 需求、节点卡和
合并证据见[历史总索引](README.md)，M-B 缺口见[能力范围](../capabilities.md)。
它们不因旧规范归档而视为已完成。

## 旧收敛与内部接口退役（2026-09-14）

本轮按用户确定的架构范围，迁移完整求解、原始类和筛选的消费者，统一使用 F2。
源代码和原始筛选参考固定在 `ec1c73e06971c7d9af98d121ba9dd1e4f7dfba7f`；
[原数值及性能处置记录](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/5534369de8f1f9e535076b36b55d2bce2c1d1e38/docs/solver-architecture-20260914.md)解释当时的新旧差异。

| 退役项与固定源码 | 当前承接 |
|---|---|
| [LowReExit 与 legacy 语义](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/ec1c73e06971c7d9af98d121ba9dd1e4f7dfba7f/sjtu_tpmshx/solvers/_solve_common.py) | 同一模块的 F2Monitor；质量残差、动量残差、回流及确认规则分别核验 |
| [3D 内部 SIMPLE Anderson](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/ec1c73e06971c7d9af98d121ba9dd1e4f7dfba7f/sjtu_tpmshx/solvers/simple_solver_3d.py)及其 stack/unstack 辅助函数 | 显式启用旧 use_anderson 会报错；热量/外层 Anderson 保留 |
| [旧筛选数值参考](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/ec1c73e06971c7d9af98d121ba9dd1e4f7dfba7f/sjtu_tpmshx/tests/test_evaluator_frozen_values.py) | 新 F2 参考保持同一参数、预算和 1e-12 比较容差；旧四项失败另存 |
| [旧 F2/legacy 计价工具](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/ec1c73e06971c7d9af98d121ba9dd1e4f7dfba7f/sjtu_tpmshx/validation/cases/price_f2_convergence_3d.py) | 同名工具只扫描 F2 动量容差，新输出 `f2_pricing_3d_v2.csv`；原 CSV 见下节固定历史 |
| [旧 C.3 质量容差扫描](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/ec1c73e06971c7d9af98d121ba9dd1e4f7dfba7f/sjtu_tpmshx/validation/cases/phase_c_gci.py) | 迁为 F2 动量容差扫描，输出 `phase_c_f2_tol_sweep.csv`；原 CSV 见下节固定历史 |

同时移除无调用者的 `_apply_phase_flags`、二维工质字典包装、旧粗网格质量容差参数。
F2 的速度检查触发参数改名为 `f2_velocity_check_tol`，不再沿用 LowReExit 名称。
原历史结果不因参考迁移而获得新的物理、实验或整体 B40 验收结论。

## 无现行消费者的诊断表退役（2026-09-15）

以下 6 个文件移出当前树。移出前确认内容与固定提交
`ec1c73e06971c7d9af98d121ba9dd1e4f7dfba7f` 一致，并核对源码、测试、打包与文档引用。
原数字、失败行和版本信息通过以下链接保留；没有把旧误差当成当前精度。

| 原文件与固定历史 | 处置依据与现行承接 |
|---|---|
| [f2_pricing_3d.csv](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/ec1c73e06971c7d9af98d121ba9dd1e4f7dfba7f/reports/f2_pricing_3d.csv) | legacy/F2 历史成本比较；无现行读取者，工具已改为 F2 容差扫描 |
| [phase_c_tol_sweep.csv](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/ec1c73e06971c7d9af98d121ba9dd1e4f7dfba7f/sjtu_tpmshx/validation/phase_c_tol_sweep.csv)及[元数据](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/ec1c73e06971c7d9af98d121ba9dd1e4f7dfba7f/sjtu_tpmshx/validation/phase_c_tol_sweep.csv.meta.json) | 旧质量容差不再控制收敛；当前扫描输出另命名，不覆盖原表 |
| [shanghai_3d_baseline_gammadf_nz10.csv](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/ec1c73e06971c7d9af98d121ba9dd1e4f7dfba7f/sjtu_tpmshx/validation/shanghai_3d_baseline_gammadf_nz10.csv) | 已退役 γ 模型的 Nz=10 诊断；现行验证使用当前闭合与物理端口 |
| [shanghai_3d_baseline_gammadf_routing_check.csv](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/ec1c73e06971c7d9af98d121ba9dd1e4f7dfba7f/sjtu_tpmshx/validation/shanghai_3d_baseline_gammadf_routing_check.csv) | 已结束的 γ 路由检查，无现行读取者 |
| [shanghai_3d_baseline_nz10_massflux.csv](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/ec1c73e06971c7d9af98d121ba9dd1e4f7dfba7f/sjtu_tpmshx/validation/shanghai_3d_baseline_nz10_massflux.csv) | 旧通量诊断快照，无现行读取者；当前原生质量/能量证据随正式结果保存 |

MMS 误差原表、阶数门槛、GCI 参考、Shanghai 主基准和有效测试继续保留。
模型拟合输出及 Graph/B40 原始失败于 2026-09-18 移到固定历史入口；一维焓参考
实现移入 tests/，见[历史总索引](README.md)。当时上海与 sCO2 压降误差见
[原求解器整理记录](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/5534369de8f1f9e535076b36b55d2bce2c1d1e38/docs/solver-architecture-20260914.md)，不作为现行精度。

## 无调用者的 UI 转发与旧系数写入工具退役（2026-09-16）

原实现固定在已合并提交 `c45d9cb1e57a28809c0250abbd34221211eb2a15`。
核对源码、测试、字符串回调和文档引用后，移除以下未被现行路径调用的实现：

| 退役项与固定源码 | 现行承接 |
|---|---|
| [UI mixins](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/c45d9cb1e57a28809c0250abbd34221211eb2a15/sjtu_tpmshx/ui/mixins) 中的 19 个私有转发/判向方法 | 页面组装、布局绘制、画布缩放、Pareto 展示/保存和分区配置直接调用所属模块函数；实际按钮与信号仍使用的窗口回调保留 |
| [快速设计 `_FlowLayout`](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/c45d9cb1e57a28809c0250abbd34221211eb2a15/sjtu_tpmshx/ui/quick_design_panel.py) | 该局部类从未实例化；对话框继续使用原有 Qt 布局 |
| [旧 `override_simple_K_cF`](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/c45d9cb1e57a28809c0250abbd34221211eb2a15/sjtu_tpmshx/solvers/df_projection.py) | 当前前处理准备 K/cF，筛选求解侧消费准备字段；现行投影函数和仍有验证调用者的压降诊断保留 |
| [旧 `clear_field_cache`](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/c45d9cb1e57a28809c0250abbd34221211eb2a15/sjtu_tpmshx/models/sco2_props.py) | 没有现行调用者；标量查询继续使用原有 `lru_cache`，场查询继续直接使用向量化 CoolProp |

求解方程、关联式、收敛条件、参考值和正式配置/结果格式未改。
