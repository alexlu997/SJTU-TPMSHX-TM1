# 原始 V0.1 需求转录

来源：用户在本对话提供的《TPMS 均质化换热器流动换热求解软件——总体框架说明》Word，WK，2026.09.08，V0.1。
以下按原文顺序转录，整理换行与表格；原文重复／跳转的章节编号保留。后来的 Python 路线、并行节点和自动合并授权来自用户后续说明，不混写为 V0.1 原文。

## 1. 项目目标

建立一套基于均质化模型的 TPMS 换热器快速流动与传热求解平台。
核心代码既可独立完成计算，也可作为换热器设计、参数优化、拓扑优化和 GUI 软件的统一计算内核。

- 前处理、求解器、后处理相互独立，通过标准数据接口通信。
- 求解器采用可插拔架构：自研 C/C++、OpenFOAM 及其他外部求解器均实现统一接口。
- 微观 TPMS 单胞用于获得均质化闭合参数；宏观换热器采用均质化模型快速求解，不直接解析 TPMS 真实曲面。

## 2. 总体软件架构

| 层级 | 主要模块 | 职责 |
|---|---|---|
| 应用层 | 设计 / 参数优化 / 拓扑优化 / GUI / CLI | 调用公共 API 完成工程设计与优化，不访问求解器内部实现 |
| 工作流层 | Case 管理 / 参数管理 / 任务调度 / 日志 | 组织完整计算流程并统一调用前处理、求解与后处理 |
| 前处理与后处理 | Geometry / Mesh / Data / Visualization | 准备计算数据；读取统一结果并计算工程性能指标 |
| 求解器接口层 | ISolver / Native / OpenFOAM / External | 对所有求解器提供统一调用方式 |
| 模型与公共数据层 | 物性 / 均质化 / 边界 / CaseData / FieldResult | 提供稳定、可复用、与求解器后端无关的数据与物理模型 |

核心原则：模块之间只通过明确的公共接口和数据结构通信；上层应用不依赖具体求解器。

## 2. 核心模块

### 2.1 前处理 Preprocessor

- 宏观换热器几何与可选的 TPMS 微观单胞几何。
- 网格生成/导入、材料与流体数据、边界条件。
- 实验数据、详细 CFD/DNS 数据的清洗与拟合。
- 均质化参数计算、读取、插值和 Case 构建。
- 以 Python 负责流程，性能敏感部分可由 C++ 实现。

### 2.2 均质化模型 HomogenizationModel

- 就是让求解器能够识别的求解模型（为了后续接入通用求解器加入的中间处理层）。
- 独立于求解器后端。
- 关键方向性参数优先采用张量数据结构。

### 2.3 流体物性 FluidPropertyProvider

- 物性与控制方程解耦（便于后续维护和优化），不在求解器内部硬编码 ρ、cp、μ、k、h。
- 支持常物性、表格、拟合、CoolProp/REFPROP 适配器及用户自定义模型。
- 面向 SCO₂ 时必须支持 T-P 相关的强变物性。

### 2.4 求解器 Solver

- 统一 ISolver 接口，至少包含 NativeSolver、OpenFOAMSolverAdapter、ExternalSolverAdapter。
- 自研求解器采用有限体积法 FVM；内部拆分连续性、动量、能量、源项、离散算子、线性求解器、边界条件和收敛控制。
- 动量模型逐步支持 Darcy → Darcy-Forchheimer → 各向异性。
- 能量模型逐步支持 LTE → LTNE。

### 2.5 后处理 Postprocessor

- Python 负责场数据读取、工程性能计算、可视化和报告输出。
- 至少输出 ΔP、Q、h、Re、Nu、f、PEC 等所需参数及优化目标/约束。

## 5. 标准接口与数据格式

- 标准数据流：Input → CaseConfig → Preprocessor → CaseData → SolverAdapter → FieldResult → Postprocessor → PerformanceResult。
- 输入/输出文件：case.yaml、case.h5、results.h5、results.vtk、metrics.json。
- 所有内部物理量统一采用 SI 单位，序列化数据必须包含 schema_version。
- Python 与 C++ 可以通过 pybind11 连接；必要时再提供稳定 C API 以支持更广泛外部调用。

| 核心对象 | 作用 |
|---|---|
| CaseData | 统一描述几何、网格、材料、物性、均质化参数、边界和求解设置 |
| HomogenizedProperties | 保存孔隙率、K、k_eff、惯性阻力及界面换热等闭合参数 |
| ISolver | 所有求解器后端必须实现的公共求解接口 |
| FieldResult | 所有后端统一返回的场数据结果 |
| PerformanceResult | 面向工程设计和优化的标量性能指标 |

## 3. 后续设计与优化扩展

- 设计变量可包含孔隙率、单胞尺寸、壁厚、TPMS 类型、方向、空间梯度、宏观尺寸及质量流量等。
- 可扩展 DOE、GA、PSO、NSGA-II、贝叶斯优化、梯度优化和代理模型。
- 拓扑优化只改变设计场/均质化参数场，通过现有 Solver 接口完成求解；第一阶段仅预留梯度/伴随接口，不急于实现。

## 4. 工程目录（建议）

| 目录 | 职责 |
|---|---|
| include/interface/ | C++ 公共接口与数据结构 |
| src/core, mesh/ | 核心数据、网格 |
| src/homogenization, properties/ | 均质化模型与流体/材料物性 |
| src/solver/native/ | 自研 C++ 求解器 |
| src/adapters/openfoam, external/ | OpenFOAM 及第三方求解器适配层 |
| python/tpms/ | 前处理、后处理、工作流、优化和可视化 |
| schemas/ | Case/Result 数据格式定义 |
| apps/ | CLI、设计软件、优化软件、未来 GUI 入口 |
| tests/ | unit / regression / validation / benchmark |
| examples/ 和 docs/ | 标准算例、验证案例和技术文档 |
