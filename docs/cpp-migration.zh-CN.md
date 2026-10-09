<a id="c-solver-migration-under-the-v03-architecture"></a>

# V0.3 架构下的 C++ 求解器迁移

[中文](cpp-migration.zh-CN.md) | [English](cpp-migration.md)

<a id="status-and-architecture-decision"></a>

## 状态与架构决定

所提供的《TPMS 均质化换热器求解软件总体框架说明 V0.3》（2026-09-08）描述目标架构，不代表已交付能力。三个业务模块与现有 TM1 公共流程一致：

```text
application -> preprocess.api -> CaseData -> solvers.api -> FieldResult
                                                           -> postprocess.api
```

保留这些边界、既有 `domain` 契约和共享模型资源。Python 与 C++ 都是受支持的求解后端，无需全面重命名目录或拆分仓库。V0.3 的有效扩展是在求解模块内提供独立通过资格检查的 C++ 后端。它消费相同物理工况，并生成可由现有后处理使用的证据。

Python/Numba 仍是默认后端。显式 `backend='cpp'` 在 macOS arm64 和 Windows x64 支持完整准备态 Quick Design 及 full 2D/3D。必需的原生 CI 已在 macOS/Python 3.13 和 Windows/Python 3.12、3.13 通过。交付使用既有 Python/Qt 入口和项目文件夹中的预编译 C++ 库。源码 GUI 验收与整体应用性能仍是独立检查；打包 `.app` 不在本次交付范围内。

macOS 文件夹启动器显式选择随附候选库，不改变公共 Python 默认值，也不证明全部工况合格。原 `cpp_sweeps_v1` 接入已退役：该路线曾由 Python 控制外循环、C++ 只提供 sweep 分块。现在通过 `RunControl` 或 `--backend` 选择完整 Python 或 C++ 后端。共享 C++ sweep 实现及低层 C ABI 仍在使用，继续保留。

<a id="complete-quick-design-capability"></a>

## 完整 Quick Design 能力

`quick_design_driver.hpp` 负责完整准备态 const/mean 物性阶段计算。它包含原有经验空气／水或 HEOS sCO2 物性、既有 Nu、一次或两次温度计算、全场热启动、逐阶段液态水检查、迭代预算、进度和取消。准备好的入口状态解析压降比例保持固定。这是既有给定流量尺寸设计近似，`physical_validation=not_established`。

`solver_c_api.h` 提供独立、带版本的 C 入口和具名配置／结果结构。接口借用九个显式长度数组。错误区分非法输入、水入口／物性状态、水温度场、算术失败和其他原生异常。取消有独立结果状态。失败场不能发布为已接受结果。构建流程分别对静态库和动态库运行同一个独立 C 调用方。

薄 Python 适配器复用共享准备态输入校验和 `FieldResult` 映射。原生阶段证据提供场、物性和原警告记录，不调用 Python 数值核或物性函数。主机库位置属于执行控制，不在 `CaseData` 中：

```python
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.solvers.api import run_case

result = run_case(prepared_case, RunControl(
    backend="cpp", native_library="/absolute/path/to/libtpmshx_solver_shared.dylib"))
```

Windows 使用 `tpmshx_solver_shared.dll`。路径必须指向该主机上已构建的库。库缺失、ABI 不符或能力不支持时明确失败。公开结果保存、加载和离线评估使用既有接口。macOS/Windows 原生 CI 包括新进程保存态 Case 重放，且禁止 Numba/Python 求解核；另检查回调失败、取消、恢复和并发运行。这些运行覆盖所测 C ABI 和命令行路径；可见桌面交付仍需独立验收。

<a id="complete-full-2d-capability"></a>

## 完整 full 2D 能力

`full_2d.hpp` 和 `full_2d_c_api.h` 提供完整矩形双流体二维驱动。驱动负责既有 SIMPLE 流动更新、入口压力参考与气体压力射击、物性／闭合更新、外循环耦合、所选 temperature/model-h/true-h 求解、Richardson 转移，以及最终场和能量证据。局部端口、空间 L/t 场、真实边界通量，以及区分的最终流动／热压力状态都保留准备态契约。

主热量指标仍为 W/m；总质量流量优化仍要求显式物理深度。执行完成与收敛保持区分，包括预算耗尽、证据检查失败和取消。

full 2D 使用 **ABI 2**。第 29 个准备态数组保留原闭合输入中的无量纲比值 `(D_h_m * 1000) / L_mm`。从舍入后的 SI 长度重建比值可能改变梯度场换热系数的末位。C 符号和结构采用 `v2`；适配器在数值调用前拒绝 ABI 1 库。必须一起分发匹配的库、头文件和适配器。已保存 FieldResult 仍由既有可移植读取器加载，无需原生库。

上述公共调用也接受 full 2D `CaseData`。CLI、桌面和设计调用方传递同一个 `RunControl`。源码 CLI 示例：

