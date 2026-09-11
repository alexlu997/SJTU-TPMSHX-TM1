# 旧项目手册（历史参考）

2026-09-12 从仓库根目录 `PROJECT_MANUAL.md` 归档，以下原文保留不变。
[归档前版本](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/804160253a128a8b0415d2e6da2ccb125d53a635/PROJECT_MANUAL.md)
中的目录、启动命令、默认模型和精度结论属于当时状态，不能作为当前使用指南。

当前入口：[首次运行](../../README.md#first-run)、
[主体源码与模块地图](../../sjtu_tpmshx/README.md)、[架构说明](../architecture.md)。
正文中的相对路径按原仓库根目录或原章节语境解释。

---

# SJTU-TPMSHX 项目说明文档

> 一份面向**人类读者**和**其他 AI（如 GPT、Gemini）**的完整说明文档。
> 目标：不读源码也能理解整个项目在做什么、由哪些文件组成、每个文件负责什么。
> 凡是项目内部的“黑话”，本文都会用通俗语言解释一遍。

---

## 0. 怎么读这份文档

- 如果你是**人**：先看第 1～3 章（定位、名词表、架构），再按需查第 6 章的逐文件说明。
- 如果你是**另一个 AI**，被要求基于本项目工作：请把第 2 章（名词表）和第 5 章（目录地图）当作“词典”，把第 6 章当作“API 索引”。本文刻意把每个专有名词都翻译成了普通工程语言，遇到缩写先回名词表。
- 文中**文件名、函数名、变量名保留英文**（与源码一致，方便检索）；**解释用中文**。
- 单位约定：温度用开尔文 K（除非注明摄氏度 °C），压力用帕斯卡 Pa，长度域用米 m，但 TPMS 单元尺寸/壁厚用毫米 mm（这是一个常见的踩坑点，见第 8 章）。

---

## 1. 这个项目是什么（一句话 → 一段话）

**一句话**：这是一套用来**设计和优化 TPMS 结构换热器**的计算软件——既能算一个给定结构的换热量和压降，也能反过来帮你“定尺寸”，还能多目标优化出一组最优方案，并配有图形界面。

**展开说**：
- **TPMS** = Triply Periodic Minimal Surface（三周期极小曲面）。可以理解为一种用数学公式定义的、在三个方向上无限重复的复杂多孔曲面结构（典型有 Diamond 和 Gyroid 两种）。用金属 3D 打印（SLM，激光选区熔化）做出来，内部是两套互不连通、彼此缠绕的流道，一套走热流体、一套走冷流体，隔着金属壁换热。它换热面积大、结构紧凑，是新型紧凑式换热器的热门方案。
- 本软件的**核心计算引擎**：把这种复杂微结构“**均质化**”（homogenization）成一团等效多孔介质，然后用计算流体力学（CFD）求解其中的流动和传热，得到两个关键工程指标：
  - **Q**：换热量（传热功率，单位 W），越大越好；
  - **dP / ΔP**：流体流过换热器的压力损失（单位 Pa），越小越省泵功。
- 软件围绕这个引擎提供四类能力：
  1. **正向计算**：给定几何 + 工况，算出 Q 和 dP（含 2D 和 3D 两套求解器）。
  2. **快速定尺**（design 模块）：给定工程需求（要冷却多少、流量多少、允许多大压降），自动反推一个 TPMS 换热器块的最优尺寸。
  3. **多目标优化**（optimization 模块）：用贝叶斯优化在“几何设计空间”里搜出一条 Q 与 dP 的最优权衡曲线（帕累托前沿）。
  4. **图形界面**（ui + main.py）：用 PySide6（Qt）做的桌面程序，可视化温度/压力/速度场、跑优化、看结果。
- 软件还附带一整套**验证与校核**（validation）：拿真实实验数据（“上海电气天然气加热器”16 个工况）对比，以及用标准数值方法学（MMS、GCI）证明求解器收敛阶数正确。

**项目代号**：SJTU-TPMSHX（上海交通大学 - TPMS 换热器）。代码包根目录是 `sjtu_tpmshx/`。

---

## 2. 名词表（把“黑话”翻译成人话）

> 这一章是全文的“词典”。第 6 章里所有缩写都能在这里查到。

| 术语 / 缩写 | 通俗解释 |
|---|---|
| **TPMS** | 三周期极小曲面。一种数学定义的、空间周期重复的复杂曲面结构，用作换热器内部骨架。本项目支持 **Diamond** 和 **Gyroid** 两种。 |
| **均质化 (homogenization)** | 不去逐根流道地精细建模，而是把微结构等效成一团“多孔介质”，用平均性质（孔隙率、等效导热、阻力系数等）描述。这样计算量小很多。 |
| **CFD** | 计算流体力学，用数值方法求解流动和传热。 |
| **SIMPLE** | 一种经典的 CFD 求解算法，专门处理“压力和速度互相耦合”的问题。它反复迭代：先猜速度、再用连续性方程修正压力、再修正速度，直到收敛。本项目用它解流动（动量方程）。 |
| **LTNE** | Local Thermal Non-Equilibrium，局部热非平衡。意思是：在多孔介质里，**固体壁的温度**和**流体的温度**不一样，要分开算。本项目同时解三个温度场：热流体温度 Ta、冷流体温度 Tb、固体温度 Ts，它们之间通过界面换热互相影响。 |
| **Q（换热量 / 热负荷）** | 单位时间传递的热量，单位瓦特 W。 |
| **dP / ΔP（压降）** | 流体进出口的压力差，单位 Pa。代表流动阻力，越小越好。 |
| **Darcy-Forchheimer（达西-福希海默 / 简称 D-F）** | 描述流体流过多孔介质压降的公式：`压降梯度 = μ·u/K + ρ·c_F·u²`。第一项是低速黏性阻力（K 是“渗透率”），第二项是高速惯性阻力（c_F 是惯性阻力系数）。本项目用它做压降闭合。 |
| **闭合 (closure) / 闭合系数** | 在均质化模型里，那些无法从大尺度方程直接得到、必须靠经验/拟合补上的系数（比如 K、c_F、换热系数）。 |
| **代理模型 (surrogate)** | 一个“快速近似函数”，用来代替昂贵的精细 CFD。本项目用它根据几何（结构类型、单元尺寸 L、壁厚 t、孔隙率）快速预测 D-F 的 K 和 c_F，避免每个设计都重跑 CFD。**ConstDF-v1** 是当前生产用的那一版代理模型。 |
| **RBF 插值** | Radial Basis Function（径向基函数）插值，一种平滑的多维插值方法。代理模型用它在“几何参数空间”里插值出 K、c_F。 |
| **Nu（努塞尔数）** | 无量纲传热强度，决定流体和壁面之间的换热系数 h。本项目用经验关联式 `Nu = c·Re^a·(D_h/L)^d` 算它。 |
| **Re（雷诺数）** | 无量纲流速指标，区分层流/湍流。`Re = ρ·u·D_h/μ`。 |
| **Pr（普朗特数）** | 流体物性的无量纲组合，空气≈0.72，水≈4~7。 |
| **D_h（水力直径）** | 流道的等效直径，用于 Re、Nu 的特征长度。 |
| **ε（孔隙率 / epsilon）** | 多孔介质里空隙体积占总体积的比例。本项目把总孔隙率平分给两套流道：`ε_A = ε_B = ε/2`。 |
| **A_0（比表面积）** | 单位体积内的换热面积，单位 1/m。 |
| **h_v（体积换热系数）** | 单位体积的换热能力 = `A_0 × h`（面积 × 面换热系数）。LTNE 里固体↔流体的热交换强度。 |
| **k_s** | 固体材料的导热系数，单位 W/(m·K)。 |
| **MMS** | Method of Manufactured Solutions（人造解法）。一种验证 PDE 求解器对不对的标准手段：先假设一个解析温度场，反推它需要什么源项，把源项塞进求解器，再看求解器算出来的和你假设的差多少。误差随网格加密下降的“阶数”能证明离散精度。 |
| **GCI** | Grid Convergence Index（网格收敛指数）。用几套不同密度网格的结果，估算“网格离散误差”有多大，是 ASME V&V 20 标准里的方法。 |
| **ASME V&V 20** | 美国机械工程师学会关于 CFD “验证与确认”的标准。本项目按它的流程（Verification 用 MMS/GCI，Validation 用实验对比）来证明可信度。 |
| **qNEHVI** | 一种多目标贝叶斯优化的“采集函数”（来自 BoTorch 库）。在“同时最大化 Q、最小化 dP”这种两目标问题上，它比传统遗传算法（NSGA-II）省 ~100 倍的计算次数。 |
| **帕累托前沿 (Pareto front)** | 多目标优化里“无法在不牺牲一个目标的前提下改善另一个目标”的那组最优解。这里是一条 Q-dP 权衡曲线。 |
| **ε-NTU 法** | 换热器集总（整体）计算的经典工程方法，用“效能 ε”和“传热单元数 NTU”估算换热量，不解流场。本项目用它做一个快速、独立的基准核对。 |
| **Shanghai 工况 / 上海 16 工况** | 一组真实实验数据：上海电气一台 Gyroid 结构天然气加热器，16 个不同流量/温度的运行点。本项目用它来检验预测准不准。 |
| **sigmoid 场 / 连续场参数化** | 一种让 TPMS 的单元尺寸 L 和壁厚 t 在空间上**平滑渐变**（而不是分块突变）的描述方法，用少量控制点 + 平滑过渡函数生成整片渐变结构，便于优化和 3D 打印。 |
| **decision vector（决策向量）** | 优化算法操纵的那串数字。这里是控制点上的 L、t 值（2D 16 维，3D 108 维），解码后变成整片渐变几何。 |
| **nTop** | 一款商业晶格/隐式建模软件（nTopology）。本项目能把优化结果导成 nTop 能读的标量场 CSV，用于真正建模出零件。 |
| **interstitial / superficial 速度** | 多孔介质里两种速度口径：interstitial 是“孔隙内真实平均速度”，superficial 是“按整个截面算的表观速度”。本项目内部统一用 interstitial（孔隙内）口径，混用会出错。 |
| **partial BC（部分边界）** | 进出口不占满整个面，只占一部分（真实换热器有集管/分配腔）。求解器用“开口比例 fraction”描述。 |
| **mass-flux inlet（质量流入口）** | 进口边界条件的一种：固定“质量流速 ρ·v”而不是固定速度 v。对可压缩空气很关键，能避免“密度涨→压降涨→压力涨→密度又涨”的发散正反馈。 |
| **Qt-free（无 Qt 依赖）** | 指某些代码刻意不引入图形界面库（PySide6），这样求解器/配置可以脱离界面单独测试和复用。 |

---

## 3. 总体架构与数据流

整个软件可以分成五个层次，从上到下、从用户到物理内核：

```
┌─────────────────────────────────────────────────────────────┐
│  1. 图形界面层  main.py + ui/ + ui/mixins/                    │
│     用户在这里填参数、点“计算”、看温度/压力/速度图、跑优化      │
└───────────────┬─────────────────────────────────────────────┘
                │ 用户输入（QLineEdit 等控件）
                ▼
┌─────────────────────────────────────────────────────────────┐
│  2. 控制器层  controllers/                                     │
│     把界面输入打包成严格类型的配置对象 ComputeConfig；          │
│     用后台线程跑求解、缓存结果、管理会话/主题/信号              │
└───────────────┬─────────────────────────────────────────────┘
                │ ComputeConfig（纯数据，无 Qt）
                ▼
┌─────────────────────────────────────────────────────────────┐
│  3. 流水线层  pipelines/                                       │
│     stages_2d.py(2D) / stages_3d.py(3D)                        │
│     四步流水线：解析输入 → 构建网格场 → 跑求解器 → 提取 Q、dP   │
└───────────────┬─────────────────────────────────────────────┘
                │ 网格数组、物性场、边界
                ▼
┌─────────────────────────────────────────────────────────────┐
│  4. 物理内核层  solvers/                                       │
│     - 几何与物性：tpms_geometry / tpms_calc / nu_correlations  │
│     - 压降代理：df_surrogate/                                         │
│     - 流动求解：simple_solver(_3d)  （SIMPLE 算法）            │
│     - 传热求解：ltne_energy(_3d)      （LTNE 三温度）           │
└───────────────┬─────────────────────────────────────────────┘
                │ 温度场 Ta/Tb/Ts、速度场、压力场
                ▼
            Q（换热量）、dP（压降）等工程指标

侧翼模块（不在主链上，但依赖物理内核）：
  · optimization/  多目标贝叶斯优化（搜帕累托前沿）
  · design/        快速定尺工具（反推尺寸，出 Excel 报告）
  · validation/    用实验数据 + MMS/GCI 验证可信度
  · core/          优化和验证共用的 3D 评估函数
  · domain/        输入合法性检查
```

**最重要的两条数据流**：

1. **“正向计算”流**（界面点一次“计算”）：
   `界面输入 → ComputeConfig → pipelines/stages_2d(_3d) → SIMPLE 解流场 → LTNE 解温度场 →（多次外层迭代耦合可压缩密度）→ 提取 Q、dP → 画图`

2. **“几何 → 压降”流**（代理模型的作用）：
   `几何(类型,L,t,ε) → df_surrogate 代理模型 → 渗透率 K、惯性系数 c_F → 喂给 SIMPLE 做多孔阻力 → 影响压降`

---

## 4. 物理模型一页纸（求解器到底在解什么方程）

软件把 TPMS 微结构当成多孔介质，在每个网格单元上解下面这套方程：

- **流动（动量 + 连续性，SIMPLE 求解）**：
  不可压或可压（理想气体 `ρ=P/(R·T)`）的 Navier-Stokes，外加多孔介质阻力项（Darcy-Forchheimer）：
  `阻力 = μ/K · u + ρ·c_F·|u|·u`。其中 K、c_F 来自 df_surrogate 代理模型。

- **传热（LTNE 三温度耦合）**：
  - 热流体 A：`ε·ρcp_A·(u·∇Ta) = ∇·(K_ffA·∇Ta) + h_vA·(Ts − Ta)`
  - 冷流体 B：`ε·ρcp_B·(u·∇Tb) = ∇·(K_ffB·∇Tb) + h_vB·(Ts − Tb)`
  - 固体 S：`0 = ∇·(K_ss·∇Ts) + h_vA·(Ta − Ts) + h_vB·(Tb − Ts)`
  
  直白说：每股流体一边被对流带走热量、一边自身扩散、一边通过界面（h_v 项）和固体换热；固体不流动，只扩散并同时和两股流体换热。

- **可压缩耦合**：空气密度随温度、压力变化，所以“解流动→更新温度→更新密度→再解流动”要外层迭代几轮。项目硬性要求保留可压缩性（否则上海工况压降误差会从 ~18% 退化到 ~39%）。

- **数值方法**：有限体积法；对流用二阶迎风（带 MINMOD 限制器防振荡）；压力修正方程在小网格用稀疏直接求解（spsolve），大网格（>3 万单元）用代数多重网格（PyAMG）+ BiCGStab 迭代。

---

## 5. 目录地图（每个文件夹一句话）

```
SJTU-TPMSHX/                       ← 仓库根
├── sjtu_tpmshx/                   ← Python 代码包（下面全部在这里）
│   ├── main.py                    ← 图形界面主程序入口（主窗口类 Main_Menu）
│   ├── assets/logos/              ← 品牌图（logo/banner PNG；由 main.py + ui_builders 加载，*.png 不入库）
│   │
│   ├── solvers/                   ← 【物理内核】几何、物性、流动、传热求解器
│   ├── df_surrogate/                    ← 【压降代理】根据几何快速预测 K、c_F 的拟合模型
│   ├── core/                      ← 优化与验证共用的 3D 评估函数（中立层）
│   ├── configs/                   ← 基准配置 JSON（上海 16 工况规格）
│   │
│   ├── controllers/               ← 界面与求解器之间的“契约层”：编排、流水线抽象、线程、缓存、主题
│   ├── pipelines/                 ← 【计算主路径】2D/3D stage 函数（解析→建场→求解→组装 ComputeResult）
│   ├── runs/                      ← 编排脚本（生产入口 + 助手 + golden gate 在根）
│   │   ├── demos/                 ← 演示脚本（3D 空气-空气、立方体、交互式可视化）
│   │   ├── diagnostics/           ← 诊断/探针（asym 几何扫描、收敛检查）
│   │   ├── smokes/                ← 冒烟测试（UI 离屏、2D/3D 管线端到端）
│   │   ├── tools/                 ← 构建/导出工具（CFD xlsx、HTML 渲染、3D 出图）
│   │   ├── cfd_asym/              ← asym 偏置等值面的 Fluent 交叉验证（PyFluent runner、κ 后处理、nTop 表达式）
│   ├── domain/                    ← 输入合法性校验（纯函数，无界面）
│   │
│   ├── optimization/              ← 多目标贝叶斯优化（qNEHVI，搜帕累托前沿）
│   ├── design/                    ← 快速定尺工具（给需求反推尺寸，出 Excel）
│   ├── validation/                ← 验证与校核（实验对比 + MMS/GCI + 守恒审计）
│   │   ├── harness/               ← 复用测试基础设施（_harness/_metrics/_case_sets/…）
│   │   └── cases/                 ← 验证 runner（shanghai/MMS/GCI/守恒审计），结果 CSV 留 validation/ 根
│   │
│   ├── ui/                        ← 图形界面组件（主题、画布、3D 面板、优化面板等）
│   │   └── mixins/                ← 主窗口类按职责拆分出的若干“混入”模块
│   │
│   └── tests/                     ← pytest 测试套件（~120 个文件）
│
├── poc/                           ← 概念验证（1D 严格守恒小求解器）
├── benchmarks/                    ← 性能基准测试（仓根运行 `python -m benchmarks.profiling.xxx`）
├── examples/                      ← 独立演示脚本（交互式 3D 可视化，仓根运行）
├── opt_runs/                      ← 历史优化跑归档（新跑输出按启动 CWD 落地，gitignore）
│
├── projects/                      ← 项目合作交付（每个项目一个自包含文件夹，只放调用包的驱动脚本）
│   ├── 624-Retrodict/             ← 工况回填（Diamond D-6-4 / D-7-5）
│   ├── 703-sCO2-D76/              ← 703 sCO2 PCHE/预冷器评估（D-7-6 晶胞）：定尺/耦合/场/Nu 闸门
│   └── 704-Aircooler-10kW/        ← 10kW 空冷器定尺 + 热约束校核
│
├── data/                          ← 实验原始数据（Excel，部分 gitignore）
├── reports/                       ← 计算结果、图、CSV
├── models/                        ← 模型/几何文件
├── data-revision.txt              ← 与代码配套的数据仓库提交版本
├── README.md / devlog.md          ← 仓库说明与开发日志
├── requirements.txt               ← macOS/Windows 通用安装入口
├── requirements-lock.txt          ← Python 3.12/3.13 共用的精确依赖锁
└── requirements-lock-server.txt   ← Windows 优化服务器附加依赖锁（CPU PyTorch/BoTorch）
```

---

## 6. 逐文件详解

> 下面按文件夹组织。每个文件给出：**作用**、**关键函数/类**、**输入输出**、**依赖**、**注意点**。

> **2026-07-20 增量（upgrade/loop 分支）**——以下新增/迁移未展开成子节。
> 当前架构和物理约束以 `docs/architecture.md` 为准；[Atlas 历史快照](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/d3ba040de0d43fce8e9b485396a5b660c2d87c5f/docs/atlas/README.md)保留当时的逐文件记录：
> - `sjtu_tpmshx/cli.py` ⭐新 — `tpmshx-run` headless 入口（ComputeConfig JSON 进、摘要出，
>   `--dry-run`/`--json`，exit 2 = 解出但被旗标；Qt 零导入）。注意与 `design/cli.py`（选型
>   子模块 CLI，本节 6.x 既有条目）是两个不同入口。
> - `sjtu_tpmshx/_version.py` ⭐新 — 版本号单源（pyproject dynamic 指向；main.py 再导出）。
> - `pyproject.toml` / `mypy-core-files.txt` ⭐新（仓库根）—
>   包元数据与类型门核心面清单；可复现安装以 `requirements-lock.txt` 为准。
> - `ui/mixins/run_results.py` ⭐新 — 结果呈现 mixin（write_result 等五方法自 run_controller
>   逐字节迁出；Main_Menu 现 14 mixin）。
> - `ui/polygon_calc.py` ⬅迁入（原 `runs/polygon_calc.py`）— 多边形域计算编排（Qt 耦合，
>   分层审计迁移）。
> - `runs/tools/audit_import_graph.py` / `build_fast_tier_manifest.py`
>   ⭐新 — 分层审计（常驻门）/ fast-tier 清单生成。
> - `solvers/threads.py` 增 `recommend_solver_threads` / `warn_if_default_pool`（大网格线程
>   一次性建议，池不自动改）。

---

### 6.1 `solvers/` — 物理内核（几何、物性、关联式）

这一组负责“算几何、算物性、算关联式”，是最底层的砖块。

#### `tpms_geometry.py` — TPMS 几何计算
- **作用**：给定结构类型、单元尺寸 L、壁厚 t，用数值方法算出孔隙率 ε、比表面积 A_0、水力直径 D_h。
- **怎么算**：用隐函数（Diamond / Gyroid 各有一个三角函数表达式）在一个 N³ 体素网格上取值；用一个阈值 C 把空间切成“固体/空隙”，从而数出孔隙率；统计体素面跨越曲面的次数得到表面积（再乘一个标定系数 1.553 修正体素法的高估）。阈值 C 与 t/L 的关系是预先用 12 个 CAD 数据点拟合好的（`C(t/L)=a·(t/L)+b·(t/L)²`，误差<0.5%）。
- **关键函数**：`compute_geometry(tpms_type, L_mm, t_mm, N=128)` → `{epsilon, epsilon_A, epsilon_B, A_0, D_h}`。`epsilon_A = epsilon_B = epsilon/2`（两股流道平分孔隙），`D_h = 4·epsilon_A/A_0`。
- **注意点**：默认体素分辨率 N=128（曾是 256，降下来省 8 倍内存，给并行优化用；ε 漂移<0.3%）。有 LRU 缓存避免重复体素化。

#### `tpms_calc.py` — TPMS 物性总计算器（核心入口之一）
- **作用**：一站式计算某个 TPMS + 工况下的全部传热/流动物性。是几何模块和关联式模块的“总装”。
- **关键函数**：
  - `compute(tpms_type, L_cell_mm, t_mm, u, T_in_K, P_in_Pa, k_s, fluid_type='air')` → 一个大字典，含 ε、A_0、D_h、Re、Nu、K_df（渗透率）、cF_df（惯性系数）、dP_per_L、H_sf（面换热系数）、K_ff（流体等效导热）、K_ss（固体等效导热）、ρ、μ、k_f。带 LRU 缓存（4096 条）。
  - `geometry(...)`：只要几何性质（不需要流体）。
  - 物性关联式：空气 `air_viscosity`（Sutherland 公式）、`air_conductivity`、`air_density`（理想气体）、`air_cp`（多项式）；水 `water_density/viscosity/conductivity/cp`（水黏度用 Vogel 式，0~90°C 误差<2%）。
  - `nu_water_gyroid_yan6(Re, Pr)`：水侧 Gyroid 的 Nu 关联式（Yan 等 2024 文献，`Nu=0.471·Re^0.627·Pr^(1/3)`）。
  - `parse_fluid_type / validate_fluid_type`：识别并校验流体（支持 air、water；sCO₂ 暂未开放，会报 NotImplementedError）。
- **输入/输出**：输入结构+工况，输出物性字典。压降用 D-F 形式 `dP/L = μu/K + ρ·c_F·u²`，K、c_F 来自 `df_surrogate.predict`。
- **依赖**：`tpms_geometry`、`nu_correlations`、`df_surrogate.predict`。
- **注意点**：Re 超出 [600, 30000] 会发警告；空气走 `nu_from_Re`（含 ×1.28 粗糙度增强），水走 `nu_water_from_Re`。

#### `nu_correlations.py` — 努塞尔数关联式（单一真相源）
- **作用**：全项目唯一的 Nu 关联式定义，避免多处重复。
- **公式**：`Nu = 1.28 × c·Pr^(1/3)·Re^a·(D_h/L)^d`。系数 `NU_COEFFS` 按 Diamond/Gyroid 分别拟合（基于实验记录表 v3.1）。`1.28` 是 SLM 表面粗糙度（Sa≈31 µm）带来的换热强化经验系数。
- **关键函数**：`nu_from_Re`（标量，空气）、`nu_vec`（向量化，给求解器网格用，带 Re_floor=10 防止 u→0 爆掉）、`nu_water_from_Re`（水侧，用普朗特数替换的雷诺类比）。
- **拟合区间**：`NU_RE_FIT_RANGE=(400,16000)`，越界发一次性警告。
- **注意点**：`eps_f` 参数为兼容保留但已不使用（2026-05-28 重构后）。

#### `fluid_props.py` — 流体物性派发
- **作用**：用一个 `FluidModel` 数据类把“空气/水”的密度、比热、黏度、导热、Nu 函数统一打包，消除散落各处的 `if fluid=='water'` 分支。
- **关键**：`FLUIDS` 字典（'air'、'water' 两项）、`get(fluid)` 查找。本质是个门面（facade），所有实现都转发给 `tpms_calc`。

#### `roughness.py` — 表面粗糙度修正（实验性，默认关）
- **作用**：提供按雷诺数变化的摩擦/换热粗糙度修正系数，用于敏感性研究。模式有 baseline（=1.0 不修正）、norris_1a（已退化为 1.0）、bhatti_shah_1b（按 Haaland/Petukhov 公式的真实修正）。
- **关键发现（2026-05-14）**：c_F 是用真实 SLM 实验压降训练的，已经隐含了粗糙度，再加摩擦乘子会**重复计算**，所以摩擦侧默认 1.0。
- **关键函数**：`f_enhancement`、`nu_extra_factor`、`apply_to_K_cF`、`f_petukhov`、`f_haaland`。

#### `continuous_field.py` — 连续场参数化（B 样条，优化用）
- **作用**：用一个 4×4 控制点网格 + 双三次 B 样条，把单元尺寸 L(x,y) 和壁厚 t(x,y) 描述成空间平滑渐变的场。这是优化器的“几何编码方式”。带 y 方向对称时决策向量是 16 维。
- **关键类**：`ContinuousFieldConfig`，方法有 `L_at/t_at`（点取值）、`evaluate_grid`（批量网格取值）、`build_grid_arrays`（生成求解器要的每格物性数组，带量化缓存加速）、`manufacturability_penalty`（可制造性惩罚：梯度太大或 t/L 比例越界会被罚，引导优化器避开难打印的设计）。
- **关键函数**：`decision_dim`、`decision_bounds`（L∈[4,8]mm、t∈[0.3,0.5]mm，绑定代理模型训练窗口）、`decode/encode_decision_vector`、`from_decision_vector`、`uniform_field`。
- **依赖**：`scipy.interpolate.RectBivariateSpline`、`tpms_calc`。

#### `sigmoid_field.py` — sigmoid 连续场（36 维）+ 几何查找表
- **作用**：另一种连续场生成方式，用 3×3 进口区 + 3×3 出口区 + 中间均匀区，用 sigmoid 平滑过渡函数拼出 L(x,y)、t(x,y)。还内置一个几何查找表（`GeometryLUT`）把 ε(L,t)、A_0(L,t) 预计算成网格，运行时双线性插值，省去反复体素化。
- **关键函数**：`sigmoid_field_2d`、`build_continuous_arrays`（总入口，从 36 维向量生成全套每格物性）、`get_geometry_lut`。
- **依赖**：`tpms_geometry`、`tpms_calc`、`scipy.interpolate.RegularGridInterpolator`。

#### `sigmoid_field_3d.py` — sigmoid 连续场的 3D 版（108 维）
- **作用**：把 sigmoid 场推广到三维，用 3×3×3 进口 + 3×3×3 出口控制立方体，张量积 sigmoid 混合，生成 (Nx,Ny,Nz) 的 L、t 场。决策向量 108 维。
- **关键函数**：`sigmoid_field_3d`、`build_continuous_arrays_3d`。
- **状态（2026-07 架构扫描）**：目前仅 `ui/demo_vis_3d.py` 与其测试引用，生产管线未接——保留待用，非遗漏。

#### `df_projection.py` — 把 2D/3D 设计投影到 SIMPLE 的 1D 阻力数组
- **作用**：SIMPLE 求解器内部用沿流向的一维 K、c_F 数组描述阻力；这个文件负责把优化器给的二维/三维几何设计“投影”成那种一维数组。还负责从 SIMPLE 收敛后的压力场里**提取压降**。
- **关键原则（2026-04-17）**：生产压降必须来自 SIMPLE 收敛压力场，不能用解析 D-F 公式直接算。
- **关键函数**：`build_master_refined_grid(_3d)`（带边界层加密的网格）、`project_cells/fields_to_streamwise_K_cF(_3d)`、`override_simple_K_cF`、`extract_dP_from_simple`（按开口比例加权）、`extract_dP_mass_flux_from_simple`（按质量流加权，偏置流型下更准）。

#### `zone_config.py` — 分区（已弃用于优化，仅界面遗留）
- **作用**：早期的“离散分区”方式——把域分成若干块，每块给不同的 L、t。`zone_config.py` 定义 `Zone`、`ZoneConfig` 数据类及生成每格数组的方法。
- **现状**：优化器已改用连续场（`continuous_field`），仅为界面“定义分区”功能保留。表格编辑辅助函数原在 `solvers/zone_editor.py`，已迁至 `ui/zone_table.py`（纯 Qt 表格操作，solvers/ 保持无 Qt 依赖）。

---

### 6.2 `solvers/` — 数值求解器内核

这一组是“真正解方程”的部分，也是计算量最大的部分。

> 2026-07-03（split-solver-kernels）：三大求解器文件的 numba 内核拆到独立模块 —— `_kernels_simple_2d.py`（2D SIMPLE 内核 + 压力泊松装配，~860 行）、`_kernels_simple_3d.py`（3D SIMPLE 内核 18 个，~830 行）、`_kernels_ltne_3d.py`（3D LTNE 内核 20 个，~1180 行）。原模块保留求解器类/网格构建器/Python 驱动/warmup，并全量 re-export 内核名（外部 import 面不变，逐字搬移、金档位相同）。

#### `_kernels_2d.py` — 共享小内核
- **作用**：把 2D 求解器里重复用到的 MINMOD 限制器抽出来，做成一个 Numba JIT 编译的函数（`minmod(gu, gd)`）。MINMOD 用于二阶迎风格式防止数值振荡：两侧梯度异号时返回 0（在极值处不修正），否则返回较小梯度。

#### `simple_solver.py` — 2D SIMPLE 流动求解器（~1290 行；内核在 `_kernels_simple_2d.py`）
- **作用**：在二维交错网格上用 SIMPLE 算法解多孔介质里的流动（动量+连续性），可选解冻结速度下的两温度传热。是上海工况 2D 验证的主力。
- **主类**：`SIMPLESolver`。构造时给域尺寸、网格数、物性、进口速度、孔隙率、K/c_F 数组、可压缩标志等。
- **关键方法**：
  - `solve(...)`：SIMPLE 主循环——x 动量扫掠 → y 动量扫掠 → 压力修正泊松方程（稀疏直接解）→ 修正速度和压力 → 查质量残差 →（可压缩时）更新密度。返回 (是否收敛, 迭代数)。`coupling='simpler'` 可选 Patankar/Tao SIMPLER 模式（实验性，openspec `simpler-coupling-2d`）——基准结论为负：精确直接解 PP 的 SIMPLE 无压力外迭代瓶颈，SIMPLER 的第二次椭圆解是纯开销（0.5-0.6×），默认勿用。低速/横流早退：`lowre_early_exit`（默认 True，3D 同款速度稳定性门控判据的 2D 移植，openspec `solver-efficiency-r1-r4`）——绝对质量残差平台工况从燃尽 max_iter 降到 ~26 iter（golden 管线 164× 提速）。
  - `solve_temperature(...)`：冻结速度下解流体+固体两温度（Gauss-Seidel）。
- **数值要点**：对流用迎风+二阶迎风修正（MINMOD）；多孔阻力线性化进源项；压力修正用 `ρ·ε·d` 加权；压力被钳在 [1 kPa, 10 MPa] 物理区间。
- **速度口径**：interstitial（孔隙内真实速度），进口 BC 用 `v=Q/(ρ·ε·A)`。
- **依赖**：`_kernels_2d.minmod`、`tpms_calc`、`df_surrogate.predict`。

#### `simple_solver_3d.py` — 3D SIMPLE 流动求解器（~1000 行；内核在 `_kernels_simple_3d.py`）
- **作用**：2D 的三维推广。在 3D 交错网格上解流动，压力泊松用代数多重网格（PyAMG）。
- **主类**：`SIMPLESolver3D`。多了 z 方向、PyAMG 重建节奏、粗网格预热、Anderson 加速等开关。
- **关键加速**：
  - 网格 >3 万单元（`_AMG_GATE=30000`）才启用 PyAMG，否则用稀疏直接解。PyAMG 层级每 100 步重建一次，并带“漂移检测”提前重建。
  - 网格 >20 万单元启用红黑 Gauss-Seidel 并行（Numba prange）。
  - `mass-flux inlet`（质量流入口，默认对理想气体开启）：固定 ρ·v 而非 v，避免可压缩正反馈发散——这是 2026-06-04 修复 air-air 偏置“跑飞”问题的关键。
- **关键方法**：`solve`、`extract_dP_weighted`、`extract_dP_mass_flux_weighted`、`update_T_field`、`apply_outlet_taper`。动量对流默认一阶迎风；`use_sou_momentum=True` 可选 minmod SOU（openspec `solver-efficiency-r1-r4`，实测 DF 源主导下 dP 差 <0.01%，故不扶正为默认）。
- **依赖**：`pyamg`（可选，缺失则退回直接解）、`anderson_acceleration`、`coarse_bootstrap_3d`。

#### `ltne_energy.py` — 2D 全域 LTNE 传热求解器
- **作用**：在整个域上同时解三个温度场（热流体 Ta、冷流体 Tb、固体 Ts），接受 SIMPLE 给的速度场。
- **关键函数**：`solve_full_domain(...)` → `(Ta, Tb, Ts, 迭代数, 是否收敛)`。内部用分块 Gauss-Seidel（每块 500 步，JIT 高效）；每格按“Ta→Ts→Tb”顺序更新；对流二阶迎风、扩散用调和平均面导热（在分区界面守恒）；支持部分进出口、温度欠松弛 `alpha_T`、可冻结 Tb。
- **依赖**：`_kernels_2d.minmod`。

#### `ltne_energy_3d.py` — 3D 全域 LTNE 传热求解器（~970 行；内核在 `_kernels_ltne_3d.py`）
- **作用**：`ltne_energy.py` 的三维版。三方向二阶迎风，可选“面心严格守恒离散”分支，内置能量/质量守恒残差审计。当 Nz==1 时直接委托给 2D 版本（逐位一致）。
- **关键函数**：`solve_full_domain_3d(...)`、`_project_faces_div_free`（可选把速度投影到无散场，保证严格能量守恒）、`energy_balance_3d/mass_balance_3d`（守恒审计）。
- **重要约定（ε 减半契约）**：调用方传完整 ε，内核内部自己做 `eps_f=0.5·ε`。历史上曾因“调用方先减半、内核又减半”导致 ε 被减成 1/4 的 bug，已修并有测试守护。

#### `anderson_acceleration.py` — Anderson 加速
- **作用**：给 SIMPLE 外层不动点迭代做“Anderson 加速”（用最近几步的残差历史外推，加快收敛）。
- **主类**：`AndersonSIMPLE`（参数：历史深度 m=5、每 K=3 步用一次、阻尼 β、条件数上限）。
- **关键陷阱**：Anderson 混合后的速度场**不再满足质量守恒**，调用方必须在每次 Anderson 步后立刻补一次压力修正，把速度投影回无散空间。

#### `coarse_bootstrap_3d.py` — 粗网格预热
- **作用**：先在半分辨率粗网格上把流场快速解个大概（松弛收敛），再三线性插值到细网格作热启动，省掉大网格的冷启动暂态。
- **关键函数**：`bootstrap_simple_3d(solver_fine, ...)` → 报告字典。当单元数 >3 万时自动启用。

#### `tpms_props.py` — 叶子模块：几何 + 流体物性关联式（arch-b-c-e B，2026-07-02）
- **作用**：`geometry()`、air/water 物性关联式、CHI_S 的唯一住所；df_surrogate 只 import 这里，打破了旧的 solvers↔df_surrogate 互赖。`tpms_calc` 全量 re-export，老 import 路径不变。import 方向锁定于 `tests/test_import_dag.py`。

#### `_solve_common.py` — SIMPLE 外循环共享骨架（arch-b-c-e C）
- **作用**：`LowReExit` —— 2D/3D 共用的低速/平台早退判据单一实现（速度稳定门控 + 平台失速），消灭"3D 修了 2D 漏"的双维护面。纯 Python 无 fastmath，浮点次序与原两份逐运算一致（golden bit-identical 门）。

#### `envelope.py` — 可压缩有效域守卫（choke 保护）
- **作用**：稳态低马赫求解器的有效域闸门。Forchheimer Δp 逼近入口绝压时流动壅塞、无稳态解，旧代码会静默返回 `converged=True` 的垃圾（负压、|v|~2000 m/s）。
- **关键函数**：`check_compressible_envelope`（解前 1D `P_out²` 种子 choke 预检）、`assess_solution_validity` / `gate_solution`（解后 Mach + 正压闸门）。由 `cfg['envelope_mode']` 驱动：`'raise'`（默认 → `ChokedFlowError`）/ `'warn'`（跑完但标 `envelope_valid=False`）/ `'off'`。
- **硬规矩**：**绝不**通过删守卫 / 放宽 `P_abs` 裁剪来“修” `ChokedFlowError` —— 那里没有稳态解，改工况（降速、缩短流向 L、提入口压力）。

#### `asym_split.py` — 偏置等值面 δ 的每侧孔隙率拆分（单一真相源）
- **作用**：非对称（offset-isosurface δ）时把总 ε 拆成 ε_A ≠ ε_B 的几何拆分比，2D/3D 管线共用。上游拆好传入（和 ≡ ε），内核**不再减半**。
- **关键函数**：`_asym_split_A`、`_eps_sides_for_run`、`_per_side_eps_override`。δ=0 与对称 ε/2 基线位相同。

#### `asym_geometry.py` — 偏置等值面几何量（marching cubes）
- **作用**：δ≠0 时用 scikit-image marching cubes 数值算每侧 A₀/D_h/壁厚/连通性（`percolates_z`），含 Richardson 3-网格外推消薄侧分辨率偏差。依赖 `scikit-image`（requirements 已列）。

#### `polygon_fvm.py` — 非结构三角网格有限体积求解器
- **作用**：在任意多边形域（如带集管的上海换热器）上用非结构三角网格解流动+LTNE。用 Rhie-Chow 插值防止压力棋盘振荡。
- **状态（2026-07 架构扫描，用户决策）**：polygon 链（本模块 + `unstructured_mesh` + `runs/polygon_calc`）当前只从 UI 菜单可达、生产管线未用——**有意保留**，是后续计划方向。
- **关键函数**：`solve_velocity_darcy`（达西流，直接解压力泊松）、`solve_velocity_simple`（完整 SIMPLE）、`solve_energy`（LTNE 三温度）、`solve_polygon_domain`（总编排）。
- **依赖**：`unstructured_mesh`、`tpms_calc`、`df_surrogate.predict`。

#### `unstructured_mesh.py` — 非结构网格生成
- **作用**：在多边形域内生成高质量三角网格，管理有限体积的面连接、边界分类、进出口管口位置。
- **主类**：`TriMesh`（节点、单元、单元中心/面积、邻居、面法向、边界类型）。`from_polygon` 工厂用 `triangle` 库做约束 Delaunay（失败回退 scipy）。
- **辅助**：`hexagon/octagon/rectangle/regular_polygon` 生成多边形顶点。

#### `polygon_calc.py` — 多边形域 CFD 编排（已迁至 `runs/`）
- **作用**：把界面输入接到 `polygon_fvm`，跑非结构网格 CFD，出温度/压力/速度三联图。四阶段：解析输入→建场→跑求解器→存结果（含单元值→节点值的体积加权、拉普拉斯平滑、百分位裁剪）。
- **位置**：界面耦合管线（读 widget、QMessageBox、matplotlib 绘图），未随 2D/3D 主路径迁入 `pipelines/`，现位于 `runs/polygon_calc.py`。

---

### 6.3 `df_surrogate/` — 压降代理模型

这一组是“用快速拟合代替昂贵 CFD 来预测压降系数”的模块。

#### `surrogate_v3.py` — 核心代理模型（ConstDF-v1）
- **作用**：用 RBF 插值，在三维特征空间 (L, t, ε_f) 上预测渗透率 K 和惯性系数 c_F。
- **怎么训练**：从实验 Excel（试验记录表）读每个几何的多个数据点，用可压缩 1D D-F 方程 `P_out² = P_in² − 2RT(μG/K + c_F G²)L` 做加权最小二乘，反解出每个几何的 K、c_F；再乘“边界效应系数”修正；c_F 设地板 1.0。然后对 log₁₀(K)、log₁₀(c_F) 做 cubic RBF 插值（smoothing=0.1）。
- **关键类/函数**：`SurrogateV3`（`predict(L,t,ε_f)→(K,c_F)`、`predict_dP`、`dump_prebuilt`）、`eval_shanghai`（上海 16 工况评估）、`eval_loo`（留一法交叉验证）。
- **关键常数**：空气气体常数 R=287.05；K 地板 1e-8（防止外推出非物理值）。
- **训练窗口**：L∈{4,5,6,8}mm × t∈{0.3,0.4,0.5}mm；L=8 时剔除 Re<1600 的过渡区点。
- **数据回退**：没有原始 Excel 时，从已提交的 `_prebuilt/*.csv` 重建 RBF（供 CI/克隆用）。

#### `predict.py` — 对外推断 API
- **作用**：运行时调用的高层接口，带缓存。
- **关键函数**：`predict_K_cF`（标量）、`predict_K_cF_vec`（向量化，给求解器网格用，~50 倍加速）、`predict_dP`（不可压）、`predict_dP_compressible`（可压缩，可选 strict 模式：堵塞时返回 NaN 而非兜底）。
- **可选残差修正**：环境变量 `TPMSHX_DF_RESIDUAL_CORR=1` 时叠加一层平滑修正。

#### `load_data.py` — 训练数据读取
- **作用**：从实验 Excel 读每个几何的训练数据，附加几何性质，做“防泄漏”检查。
- **关键防泄漏（重要）**：`load_all()` 会拒绝任何含 “shanghai/上海” 的文件名、t=0.6mm（上海特有壁厚）、L=7.0mm（上海特有单元）的数据——因为上海 16 工况是**预测目标**，训练集若混入就破坏了“样本外预测”的可信度。

#### `residual_correction.py` — 残差学习层（可选）
- **作用**：在 (log₁₀Re, ε_f) 空间上用 RBF 拟合代理模型的相对残差（捕捉低/高 Re 处的 U 形偏差），乘性修正压降，不改 K、c_F。默认关闭，需训练数据可用。

#### `_domain.py` — 训练窗口常数（单一真相源）
- **作用**：纯常数文件，定义代理模型的有效区间：`TRAIN_L=(4,8)`、`TRAIN_T=(0.3,0.5)`、`TRAIN_RE=(400,16000)` 及离散训练节点。重标定模型只改这里。

#### `surrogate_domain.py` — 窗口守卫
- **作用**：`check_surrogate_domain_at_point(...)` 在评估前检查某点是否落在训练窗口内；越界则按 `allow_extrap` 决定报错还是只警告（环境变量 `TPMSHX_ALLOW_EXTRAP=1` 可放行）。

#### `build_prebuilt_surrogate.py` — 预构建 CSV 生成器
- **作用**：在有原始 Excel 的机器上跑一次，把标定好的 (L,t,ε_f,K,c_F) 序列化成 CSV 提交进仓库，让没有原始数据的环境也能重建模型。`python -m df_surrogate.build_prebuilt_surrogate`。

#### `backend.py` / `gamma_df.py` / `smooth_df.py` — 后端注册表与实现
- **作用**：D-F 闭包后端派发（`TPMSHX_DF_METHOD` 环境变量选择）。默认 `gamma_df`：光滑 CFD 基线 × 实验锚定的粗糙度因子 γ（`cF = cF_smooth × γ`）；`rbf`（surrogate_v3 直拟实验 Δp）为可选。**两个后端都已含 SLM 表面粗糙度——严禁再叠乘摩擦/粗糙度系数（重复计入）。**

#### `kappa_asym.py` / `ingest_cfd_kappa.py` — 非对称 κ 修正（asym 家族）
- **作用**：偏置等值面每侧闭包的相对比修正：`X_asym(ε_side) = κ_X(r)·X_sym`，`r = ε_side/ε_sym`，X∈{K, c_F}，对称锚点 `X_sym = predict_K_cF(..., ε_total/2)`。相对比消掉共享的 CFD 出处（网格/湍流模型/AM 粗糙度因子），只留几何导致的每侧偏移。`ingest_cfd_kappa` 从外部 Fluent 每侧批跑 CSV（配套 `runs/cfd_asym/`）拟合单调 κ(r) 表。
- **恒等守卫**：默认关（环境变量 `TPMSHX_ASYM_KAPPA=1` 激活）；无 κ 表或 r≈1（δ=0）时 κ≡1 —— golden 与对称基线位相同不受影响。

---

### 6.4 `core/` 与 `configs/`

#### `core/evaluators.py` — 3D LTNE 综合评估器（中立层）
- **作用**：优化和验证共用的 3D 单设计评估函数。把一个决策向量端到端跑成 (Q, dP_A, dP_B, dP_total, mass)。
- **流程**：解码决策向量→2D 连续场→拉伸成 3D 数组→投影 K/c_F→（可选粗糙度修正）→建 SIMPLE 3D 求解器→冷启动解流场→外层 LTNE 耦合循环（最多 3 轮，更新密度/黏度）→积分换热量 Q（`Σ h_vB·(Ts−Tb)·dV`）和压降、质量。
- **关键函数**：`evaluate_3d(x_decision, cfg, ...)`、`_build_3d_arrays(...)`。带堵塞检测（1D 种子 P_out²≤0 时标记 invalid）。
- **存在意义**：打破“optimization → validation”的反向依赖（审计 2026-05-28 M4）。

#### `configs/shanghai_baseline.json` — 上海 16 工况规格
- **作用**：上海电气天然气加热器验证案例的权威规格。
- **内容**：几何（Gyroid，L=7mm，t=0.6mm，k_s=16）、域尺寸（空气侧流向长 0.182m、水侧 0.042m、轴向高 0.042m、36 个并联通道、单通道流通面积 1.80565e-5 m²）、元数据。
- **注意**：边界条件刻意不入规范（各审计脚本约定不同）；2026-05-28 把流向长从过时的 0.231 改成 0.182。

---

### 6.5 `controllers/` — 界面与求解器的契约层

这一组把“图形界面”和“数值求解器”解耦，让求解器不依赖 Qt。

#### 计算契约（contracts-layer 拆分后，2026-07-02）：`domain/compute_config.py` + `domain/compute_result.py`
- **作用**：dataclass 契约现在住在 `domain/`（controllers/pipelines/validation 都从下方 import，import 图成 DAG）。`ComputeConfig` 组合：`FluidConfig`、`GeometryConfig`（Lz=None 表示 2D）、`SolverConfig`、`PartialBCConfig`、`ZoneInputConfig`、`ExtrapPolicy`、`FeatureFlags`；属性 `is_3d` 由 Nz≥2 判定。`ComputeResult`（Q、dP、出口温度、场/系数/残差/诊断）同层独立模块。
- **关键方法**：`from_json/to_json/from_dict`（支持规范布局和上海基准遗留布局）。窗口采集在 **`ui/window_config.py` 的 `config_from_window(window, strict, force_3d)`** —— 唯一读控件处（鸭子类型，不 import Qt）。
- **依赖**：仅标准库。

#### `compute_pipeline.py` — 计算流水线抽象（统一 2D/3D）
- **作用**：用抽象基类统一 2D/3D 求解入口，三阶段状态机：`build_fields()` → `run_solvers()` → `finalize()`。
- **关键类**：`ComputePipeline`（抽象）、`Pipeline2D`/`Pipeline3D`（具体，委托给 `pipelines/` 的 stage 函数）、`CancelledError`。`pipeline_for(cfg)` 工厂按维度派发。`ComputeResult` 从 `domain.compute_result` import。
- **要点**：阶段间检查取消令牌，支持中途取消；进度回调在 20/90/100% 触发；stages 的 import 保持方法内懒加载（numba 链冷启动开销），非循环。

#### `compute_orchestrator.py` — Qt 原生求解线程生命周期
- **作用**：用 `QThreadPool + QRunnable + 信号` 取代裸线程轮询，跑后台求解。带重入保护、协作式取消、求解器 stdout 捕获（500KB 环形缓冲，给日志查看器）、各模式 ETA 历史。
- **关键类**：`ComputeOrchestrator`（信号：started/progress/finished/error/cancelled；方法：`start(mode, worker_fn, cfg)`、`cancel()`、`eta_seconds()`）、`CancelToken`。
- **要点**：取消是“协作式”的（设标志，不强杀线程，否则会破坏 Numba 状态）。

#### `result_cache.py` — 结果缓存
- **作用**：按模式（2d/3d/poly）集中存结果，带“脏标记”和“最近运行”环形缓冲。主窗口仍用旧属性名通过 @property 桥接访问。
- **关键类**：`ResultCache`（`set_result/get_result/has_results/push_recent/mark_drawn` 等）。

#### `session_manager.py` — 会话与预设持久化
- **作用**：把会话状态、用户预设、活动工作区（A/B/C）存盘，带版本号和**原子写**（先写临时文件再重命名，防崩溃损坏）。
- **关键类**：`SessionManager`（`load/save_session`、`load/save_user_presets`、`get/set_active_workspace`）。

#### `theme_manager.py` — 主题管理
- **作用**：包装 `ui.theme`，集中主题状态和切换通知；通过把样式镜像到模块全局变量，保持旧代码不改也能用。
- **关键类**：`ThemeManager`（`set_theme`、`current_styles`、`bind_to_module`）。注意：切主题不会自动重绘界面，需调用方重建控件。

#### `signal_router.py` — 信号路由注册表
- **作用**：集中登记所有 Qt 信号/槽连接，支持关机时统一断开，解决“绑定方法导致窗口无法释放”的引用环问题。
- **关键类**：`SignalRouter`（`connect/adopt/disconnect_one/disconnect_all`，用弱引用追踪发送者）。

---

### 6.6 `optimization/` — 多目标贝叶斯优化

#### `optimizer_qnehvi.py` — 优化主循环
- **作用**：用 qNEHVI 采集函数做多目标贝叶斯优化（同时最大化 Q、最小化 dP）。在 16 维设计空间上比遗传算法省 ~100 倍评估次数。
- **算法**：32 个 Sobol 初始点 → 每轮用高斯过程代理（每目标一个）+ qNEHVI 选 q=2 个新点 → 并行评估 → 算超体积，连续几轮无明显提升就提前停。
- **关键技巧**：dP 跨 4 个数量级，内部用 `−log₁₀(dP)` 作为目标（否则高斯过程精度差）；dP 硬钳在 1 MPa（未收敛的脏设计否则会读出几 MPa 假压降）。
- **关键函数**：`run_qnehvi(config, n_init, n_iter, q_batch, ...)`、`_eval_worker`、`_pareto_mask_max`、`hv_plateau_detected`、`_save_pareto_csv`。
- **依赖**：`torch`、`botorch`、`gpytorch`、`joblib`、`solvers.continuous_field`、`optimization.evaluator`。

#### `evaluator.py` — 2D 单设计评估器
- **作用**：优化循环的“物理引擎”。给一个决策向量，约 30~60 秒算出 (Q, dP, mass)。
- **流程**：解码→自适应网格→建 SIMPLE A/B→冷启动解流场→（外层 ρ(T) 耦合，默认 3 轮，可压缩硬约束）→LTNE 传热→提取 dP、积分 Q、算固体质量、加可制造性惩罚。
- **关键函数**：`evaluate_design(x, cfg, ...)` → `(−Q, dP, mass)`（负号是因为 BO 求最大）。
- **重要常数**：`tol_simple=1e-3`（偏松，过紧会在 Sobol 探索阶段 100% 拒绝）；`n_rho_loops=3`（可压缩耦合是硬要求）。`DEFAULT_CONFIG` 含 ~50 个默认键。

#### `evaluator_3d.py` — 3D 单设计评估器
- **作用**：包装 `core.evaluators.evaluate_3d`，把 Q 归一化成 W/m 让 3D 帕累托和 2D 同轴可比。
- **关键函数**：`evaluate_design_3d(x, cfg, ...)`。`DEFAULT_CONFIG_3D` 用快速网格 30×12×6。

#### `parallel_runner.py` — 多种子并行编排
- **作用**：用进程池并行跑 M 个独立 BO 种子（每个内部又有 joblib 并行），最后合并各自的帕累托前沿。为 12 核工作站设计（3 种子 × 4 内部 = 12 并发；OMP/MKL 线程钉为 1 防过载）。
- **关键函数**：`run_qnehvi_multiseed(...)`、`_seed_subprocess_main`、`_merge_paretos`。CLI：`python -m optimization.parallel_runner --seeds 3 ...`。

#### `export_ntop_csv.py` — 导出 nTop 标量场
- **作用**：把一个帕累托解（决策向量）转成 nTop 软件能读的标量场 CSV（[x_mm, y_mm, L_mm] 和 [x_mm, y_mm, t_mm]），用于真正建模出渐变 TPMS 零件。
- **关键函数**：`export_decision_vector(...)`、`export_pareto_row(...)`。CLI：`python -m optimization.export_ntop_csv --pareto ... --row 7 --out ...`。

---

### 6.7 `design/` — 快速定尺工具

给定工程需求（要冷却到多少度、流量、允许压降），反推一个 TPMS 换热器块的最优尺寸。

#### `cli.py` — 命令行入口
- **作用**：两种模式：`auto`（枚举所有 结构×L×t 组合找最优，可选精修）、`fixed`（给定单个结构直接定尺）。
- **CLI**：`python -m design.cli --xlsx cases.xlsx --arrangement cross --out out.xlsx [--refine] [--mode fixed --cell Diamond,6.0,0.4]`。

#### `cases.py` — 工况读取
- **作用**：定义 `DesignCase` 数据类（热/冷流体、进口温压、流量、热负荷或温降、压降上限），从 Excel/CSV 读多工况表。需要 openpyxl，处理 kPa→Pa、kW→W 换算。

#### `fluids.py` — 物性与 Nu 派发
- **作用**：统一接口取流体物性（ρ,μ,k,cp,Pr）和 Nu（空气用项目幂律，水用 Yan[6]），并给出各流体的 Nu 有效 Re 区间（空气 400~16000，水 150~3000）。

#### `forward.py` — 单工况正向评估
- **作用**：给定几何+工况，解 2D LTNE，返回出口温度、换热量、压降、雷诺数。底层复用 3D 求解器（Nz=1 退化成 2D）。
- **关键函数**：`forward(...)` → `ForwardResult`；`dP_fracs(...)`（解析 D-F 压降，无需解传热）。
- **要点**：叉流用 2D（α=0.7，早停）；逆流必须用 3D（Nz=2，低松弛 α=0.3），因为 2D 逆流会极限环振荡。

#### `sizing.py` — 最小体积定尺引擎（核心算法）
- **作用**：给定结构+单元参数，找让体积最小、同时满足所有工况冷却+压降约束的尺寸（宽度 s、长度 Lx）。
- **算法**：体积 V(s)=s²·Lx(s) 是 U 形（s 越大越好冷却→Lx 越小），用**黄金分割搜索** s；每个 s 下用 **Brent 法（brentq）** 求满足出口温度的 Lx（比二分快 ~3 倍）；最后做“全工况边界修正”（黄金最优点可能只满足主导工况，需二分上移到全工况可行）。带热启动（相邻 s 复用上一解）。
- **关键函数**：`size_fixed_cell(cases, topo, l, t, ...)` → `Design` 数据类；`solve_Lx(...)`。
- **关键常数**：建造包络 S_MAX=LX_MAX=0.45m；黄金迭代 10 次；dP 退化阈值 30%。

#### `select.py` — 离散枚举
- **作用**：在 {2 结构 × 5 个 L × 4 个 t = 40 组合} 上分别跑 `size_fixed_cell`（joblib 并行），标记帕累托最优（最小体积/最小重量/最小压降）。
- **注意**：L=7、t=0.6 超出代理训练节点，置信度较低。

#### `optimize.py` — 连续 (l,t) 精修
- **作用**：在枚举出的最优解附近，用 Nelder-Mead 单纯形法在连续 (l,t) 上精修体积（`--refine` 时调用）。收益通常 <1~3%。

#### `report.py` — Excel 报告
- **作用**：把枚举结果写成双 sheet Excel：“构型汇总”（40 个候选）+ “工况明细”（每个可行设计的逐工况性能）。用 pandas + openpyxl。

#### `examples/quick_design_template.xlsx`
- 工况输入模板，用户复制后填自己的设计工况。

---

### 6.8 `validation/` — 验证与校核

证明软件可信：和真实实验对比，并用数值方法学证明求解器正确。

| 文件 | 作用 | 关键指标/门槛 |
|---|---|---|
| `validate_shanghai_lumped_dual_nu.py` | 上海 16 工况的**集总 ε-NTU** 基准（不解流场，只用进口条件，无出口泄漏，论文级基准） | Q 误差 RMSRE **1.73%** |
| `validate_shanghai_3d_real.py` | 上海 16 工况的 **3D SIMPLE+LTNE 生产验证**（空气可压缩，水侧温度规定为线性） | dP 5.28% / Q 3.21%（Nz=3 门，mass-flux 入口后；现值以 `validation/_CSV_STATUS.md` 为准） |
| `validate_d76_3d.py` | Diamond L7/t0.6 的独立 3D 压降门，防止 D-F 代理模型外推失真 | D_7_6 有效工况，仅对 dP 评分 |
| `validate_shanghai_aligned.py` | 2D 验证，精确复刻界面“计算”路径，确保求解器按界面意图工作 | dP ~8.4%（mass-flux 入口后；现值以 `validation/_CSV_STATUS.md` 为准） |
| `mms_3d_air_air.py` | MMS 人造解法（用 sympy 推导解析解+源项）验证 3D LTNE 求解器离散一致性 | 单网格 rel L2<2%、Linf<3K |
| `mms_phase_a3_h_refine.py` | 5 套网格的 MMS 阶数验证（log-log 拟合观测收敛阶 p_obs） | p_obs≥1.5~1.8、网格30的 L2<1% |
| `mms_phase_a4_boundary.py` | 按边界区域（进口/出口/侧壁/内部）分解 MMS 误差，分别验证各边界格式 | 进口 L2<1e-12、内部阶数≥1.8 |
| `mms_phase_b4_order.py` | 验证“严格守恒”内核分支仍保持二阶精度 | p_obs≥1.8 |
| `phase_c_gci.py` | Roache GCI 网格收敛指数（用多套网格估离散误差） | GCI(网格20)<5% |
| `audit_3d_conservation.py` | 3D LTNE 能量/质量守恒审计（T1~T6 合成测试案例） | 每相能量残差 ε<1%、总<0.5% |
| `audit_partial_b_ltne.py` | 部分进出口下 LTNE 守恒的归档诊断（问题已修，只读存档） | — |
| `cross_check_water_nu.py` | 水侧 Nu 和文献（Wakao、Dittus-Boelter、Yan[6]）交叉核对 | 出对比图 |
| `verify_pareto_3d.py` | 把 2D 优化挑出的帕累托点拉伸到 3D 重算，量化 3D 物理修正 | 报告 ΔQ%、ΔdP% |
| `_provenance.py` | 给所有验证 CSV 加“出处头”（脚本名、git 提交、时间戳）保证可复现 | — |
| `_metrics.py` | 共享误差度量函数（RMSRE、偏差、最大相对误差） | — |
| `README.md` / `_CSV_STATUS.md` | 验证脚本索引 + CSV 现行/过时状态说明（引用数字前必读） | — |

---

### 6.9 `ui/` — 图形界面组件

基于 PySide6（Qt）的桌面界面，暗色“玻璃拟态”主题。

| 文件 | 作用 |
|---|---|
| `theme.py` | 主题系统（亮色 + 暗色玻璃拟态）：排版、间距、圆角、配色、按钮语义。 |
| `ui_builders.py`（~2190 行） | 构建所有界面控件：标题栏、参数标签页（布局/域/流体/分区/优化）、画布区。所有控件挂到 window 属性上。 |
| `field_factory.py` | 带主题注入的控件工厂（标签、输入框、结果标签、行、分区卡片），让 ui_builders 不依赖模块全局。 |
| `fmt.py` | 数字格式化（SI 前缀如 192.4 kPa、百分比、时长）。 |
| `math_symbols.py` | 把 `D_h`、`mu_f`、`rho_s` 等转成 Unicode 下标/希腊字母（Qt 标签不支持 LaTeX）。 |
| `expr_eval.py` | 输入框安全表达式求值（用户可输 `0.042/2`，基于 AST 白名单，不用 eval）。 |
| `ui_constants.py` | 提示时长、V&V 速度/雷诺数阈值等常数。 |
| `matplotlib_canvas.py` | matplotlib 画布，画 2D 等值线、分区热图、帕累托散点。 |
| `panel_vis_3d.py` | 嵌入式 PyVista 3D 可视化面板；构造阶段按工具栏、参数控件、操作控件、视口、状态和定时器拆分，渲染逻辑保留在同一组件内。 |
| `optimize_panel.py` | 优化器界面绑定（后台线程跑 qNEHVI、帕累托散点、点击载入解）。 |
| `quick_design_panel.py` | 快速设计面板（调用 design 模块定尺，结果表格）。 |
| `command_palette.py` | Ctrl+K 模糊搜索命令面板（仿 VSCode）。 |
| `zone_editor.py` | 布局画布上可拖拽的分区边界手柄。 |
| `sensitivity.py` | 敏感性扫描 N×N 热图（快速 0 维关联式，点格载入配置）。 |
| `sparkline.py` | 轻量内嵌迷你折线图（纯 QPainter，显示优化超体积历史）。 |
| `microanim.py` | 微动画（完成脉冲光、浮动提示气泡）。 |
| `glass_panel.py` | 暗色玻璃拟态背景图生成（渐变+光晕+颗粒）。 |
| `preflight.py` | 网格合法性预检（纯函数，可独立测试）：边界层加密能否放下、进出口覆盖、流向分辨率、单元数上限。 |
| `coord_inspector.py` | Ctrl+I 坐标检视停靠面板（鼠标悬停显示各场在该点的值，可钉点对比）。 |
| `session_overview.py` | 总览仪表盘对话框（KPI 卡片、Q 历史迷你图、预设快捷键、最近运行）。 |
| `demo_vis_3d.py` | 独立 3D 可视化演示脚本（无界面，跑上海 case 8 出 PNG）。 |
| `layout_drawer.py` | 几何布局绘制（2D 矩形/六边形/八边形、3D 立方体线框 + 进出口着色）。 |
| `vis3d_constants.py` | 3D 可视化共享常数（场顺序、配色、切片控件外观）。 |
| `delegates.py` | 自定义表格项委托（编辑时自动全选文本）。 |

#### `ui/mixins/` — 主窗口类的职责拆分

主窗口 `Main_Menu` 是个“上帝对象”，按职责拆成若干 mixin（Python 多继承混入），方法在运行时按 MRO 解析。

| 文件 | 作用 |
|---|---|
| `ui_builder.py` | 页面/标签/画布构建 + 状态栏/撤销栈/帮助安装。 |
| `run_controller.py`（~1100 行） | 计算运行编排：2D/3D/多边形入口、重入保护、预检、编排器信号处理、结果写回与画图、诊断摘要（`_diag_summary` + 诊断详情对话框）。 |
| `optimize_ui.py` | 优化 + 快速设计启动器（薄委托）。 |
| `zone_panel.py` | 分区面板按钮处理（委托给 ui.zone_table）。 |
| `fluid_input.py`（~450 行） | 每侧流体输入：自动填充物性、温度单位切换、流向/形状变化、布局绘制。 |
| `run_history.py` | 最近运行菜单、会话时间线、可复现链接、预设管理。 |
| `tab_view.py` | 标签切换（三页签工作台：几何布局/结果/优化，结果页内 2D\|3D 切换）、画布缩放、3D/2D 面板分离/重附。 |
| `dialogs.py` | 只读信息对话框（总览、求解日志查看器、快捷键速查）。 |
| `appearance.py` | 主题/密度/强调色切换与持久化（arch-b-c-e E 拆分）。 |
| `session_presets.py` | 会话保存/恢复 + 用户预设管理（arch-b-c-e E 拆分）。 |
| `shortcuts.py` | 快捷键装配 + 页签循环/最近运行滚动（split-ui-main 拆分）。 |
| `io_actions.py` | 导出结果/图像、存取配置对话框（split-ui-main 拆分）。 |
| `result_bridge.py` | ResultCache @property 桥（`_has_results*` 等；setter True 为 no-op 的陷阱注释在此）。 |

#### `main.py`（~1540 行） — 界面主程序入口
- **作用**：应用入口和主窗口类。
- **主类**：`Main_Menu(RunHistoryMixin, DialogsMixin, ZonePanelMixin, OptimizeUIMixin, TabViewMixin, UIBuilderMixin, FluidInputMixin, RunControllerMixin, AppearanceMixin, SessionPresetsMixin, ShortcutsMixin, IOActionsMixin, ResultBridgeMixin, QMainWindow)`（13 mixin）。
- **职责**：窗口初始化；持有编排器/会话/缓存/主题/信号路由五大控制器；温度单位切换；计算状态与重入保护；会话自动恢复；预检/onboarding（`__file__` 锚定，设计上留在 main）。
- **当前 UI 边界**：`builders_canvas.build_canvas_area` 只编排同文件的具名构建函数；`ThreeDVisPanel.__init__` 只编排控件、视口、状态和定时器初始化。没有第二个消费者的 Qt/PyVista 渲染逻辑继续留在原组件内。

---

### 6.10 `pipelines/` — 计算主路径（原 runs/run_calculation*.py）

界面“计算”按钮的实际求解编排。历史上是 `runs/run_calculation.py` / `run_calculation_3d.py` 两个巨型脚本，现拆为 Qt-free 的 stage 函数，由 `controllers/compute_pipeline.py` 的 `Pipeline2D`/`Pipeline3D` 按 `build_fields() → run_solvers() → finalize()` 调用（UI 侧入口在 `ui/mixins/run_controller.py` + `controllers/compute_orchestrator.py` 后台线程）。

2026-07-03（split-pipelines）再拆一层：`stages_2d`/`stages_3d` 只留 **cfg 边界**（parse/build/run_cfg/finalize）并全量 re-export 迁出符号（外部 `from pipelines.stages_3d import _run_3d_stack` 等 import 面零变更）；引擎按下表分家。依赖是 DAG：`flux_3d`/`grid_3d` ← `run_stack_3d` ← `stages_3d`；`solve_2d` ← `stages_2d`。

| 模块 | 内容 |
|---|---|
| `stages_2d.py`（~780 行） | 2D cfg 边界：`_parse_inputs_cfg`（防单位滑移、代理窗口守卫、分区配置）→ `_build_fields_cfg`（对齐/加密网格、4 流向坐标变换、K/c_F 覆盖）→ `_run_solvers_cfg` → `_finalize_cfg`。 |
| `solve_2d.py`（~1240 行） | 2D 引擎：`_run_solvers`（外层 LTNE 迭代耦合可压缩 SIMPLE）、`_compute_Q_richardson`、`_compute_pressure_2d`（按开口比例加权提 dP）、`_enthalpy_balance_2d`、`_PipelineWindowShim`。 |
| `stages_3d.py`（~360 行） | 3D cfg 边界：`_parse_inputs_3d_cfg` → `_build_fields_3d_cfg` → `_run_solvers_3d_cfg` → `_finalize_3d_cfg`（render/export 契约锁在 `tests/test_finalize_3d_result_sync.py`）+ re-export 块。 |
| `run_stack_3d.py`（~2020 行） | 3D 引擎：`_run_3d_stack`（核心循环，被诊断/演示/优化直接调用）、`_run_two_simple_parallel`（A、B 两股 SIMPLE 并行，独立线程释放 GIL）、`_conservation_diagnostics_3d`、choke 种子 `_seed_p_ref`、剖析（`TPMSHX_PROFILE_3D=1`）。 |
| `flux_3d.py`（~250 行） | 面通量加权（`_face_flux_weights`、`_mass_weighted_T_out/h_out`、`_simple_mass_flow`）+ 粗糙度施加（`_apply_roughness_KcF/h_v`）+ sCO2 局域 h_v。 |
| `grid_3d.py`（~160 行） | 轴映射 `_resolve_axis_map`、分区场 `_build_zone_fields_3d`、网格 `_build_grid_3d`、间距 `_solver_spacings`。 |
| `stages_3d_helpers.py`（~460 行） | Phase-3 早期抽出的纯 numpy 助手（χ_B 阈值等）。 |
| `_stage_common.py` | 2D/3D 共享非内核胶水（域尺寸防火墙、外推守卫、safe_float、props 三元组）。 |

- **2D 要点**：**出口锚定**（与 3D 同一契约：`P_ref_abs` = 出口绝对压，一维可压缩闭式播种。旧文案"入口锚定、很少 choke"描述的是 2026-07-12 修复的生产 bug——台账 C8——不是设计；2D 目前仍无预解 choke 守卫，台账 O1）；`rho_inlet_ref` 显式传参防外迭代 ratchet。
- **3D 要点**：ε 减半契约（调用方传完整 ε；asym 例外见 `solvers/asym_split.py`）；出口锚定 —— `solvers/envelope.py` 的 choke 守卫主要在这里生效；外层 ρ(T) 耦合循环（默认 max_outer=5，A、B 都收敛就早停）；边界层加密单元数封顶 ~5 万。

---

### 6.11 `runs/` — 生产/演示/诊断脚本

生产入口 + 助手脚本；golden gate（`runs/_out/_golden_2d.py`、`_golden_3d.py`，gitignored，本地）也挂在这里。计算主路径已迁往 `pipelines/`（见 6.10）。

| 位置 | 文件 | 用途 |
|---|---|---|
| 根 | `run_production_qnehvi.py` / `run_production_qnehvi_parallel.py` | 生产级贝叶斯优化（~80 次评估，45~75 分钟）/ 并行版（~2 倍加速）。 |
| 根 | `run_3d_qnehvi_fast.py` | 3D 快速模式优化（小网格、少迭代）。 |
| 根 | `polygon_calc.py` | 多边形域 CFD 编排（polygon 链，有意保留，见 6.2）。 |
| 根 | `benchmark_simpler_2d.py` / `benchmark_sou_3d.py` | SIMPLER 耦合 2D / 3D SOU 动量的性能基准。 |
| 根 | `_case_template.py` / `_smoke_boot.py` | 工况模板 / 冒烟引导助手。 |
| `demos/` | `demo_3d_air_air.py`、`demo_3d_cube_air_air.py`、`demo_3d_cube_volume.py`、`demo_vis_3d_interactive.py` | 3D 演示与交互式可视化。 |
| `smokes/` | `smoke_ui_offscreen.py`、`smoke_ui_screenshots.py`、`smoke_ui_3d_modes.py`、`smoke_ui_2d_pipeline.py`、`smoke_ui_3d_pipeline.py`、`smoke_3d_eval.py` | UI 离屏实例化/截图、2D/3D 管线端到端、3D 评估计时。 |
| `diagnostics/` | `asym_geometry_scan.py`、`asym_a0_convergence.py`、`asym_target_scan.py`、`asym_porosity_preview.py`、`asym_geometry_report_html.py` | asym 几何扫描/收敛/预览/报告。 |
| `tools/` | `asym_build_cfd_design_xlsx.py`、`asym_build_cfd_worklist_xlsx.py`、`asym_plan_to_html.py`、`render_3d_styles.py` | CFD 工况簿构建、HTML 渲染、3D 出版图。 |
| `cfd_asym/` | `asym_pyfluent_runner.py`、`asym_postproc_kappa.py`、`asym_ntop_expressions_html.py` | Fluent 交叉验证批跑（PyFluent）、κ 后处理（喂 `df_surrogate/ingest_cfd_kappa`）、nTop 表达式。 |

---

### 6.12 `domain/` 与仓根工具目录 `poc/`、`benchmarks/`、`examples/`

> 2026-06-10 Batch-5：`poc/`、`benchmarks/`、`examples/`、`opt_runs/` 从包内迁至仓库根（非库代码不再随 `import sjtu_tpmshx` 分发）；脚本自带 sys.path bootstrap，从仓根运行。

#### `domain/validator.py` — 输入校验（纯函数，无界面）
- **作用**：拿标量/字典返回警告或抛 ValueError。
- **关键函数**：`validate_geometry(...)`、`validate_fluid(...)`（sCO₂ 仍抛 NotImplementedError）、`suggest_grid_2d/3d(...)`（启发式网格建议，3D 封顶 5 万单元）、`compute_volumetric_htc(A_0, H_sf)`。

#### `poc/poc_1d_ltne_strict_conservation.py` — 1D 严格守恒概念验证
- **作用**：用面心 Moukalled 有限体积格式做 1D LTNE，验证“两股逆流 + 非均匀孔隙率”下能否做到严格守恒（`|Q_enth_A|=|Q_sA|=|Q_sB|=|Q_enth_B|`）。用于论证生产 3D 内核采用面心格式。

#### `benchmarks/benchmark_a.py` — 性能基准
- **作用**：测 5 个场景的耗时（冷导入、热导入、遗留验证脚本、50 工况串行/并行批跑），出 JSON 和与基线对比。

#### `examples/demo_vis_3d_interactive.py` — 交互式 3D 可视化
- **作用**：PyVista 交互窗口看 3D 解场（[f]切换场、[1/2/3]切片法向、[s]截图）。`--test` 离屏、`--real-aspect` 保持真实比例。

---

### 6.13 `tests/` — 测试套件总览（~120 文件）

用 pytest（配置在仓根 `pytest.ini`：testpaths、`slow`/`fast` 标记注册、strict-markers）。`conftest.py` 负责：在导入 PySide6 前设 Qt 离屏平台、把包根加入 sys.path、预建 QApplication。

| 类别 | 守护什么 | 代表文件 |
|---|---|---|
| 求解器核心 | SIMPLE、能量、3D 耦合 | `test_simple_solver_3d.py`、`test_ltne_energy_3d.py`、`test_anderson_simple.py` |
| MMS 与验证 | 人造解法、收敛阶、边界格式 | `test_mms_phase_a3_gates.py`、`test_mms_phase_a4_gates.py`、`test_mms_b4_conservative_order.py` |
| 守恒与能量平衡 | 严格能量守恒、质量平衡 | `test_conservation_3d_energy.py`、`test_mass_flow_consistency_3d.py` |
| 回归与验证 | 上海 16 工况基准、防数据泄漏 | `test_shanghai_regression.py`（环境变量开启的慢测）、`test_load_data_no_shanghai.py` |
| 界面与配置 | ComputeConfig、流水线、校验器 | `test_compute_config.py`、`test_compute_pipeline.py`、`test_domain_validator.py` |
| 几何与场 | 分区、连续场、网格加密 | `test_continuous_field.py`、`test_sigmoid_field.py`、`test_field_factory.py` |
| 物性与关联式 | Nu、Re、密度/黏度、流体类型 | `test_nu_correlations.py`、`test_fluid_props.py`、`test_fluid_type_validation.py` |
| 流水线与编排 | stage 函数、编排器、结果契约 | `test_compute_pipeline.py`、`test_compute_orchestrator.py`、`test_finalize_3d_result_sync.py` |
| 边界与部分流 | 部分进出口、ghost 单元 | `test_partial_bc_ghost_b.py`、`test_chi_b_reverse_mirror.py` |
| 3D 方向与对称 | 6 个流向派发、反向镜像不变性 | `test_3d_direction_invariance.py`、`test_3d_reverse_mirror.py` |
| 优化与代理 | 代理预测、优化器辅助、导出 | `test_predict_K_cF_vec_batch.py`、`test_optimizer_qnehvi_helpers.py`、`test_export_ntop_csv.py` |
| 冒烟与集成 | 界面实例化、流水线端到端 | `test_main_smoke.py`、`test_pipeline_2d_smoke.py`、`test_evaluator_sanity.py` |
| design 子模块（`tests/design/`，15 文件） | 定尺、枚举、工况读取 | `test_cases.py`、`test_sizing_inner.py`、`test_optimize.py` |

运行示例：`python -m pytest sjtu_tpmshx/tests/ -q`（全套件）；`python -m pytest -q -m "not slow and not heavy"`（开发子集，同 CI）；`TPMSHX_RUN_SHANGHAI_REGRESSION=1 python -m pytest sjtu_tpmshx/tests/test_shanghai_regression.py -v`（慢回归）。

---

## 7. 典型工作流（怎么用）

1. **图形界面跑一次正向计算**：在 `sjtu_tpmshx/` 目录内运行 `python main.py`（仓库根无 main.py） → 填几何/流体/边界 → 点“计算”（2D 走 `pipelines/stages_2d.py`，3D 走 `pipelines/stages_3d.py`，后台线程由 `controllers/compute_orchestrator.py` 管理）→ 结果页看温度/压力/速度场 + 诊断侧栏。

2. **命令行快速定尺**：准备工况 Excel（照 `design/examples/quick_design_template.xlsx`）→ `python -m design.cli --xlsx cases.xlsx --arrangement cross --out out.xlsx` → 得双 sheet Excel 报告。

3. **多目标优化**：`python -m optimization.parallel_runner --seeds 3 --n_init 32 --n_iter 24` → 得帕累托前沿 CSV → 可用 `optimization/export_ntop_csv.py` 导成 nTop 标量场建模。

4. **验证可信度**：`python validation/cases/validate_shanghai_lumped_dual_nu.py`（论文基准 Q 1.73%）或 `validation/cases/validate_shanghai_3d_real.py`（3D 生产验证）。引用任何数字前先读 `validation/_CSV_STATUS.md`。

---

## 8. 全局约定与常见陷阱

1. **单位混用**：域尺寸 L/H/Lz 用**米**，但 TPMS 单元尺寸 L_cell、壁厚 t 用**毫米**。代码有防御性检查（域>10m 报错）。
2. **必须可压缩**：任何求解器重构都要保留空气 `ρ=ρ(P,T)` 理想气体。丢掉可压缩耦合会让上海 3D 压降误差从 ~18% 退化到 ~39%。
3. **速度口径统一 interstitial**（孔隙内真实速度），不要和 superficial（表观）混用。
4. **粗糙度别重复算**：c_F 已用真实 SLM 实验压降训练（隐含粗糙），Nu 已含 ×1.28。再加摩擦乘子 = 重复计算。
5. **防数据泄漏**：上海 16 工况是预测目标，训练集严禁含 t=0.6mm 或 L=7.0mm 的点（`df_surrogate/load_data.py` 会拒绝）。
6. **Qt-free 契约**：求解器、配置、校验层刻意不依赖 PySide6，方便无界面测试和批跑复用。读 Qt 控件只在 `ui/window_config.py` 的 `config_from_window` 一处（contracts-layer 拆分，2026-07-02）。
7. **ε 减半契约**：3D 内核约定调用方传完整 ε，内核自己 `eps_f=0.5·ε`。曾因双重减半出 bug，现有测试守护。
8. **mass-flux 入口**：3D 默认对理想气体用质量流入口（固定 ρ·v），避免可压缩正反馈“跑飞”。
9. **代理外推**：几何超出训练窗口（L∈[4,8]、t∈[0.3,0.5]）时，代理会把 K 钳到地板，需用 `TPMSHX_ALLOW_EXTRAP=1` 显式放行。

---

*文档结束。如需更深入某个文件，请直接阅读对应源码——本文已给出每个文件的定位、关键函数和数据流，可作为索引。*
