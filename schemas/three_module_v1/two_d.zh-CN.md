<a id="2d-producer-contract--implementation-v1"></a>

# 二维生产者契约——实现 v1

[中文](two_d.zh-CN.md) | [English](two_d.md)

`CaseData.grid` 记录物理 `(x,y)` 轴、单位为 m 的 `dx`/`dy`、边缘数组和分段坐标。形状表示包含壁面细化后的实际单元数，不是请求数。求解器校验有限正宽度、域范围和匹配的边缘；不得调用前处理。

`parameters` 包含解析后的入口温度（K）、速度（m/s）、尺寸（m）、各侧端口中心和宽度（m），以及方向（0:+x、1:-x、2:+y、3:-y）。还包含 `L_cell_m`、`t_wall_m`、导热率（W/(m K)）、孔隙率和水力半径（m）。`run_settings` 保存既有数值／控制 dataclass 数据，几何量使用 m。分区已由准备态分区数据负责，因此从该设置中移除。`static_properties` 包含入口物性和几何评估值，运行时无需重新读取固体均质化环境。

`flow_inputs.A/B` 记录实际 SIMPLE 横向／流向宽度（m）、`K_m2/cF_per_m` 行系数、标量 `seed_K_m2/seed_cF_per_m` 和 D-F 适用范围元数据。非连续分区保留行模型，包括一维分区、离散网格和原网格 sigmoid 路径。它们按真实单元宽度对横向 L/t 场加权平均，再评估固定 D-F 模型，并按实际流向排列各行。

对于 `zones.axis="continuous"`，各侧还记录其 SIMPLE `(cross, stream)` 坐标中的完整 `K_field_m2/cF_field_per_m` 局部数组。每个物理 L/t 单元独立评估；负向流动沿流向反转。横向均值只填入用于压力初始化的行数组；动量方程消费完整局部数组。在支持实验连续场迁移时，前处理将已解析的固定修正因子应用于局部 CFD 数组，并记录 `continuous-field-extrapolation`。执行使用这些已修正数组。

执行器对照物理网格校验网格与系数，包括连续工况必需的局部数组。接收进程的 D-F 环境设置不能替换它们。温度相关物性、梯度压力重新初始化和入口射击仍属于数值执行步骤。

`thermal_geometry` 包含固定标量或逐单元 A_0（1/m）、D_h（m）、epsilon、非对称侧别分配，以及各侧面积／直径相对于对称参考值的信息。这些是显式准备态输入；改变几何需要重新生成一致的 Case。运行时基于它们评估当前状态的 Nu 和输运，并消费保存的入口几何开口。独立的 `config_snapshot` 只保存历史来源，删除它不改变执行。CaseData 不保存回调或运行时模型。

`boundary_openings.A/B` 记录入口和出口的几何重叠及既有渐变轮廓。两者不同。Tout 选择正几何重叠并使用有符号原生质量通量；不得再次乘以渐变轮廓。既有数值构造器保留其物理端口规则。

`design_fields` 使用物理单元形状。`eps_arr` 是总孔隙率；`r_h_arr` 单位为 m；`K_ffA_arr/K_ffB_arr/K_ss_arr` 为 W/(m K)；`h_vA_arr/h_vB_arr` 为 W/(m3 K)；`A_0_arr` 为单位体积界面面积（1/m）。`L_field_m/t_field_m`、分区 `L_m/t_m` 和网格单元 `L_m/t_m` 均为 m。`zone_id` 是无量纲整数。

一维分区、离散二维网格和 sigmoid 设计在最终物理单元中心采样单胞与壁厚几何，包括非均匀网格。它们必须提供逐单元 `thermal_geometry`，供局部换热计算消费。准备态分区存档缺少这些字段时必须拒绝；应重新准备原始配置。`zones.axis="continuous"` 在相同物理中心采样 L(x,y)/t(x,y)，不使用离散分区的高斯滤波。原始样条控制量保留在 `parameters.continuous_field`，同时保存准备好的 SI 场。二维后端拒绝 `n_ctrl_z`。均匀数组必须与标量几何输入一致。连续场适用和标定限制仍见[架构](../../docs/architecture.zh-CN.md)；平滑控制量不能证明梯度精度或可制造性。

四个 `ModelRef` 分别标识流体 A、流体 B、几何和固定 CFD D-F 表，索引位于 `metadata.model_roles`。流体引用保留本次运行的 sCO2 Nu 参数及其来源／适用范围。未知资源版本，以及不一致的流体或拓扑声明，必须在执行前失败。实验 `alpha_D/alpha_G` 是总 Ceff，不是历史系数再乘独立因子。三维也遵守只应用一次的规则。重放准备态 Case 不重新加载当前参数资源。

`FieldResult.fields` 将最后一次主热求解的原始 `Ta/Tb/Ts` 与 `*_display` 副本分开。`P_thermal_A/B` 是最后热求解使用的局部绝对压力。`P_report_A/B` 是未平滑的最终报告压力，属于独立状态。`field_metadata` 声明各数组的单位、位置、轴和状态。压力证据还保存最终 SIMPLE 入口／出口表压行、轮廓权重和绝对参考值，供保留的后端摘要使用。

正式 dP 使用 `P_report_A/B`、物理单元宽度和几何开口比例。采用 `pressure_face_v1` 外推到物理端口面，然后按单位深度的开口面面积平均。它不使用旧轮廓权重或平滑压力场。

`boundary_fluxes.mass_A/B` 是 `(x-face,y-face)` 数组，形状分别为 `(Nx+1,Ny)` 和 `(Nx,Ny+1)`。正方向沿物理轴，单位为 kg/(s m)，已包含开口面面积和孔隙率。`model_h` 保留完整的有符号焓通量面（W/m）及入口导热面。`true_h` 保留原生焓 h（J/kg）、给定入口焓和有符号质量面；原有单层 z 适配器在数组形状中明确体现。`fine` 单独标识细化热求解返回值。`run_status` 保留数值收敛状态和最后热返回后的最终流动更新，不能将未收敛运行改标为已接受。

后处理只读取原生证据。正式 `Q=abs(Q_A)` 使用最后主网格热状态，即 `native_boundary_v1`。model-h 积分有符号焓通量面，true-h 使用原生边界焓热负荷，温度形式保留其 rho-cp／速度／轮廓约定。已接受的各侧 Richardson 热负荷保存为独立 `Q_richardson_A/B` 指标，不替换主网格 Q。后端摘要和 `reporting_reference` 为既有使用方保留历史定义。

Tout 使用原始主网格温度，以及真实开口上向外为正的质量通量。Q 单位为 W/m。证据缺失时指标不可用，不得调用求解器。有限指标不改变来源运行的数值或物理状态。固体质量另需显式提供固体密度，不能从 k_s 推断。