```bash
"$PYTHON" -m sjtu_tpmshx.cli solve case.h5 results.h5 --backend cpp \
  --native-library /absolute/path/to/libtpmshx_solver_shared.dylib
```

绑定校验准备态输入，传递借用的输入视图，在释放前复制结果所有者持有的数组，并映射到既有 `FieldResult`。主机库和表目录不序列化到工况或结果。新进程 CLI 求解、保存回读和离线评估不加载 Numba 或 Python 数值驱动。数值资格检查以固定容差，与修正后的 Python 参考比较完整场、状态、预算、压力和能量证据。显式选择原生后端或 macOS 包运行成功，都不证明 Windows 验收，也不改变默认后端。

<a id="complete-full-3d-capability"></a>

## 完整 full 3D 能力

`full_3d.hpp` 和 `full_3d_c_api.h` 通过 ABI 1 提供矩形双流体三维外循环驱动。它消费相同准备态 XYZ 场和局部端口几何，执行带压力参考的 SIMPLE 及所选 temperature/model-h/true-h 耦合，并返回原有最终状态证据、警告和场位置。可选粗网格初始化保留细网格压力边界值。原生结果不由 Python 数值核提供。

初始化诊断是 ABI 1 的增量能力。原输入、结果和第一粗层摘要布局不变。`tpmshx_full_3d_get_bootstrap_trace_v1(result, side, trace)` 为 side 0/1 提供独立只读视图。字符串和层数组由结果所有者持有，仅在调用 `tpmshx_full_3d_release_v1` 前有效。查询不执行数值工作，也不分配内存。已有 C 调用方继续使用原 ABI 1 结果布局。当前 Python 绑定要求新查询符号；旧库缺少该能力时明确报错，不虚构轨迹或代用 Python 求解。

轨迹记录显式启停、实际粗网格形状与深度、逐层上限、进入的迭代数和停止原因。它保留原递归 `count > 2000`、子层上限 200、最小轴长及停止规则。`started_cap_sum` 是实际进入迭代的各层上限之和，不是共享全局初始化预算。未开始即取消的父层贡献零迭代，且不计入该上限和。绑定在释放前复制轨迹，写入 Python full 3D 同样使用的 `diagnostics.coarse_bootstrap_trace`。不含此可选键的旧结果仍可读取。

合作式取消结果仍持有部分诊断视图，C 调用方可在释放前查询。Python 绑定抛出 `CancelledError`，在 `coarse_bootstrap_trace` 附带独立副本，不发布部分 FieldResult。硬 C API 错误仍保持调用方结果不变，也不发布所有者，因此此时不能通过查询取得完整轨迹。原算法捕获的初始化局部失败仍被记录，不能声称种子已应用，也不能用配置上限替代实际计费工作。

共享物理端口压力归约保留参考掩码数组顺序和连续成对求和，同时用于加权压力与开口面积。这也固定压力射击的入口锚点。改变求和顺序，即使初始压力只差舍入量，也可能改变后续 SIMPLE 停止迭代。完整场检查因此必须保留原迭代预算和比较容差。

相同公共 `run_case` 和 CLI 命令可选择 full 3D CaseData。数值资格检查包含原 24³ 工况及完整场、压力和热证据，预算与比较门槛不变。该特定限预算工况在两个后端均为 `converged=False`；相符不等于收敛。full 3D model-h 热量仍为 W。原 temperature 路线缺少完整焓证据时，仍保留热量不可用边界。优化继续使用独立的 model-h 物理边界与能量检查。

<a id="fixed-flow-conservative-temperature-candidates"></a>

## 固定流动的守恒温度候选算法

`enthalpy_driver.hpp` 中的 C++ `solve_enthalpy` 接口接受显式 `EnthalpyAlgorithm::temperature_fou` 或 `temperature_sou`。既有调用默认使用 `legacy_h_fou`；版本 1 C 接口也保留该路线。温度候选目前覆盖张量网格上的两个求解流体，包括单位深度二维拉伸。输入包括有符号质量面、局部绝对压力、有效固体导热率和体积换热系数。各侧必须声明标量入口方向；从其他外表面流入会被拒绝。外部导热边界绝热。此入口不准备质量流量、不求解 SIMPLE，也不评估 Nu。

每次非线性更新冻结独立的真实 h、T 和 cp 数组，然后交替执行正序／逆序的 A、B 和固体 sweep。流体对流采用线性化 `h* + cp*(T-T*)`，扩散采用温度。SOU 在物理坐标上直接根据真实焓冻结 minmod 修正，包括出口面，并对固体使用完全松弛。FOU 对所有相使用给定松弛。

SOU 在真实状态更新前，将完成的三相块增量乘以 0.6。这抑制了拉伸 full 2D 网格上已复现的限制器振荡，不改变稳态方程。FOU 不加块阻尼。随后，带检查的 HEOS PT 更新以真实状态替代线性化焓，再评估残差与热负荷。不使用 BICUBIC 表、H→T 反演、裁剪或恢复回退。

