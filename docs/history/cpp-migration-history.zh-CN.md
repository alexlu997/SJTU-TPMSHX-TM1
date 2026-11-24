# C++ 迁移与 ABI 演进历史

[中文](cpp-migration-history.zh-CN.md) | [English](cpp-migration-history.md)

本文档归档历史 C++ 迁移阶段、已退役 ABI 版本及过往数值资格检查记录。
当前受支持的行为与接口见[C++ 接入说明](../cpp-migration.zh-CN.md)、[原生阶段接口](../native-stages.zh-CN.md)和[架构说明](../architecture.zh-CN.md)。
所有原始历史数值、容差与失败结论均保持原状。

## 求解器迁移阶段（0.1 至 0.2 版本）

0.1 版本同时保留 Python 和 C++ 两个数值后端。
[0.1 版本架构文档](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/v0.1.0/docs/architecture.zh-CN.md)记录了当时的双后端比较标准：换热量、压降和质量流量差不超过 0.1%，温度差不超过 0.01 K，速度差不超过 `1e-6 m/s + 1e-5 * u_inlet`。
[0.1 版本迁移记录](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/v0.1.0/docs/cpp-migration.zh-CN.md)中的历史双后端比对结果仅对应当时构建。
0.2 版本退役了 Python 数值后端、Numba/PyAMG 依赖及纯 Python 研究入口（`prepare_research_case` 与 `research_three_d_v1`）。

| 阶段 | 历史实现边界 | 进入下一阶段前的必需证据 |
| --- | --- | --- |
| 0：热学算子 | 独立原生扫描与能量审计算子；Python/C++ 混合选择器已退役。 | 算子检查以及公共场、通量、指标、交接、取消和错误对比。 |
| 1：完整热学驱动 | 按原顺序移植 Picard 状态、物性刷新、EOS 反演、残差、热启动和合作式取消。 | 固定入口、压力和网格输入，保持 A/B/固体方程与边界能量门槛不变。 |
| 2：流动与耦合 | 移植矩形算例的 SIMPLE、压力与质量修正及外循环耦合。 | 动量与新密度 F2 门槛、物理入口压力、出口回流与能量检查。 |
| 3：完整 C++ 后端 | 消费 `CaseData` 并产出完整 `FieldResult`，不调用 Python 求解核。 | 独立进程交接、单位、场位置、模型来源及不支持模式的显式拒绝。 |
| 4：应用与发布 | 通过 `solvers.api` 向 GUI、快速设计、优化和离线后处理提供 C++ 后端。 | 固定算例对比，以及 macOS arm64 和 Windows x64 的构建与打包证据。 |

### 2026-09-21 CoolProp 二进制检查

2026-09-21 对本地 CoolProp 7.2.0 wheel 的检查显示其包含 C++ 头文件和 MIT 许可证。
但其中二进制文件为 CPython Mach-O bundle，而非可独立链接的 `libCoolProp` 库。
独立 C++ 链接因不支持的 Mach-O 文件类型失败，该环境中也不存在独立静态库或动态库。
该次检查未下载源码或安装依赖。
随后项目采用独立离线构建的 CoolProp 8.0.0，锁定配置见 [dependencies-lock.toml](../../engineering/native_build/dependencies-lock.toml)。

### 已退役的数值路径与求解选项

