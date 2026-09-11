# 架构审计 2026-07（P1.1，升级循环 iter 6）

证据基线：master `4b32da4` + upgrade/loop 前 5 轮。取证方式：AST 实测 import 图
（`sjtu_tpmshx/runs/tools/audit_import_graph.py`，原始日志保留于 Git 历史）+
两路只读代码侦察（file:line 全部核对到当前代码，非文档转述）。本文是 P1 后续条目的工作底稿；
与 [当时的交接审计](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/d3ba040de0d43fce8e9b485396a5b660c2d87c5f/docs/atlas/HANDOFF-windows-server.md) 冲突处**以本文为准**（HANDOFF 部分条目已过时，见 §3）。

## 0. 执行摘要

架构比 HANDOFF 时代的文档记载**更健康**：数值核心零 Qt 依赖、依赖方向大体正确（solvers 扇入 109
是承重墙、logutil 纯汇点）、run_stack_3d 与 stages_3d/flux_3d 之间**没有逻辑重复**（2026-07-03
拆分已收尾成 re-export 树）、W7 缓存修复到位且有测试锁定。真实的债，按险级排序：

1. **正确性级**：两个 BO 评估器都缺 post-solve `gate_solution`（Mach/正压门）。
   *（勘误 iter 7：本行原引 HANDOFF §1 的 max_outer/压力字面量为"仍在"——实测已全修
   （SolverConfig.max_outer_ltne 自 8ea7ce5 起活、压力字面量 2026-07-11 改真实转发）且已被
   `test_validate_pipeline_runner_wiring.py` 四断言锁死。教训：审计条目须现场核实，不得转述文档。）*
2. **潜伏炸弹级**：`compute_geometry` 返回共享可变 dict、`_phi_grid` 返回未冻结共享 ndarray
   （W7b 同族，当前调用方只读所以未爆）；`TPMSHX_CHI_S` import 时冻结（影响 K_ss 的 reload 隐患）。
3. **结构级**：`_run_3d_stack` 单函数 1955 行；3 条实测分层违规 + main↔ui 组合环；
   sys.path 引导 5 模式约百处；两套 BO 评估器与各自生产管线的受控漂移缺契约锁定。

## 1. 分层现状（实测）

15 个顶层单元，34 条核心边（non-free→non-free）。意图分层与实测吻合度高：

```
L0 logutil(in=32,out=0) · configs · domain(in=17,out=1)
L1 solvers(in=109,out=15)          ← 承重墙
L2 df_surrogate(in=23,out=19) · design
L3 pipelines(out=73) · core · optimization
L4 controllers
L5 ui · main
free validation · runs · tests · poc
```

**实测违规（3 + 1）——P1.9 裁决结果（iter 20）：前两条 SANCTIONED（工具内附理由）、
后两条已修（polygon_calc 迁 ui/、__version__ 抽 _version.py 叶子）；
`--fail-on-violations` 已由 test_import_layering 常驻套件**：
- `solvers → df_surrogate`（6 处：continuous_field.py / df_projection.py / polygon_fvm.py）——
  求解器层 import 闭合提供方。属**依赖倒置候选**：要么闭合注入化，要么正式承认 df_surrogate
  位于 solvers 之下（改分层模型 + 注释背书）。→ P1.9
- `domain/validator.py → df_surrogate`（1 处）——配置校验向上够 surrogate。→ P1.9
- `ui/mixins/run_controller.py → runs`（1 处）——GUI 最胖 mixin（1213 行）import 脚本层。→ P1.9
- `main ↔ ui` 双向（main→ui 20 / ui→main 1）——组合根循环，同层未被工具标记，需人工裁决。→ P1.9

**资产（重构时保住）**：核心零 Qt（Qt 只在 ui/61 文件 + main + 4 个 controllers）；
`controllers/compute_pipeline.py`（264 行，Qt-free）是 headless 接缝，`Pipeline2D/3D` + `pipeline_for(cfg)`。

## 2. 双 evaluator 的真相（修正 HANDOFF §3 的框架）

**它们不是同一件事的两个实现**：`core/evaluators.py::evaluate_3d` 是 **3D** BO 评估器
（SIMPLESolver3D×2 + solve_full_domain_3d），`optimization/evaluator.py::evaluate_design` 是
**2D** BO 评估器。正确的比较轴是**各自 vs 自家生产管线**：