SOU recipe 2 在该阻尼普通映射上使用六样本 Anderson 候选。选择前以真实 HEOS PT 物性和原能量审计校验每个候选。候选必须严格降低按原容差归一化的方程比和耦合比中的最大值。无效或非有限候选保留普通更新。接受候选后继续迭代。首次／最终块以及普通温度更新较小时，都使用完整普通 PT／审计块；只有该块可以判收敛。`picard_relaxation=0.6` 描述普通映射，不描述每个 Anderson 增量。

同一个已加载库的 `tpmshx_energy_algorithm_version_v1` 根据实际返回算法报告 FOU recipe 1 或 SOU recipe 2。Python 将该身份记录在主／外循环证据、有效设置和边界捕获中。缺少查询的旧库在守恒流动执行前失败。已保存 SOU recipe 1/2 边界证据仍可读取，不重放 EOS 或推断版本。算法 recipe 版本独立于 C ABI。

候选要求正的耦合、方程容差，以及以 K 为单位的正 `temperature_update_tolerance`。三项检查必须在同一真实状态上同时满足。`EnthalpyResult::algorithm` 标识实际算法；`temperature_update` 仅存在于这些路线。既有 `residual` 仍记录归一化真实焓更新。SOU 最终证据重新构造实际面修正，并一致用于边界热负荷和局部残差。达到迭代上限时保留真实证据；取消使部分场无效并清除该证据。

`conservative_energy_smoke` 检查独立冻结平衡、六方向非均匀面通量、焓参考不变性和非法输入。`conservative_energy_driver_smoke` 检查真实 EOS 状态、冷／热启动一致性、独立出口热负荷、取消、迭代上限和物理域失败。依赖组件验证运行两者。其范围是固定流动数值资格；生产流动／闭合验收，以及与原 BICUBIC 路线的比较，仍是独立要求。

<a id="explicit-full-flow-candidate-selection"></a>

### 显式选择完整流动候选

在 `prepare_case` 前，将 `solver.enthalpy_algorithm` 设为 `temperature_fou` 或 `temperature_sou`，并将 `solver.enthalpy_temperature_tol_K` 设为所需正 K 容差。随后使用 `backend='cpp'` 和匹配原生库执行已保存工况。默认值仍为 `legacy_h_fou` 和 1e-8 K。当前候选要求既有双流体 true-h 路线。在 Python、Quick Design 或不支持的热路线中选择时明确失败。该选择不扩大流体、沸腾、冷凝或 Nu/Darcy-Forchheimer 适用范围。GUI 尚未提供此算法选择。

完整三维候选也支持 `port_wall_refine` 生成的非均匀张量网格，覆盖完整和部分开口。计算使用实际单元宽度及端口面质量流量。model-h 的端口能量标志不改变此 true-h 路径。此支持不改变已保存算法、默认值或验收门。

完整驱动保留原 SIMPLE、压力、物性、外耦合和最终验收门。full 3D 还保留两次温度预测 sweep 和原质量准备。候选 recipe 每个非线性步使用五次 sweep。FOU/SOU 流体松弛分别为 .6/.2，固体松弛分别为 .6/1。full 3D 在准备态 Case 中保存已解析控制量；二维 recipe 由算法版本固定。两者保留原迭代预算，并要求真实耦合／方程能量比不大于 .001，同时满足声明的温度更新容差。原生结果记录实际整块 Picard 松弛：FOU 为 1，SOU 为 0.6；它与流体及固体行松弛分开。

`tpmshx_solve_full_2d_v3` 和 `tpmshx_solve_full_3d_v2` 接受共享 `tpmshx_energy_options_v1`，保留旧结果 POD 和释放函数。对应 `get_energy_evidence_v1` 查询借用同一所有者，不执行求解。它提供实际算法／温度更新、最终 epsilon×HEOS 导热率、六个向外有符号焓功率面，以及逐外步标量身份。旧入口仍可用，数值行为不变。

Python 绑定在释放前复制查询视图，并记录 `backend_version=full_2d_v3` 或 `full_3d_v2`。候选结果采用可移植 `thermal_mode=conservative_energy`。`boundary_fluxes.true_h` 包含既有真实 h、入口 h、质量数组，以及算法／版本、六面 `boundary_power`、W/m 或 W 单位和完整性标志。各侧热负荷为 `-sum(boundary_power)`。

SOU 在出口面重构物理焓，因此旧 FOU 单元焓归约不能提供该热量。面证据缺失或无效时指标不可用，不进行替代重构。最终流动更新后的压力和速度，与已接受或限预算的最后热状态保持区分。二维候选保留 true-h 单位深度约定，不生成 Richardson 证据。

<a id="first-implemented-slice"></a>

## 首个实现单元

`native/include/tpmshx/enthalpy_sweeps.hpp` 和 `native/src/enthalpy_sweeps.cpp` 实现 `solvers/ltne_enthalpy_3d.py` 的串行真实焓 LTNE Gauss–Seidel sweep：

