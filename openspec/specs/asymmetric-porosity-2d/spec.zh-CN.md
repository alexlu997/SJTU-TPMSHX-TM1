<a id="asymmetric-porosity-2d-specification"></a>

# asymmetric-porosity-2d 规范

[中文](spec.zh-CN.md) | [English](spec.md)

<a id="purpose"></a>

## 用途
规定二维非对称孔隙率的分配和输运约束。当前共享几何入口为 `models/asym_split.py`。流体和偏移的适用范围仍受 `docs/architecture.md` 约束。

<a id="requirements"></a>

## 要求

<a id="requirement-2d-ltne-kernel-accepts-distinct-per-side-void-fractions"></a>

### 要求：二维 LTNE 核接受不同的两侧孔隙率
二维 LTNE 求解器 `solve_full_domain` 必须接受不同的两侧单通道孔隙率 ε_A 和 ε_B。两个 Gauss-Seidel 核都必须接收这两个值：字典序 `_gs_full_chunk` 和红黑序 `_gs_full_chunk_rb`。各流体的对流输运必须使用其自身通道孔隙率加权。当 ε_A ≠ ε_B 时，不得抛出 `NotImplementedError`。

<a id="scenario-asymmetric-split-solves-without-error"></a>

#### 场景：接受非对称分配
- **当** 调用 `solve_full_domain`，且 ε_A ≠ ε_B；每个单元均满足 ε_A + ε_B = ε，绝对容差为 1e-9
- **则** 接受该分配，两个核都使用各侧不同的孔隙率；原有收敛和失败报告仍然适用

<a id="scenario-per-side-weighting-is-applied-in-the-kernel"></a>

#### 场景：核内分别加权
- **当** 某单元满足 ε_A > ε_B
- **则** 该单元中，流体 A 的对流系数乘以 ε_A，流体 B 的对流系数乘以 ε_B；不得共同使用 ε/2

<a id="scenario-over-allocation-and-under-allocation-are-rejected"></a>

#### 场景：拒绝过量或不足的分配
- **当** 任一单元的 abs(ε_A + ε_B − ε) 超过 1e-9，或仅提供一侧孔隙率
- **则** `solve_full_domain` 抛出 `ValueError`；不得因重复减半而损失一半输运能力

<a id="requirement-symmetric-input-is-bit-identical-to-the-legacy-path"></a>

### 要求：对称输入与原有路径逐位一致
对称情况满足 ε_A = ε_B = ε/2，即偏移 δ=0。此时，输出场必须与原有单一 `eps_f_arr` 路径逐位一致。二维对称路径等值检查和 Shanghai 回归检查继续生效。

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
二维前处理必须根据等值面偏移 δ（`cfg['delta_levelset']`）计算 ε_A 和 ε_B。其几何分配比例必须与三维前处理相同。运行时将准备好的孔隙率传给 `solve_full_domain`。当 δ=0 时，核内必须对完整 ε 使用默认对称分配；上游不得预先减半。

<a id="scenario-nonzero-offset-drives-an-asymmetric-run"></a>

#### 场景：非零偏移驱动非对称计算
- **当** `cfg['delta_levelset'] ≠ 0`
- **则** 流水线计算 (ε_A, ε_B) = (ε·split_A, ε·(1−split_A))，二维计算全程使用两侧非对称孔隙率

<a id="scenario-zero-offset-uses-the-symmetric-path"></a>

#### 场景：零偏移采用对称路径
- **当** `cfg['delta_levelset'] = 0`
- **则** 不提供两侧覆盖值；核内仅计算一次 ε/2，并将同一数组用于两侧

<a id="requirement-2d-duty-extraction-weights-mass-flux-by-per-side-void"></a>

### 要求：二维热负荷提取按两侧孔隙率加权质量通量
δ≠0 时，二维 dP/Q 提取必须使用各侧自身的孔隙率加权质量通量：A 侧使用 ε_A，B 侧使用 ε_B。这适用于质量流量、质量加权出口温度和出口焓。加权必须与传给核的孔隙率一致，使 ṁ_A / ṁ_B 和热负荷反映非对称几何。

<a id="scenario-asymmetric-duty-weighting"></a>

#### 场景：非对称热负荷加权
- **当** δ≠0，且计算各侧出口质量通量
- **则** A 侧使用 ε_A，B 侧使用 ε_B；ṁ_A / ṁ_B 反映实际单通道孔隙率，不得共同使用 ε/2