| 能力 | evaluate_3d vs Pipeline3D | evaluate_design vs Pipeline2D |
|---|---|---|
| P_ref_abs 种子 | **手抄代数** `P_in²−2RT·C·L` + 本地 R_AIR（:224,230,268），不 import envelope | `envelope.predict_outlet_p_sq` + 1e4 地板 + 实际阻力重播种（:319,392,:258-264）✓ |
| 预解 choke | NaN+invalid dict（:243-267），不 raise | **raise ChokedFlowError → 罚值**（:320-323 等，aa3f477 新增）；注意**比管线更严**（stages_2d:515-529 是 clip 不 raise，ledger O1） |
| 热重播种 | aa3f477 已改严格 NaN（:472-505，**HANDOFF §3a 此行已过时**） | 实际阻力重播种 raise ✓ |
| post-solve gate_solution（Mach/正压） | **缺** | **缺**（管线有：run_stack_3d:2151,2159） |
| rho_inlet_ref | **不传**（管线传） | **不传**（stages_2d:546,561 传，防 ratchet） |
| 警告注册表 reset | **缺**（Pipeline.run 有 :120-123） | **缺** |
| B 侧 var-ρ 重播种 | 无（自文档 :336,531-534，**有意的**廉价筛选） | n_rho_loops 双侧 ✓ |
| 收敛模式 | 默认 legacy（管线 f2；**有意**，BO 吞吐） | 结构与管线一致 |
| 目标整形 | 无罚值/无 dp_cap（wrapper 只处理 invalid） | 制造性罚值 + dp_cap + reject_unconverged |

**追加（iter 10）**：rho_inlet_ref 一行的深挖发现**管线间口径不一致**——2D 管线显式钉物理
ρ(T_in,P_in)·u，3D 求解器无该旋钮、首解捕获 ρ(T_in,P_out_seed)（亏空冻结点 7.4%/19.3%，
且与 validate 的实验 ṁ→u 换算相悖，已被 γ_df 锚定部分吸收）。标定级决策 → DECISIONS D3。

**结论**：evaluate_design 离 Pipeline2D 近（共享 extract_dP_from_simple、同一 envelope 权威）；
evaluate_3d 离 Pipeline3D **最远**（完整的第三套物理装配）。收敛方向不是"全部路由进 Pipeline"
（会毁掉 BO 吞吐预算——legacy 模式与 B 侧冷解是有意设计），而是：
(a) **契约测试**先锁定"有意差异 vs 事故差异"清单；(b) 种子/门禁代码路径共享权威
（3D 评估器 import envelope、双方补 gate_solution、传 rho_inlet_ref、reset 注册表）；
(c) 目标整形留在适配层；(d) 定契约："Pareto 选点必须经 Pipeline 复核后才可引用数字"。
**HANDOFF §2a"优化器无 choke 检查"对预解已过时**（aa3f477），对 post-solve 仍成立。

## 3. run_stack_3d.py 解剖（2380 行）

**无重复**：flux 助手单源于 flux_3d.py，stages_3d.py 只是 cfg 阶段包装 + re-export；
`_run_3d_stack`（:425-2380，~1955 行）才是问题本体。两个入口面：Pipeline3D（cfg 阶段）与
raw-cfg 直调（golden/_out、validate_shanghai_3d_real、demos/smokes——拆分时 **stages_3d 的
re-export 面就是兼容层**，必须保持）。

五条拆缝（P1.5 的执行顺序：A→B→D→E→C，每步 golden 位同）：

| 缝 | 行区 | 内容 | 跨缝状态 | 难度 |
|---|---|---|---|---|
| A | 439-853 | cfg→网格→轴映射→DF surrogate→SIMPLE A/B 构建→初始并行解 | 状态包（sA/sB/轴映射/K·cF·ε 场/标量） | 低，最先拆 |
| B | 862-1040 | 5 个 h_v 闭包 | 只读几何/cfg → 显式 context 即可提升为模块函数 | 低 |
| D | 1773-1974 | 指标/场提取 | 近纯函数（读收敛后的 sA/sB/T 场） | 低 |
| E | 1976-2379 | 守恒诊断+envelope 门+收敛裁决+结果组装 | 自足尾段 | 中 |
| C | 1153-1763 | `_outer_step_3d`/`_outer_post_3d`（8 个 nonlocal，原位 `[:]` 突变） | **需显式耦合态对象**保位同 | 高，最后拆 |