- 依次更新流体 A、流体 B 和固体，保留原有递增 i/j/k 顺序。
- 六面使用有符号质量流量；流入使用给定焓，流出使用单元焓，壁面为零流量；不推断均匀流动捷径。
- 使用非均匀正交单元宽度和调和面导热率。
- Fourier 导热使用在冻结 `(T*, h*, cp)` 附近线性化的温度；等温时压力相关焓差不会产生虚假导热。
- 原位执行欠松弛焓／固体温度更新，分别准确累计 A/B 焓裁剪次数，覆盖请求的全部 sweep。

该库采用 C++17，仅依赖标准库。输入为借用的连续 double 数组，显式声明长度、单位和交错位置。修改前先校验输入。数组由调用方所有，可变状态不得与其他状态或系数数组别名。数组顺序为 `(i*ny+j)*nz+k`。有限输入运算溢出导致非有限对角元、右端或更新时，抛出 `std::domain_error`。异常后的部分更新状态不得使用，也不能静默裁剪或接受。支持单单元轴。单位深度二维拉伸保留既有二维驱动归一化，不虚构物理厚度。

该单元不执行 EOS 查询、SIMPLE、质量通量平衡、Picard／物性更新、外循环收敛／取消、CaseData 加载或 FieldResult 捕获。核无裁剪运行不证明结果收敛或物理有效。

<a id="second-implemented-slice-actual-state-energy-audit"></a>

## 第二个实现单元：真实状态能量审计

同一库提供 `thermal_energy_audit`，复现 `ltne_enthalpy_3d.py` 和 `result_math.py` 中的生产 true-h 能量算子：

- 真实状态 A/B 单元残差为 Fourier 导热＋固体交换－有符号迎风焓散度。调用方提供真实 EOS 温度和有效流体导热率，不使用 sweep 的冻结线性化状态。
- 计算绝热固体单元残差和六面有符号边界焓热负荷。入口／回流面使用给定入口焓，流出使用单元焓。
- 保留既有耦合比与方程比，包括不变的分母 `max(abs(Q_A), abs(Q_B), 1)`、流体残差绝对值和／最大值及固体和。三维输出为逐单元 W，既有单位深度二维拉伸为 W/m。

算子不应用验收阈值，也不评估 EOS、校验物理适用范围、平衡质量、统计此前裁剪或判定收敛。这些驱动检查仍然必需。非法输入在写残差前拒绝。算术溢出报错，并使全部输出缓冲区无效；状态／系数数组保持只读。

资格检查比较真实残差场和能量预算，不只比较最终比值。独立检查包括六个有符号流向、单单元 20 W 交换、内面抵消、等温压力相关焓，以及故意不平衡的局部温度场。最后一种场的全局／耦合预算为零，但方程残差为正。

<a id="shared-finite-volume-temperature-consumers"></a>

## 共享有限体积温度算子的使用方

集成 fullCC 候选通过严格 model-h 驱动和真实热状态质量面，输运既有空气／水积分焓 h(T)。它替代早期可变 cp 的 m*cp*T 提案。早期物理契约失败保留为历史，不描述当前实现。此前数值和资源资格仍归属于各自构建；最终库和应用验收保持独立。固定 cp Quick Design 是另一种近似，不代表可变 cp 积分焓。

私有 `energy_fv_rows.hpp` 提供共享输运、Fourier 导热、LTNE 交换和物理源项行。它不选择流体模型、不准备 SIMPLE/MAC 面、不持有 EOS，也不授予调用方收敛规则。CMake 对所有实例化共享行的源码应用相同的禁止浮点收缩策略，包括直接核 smoke。这样可避免链接顺序选择同一模板的不同舍入副本。该策略仅作用于相关源码；保留的旧热核维持原编译选项。

实际调用边界如下：

| 使用方 | 驱动与保留契约 |
| --- | --- |
| Quick Design const/mean 与独立 CC | `temperature_driver.cpp` 的 `solve_temperature`；每阶段固定系数、热容输运、冷／热启动、有限预算和取消。 |
| 空气／水 full2D temperature 主／细网格，以及 full3D CC Nz=1 | 严格 `solve_model_h_2d`；既有空气／水 h(T)、A-SOU/B-FOU、准备态 mass/K/h_v，以及原调用预算。 |
| 空气／水 full3D CC Nz>1 | 严格 `solve_model_h_3d`；两侧 SOU、准备态 mass/K/h_v、给定 B、非对称几何，以及仅严格模式支持的水／水。 |
| 既有产品 model-h | 默认非严格 model-h 驱动及原资格／停止规则；fullCC 复用不授予优化资格。 |
| full3D true-h CC 预热 | 既有私有 `legacy_single_a_temperature`，给定 B 为空。Nz=1 使用原 G4 两次 sweep 映射；Nz>1 使用 conservative=false、force_cell_centered=true。两侧都求解；后续焓驱动保留所选算法和物理门。 |
| 单 A 侧 sCO2 CC | 同一私有 G4 核，采用给定 B 和原热预算；身份为 `legacy_frozen_cp_single_a_cc_v1`，保留原单流体路径，不提供积分 h(P,T) 账本。 |
| 交错／MAC temperature | 既有投影／缓存及热容面准备；保留的非守恒平流研究修正不具备 fullCC 积分焓资格。 |
| true-h | 既有默认 legacy H-FOU，或显式守恒温度算法；EOS 及各自检查仍由焓驱动负责。 |

