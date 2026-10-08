<a id="quick-design-mode-in-the-current-v1-draft"></a>

# 当前 v1 草案中的快速设计模式

[中文](quick_design.zh-CN.md) | [English](quick_design.md)

模式为 `metadata.mode=quick_design`，复合模型为 `plug_ltne_analytic_dp_v1`。Python 和 C++ 都支持 `quick_design_v1` 能力。`FieldResult.backend_id` 将所选后端记录为 `python` 或 `cpp`。这是既有的给定速度 LTNE 尺寸设计近似，采用入口状态的解析 D-F 压损，不运行 SIMPLE。原有 sCO2 代表 Pr 限制仍包含在输出来源警告中。

<a id="prepared-input"></a>

## 准备态输入

`preprocess.api.prepare_quick_design` 接受既有 DesignCase，以及几何和尺寸设计选项。`config_snapshot` 记录原始 DesignCase，执行不使用它。准备态数据包含：

- 物理 `grid`：维度为 3，含 x/y/z 轴、宽度和累计边缘，单位为 m。交叉流使用 60 × 40 × 1，并委托既有二维核；逆流使用 60 × 1 × 2。两种模式都保留真实物理高度。即使 Nz=1 委托二维核，输出热负荷仍为总 W，不是 W/m。
- `design_fields`：均匀总孔隙率 `eps`、单侧 `eps_A=eps/2` 和有效固体导热率 `K_ss`（W/(m K)），均位于准备态网格。此模式拒绝非均匀场或不会被消费的场。
- `parameters.operating_point`：冷热流体标识、入口温度（K）、绝对压力（Pa）和给定质量流量（kg/s）。
- 几何：`L_cell_m`、`t_wall_m`、`Lx`、`s`、`height`、`D_h` 单位为 m；`A_0` 为 1/m，`k_s` 为 W/(m K)。原有几何分辨率为 128。
- `controls`：既有方向、欠松弛、最大迭代数、热负荷容差和分块大小。交叉流保留 alpha 0.7、8000、qtol 1e-4 和 chunk 100。逆流保留 alpha 0.3、20000，以及核的 qtol/chunk 默认值。请求的热 `tol` 独立保留。
- `initial_fields`：可以缺省，或提供三个有限的单元温度数组（K）。副本跨越契约边界，接收求解使用其数值。
- `df_options`：仅含已解析的 `method`，即 `cfd_full_core_3cell_fixed_v2`。它优先于接收进程环境，但不进行进程全局重放。旧覆盖标志和残差修正标志已退役。
- `inlet_pressure_fractions`：准备好的 A/B 解析 dP/P_in，无量纲、有限且非负。生产者使用 `df_options` 执行既有入口状态 D-F 计算；执行不得启动标定或重载训练数据。入口条件或几何改变后，必须重新准备这些固定值。缺少它们的旧中间 Case 必须拒绝。
- `prop_model`：const 为一次入口物性计算；mean 在入口／出口平均温度下增加一次计算。运行时物性评估属于模型执行。执行时不重建几何或网格。

两种物性模式的水 Nu 关联都使用 **320 K / 0.2 MPa** 的 Pr。mean 阶段按各流体平均温度和原入口压力更新 rho、mu、k 和 cp；Re 与体积换热随之变化，但水 Nu 的代表 Pr 不变。每阶段使用空间均匀物性。mean 是两阶段近似，不是局部变化或迭代收敛的物性场。结果 `metadata.properties.Pr` 描述实际阶段物性状态，不是水 Nu 使用的代表 Pr。

sCO2 Nu 独立保留 480 K / 9 MPa 约定。这些约定不能证明实验精度，也不能扩大流体或关联式有效范围。

快速设计 ModelRef 版本 `v2-5f1cafb` 标识提取出的复合闭合关系和数值预算约定。独立流体 ModelRef 标识两侧实际物性提供方。未知版本和不匹配的流体身份必须拒绝。模型版本标识公式，不代表实验精度。

<a id="native-result-and-independent-evaluation"></a>

## 原生结果与独立评估

温度、给定速度、流体／固体导热率、体积耦合和孔隙率场具有显式单位、x/y/z 单元位置和最终阶段状态元数据。`boundary_fluxes.A/B` 保留给定质量流量（kg/s）、入口温度（K）、本阶段 cp（J/(kg K)）、密度（kg/m3）和速度（m/s）。出口仍对相应完整面采用原有算术平均。

`pressure_evidence` 包含解析 D-F 求解的入口／出口绝对压力状态、模型身份和既有阻塞压力补救标志。这些是解析边界状态，不是虚构的压力 PDE 场。所有已解析模型输入保留在结果元数据中。

独立后处理根据“给定质量流量 × 最终阶段 cp × 原生出口／入口温差”计算冷热侧热负荷。Q 表示热侧放热，单位为 W。dP 通过解析边界压力相减得到，单位为 Pa。Re 根据记录的物性、速度和几何计算。设计应用将 dP 除以各侧原始绝对入口压力，以保留压降比例输出。离线计算不需要调用模型、EOS 或求解器。

能量比较为 |Q_hot−Q_cold| / max(|Q_hot|, |Q_cold|, 1e-30)。ForwardResult 将该诊断的值、状态和原因与必需的前向指标分别保存。最终逐工况记录、GUI 诊断页和 Excel 保留两侧热负荷及该诊断，包括最终验收失败的工况。诊断缺失时保持不可用，不能填零。此展示不增加能量平衡验收阈值，也不改变尺寸设计可行性；数值收敛和物理验证仍然独立。此模式明确不支持质量和完整边界质量不平衡指标。

执行／收敛、各阶段原生信息和尚未建立的物理验证保持区分。已完成但未收敛的求解，其有限指标仍可用，同时保留原运行状态。ForwardResult 增加 run_status 和 warnings；尺寸设计最终逐工况记录和报告保留它们。来源消息还进入活动的原有警告作用域。消息作为数据返回，不在每次独立搜索的中间评估中重复发出。非有限热返回值仍在出口、热负荷或压力报告前抛出异常。