死/遗留分支（拆分时顺带标注，不删行为）：fast_sweep（:444-458，故意不收敛的筛查档）、
chi_B_method 三支（:1251-1291，默认 'none'，m4 留作回归对照）、H2 审计钩（:1301-1319）、
sCO2 压缩性实验路径（:1529-1605，opt-in 未验证）。env 读取全部 per-call（本文件无 import 冻结）✓。

## 4. sys.path 引导清单（5 模式，~100 处）

P1：包根引导（df_surrogate/validation/runs 各处，parents[2] 系）；P2：仓根引导（main.py:12-14
双根是正版）；P3：双插（validation/sco2_* 加 sibling 目录）；P4：projects/** 11 处外部消费者；
P5：tests/ 约 65 处两种习语混用。**结构性根治 = P1.8 打包**（editable install 后逐波删除）；
在此之前不做零星清理（每处删除都有回归面，收益为负）。

## 5. 模块级可变态清单

**(a) 修好的样板**：`sco2_props._FIELD_CACHE`（数组 writeable=False + reset 钩——**本仓的标杆做法**）；
`tpms_calc.compute`（W7b：返回 dict 拷贝 + DF-env 入键，测试锁定）。

**(b) W7b 同族潜伏隐患（→ P1.6，小改 + golden 位同）**：
- `tpms_geometry.compute_geometry`（:189，lru 4096）返回**共享可变 dict**（:242-248）——未享受拷贝修复；
  当前两个调用方只读。修法照 W7b：返回浅拷贝（值全标量）。
- `tpms_geometry._phi_grid`（:59，lru 4）返回**未冻结共享 ndarray**——15+ 消费者全只读；
  修法照 _FIELD_CACHE：`writeable=False`。

**(c) 待查**：`ltne_energy_3d._LAPLACIAN_AMG_CACHE`（:41，无 reset，需确认 AMG 层级只读复用）；
`sigmoid_field._lut_cache`（无界，LUT 不可变假设未强制）；backend/gamma_df 缓存无 reset（实践只读）。

**(d) import 冻结**：`tpms_props._CHI_S_ENV`（:186）——**真实隐患**（影响 K_ss，运行中设
TPMSHX_CHI_S 无效）→ P1.6 改 per-call；`design/sizing.S_MAX/LX_MAX`（:21-22）——**有意设计**
（loky spawn 继承语义，文档已注明），不动。

警告去重集合（predict._CHOKE_WARNED、nu_correlations 三个、tpms_props 两个）无 reset 钩：
Pipeline.run 会 reset 其中两类，**评估器不 reset**（BO 下警告闩死）→ 并入 P1.3。

## 6. P1 子项回填（已写回 ROADMAP，此处为依据）

P1.2 已验证为"上游已修+已锁定"收案（iter 7；HANDOFF §1 整节过时）。P1.3/P1.4 按 §2 重写
（权威统一 + 契约测试，放弃"全路由"）。
P1.5 按 §3 五缝定序。P1.6 新增缓存加固与 env 冻结修复（§5b/§5d）。P1.7 死路径清理维持。
P1.8 打包（§4 的根治）。P1.9 新增分层违规裁决（§1），收尾把 `--fail-on-violations` 挂进 CI/check。

### TM1 shared model extraction (2026-09-10)

The shared model implementations now live in `models` below numerical solvers.
Existing `solvers` model paths alias the same module objects, preserving state
and monkeypatch identity for current consumers. `models -> df_surrogate` retains
the existing physical closure dependency; DF model consumers now import the
shared models directly. This replaces the model portion of the previously
sanctioned solver/closure cycle without changing any physical formula. The
import audit assigns models layer 0.5 and continues to reject model imports of
numerical solvers. Clean-process model evaluation separately checks that no
solver, pipeline, Numba or Qt module is loaded.