保留的 CC 预热是确定性的 true-h 调用契约，与既有单 A 实现共享。它不增加公共选择项或核副本。两次 sweep 结果仅为初态。焓驱动仍校验所有 sCO2 热启动温度，并提供最终热结论。Nz>1 交错预热保留既有共享温度路线。full2D true-h 不使用此 full3D 预热。

fullCC 使用已接受的热状态 SIMPLE 质量面，不乘 cp，不从单元速度重建质量，也不重复乘孔隙率／开口。model-h 驱动在重构面温度上评估既有 h(T)，并使用原准备态 Fourier 导热率和交换系数。full2D 行与功率使用单位深度、W/m。full3D Nz=1 要求活动 z 面质量为零；将真实质量除以深度后交给二维求解，再将残差、源／储库和边界功率乘以深度一次，返回 W。温度不变。

严格 fullCC 保留热负荷／场稳定条件，并额外要求新计算的完整边界账本。各相绝对单元残差和中的最大值，以及耦合边界／源不平衡中的较大者，必须不超过界面交换尺度的 1e-7，尺度下限为一个原生功率单位。检查失败时在原预算内继续。物理流入不完整时不能收敛。严格 SOU 使用真实入口距离和单侧流出重构。严格入口 Fourier 导热在行和审计中都使用热阻／矩规则。非严格产品 model-h 边界不变。fullCC 仍不支持非零制造体源。给定 B 是外部温度储库，不参与更新、Anderson 或求解方程，也不虚构 B 证据。

以下受控线迭代仅描述固定系数 QD／独立 CC 驱动，不描述严格 fullCC model-h 适配器。独立 CC 从给定单元场重构唯一有符号热容面。显式热容输入已包含孔隙率／面积／深度因子，并优先于该重构。每个内面使用一个 T-minmod 修正。流入完整、二阶输运活动且不采用红黑排序时，每块包含至多四次点 sweep 和一次带检查的线 Newton 试探。

只有真实状态物理误差严格下降时才接受试探。两个比较状态都采用相同的 0.6 块阻尼；拒绝后保留阻尼点状态。A 和 SOU B 的点 sweep 使用 min(caller alpha,0.2)；FOU B 与线试探使用调用方 alpha。退化或红黑工况使用点块。预算统计每个请求步；取消不能证明收敛。

该固定系数驱动的完整边界收敛要求 Q／场稳定，以及新计算的最大相残差／耦合边界源平衡不大于 1e-7。归一化使用较大界面功率，下限为 1 W 或 W/m。直接热容调用存在未标识外流入时不能收敛。独立重构热容调用在边界不完整时保留历史稳定状态，同时明确暴露缺失边界证据。此固定系数驱动不查询 EOS。CC 仍拒绝非零制造体源；交错／model-h 保留既有源能力。给定 B 是外部温度储库，不提供已求解 B 残差证据。

只读查询区分实际固定系数受控线、交错和 model-h recipe。fullCC 空间契约标识为二维／Nz=1 的 `model_h_tface_sou_fou_strict_v3`，或 Nz>1 的 `model_h_tface_sou_sou_strict_v3`。增量 full2D/full3D `get_model_enthalpy_evidence_v1` 保留既有求解结果布局，返回 `tpmshx_model_enthalpy_evidence_v1`，不使用旧热容账本布局。

每个求解流体记录既有二次 cp(T) 的 [c0,c1,c2,Tbase,Tref] 及积分基准 h(Tref)=0。还记录求解相标志、物理残差、源／储库功率，以及向外 m*h(T_face)／Fourier 平面。视图借用结果所有者；绑定在释放前复制。二维主／细网格阶段保留独立实际身份。请求的热模式仍为 `temperature`，可移植证据声明 `model_enthalpy_temperature_v1`。离线后处理校验并归约已捕获功率，不运行求解器、EOS 或新面重构。可用性不等于收敛，这些记录也不赋予产品 model-h 优化资格。新账本字段缺少声明时无效；不含新字段的历史文件保留原规则。

当前资格范围有限。六十个严格入口热阻／矩 smoke 配置覆盖六方向和十类系数／边界，检查局部行与账本，不是完整 PDE 网格阶数结果。定义的 N3 分层协议另通过独立算子／K=0 解析检查、来自 20 个独立行的 84 个接受轴向阶数区段、共 42 项指标，以及六组实际 64³ 制造解的原绝对误差门。它不证明任意三维流动全局二阶；32→64 阶数仍作为趋势报告。原六组 MMS 总体为 0/6 通过，原轴向总体为 4/6 通过、2/6 失败；后续协议不改写这些历史结果。