- **冻结 H-FOU、H 扫描 C 导出与 T-FOU**：在 T-SOU 成为保守 EOS 能量默认算法后退役。历史 `enthalpy_eos`、`sco2_enthalpy_eos`、FOU 配方 1 及 SOU 配方 1/2 记录保持可读。
- **外层物性 Anderson**：在完整三维 ABI 2 中退役。固定物性松弛与热学 Anderson 继续保留。
- **单侧 A 路 sCO2 执行**：已退役。带有 `legacy_frozen_cp_single_a_cc_v1` 的归档结果保留其缺少完整 `h(P,T)` 输运的状态。
- **完整三维 true-h 预热扫描**：私有 G4 迭代行与专用交错预热行已退役；前段准备在进入 EOS 求解前执行零次温度扫描。
- **变比热 `m*cp*T` fullCC 方案**：因物理契约失败退役，由严格积分 `h(T)` model-h 驱动替代。
- **初代 AMGCL 压力候选**：因完整算例比对未通过被替换，现采用 SuperLU/COLAMD（<= 2,000 单元）与经典代数多重网格；AMGCL 仅保留用于交错温度投影。
- **其他已退役求解选项**：二维 `SIMPLER` 分支、B 侧部分开口实验（M4 面积缩放、参与掩码、温度冻结、H2 出口导热抑制）、`tol_simple` / `TPMSHX_SIMPLE_TOL`、`TPMSHX_TRUE_H_KERNEL`（`numba`、`cpp_sweeps_v1`）、`energy_nan_hit` NaN 替换入口值逻辑、高斯显示滤波，以及 `postprocess.report` / `postprocess.visualization`。

## 2026-11 C++ 核心迁移里程碑

2026 年 11 月，六个阶段将剩余数值核从 Python 迁移至四个独立的 C++ 共享库：

