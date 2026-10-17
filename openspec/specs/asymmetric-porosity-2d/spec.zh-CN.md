<a id="asymmetric-porosity-2d-specification"></a>

# asymmetric-porosity-2d 规范

[中文](spec.zh-CN.md) | [English](spec.md)

<a id="purpose"></a>

## 用途
规定二维非对称孔隙率的分配和输运约束。当前共享几何入口为 `models/asym_split.py`。流体和偏移的适用范围仍受 `docs/architecture.md` 约束。
0.2 通过 `prepare_case → run_case → evaluate` 调用原生完整二维驱动。准备态保存总孔隙率和几何分配比例，原生驱动据此生成两侧孔隙率。
[0.1 规范](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/v0.1.0/openspec/specs/asymmetric-porosity-2d/spec.zh-CN.md)保留已退役 Python 入口和核的原始要求。

<a id="requirements"></a>

## 要求

<a id="requirement-2d-ltne-kernel-accepts-distinct-per-side-void-fractions"></a>

### 要求：二维 LTNE 核接受不同的两侧孔隙率
在所选物理路线支持非对称的前提下，原生二维热驱动必须使用不同的两侧单通道孔隙率 ε_A 和 ε_B。各流体的对流输运必须使用其自身通道孔隙率加权。已退役的 Python 核名称不再表示当前入口。

<a id="scenario-asymmetric-split-solves-without-error"></a>

#### 场景：接受非对称分配
- **当** 受支持的二维准备态满足 ε_A ≠ ε_B，且每个单元均满足 ε_A + ε_B = ε，绝对容差为 1e-9
- **则** `run_case` 使用各侧不同的孔隙率；原有收敛和失败报告仍然适用

<a id="scenario-per-side-weighting-is-applied-in-the-kernel"></a>

#### 场景：核内分别加权
- **当** 某单元满足 ε_A > ε_B
- **则** 该单元中，流体 A 的对流系数乘以 ε_A，流体 B 的对流系数乘以 ε_B；不得共同使用 ε/2

<a id="scenario-over-allocation-and-under-allocation-are-rejected"></a>

#### 场景：拒绝无效准备态分配
- **当** 准备态分配比例非有限、超出 0 < split_A < 1，或声明为对称时不等于 0.5
- **则** 原生执行抛出 `ValueError`；两侧孔隙率必须由同一总 ε 和分配比例生成，不得再次减半

<a id="requirement-symmetric-input-is-bit-identical-to-the-legacy-path"></a>

### 要求：对称输入保留现有回归门槛
对称情况满足 ε_A = ε_B = ε/2，即偏移 δ=0；原生分配比例必须为 0.5。现有原生对称和 Shanghai 回归检查保留其数值门槛。与 Python 单一 `eps_f_arr` 路径逐位比较的原始要求保留在 0.1 历史规范中。

<a id="scenario-zero-offset-preserves-symmetric-path-parity"></a>

#### 场景：零偏移保持对称路径一致性
- **当** δ=0，即孔隙率对称且未提供两侧覆盖值
- **则** 输出数组保留对称路径的数值；现有数值等值和守恒检查继续生效

<a id="requirement-per-side-void-fractions-conserve-total-porosity"></a>

### 要求：两侧孔隙率之和守恒
根据偏移 δ 得到的两侧孔隙率，在每个单元的和必须等于配置的总孔隙率 ε。分配不得增加或减少孔隙率。

<a id="scenario-geometry-split-preserves-the-total"></a>

#### 场景：几何分配保持总量
- **当** 将几何分配比例 s = split_A 应用于总孔隙率 ε
- **则** ε_A = ε·s，ε_B = ε·(1−s)，且每个单元均满足 ε_A + ε_B = ε

<a id="requirement-2d-pipeline-derives-per-side-porosity-from-the-offset-δ"></a>

### 要求：二维流水线根据偏移 δ 计算两侧孔隙率
二维前处理必须根据等值面偏移 δ（`ComputeConfig.geometry.delta_levelset`）计算分配比例，并与三维前处理使用相同的几何分配比例。原生完整二维驱动接收准备好的总 ε 和分配比例；δ=0 时，各侧只能对总 ε 减半一次。

<a id="scenario-nonzero-offset-drives-an-asymmetric-run"></a>

#### 场景：非零偏移驱动非对称计算
- **当** `ComputeConfig.geometry.delta_levelset ≠ 0`
- **则** 流水线计算 (ε_A, ε_B) = (ε·split_A, ε·(1−split_A))，二维计算全程使用两侧非对称孔隙率

<a id="scenario-zero-offset-uses-the-symmetric-path"></a>

#### 场景：零偏移采用对称路径
- **当** `ComputeConfig.geometry.delta_levelset = 0`
- **则** 准备态分配比例为 0.5，原生执行对各侧使用 ε/2，不再乘一次 0.5

<a id="requirement-2d-duty-extraction-weights-mass-flux-by-per-side-void"></a>

### 要求：二维热负荷提取按两侧孔隙率加权质量通量
δ≠0 时，二维 dP/Q 提取必须使用各侧自身的孔隙率加权质量通量：A 侧使用 ε_A，B 侧使用 ε_B。这适用于质量流量、质量加权出口温度和出口焓。加权必须与传给核的孔隙率一致，使 ṁ_A / ṁ_B 和热负荷反映非对称几何。

<a id="scenario-asymmetric-duty-weighting"></a>

#### 场景：非对称热负荷加权
- **当** δ≠0，且计算各侧出口质量通量
- **则** A 侧使用 ε_A，B 侧使用 ε_B；ṁ_A / ṁ_B 反映实际单通道孔隙率，不得共同使用 ε/2