N5 的十二个刻意限预算请求成功返回，并通过十四个已记录热阶段的算术审计，但产品请求收敛为 0/12，热阶段收敛为 2/14。独立正常预算总体通过三个完整稳态使用方：二维主／细网格、三维 Nz=1、三维 Nz>1；四个热阶段审计也全部通过。此前稳态候选的 2/3 结果及失败的二维主／细网格检查保留为历史。

这些固定总体不证明实验精度或 N6 性能／内存验收。旧固定热容组件计时不是相同 h(T) 算子的完整驱动成本比较。新原生算法要求独立矩阵、解析、网格序列、真实状态平衡和生命周期资格。旧 Python 轨迹测试只保留为同算法历史证据，不能证明改变后的原生方法等价。原生成功退出、完整物理账本、收敛和实验精度是不同事实。Python 数值方法和默认后端仍分别管理。

<a id="build-and-run-the-qualification-checks"></a>

## 构建并执行资格检查

已有 POSIX C++17 编译器和 `make` 时，从仓库根执行：

```sh
make -f native/Makefile CXX=c++
make -f native/Makefile CXX=c++ shared
make -f native/Makefile check
```

这生成 `.cache/native/libtpmshx_thermal.a`。C++ 调用方包含 `native/include` 并链接该归档。温度线求解器构建要求既有锁定 Eigen 头文件，并启用 `EIGEN_MPL2_ONLY`。`TPMSHX_EIGEN_INCLUDE` 默认指向 `.cache/native-deps` 中锁定 CoolProp 源码的 `externals/Eigen`。隔离源码树可显式设置该变量。目录缺失时构建失败，不下载依赖。

低层归档不链接 Python、Qt、NumPy、CoolProp/EOS、OpenMP 或绑定库运行时。完整依赖组件库另有 EOS／压力依赖。`check` 编译并运行能量审计算子和温度驱动的独立 C 静态／动态调用方，以及 C++ 静态调用方。shared 目标在 macOS 生成 `.cache/native/libtpmshx_thermal.dylib`，其他 POSIX 平台生成 `.so`。该低层库不随 Python wheel 或桌面应用打包，不自动发现，也不在运行中构建。

Windows 已有 x64 Visual Studio 开发者命令提示符时运行：

```bat
nmake /f native\Makefile.msvc check
```

这在 `.cache/native` 下生成 `tpmshx_thermal.lib`、`tpmshx_thermal.dll` 和独立的 `tpmshx_thermal_import.lib`，再运行相同 C/C++ 调用方。C ABI 使用显式 Windows 导出／导入和 `cdecl`；ctypes 通过 `CDLL` 加载 DLL 路径。这些命令不安装编译器。

`thermal_c_api.h` 提供带版本的 sweep ABI 和有长度限制的错误消息，异常不跨越 C 边界。独立 C/C++ 调用及直接 C ABI 测试保留缓冲区和物理参数校验。退役的 Python 混合适配器不再属于生产执行路径。能量审计测试仍使用仅供测试的桥接。

通过常规环境检查后，使用 `.venv-path` 解释器：

```sh
tm1_python="$(head -n 1 .venv-path)"
"$tm1_python" -m sjtu_tpmshx.runs.tools.check_locked_environment
"$tm1_python" -m pip check
MPLCONFIGDIR="$PWD/.cache/matplotlib" \
XDG_CACHE_HOME="$PWD/.cache/xdg" \
NUMBA_CACHE_DIR="$PWD/.cache/numba" \
TPMSHX_REQUIRE_CPP_TESTS=1 \
"$tm1_python" -m pytest -q sjtu_tpmshx/tests/native
```

旧 `TPMSHX_TRUE_H_KERNEL=cpp_sweeps_v1` 不再启动混合求解。Python 在 SIMPLE 前拒绝该设置，包括已保存准备态 Case，不静默改变记录的算法。环境快照保留旧选择项只为明确拒绝。未设置或设为 `numba` 时使用不变的 Python 核。新 Case 不再捕获 `TPMSHX_THERMAL_LIBRARY`。改用完整原生后端的 `--backend cpp --native-library /absolute/path/to/libtpmshx_solver_shared.dylib`；主机库路径通过 `RunControl` 提供。

旧结果仍可在不加载数值核或旧混合库时读取和评估。Python true-h 证据继续记录 `sweep_kernel='numba'` 和 `energy_audit='python'`。必需标志使编译器缺失成为该资格命令的失败。普通 Python 测试在平台编译器缺失时可跳过，但跳过不代表原生验收。现有 macOS 3.13 和 Windows 3.12/3.13 快速 CI 路线要求原生资格。本地 macOS 通过不证明 Windows 编译、执行或分发验收。测试不安装编译器或 Python 依赖。