- **模型数据收敛**：[PR #275](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/275) 将公共常量统一至 `model_parameters_v1.json` 及生成的 C++ 头文件。
- **原生几何核心**：[PR #276](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/276) 引入 `geometry/`（geometry ABI 2）。
- **原生网格与设计场**：[PR #277](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/277) 将网格、端口、连续样条、sigmoid 场、LUT 和分区移入 `tpmshx_geometry_shared`（field ABI 3）。
- **原生准备核心**：[PR #278](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/278) 建立独立的 `preprocess/` CMake 工程。
- **原生结果核心**：[PR #279](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/279) 建立支持 Linux/macOS/Windows 独立评估的 `postprocess/`。
- **使用方清理**：移除过时的 GUI 插值导入、`shared/models/grid_3d.py`、`asym_split.py`、`shared/models/quick_design.py`、Python 二维准备流程及 `tpms_calc._compute_cached` 数值实现。

### 阶段 ABI 渐进演进记录（2026-11，已于 2026-11-23 与 2026-11-24 退役）

2026-11 迁移期间，二维与三维阶段接口曾按以下顺序渐进扩展，现已统一收敛：

| 已退役系列 | 2026-11-23/24 收敛前的渐进版本 |
| --- | --- |
| 二维准备 v1–v6 | v1 均匀对称空气/空气；v2 16 组流体与标量标记；v3 均匀总流量；v4 连续 XY；v5 条带／矩形；v6 sigmoid 与 LUT。 |
| 二维准备 v7–v11 | v7 `GridKinds2D` 窄标量标记；v8 空间总流量；v9 带类型缓存回调；v10 非零 `delta_levelset` 侧几何；v11 孔隙率与条带水力半径。 |
| 三维准备 v1–v5 | v1 均匀三维；v2 三维总流量；v3 连续 XY/XYZ 三维；v4 XY 网格矩形与全局偏移；host v5 共享缓存回调。 |
| 二维与三维阶段运行 | 二维一次性运行 v1–v4、保存描述符 v1–v4 与三维一次性运行 v1–v2（已由扁平保存态二维 v5 与三维 v3 替代）。 |
| Quick Design v1 与宿主操作 | 原生双精度 v1 准备／运行、14 个未使用的 `quick_*` C 入口、`QuickProtocols` 回调及 30 项原始对象宿主回调表。 |

## 2026-11-23 与 2026-11-24 ABI 收敛与清理（D1 至 D4）

| 阶段 | 日期 | PR 或提交 | 退役接口与变更摘要 |
| --- | --- | --- | --- |
| Phase 1 | 2026-11-23 | [PR #357](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/357) | 清理测试布局并退役未使用的开发脚本。 |
| Phase 2 | 2026-11-23 | [PR #358](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/358) | 将 C ABI 收敛为现行生产入口；移除二维/三维准备 v1–v11 前序入口、Quick Design v1、二维运行 v1–v4、三维运行 v1–v2、二维 v6/三维 v5 之前的直接求解入口、结果查询 v2、`tpmshx_result_platform_info_v1` 及 14 个未使用的 `quick_*` C 入口。 |
| Phase 3A | 2026-11-23 | [PR #359](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/359) | 在 Result ABI 3（`tpmshx_stage_input_v3`）下将结果核心规范化为 `float64` 与 `int32` 标签；退役 `QuickProtocols` 回调。 |
| Phase 3B | 2026-11-24 | [PR #360](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/360) | 将准备、几何、场与 Quick Design 接口规范化为 `float64`；退役窄标量/`binary16` 模拟、Quick 原始对象宿主操作回调及全流程测试参考，保留纯公式测试参考实现。 |
| Phase 3C | 2026-11-24 | [PR #362](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/362) | 扁平化全部准备与保存阶段运行 C 结构体（移除嵌套 `values` 链），统一回调为 `tpmshx_preparation_callbacks_v1`，二维/三维准备族改用简洁 `v1` 符号，并统一二维保存态 ABI 5 与三维保存态 ABI 3。 |
| Phase 4 | 2026-11-24 | [PR #363](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/363) | 退役 Python 直接完整驱动（`NativeFull2DDriver`、`NativeFull3DDriver`、`prepared_*`），移除已退役的清单节点并缩短原生 CI 路径。 |
| Phase 5 | 2026-11-24 | [PR #364](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/364) | 重写架构、原生阶段、C++ 接入和 `python/README` 双语文档，使其仅描述 D4 之后的现行接口，并将历史记录归档至此。 |
| Phase 6A | 2026-11-24 | [PR #365](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/365) | 退役未发布的温度、焓、model-h、SIMPLE 二维与 SIMPLE 三维单驱动 C ABI 及其 C 冒烟测试。移除直接求解、续算与完整结果释放导出（`tpmshx_solve_full_2d_v6`、`tpmshx_solve_full_3d_v5`、`tpmshx_solve_quick_design_v1`、`tpmshx_full_{2,3}d_run_*`）。退役对应的 Python `solver_library` 绑定与解码函数。保存态阶段入口仍是唯一的 C SDK。 |

## 历史数值资格检查记录

以下历史记录保留其原始数值与结论。
后续代码修复不把历史失败改写为通过。

- **严格入口热阻／矩烟雾检查**：6 个方向、10 类系数／边界共 60 组配置验证了局部行与账本，不代表全局 PDE 网格阶数。
- **N3 分层协议**：通过了独立算子与 `K = 0` 解析检查、覆盖 42 项指标 20 个唯一行的 84 个接受轴向阶数段，以及 6 组真实 64³ 制造解的原始绝对误差门槛。32³ 至 64³ 速率保持为报告趋势，不证明任意三维流动全局二阶。
- **原 MMS 样本集（N3 之前）**：原 6 组 MMS 样本通过 0/6 组；原轴向样本通过 4/6 组、失败 2 组。
- **N5 使用方样本集**：12 组刻意限步的使用方请求均正常返回并通过 14 项已记录阶段的算术审计，其中 0/12 项产品请求收敛、2/14 个热学阶段收敛。独立的正常预算样本集通过了全部 3 个完整稳态使用方（二维主／细网格、三维 `Nz = 1`、三维 `Nz > 1`）及全部 4 项热学阶段审计。
- **前序稳态候选**：3 个稳态使用方中通过 2 个，二维主／细网格门槛未通过。
- **历史 24³ 限步三维算例**：历史 Python/原生对比返回 `converged = False`；双后端一致不证明收敛。
- **历史 83 算例记录**：仅作为历史记录保留，不自动将实验验证结论延续至后续原生移植。