同算法比较前固定容差：焓 `rtol=2e-13`、`atol=2e-8 J/kg`，固体温度 `atol=2e-11 K`。这些容许相对 Numba fastmath 的双精度编译器／FMA 顺序差异，与 PDE 收敛和实验不确定度不同。裁剪次数必须完全一致。原生构建不启用 fast-math。

检查覆盖固定随机种子的可变场、有符号／零面流量、非均匀网格、六流向、单单元轴、零对角元、裁剪，以及修改前拒绝。独立物理检查覆盖等温压力相关焓，以及常物性指数冷却解析解的一阶网格收敛和边界／源能量平衡。它验证 sweep 算法，不验证 sCO2 系统预测或加速。

能量审计固定比较容差为 `rtol=2e-12`，逐单元 `atol=1e-9 W`，归约预算 `atol=1e-8 W`，无量纲比 `atol=1e-12`。二维使用相同来源单位归一化。这些比较算术实现，不改变生产验收门。性能资格必须计入输入校验和绑定开销，以相同预热状态比较 Numba sweep 和 NumPy 审计算子，并与 EOS、编译及端到端执行分开。核结果不能证明应用加速。

公共执行测试以固定 `rtol=atol=1e-10` 比较二维／三维 sCO2／水和空气／sCO2 场、有符号边界通量、压力证据和指标，同时保留原 F2 与 true-h 物理门。还检查保存态 Case 选择、取消和真实原生错误退出。两个原生算子都不因存在而自动成为生产选择。

<a id="isolated-eos-and-pressure-dependency-qualification"></a>

## 隔离 EOS 与压力依赖资格

依赖组件构建为显式步骤，与生产后端选择分开。输入锁定在 [native/dependencies-lock.toml](../native/dependencies-lock.toml)：CoolProp 8.0.0 及九个固定提交的 CPM 头文件依赖、SuperLU 7.0.1 及选定的三项 SciPy 1.18.1 double-LU 修正、AMGCL 1.5.0 和可移植 CMake 4.4.4。SuperLU 源码不等同于 SciPy 内附修订。源码、二进制、日志和 EOS 表都保存在本工作树 `.cache/native-deps`。[第三方说明](../native/THIRD_PARTY_NOTICES.md)记录链接组件和原始许可声明。

获得原生依赖准备的明确授权后，使用配置解释器和既有锁检查。`fetch` 是完整依赖的联网步骤；`fetch-eigen` 仅获取无 EOS 热库所需的固定 Eigen 5.0.1 头文件。`build` 离线运行，不安装 Python 包或改变共享环境。CoolProp 构建使用显式本地 CPM 路径并关闭 FetchContent 联网，不获取可选测试或包装模块：

```sh
"$tm1_python" scripts/build_native_dependencies.py fetch
"$tm1_python" scripts/build_native_dependencies.py build
"$tm1_python" scripts/build_native_dependencies.py verify
TPMSHX_REQUIRE_NATIVE_DEPS_TESTS=1 \
MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg" \
"$tm1_python" -m pytest -q -ra \
  sjtu_tpmshx/tests/native/test_native_eos.py \
  sjtu_tpmshx/tests/native/test_native_pressure.py \
  sjtu_tpmshx/tests/native/test_superlu_error_boundary.py \
  sjtu_tpmshx/tests/native/test_fluid_properties.py \
  sjtu_tpmshx/tests/native/test_quick_design_driver.py \
  sjtu_tpmshx/tests/native/test_cpp_quick_design.py
```

EOS 调用方以与 Python 参考相同的具名后端评估 CO2 和 Water，即 HEOS 或 BICUBIC&HEOS。检查正向物性、焓反演、既有 CO2 范围、稳定液态水约束和独立可变状态。它不以 CoolProp 数值替代项目经验空气／水输运函数。每个进程使用显式表目录，不改变父 Python EOS 设置。`test_native_eos.py` 固定物性比较容差；它与 PDE 验收以及 BICUBIC 相对 HEOS 的插值误差分别管理。

压力调用方消费规范 32 位 CSR，保留原零 Dirichlet 行，并报告原 `Ax-b` 残差和固定点误差。不超过 2000 单元的二维／三维系统使用 SuperLU/COLAMD。较大三维系统使用原 PyAMG 5.3 的经典强度、分裂、修正插值、Galerkin 顺序和对称 Gauss–Seidel 循环，同时保留原 SciPy BiCGStab 停止及 breakdown 规则。

200 次预算、已解析相对容差，以及复用预条件器时使用当前矩阵乘法的规则不变。仅原 breakdown 路径以 L2 缩放右端重试；资格检查报告未缩放方程残差。最初 AMGCL 压力候选未通过完整工况比较，已被替换。AMGCL 仍用于独立交错温度投影。构建排除 MC64/ILU，并使用三项锁定的 SciPy double-LU 数值修正。

SuperLU 调用采用纯 C 错误边界和线程局部分配账本。分配失败和 ABORT 在清理后返回有界错误，跳转不跨 C++ 栈帧。macOS 资格在每个观测到的分配序号注入失败，并在 release 和 ASan/UBSan 构建中检查同进程恢复、长 ABORT 消息、奇异 info 和独立并发线程。Windows 必需 CI 也通过 release 分配、ABORT 和恢复检查；这不将 sanitizer 证据扩展到 Windows。非法输入和未知后端错误不静默回退 LU。这些压力测试本身不能建立完整原生 SIMPLE 或外耦合资格。

完整固定流动 true-h、二维／三维 model-h 和二维／三维 SIMPLE 均已有独立 C++ 实现、带版本 C 接口，以及 `solvers/backends/cpp/` 下的显式 Python 绑定。热绑定返回既有能量和原始边界元数据。原生 model-h 在 C 调用方释放结果前持有审计数组；Python 绑定释放前复制视图。回调异常和取消丢弃部分状态。

SIMPLE 接口持有逐实例压力缓存，并保留原 F2、出口、热启动状态和原始质量证据。这些可独立调用驱动也支撑上述完整二维／三维外耦合后端。macOS SuperLU 构建使用锁定 SciPy 参考所用的系统 Accelerate BLAS，并为二维 SIMPLE 保留原 CSR／转置 LU 运算顺序。Windows 使用锁定可移植 CBLAS 源码，由必需原生 CI 执行。动量串行循环不表示 BLAS 单线程；线程策略和测得性能须分别记录。

`native-dependencies` CI 在 macOS/Python 3.13 和 Windows/Python 3.12/3.13 构建并执行这些调用方与必需测试。可执行文件缺失会使必需作业失败。普通 Python 运行可以跳过未构建组件，但不能据此声明原生资格。两平台均有真实必需 CI 通过记录；证据仅覆盖其构建与工况。

<a id="remaining-stages-and-acceptance-gates"></a>

<a id="migration-stages-and-remaining-acceptance-gates"></a>

## 迁移阶段与剩余验收门

| 阶段 | 实现边界 | 继续推进所需证据 |
| --- | --- | --- |
| 0：热算子 | 独立原生 sweep 和能量审计算子；Python/C++ 混合选择项已退役。 | 算子检查，以及公共场／通量／指标、交接、取消和错误比较。 |
| 1：完整热驱动 | 按相同顺序迁移 Picard 状态、物性刷新、EOS 反演、残差、热启动与合作取消。流体物性和 Nu/hv 闭合评估分开。 | 固定入口／压力／网格输入；A/B/固体方程和边界能量门不变；裁剪／无效／取消保留原含义；比较独立原生场与通量。 |
| 2：流动与耦合 | 迁移 SIMPLE/Brinkman–Forchheimer、压力与质量修正，再迁移所声明矩形子集的原外耦合顺序。 | 动量及新密度局部／全局质量 F2 门；物理入口压力、出口／回流和能量检查；方向与网格测试；相同准备态几何／闭合，不重调系数。 |
| 3：实际 C++ 后端 | 使用最小求解侧适配器消费 CaseData，生成完整 FieldResult，只声明已接受能力。 | 不依赖 Python 求解核；分进程工况／结果交接；状态、单位、场位置和模型来源；缺失或不支持能力明确拒绝。 |
| 4：应用与发布 | 通过既有公共求解 API 选择已合格后端，保留 GUI／设计／优化与离线后处理。 | 仅在支持范围内使用固定二维／三维工况；按预定容差比较跨后端 Q、压力、温度和通量；各支持平台的构建及交付证据。 |

阶段 1 前必须明确原生物性库交付、许可和构建策略。当前 Python CoolProp 安装不能证明已有完整可移植 C++ 开发／运行包。不得静默以拟合代替 HEOS，也不得用 sCO2 标定吸收迁移误差。跨语言共享闭合必须保留生产版本、来源和有效范围，不另行重拟合系数。

2026-09-21 检查的本地 CoolProp 7.2.0 wheel 包含 C++ 头文件和 MIT 许可，但二进制为 CPython Mach-O bundle，不是可独立链接的 `libCoolProp`。独立 C++ 链接以不支持的 Mach-O 类型失败；该环境未发现独立 archive/dylib。检查时未下载源码或安装依赖。之后获准的隔离构建见上文。完整驱动仍需在各目标平台验证 HEOS／最终状态与 BICUBIC 迭代语义，包括真实 Windows 执行。

每个阶段比较前，先冻结代表工况和比较容差，并保留失败工况及原分母。解析、网格、守恒资格与实验验证分别执行。原 83 工况记录保持历史身份，原生迁移不继承其实验结论。性能测量须区分编译、EOS、流动、热 sweep 和总时间，以相同预热状态和收敛门比较。

OpenFOAM、完整外部求解器 ABI、通用非结构网格、额外物理模型和抽象工厂框架都不是此次迁移的前提。只有具体且独立通过资格检查的能力需要时，才加入对应功能。
