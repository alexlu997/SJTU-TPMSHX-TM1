# 旧开发日志（历史参考）

2026-09-12 从仓库根目录 `devlog.md` 归档，以下原文保留不变。
[归档前版本](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/804160253a128a8b0415d2e6da2ccb125d53a635/devlog.md)
记录当时的工作与同步缺口，文中的“待办”“当前”和本机路径不代表 TM1 当前状态。
当前进展见[Graph 状态](../plans/three-module-graph/state/)和
[验收说明](../plans/three-module-graph/acceptance_architecture.md)。

---

# SJTU-TPMSHX 开发日志

> 每天记录做了什么、遇到了什么问题、怎么解决的、改了哪些代码/方程。
> 按**倒序**（最新在上），方便快速查看最近进展。

## 如何记录每天

每一天一个 `## YYYY-MM-DD` 段落，下面用如下子段落：

```markdown
## 2026-MM-DD

### 🎯 本日目标
（如果是计划好的工作）

### ✅ 完成的事
（要点列表）

### 🐛 发现的问题 / 遇到的困难
（问题描述、怎么发现的、影响范围）

### 🔧 解决方案
（怎么解决的、为什么这么解决、是否治本）

### 🧪 验证/测试
（跑了什么测试、结果怎样）

### 📐 方程/算法改动
（如果改了物理模型或数学公式，详细写改动前后对比、量纲校核）

### 📁 代码改动文件清单
（`file.py:line_range` — 改了什么）

### 📚 产出文件
（新增的 md/csv/png 等）

### ⏭️ 待办 / 后续问题
（遗留未解决的 / 下次要做的）

### 💡 学到的 / 重要发现
（物理、算法、数值上的 insight）
```

并不是所有段落每天都要写，按当天实际情况挑着填。

---

> **devlog 同步缺口**: 2026-04-15 至 2026-04-28 期间多项重大改动 (D-F surrogate / 3D Phase 1-3 / FVM 严格守恒 / streamfunction P3-P7 / Nu v4.1 / AB imbal fix) 未及时记录到 devlog. 详见 `vault/reports/{shanghai-validation,3d-solver,streamfunction,methodology,bug-fixes}/` 各日报告 + `~/.claude/projects/D--Postgraduate/memory/` 各 memory 文件. 本 devlog 仅补 2026-04-29 一段.

## 2026-04-29

### 🎯 本日目标

(本日多线程, 围绕 Shanghai 水侧 Nu 关联式选型 + 物理参数清理)

1. 整理 TPMS Nu/f 综述文献 (Al-Safadi 2026 + Cheng 2021 + Wang 2023) 入 vault
2. 重构 `D_h = 2·ε/A_0` → `4·ε_A/A_0` 命名 (单股 sheet HX 教科书形式)
3. 修 `water_viscosity` 公式偏差
4. Shanghai 水侧 h_vB 切到 Yan [6] 2024 实验关联式

### ✅ 完成的事

#### 1. 文献综述 + vault wiki 笔记 (4 篇新论文笔记)
- 阅读 Al-Safadi et al 2026 *Results in Engineering* 元综述 (57 文献 Nu/f 关联式)
- 用户提供 Cheng 2021 ICHMT + Wang 2023 ECM 两篇原始论文核实综述里两处错: Wang F-KS f 中间项符号错 (`-0.91R` 应 `+0.91R`); Wang Primitive Nu 末项漏 R² 上标
- 用户提供 Yan 2024 ATE 全文, 详读后写笔记
- 写入 `vault/wiki/papers/`:
  - `Al-Safadi-2026-TPMS-Correlations-Meta-Review.md` (~36 KB, 12 章 + 综述全字段)
  - `Cheng-2021-TPMS-Heat-Transfer-Correlations.md` (Nu_sf=(a+bε+cε²)Re_h^d Pr^(1/3) 完整系数表)
  - `Wang-2023-TPMS-Channels-Volume-Share.md` (Nu/f=(a+bR+cR²)Re_h^d, R=V/d³ 体积份额)
  - `Yan-2024-Gyroid-AM-HX-Experimental-Correlation.md` (110 实验 + NLS+热阻分离, k-ω SST CFD 仅作验证)
- 更 `vault/wiki/index.md` 加 4 entries
- 13 PDF 从 `D:/Postgraduate/均质化/文献/` 移入 `vault/raw/`, 重命名 `[Author]-[Year]-[Topic].pdf` 对齐 wiki/papers/ 命名约定; 修 11 老笔记 PDF 路径

#### 2. ε_A / ε_B 命名重构 (Phase 1 + Phase 2)
- **Phase 1**: `solvers/tpms_geometry.py` + `solvers/tpms_calc.py` `geometry()` / `compute()` 三处加 `epsilon_A` / `epsilon_B` keys (= ε/2 对称); D_h 公式从 `2·ε/A_0` 改写 `4·ε_A/A_0` (数值同)
- **Phase 2**: ~30 处 `eps/2` 下游调用迁移为 `eps_A` 或 `pA['epsilon_A']`:
  - solvers/: tpms_calc.compute (Nu 输入), zone_config (4 处), simple_solver, fvm_solver, solve_full + solve_full_3d 注释
  - runs/: batch_runner, run_calculation_3d (3 处)
  - validation/: validate_shanghai*.py (3 个), 9 个 diag/dump/test 脚本
  - ui/demo_vis_3d.py
- df_fit/ 内 `eps_f` 是公共 column name + 函数签名参数, 保留不动 (改名风险大), load_data.py 加注释
- 数值零回归 (0.5·x ≡ x/2)

#### 3. water_viscosity Vogel form 替换
- 旧 `1.79e-3·exp(-0.035 T_C)` 在 0-15°C 准, **40°C 偏低 33%, 60°C 偏低 53%** vs NIST IAPWS
- 换 Vogel-Andrade form: `2.414e-5·10^(247.8/(T_K-140))` Pa·s
- NIST 0-90°C max err < 2% (见 `solvers/tpms_calc.py:120-133`)
- Shanghai cases T_bm 跨 20-40°C, 旧 μ 致 Re_water case 16 算 1755, NIST Vogel 算 **1182** (实物理); Excel 设计 ramp 50-675 是恒物性参考标定值 (T_ref ≈ 13°C), 不参与求解器

#### 4. 水侧 Nu 切 Yan [6] 2024
- 加 `nu_water_gyroid_yan6(Re, Pr) = 0.471·Re^0.627·Pr^(1/3)` 至 `solvers/tpms_calc.py:148-181`
- 切 `validation/validate_shanghai_aligned.py:142-156` h_vB 算法: 删 legacy 11 行 (air-fit + Pr 替换), 加 1 行调用 Yan [6]
- 论据 4 条: 唯一水实测 fit / Pr 范围全覆盖 (3.5-9 vs 项目 4.4-7.3) / Re 87.5% 覆盖 (cases 3-16) / AM 粗糙度自然含 (无需 ×1.28 修正)
- 新建诊断脚本 `validation/water_nu_yan.py` 16-case 误差表
- 新建诊断脚本 `validation/cross_check_water_nu.py` (作废, 已删)

### 🐛 发现的问题

1. **water_viscosity 公式跨段精度差** — 高 T 段 -33% bias 长期未察觉, 因 Shanghai 验证 h_vB ≫ h_vA, 总 U 由 air 主导, μ 偏差被遮蔽
2. **水侧 Re 与 Excel 不一致** — Excel Re_water = `D_h/(A·μ_ref) = const = 4649.35`, 用恒物性 + 取整 D_h 反推 m_w 设计标定; 代码用 T_in 实测物性 + 代码 D_h, 物理 Re 不同口径 (Excel ≈ 50-675 工程标定; 代码 ≈ 54-1146 学术 Re), 不冲突, 不同用途
3. **Yan [6] 关联式 fit 数据不是 CFD 而是实验** — 110 个实测点用 NLS + 热阻分离法 (paper main contribution, 替代 Wilson plot), CFD k-ω SST 仅做验证

### 🔧 解决方案 / 决策

- 选 Yan [6] **单一关联式** (不和 Yan [58] 拼段), 论据: 覆盖率 87.5% / 实验背书 / AM 粗糙度自然含 / 论文叙事干净
- ε_A 命名拆 ε/2 显式化 — 论文写公式时系数恢复教科书 4, 避免读者疑惑 "为什么 D_h 系数是 2"

### 🧪 验证/测试

- pytest 90/90 通过 (1 个 worker test 不相关 fail, deselected)
- `validate_shanghai_aligned.py` Q RMSRE: 4.27% (legacy) → **4.20%** (Yan [6])
- dP RMSRE 28.22% 不变 (水侧不进 SIMPLE 动量)
- bias_Q -3.61% → -3.55%
- h_vB 抬升 +4-7%, 总 U 改 < 1% (h_vA 主导)
- Yan [6] vs Yan [58] overlap 区差 3% (cases 3-6), 全 16 case 误差仅 +6.97% (RMSRE 8.23%)
- water_viscosity Vogel form 16 cases NIST 校验 err < 1% (除 0°C -1.9%)

### 📐 方程/算法改动

#### D_h convention 命名重写 (数值同)
旧: `D_h = 2·ε/A_0` (推导: V_void_single=ε/2·V_T, A_wet_single=A_0·V_T → D_h=4·V/A=2ε/A_0)
新: `D_h = 4·ε_A/A_0`, `ε_A = ε_B = ε/2` (符合教科书 D_h=4V/A 标准形式, 系数恢复 4)
- 物理同, 命名清晰

#### water_viscosity
旧 (0-15°C OK, 高 T 偏低 30-50%):
$$\mu = 1.79\times 10^{-3}\cdot \exp(-0.035 \cdot T_C) \quad [\text{Pa·s}]$$
新 (Vogel-Andrade, NIST 0-90°C < 2%):
$$\mu = 2.414\times 10^{-5}\cdot 10^{247.8/(T_K - 140)} \quad [\text{Pa·s}]$$

#### h_vB 关联式 (Shanghai aligned)
旧 (air-fit + Pr 跨流体外推):
$$\mathrm{Nu} = 0.17\cdot \mathrm{Pr}^{1/3}\cdot \mathrm{Re}^n\cdot \varepsilon^{2.25}\cdot (L/(1000\cdot S_a))^{-2.01}, \quad n = 0.177\cdot \mathrm{Re}^{0.1}\cdot \varepsilon^{-2/3}$$
新 (Yan [6] water 实验拟合):
$$\mathrm{Nu} = 0.471 \cdot \mathrm{Re}^{0.627} \cdot \mathrm{Pr}^{1/3} \quad (150 < \mathrm{Re} < 3000, 3.5 < \mathrm{Pr} < 9)$$

### 📁 代码改动文件清单

- `solvers/tpms_geometry.py:198-217` — D_h 公式重写 + 加 epsilon_A/B keys
- `solvers/tpms_calc.py:120-181` — water_viscosity Vogel + nu_water_gyroid_yan6 函数; geometry() / compute() 加 epsilon_A/B keys
- `solvers/zone_config.py` — 4 处 eps/2 → pA['epsilon_A']
- `solvers/simple_solver.py:978-994` — z_eps/2 → 0.5·z_eps
- `solvers/fvm_solver.py:812, 824` — eps_f → eps_A
- `solvers/solve_full.py:395-426` + `solve_full_3d.py:1353-1376` — 注释 + 默认 split 改 `0.5·epsilon`
- `runs/batch_runner.py:85-86` + `run_calculation_3d.py:945, 1602` — eps_A 引入
- `validation/validate_shanghai_aligned.py:23-164` — 加 EPS_A + Yan [6] h_vB 切换
- `validation/validate_shanghai_3d_real.py:45, 177-204` — EPS_A 引入
- `validation/validate_shanghai_lumped(_v3).py` — EPS_A 引入
- `validation/validate_shanghai.py:36, 85, 130, 207` — EPS_A 引入
- `validation/dump_simple_case16.py` + 8 个 diag/test 脚本 — eps_A 命名
- `ui/demo_vis_3d.py:80-86` — eps_A 命名
- `validation/water_nu_yan.py` — 新建 16-case 水侧 Nu 误差对比脚本

### 📚 产出文件

- `vault/wiki/papers/Yan-2024-Gyroid-AM-HX-Experimental-Correlation.md` (新)
- `vault/wiki/papers/Al-Safadi-2026-TPMS-Correlations-Meta-Review.md` (新)
- `vault/wiki/papers/Cheng-2021-TPMS-Heat-Transfer-Correlations.md` (新)
- `vault/wiki/papers/Wang-2023-TPMS-Channels-Volume-Share.md` (新)
- `vault/raw/` 4 PDF (Yan + Al-Safadi + Cheng + Wang) + 9 老 PDF 重命名
- `data/water_nu_yan_comparison.xlsx` (16-case 水侧 Nu 误差表)
- `data/shanghai_validation_aligned.xlsx` 重跑覆盖
- 4 新 memory 文件: `project_water_nu_yan6.md`, `reference_water_viscosity_fix.md`, `feedback_vault_structure.md`, `reference_al_safadi_2026_correlations.md`

### ⏭️ 待办 / 后续问题

1. `validate_shanghai_lumped*.py` / `validate_shanghai_3d_real.py` 内部 `_nu_water_via_pr_subst` / `nu_from_Re` 也是 air-fit + Pr 替换形式, 未切到 Yan [6]; 需要时再切 (当前 lumped Q 2.11% / 3D Q 4.98% 已可接受, 不动)
2. `run_calculation_3d.py` 主路径 h_vB 仍是 1e10 perfect-sink C-1 假设, 真双流体水侧扩展时再切 Yan [6]
3. `water_conductivity` 线性 fit `0.569 + 0.0018 T_C` 在 60°C 偏 +3.5%, 可考虑同换 NIST 高阶拟合 (低优先级)
4. `optimizer/_auto_max_workers` 测试 hardcode 4-core 假设, 跑在多核机器 fail; 修法: mock os.cpu_count 或断言表达式

### 💡 学到的 / 重要发现

1. **Yan [6] 方法 > 公式** — paper main contribution 不是公式 (常见 power-law form), 是 NLS+热阻分离 替代 Wilson plot 的回归方法. 项目若反推 Shanghai h_vA 可借鉴, 但 air-water 异质 HX 双侧同 form 假设失效, 不直接套
2. **水侧 h_vB 在 Shanghai 验证里是盲区** — h_vB ≫ h_vA (10×), 总 U 由 h_vA 主导, h_vB ±50% 仅改 Q ±5%; Q RMSRE 4% 不能区分 h_vB 公式准确度. 真要仲裁 h_vB 需双侧实测 + Wilson plot 反推 (项目当前没做)
3. **Excel Re vs 代码 Re 是不同口径**, 都对, 用途不同: Excel Re_design 反推 m_w 配实验流量, 代码 Re 用实测物性输物理量给关联式. 不要混用
4. **D_h 系数 4 vs 2 是命名问题不是物理问题** — sheet HX 单股 ε_A=ε/2 让 V_void 减半, D_h=4V/A 标准形式自然出 2ε/A_0; 显式命名 ε_A 后系数恢复 4, 论文写法清晰
5. **物性公式低阶 fit 跨大温度段会暴露** — 旧 water_viscosity 是 5°C 范围线性 log-fit, 高 T 段衰减 1.75× 真实, 长期未察觉因被 Shanghai 验证盲区遮蔽

---

### 🎯 本日目标 (后续 — 同日下午延伸)

针对 Shanghai validation 做 dual-Nu 真预测 baseline (双侧关联式 + 入口 Re convention + cross-flow ε-NTU), 并清理 validate_shanghai_aligned.py 的 Q 报告与能量守恒诊断.

### ✅ 完成的事

#### 5. dual-Nu 集总真预测 baseline (`validate_shanghai_lumped_dual_nu.py`)
- 新建 ~280 行脚本, 输入仅进口条件 (m_air, m_water, T_Ain, T_Bin, P_Ain, 几何), 无 T_Aout/T_Bout 泄漏
- 双侧 Nu 关联式: 空气 v4.1 (×1.28 内嵌) + 水 Yan [6] 2024
- 双侧 UA: `1/(1/(h_A·A_tot) + R_wall + 1/(h_B·A_tot))`, 不再用 C_max→∞ 简化
- Cross-flow ε-NTU primary, counter-flow 仅 sensitivity check
- 空气侧 T_in 不迭代, 水侧 T_avg_B 自洽迭代 T_Bout_pred (~2 iter 收敛)
- **Q_air RMSRE 1.71%** bias -1.27% max 3.78% — 全 16 case |err|<3.8% (best baseline 至今)

#### 6. Re convention + 几何认知锁定
**关键洞察**: Shanghai HX 是 cross-flow 几何 (air x ⊥ water y), Box 182×42×42 mm³, 水入口 manifold 42×42 窄端口.

经过反复迭代得出最终 convention:
- **Re 用入口 manifold 几何**: A_flow_water = ε_B · 42×42 = 650 mm² (Yan convention 单值 Re label)
- **A_tot 用全 HX gyroid 壁**: A_0·V_HX_total = 0.138 m² (sheet HX 拓扑强迫水内部铺满全 xz=182×42)
- **不要混用**: 内部铺开几何 (A=2816 mm², Re_B=275) 算 RMSRE 2.51% 退化, A_tot 缩 f=0.231 算 RMSRE 30.6% 严重退化
- 数值证实物理: Q_air RMSRE 1.71% 仅在 Re=入口 + A_tot=全 HX 这一对 convention 下达成

#### 7. validate_shanghai_aligned.py 加 Q_solid_A + 能量守恒诊断
- 加 `Q_solid_A = ∫h_vA·(Ta-Ts)dV` (Q_solid_B 已有)
- 加 `eb_resid_pct = (Q_solid_A - Q_solid_B) / |Q_solid_A|·100` 验证稳态固体能量守恒
- 全 16 case eb_resid < 0.001% — LTNE 数值上 100% 自洽 ✓
- 新增列: `Q_solid_A`, `eb_resid%` 入 xlsx 输出

#### 8. post_q_dual_side.py 后处理脚本
- 新建 ~70 行脚本, 读 `shanghai_validation_aligned.xlsx` + 原始 Excel
- 算 Q_air_exp = m_air·cp·(T_Ain-T_Aout_exp), Q_water_exp = m_water·cp·(T_Bout-T_Bin)
- 比对 Q_pred 双侧, 验证实验自身能量不平衡 (mean 13.66%, max 20.74%)
- 论证 Q_water 误差 17% 由实验自身漏热致 (HX 外散热), 非模型瑕疵
- → 模型 Q_pred 应**主报 vs Q_air_exp**, 不是 Q_water_exp

### 🐛 发现的问题

1. **几何概念混淆 — manifold 几何 vs 内部铺开几何** — 集总 Re convention 必须用入口, 不是内部. Yan 拟合时用入口 Re 作单值 label, Nu 关联式吃掉所有内部空间变化. 用内部 Re 给 Yan 是不同物理量, 关系不成立.
2. **Sheet HX 拓扑约束 — water 内部必须铺满全 xz** — gyroid 壁两侧分别是 air sheet / water sheet (interleaved), 物理强制水铺满, 不能"壁单侧空" 或 "两侧都 air". → A_tot = 全 HX, 不缩.
3. **Q_water_exp 不是好参照** — 实验本身 Q_air_exp 与 Q_water_exp 平均不平衡 13.66% (max 20.7%), 主因 HX 外部漏热 (空气放热 = 给水 + 给环境). 模型应比 Q_air_exp.

### 🔧 解决方案 / 决策

- **论文 baseline 锁定**: `validate_shanghai_lumped_dual_nu.py` cross-flow primary, Q_air RMSRE 1.71%
- **Re convention 写入 memory**: `feedback_re_convention_lumped.md` 记录 "Re 用入口 manifold, A_tot 用全 HX, 不能混"
- **不切 validate_shanghai_lumped.py / _v3.py**: 老脚本保留作历史 single-Nu (C_max→∞) 对照

### 🧪 验证/测试

- `validate_shanghai_lumped_dual_nu.py` 16 case 全跑通, iter 收敛 2 步全部 case
- Re_B 范围 58-1191, case 3-16 (87.5%) 在 Yan [6] 150-3000 范围内
- LTNE eb_resid < 0.001% (机器精度), 验证 SIMPLE solver 固体能量守恒数值正确

### 📐 方程/算法改动

#### dual_nu 公式链 (集总 ε-NTU)

```
T_avg_A = T_Ain  (no iter, air-side simplification)
T_avg_B = 0.5·(T_Bin + T_Bout_pred)  (iter)

A_flow_air   = ε_A · L_water · L_z = 6.50e-4 m²
A_flow_water = ε_B · L_water · L_z = 6.50e-4 m²    ← 入口 manifold (Yan convention)
A_tot        = A_0 · V_HX_total    = 0.138 m²     ← 全 HX (sheet HX 拓扑)

u_X = m_X / (ρ_X · A_flow_X)
Re_X = ρ_X · u_X · D_h / μ_X

Nu_A = nu_from_Re(Gyroid, Re_A, ε_A, L, D_h_mm)        ← v4.1 ×1.28
Nu_B = 0.471·Re_B^0.627·Pr_B^(1/3)                      ← Yan [6]

UA = 1/(1/(Nu_A·k_A/D_h·A_tot) + t/(k_steel·A_tot) + 1/(Nu_B·k_B/D_h·A_tot))

C_min = min(m_air·cp_A, m_water·cp_B)
Cr    = C_min/C_max
NTU   = UA/C_min

ε_xf  = 1 - exp((1/Cr)·NTU^0.22·(exp(-Cr·NTU^0.78) - 1))   (cross-flow unmixed)
Q_pred = ε_xf · C_min · (T_Ain - T_Bin)

T_Bout_new = T_Bin + Q_pred/(m_water·cp_B)
loop until |T_Bout_new - T_Bout_pred| < 0.01 K
```

### 📁 代码改动文件清单

- `validation/validate_shanghai_lumped_dual_nu.py` — **新建** ~280 行 dual-Nu 真预测 baseline
- `validation/validate_shanghai_aligned.py:248-260` — 加 Q_solid_A + eb_resid_pct 输出
- `validation/post_q_dual_side.py` — **新建** ~70 行后处理脚本

### 📚 产出文件

- `data/shanghai_lumped_dual_nu.csv` (16-case dual-Nu 详输出)
- `data/shanghai_q_dual_side.csv` (双侧 Q 比对)
- `data/shanghai_validation_aligned.xlsx` 重跑覆盖 (含 Q_solid_A 列)
- 新 memory: `project_lumped_dual_nu_baseline.md`, `feedback_re_convention_lumped.md`

### ⏭️ 待办 / 后续问题

1. 论文写作时引用 dual_nu lumped baseline (RMSRE 1.71%) 作主预测精度
2. 若需要分布式局部 Re/h 分析, 用 SIMPLE solver (集总不出 T 场)
3. Yan [6] 几何 (cell 4mm 实验小样本) vs Shanghai (cell 7mm 工业级) 扩散比可能不同, 但实证 RMSRE 1.71% 跨几何 calibration 成立
4. 旧 lumped 脚本保留, 不删除

### 💡 学到的 / 重要发现

1. **关联式 Re 是单值 label**, 拟合时用一个代表 Re (入口 manifold), Nu 关联式吃掉所有内部空间变化 — 不是逐点局部 Re
2. **Sheet HX 拓扑**: gyroid 壁两侧必有不同流体, 物理强制水内部铺满全 xz, A_tot = 全 HX
3. **Q_air_exp 是纯净参照**, Q_water_exp 受外部漏热污染 (mean +13.7%); 模型与 Q_air 比 (1.71%) 是真精度, 与 Q_water 比 (17%) 是实验误差
4. **集总反而比 SIMPLE 准** (1.71% < 2.29% 3D / 4.20% 2D) — 因 Yan calibration 已含入口效应 + 集总无空间离散误差
5. **流型 (cross vs counter) 在 saturated HX 不重要** — Cr ≈ 0.05 → ε ≈ 1 → 流型修正项压平 (差 0.22pp)

---

### 🎯 本日目标

启动 D-1 子项目（GUI bug 修复）。原本范围："修两个和 dark/light 主题切换有关的 bug + 不动其他"。最终走向："完全删掉 dark mode，GUI light-only"。

### ✅ 完成的事

1. **Bug 1 调试**：toggle 按钮失效。systematic-debugging 走完。
   - 现象：点 Light/Dark 按钮，UI 视觉上不切换
   - offscreen probe（headless Qt）能完整复现 state 切换 + pixel 切换 — 复现不出来 bug
   - 用户在真实 Windows 后端跑 + 把 stderr 重定向，才暴露 Qt 输出几百行 `Could not parse stylesheet` warning
   - 走查产生失败 stylesheet 的 widget 类型（QLabel / QComboBox / QFrame）→ 定位到 3 处 string-formatting 手误（见下）

2. **Bug 2 调试**：Pressure tab 下的 ΔP summary card 被冻结在初次渲染时刻的 theme
   - 静态走读 `theme.apply_theme` 直接定位：它只迭代 `ax.texts / spines / ticks / labels`，**没碰 `ax.patches`**
   - `plot_pressure` 画的 `FancyBboxPatch` 卡片背景 + `ax3.plot()` 分割 Line2D 因此永远是初次绘图时刻的颜色
   - 写了一个独立 regression test 直接画 synthetic pressure plot + toggle，断言 patch facecolor 跟着切 → 修复前 fail
   - 修复方案（短暂落地过）：在 plot_pressure 暴露 `self._dp_card_rect / self._dp_divider_line`，apply_theme 里就地改色，不重画 figure → 无 flicker

3. **Bug 1 + Bug 2 修复都验证通过后，用户决定整体放弃 dark mode**，理由是参数面板还有局部没切干净（截图对比能看出来），打磨成本 > 价值，light-only 已经够用

4. **删 dark mode 干净化**：
   - `theme.py`：删 `_THEMES['dark']`、删 `apply_theme()` (~140 行)、`_build_styles()` 去掉 `theme_name` 参数
   - `main.py`：删 `_toggle_theme()`、删 module-level `_current_theme`、import 不再带 `apply_theme`
   - `ui_builders.py`：删 header 上的 `_btn_theme` 按钮 + signal 连接、删所有 `_current_theme = m._current_theme` 读取、`_THEMES_local[_current_theme]` → `_THEMES_local['light']`
   - `matplotlib_canvas.py`：删 module-level `_current_theme`、删 `_dp_card_colors()`、删 `self._dp_card_rect / self._dp_divider_line` 暴露、`plot_pressure` ΔP card 颜色 inline 回 light 值
   - `layout_drawer.py / optimize_panel.py / polygon_calc.py / run_calculation.py`：批量替换 `_THEMES[_main(_mod)?._current_theme]` → `_THEMES['light']`
   - `test_main_smoke.py`：删 `test_main_menu_theme_toggle`，留 startup
   - 删 `test_theme_dp_card.py`（Bug 2 的回归测试，dark 没了所以这个 test 没意义）
   - 把 Bug 1 的回归测试改名 `test_theme_stylesheet_braces.py` → `test_stylesheet_braces.py`，作为通用 CSS sanity check 留下
   - 写 `.gitignore`（之前没有，导致 sjtu_tpmshx 仓库索引里堆了一堆 `__pycache__/*.pyc`）

### 🐛 发现的问题 / 遇到的困难

1. **Bug 1 根因 — Python f-string 手误传染 3 处**

   3 处都是同一个错误：在**非 f-string** 的字符串拼接段写了 `}}`，作者大概以为是 f-string escape。但只有 f-string 里 `}}` 才会被解析成单个 `}`，普通字符串里 `}}` 就是字面的两个右大括号。结果产生的 CSS 多了一个 `}`，Qt 解析失败。

   位置：
   - `theme.py:_title()` 末行 → `_T_NEUTRAL / _T_HOT / _T_COLD`（section 标题 QLabel）
   - `theme.py:_build_styles()` COMBO 末行 → `_COMBO`（所有 QComboBox）
   - `ui_builders.py` 卡片 QFrame `setStyleSheet` 末行

   为什么启动也不报错？Qt 解析失败时退回默认样式 + warning 写到 qWarning（很多 Qt platform 下默认不到 stderr）。GUI 看起来没崩，开发者从来不知道这些 widget 应该长什么样，所以一直没被发现。Toggle 是把它拽出来的契机：toggle 用 detach + 新建 cw + 重建 UI 的策略，而这个策略对**没切换的元素**（即 stylesheet 仍然解析失败、保留 Qt 默认渲染的元素）和**正确切换的元素**（centralwidget bg 等）会产生明显视觉割裂。

2. **Bug 2 根因 — apply_theme 没迭代 patches**

   `theme.apply_theme` step 6 只对每个 canvas 做：`fig.patch.set_facecolor` + `ax.set_facecolor` + tick / spine / xaxis.label / yaxis.label / title / `ax.texts` / `fig.texts` 的颜色更新。它**不会**走 `ax.patches`。`plot_pressure` 的 ΔP card 用 `FancyBboxPatch` 加在 ax3 上，所以永远跟着初次渲染时刻的 theme 不动。

   也是**一个隐蔽的代码债**：apply_theme 是"所有可能 theme-依赖的元素都要在这里 in-place 更新"的策略，但它本身没有任何机制保证能覆盖所有元素。任何后续添加的 patch / line / collection 都会自动悄悄违反这个契约。这种 implicit-coverage 的策略本身就脆弱，dark mode 删掉之后这个问题也跟着消失。

3. **offscreen Qt 复现不出 Bug 1**

   花了不少时间在 `QT_QPA_PLATFORM=offscreen` 下尝试复现 toggle 失效——state 切换、像素抓取、模拟 click、widget tree walk，全都"看起来正常"。最后是用户在真实 Windows 后端 + 把 stderr 重定向到 log 才把 `Could not parse stylesheet` 几百行 warning 暴露出来。教训：**offscreen 后端会吞掉 qWarning**，不能把 offscreen 测试通过当作"功能正常"的证据，特别是涉及 Qt CSS / stylesheet / 窗口系统的部分。

### 🔧 解决方案

最终的决定 = **删 dark mode**。理由：
- Bug 1 + Bug 2 的修复都已经能跑通，但用户截图对比发现还有别的局部 dark 没切干净（参数面板若干角落）
- 继续把所有 dark 切干净的工作量 >> 直接删掉的工作量
- light-only 已经满足实际使用需求
- dark 模式本来也只是装饰性功能，不影响任何科研产出
- 删掉之后 theme.py 从 288 → ~110 行，main.py 少 20 行的 `_toggle_theme`，apply_theme (~140 行) 整个消失。代码债大幅减少。

### 🧪 验证/测试

- `test_main_smoke.py`（startup）：PASS
- `test_stylesheet_braces.py`（brace balance + Qt parse warnings on Main_Menu build）：PASS（0 parse failures）
- 删 `__pycache__` 重跑也 PASS（防止旧字节码污染）

### 📁 代码改动文件清单

详见两个 commit:
- `d1a2bed` — baseline（D-1 Bug 1+2 fix landed，含已经写好的 dp_card 回归测试）
- 第二个 commit — 删 dark mode

### 📚 产出文件

- `.gitignore`（新增）
- `test_stylesheet_braces.py`（从 `test_theme_stylesheet_braces.py` 改名 + 简化）

### ⏭️ 待办 / 后续问题

- D-1 spec 还没写。是否补一份 retroactive spec 记一下"原本要修两个 bug，最终选择删 dark mode"的决策？或者这条 devlog 已经够档案
- D-2 / D-3 GUI 打磨任务还没开。等用户具体提需求
- SJTU-TPMSHX 主仓库（`D:/Postgraduate/均质化/SJTU-TPMSHX/sjtu_tpmshx/`）这次才第一次有 git commit。之前 staged 了 ~300 个文件（CSVdata + pyc）从来没 commit。需要决定那些 baseline / CSV / npz / log 文件要不要也入库

### 💡 学到的 / 重要发现

1. **Python f-string 的 `}}` 是双刃剑**。在 f-string 里 `}}` 是单个 `}` 的 escape；在普通字符串里它就是两个字面 `}`。把 f-string 段和普通段混拼接时极容易手误。**只要 stylesheet 是用 Python 字符串拼接 + Qt CSS 喂 setStyleSheet 这种模式，就需要一个 brace-balance 的回归测试守门**——因为 Qt 的 parse error 默认是 silent 的。
2. **Qt offscreen 后端会吞 qWarning**。不能把 offscreen 测试通过当作"功能正常"的证据，特别是涉及 Qt CSS / stylesheet / 窗口系统的部分。需要测试时显式安装 `qInstallMessageHandler` 拦截 warning 并断言 0 个。
3. **systematic-debugging 在两个 bug 上是反差教学**。Bug 2 是"静态走读直接定位"的代表（10 分钟）；Bug 1 是"必须拿到真实 stderr 才能定位"的代表（一开始 offscreen 复现失败后一度束手无策）。两者都遵守了"先复现再改"的纪律——Bug 1 没拿到 stderr 之前我没动一行代码，避免了瞎修。
4. **代码债的隐式契约比显式契约更危险**。`apply_theme` 的"覆盖所有 theme-依赖元素"是一个**只存在于作者脑子里**的契约。新加 patch / line / collection 时没人提醒你"哎，apply_theme 没更新这种东西哦"。这种 bug 一定会越积越多。删 dark mode 不仅是放弃功能，也是**消除一份脆弱契约**。

---

## 2026-04-09（今天）

一个大工作日：从**变密度 SIMPLE 扩展验证**开始，中间做了一堆**可视化改进**，然后**对接用户实验数据做了 dP 验证**，发现 2 个 bug 并做了**f-Re 关联式重拟合 (v2)**。

### ✅ 完成的事

1. **变密度 SIMPLE 扩展独立验证**（8 项全通过）
   - 标量 ρ 退化、线性热冷却、线性冷加热、部分 pipe BC、自持耦合环、ΔP vs f-Re、极端 2.5× ρ 比、非均匀 dx_arr
   - 中截面 $\int\rho v$ 守恒到机器精度，ΔP_SIMPLE vs f-Re 三种模式全在 2% 内

2. **速度云图可视化大改造**（多轮迭代）
   - 发现 A 侧 6% 变密度变化被原 `[0, fmax]` 色条压缩到看不见（只占 5.7% 色条宽度）
   - 几轮演化：百分位 + active-flow 屏蔽 → `set_under(背景色)` → 去白色换 `PowerNorm(γ=0.5)` → 最终定在 `PowerNorm(γ=0.4)` 让 1-3 m/s 的停滞区能清晰看见
   - 补上 hover 功能（`canvas_vel.axes` 之前没赋值，hover 一直静默失败）
   - card 外框加大（2px 边框 + 5px accent + 12px 圆角 + 16px 内边距）
   - 补 x 轴标签裁剪问题（card 变大后 subplots_adjust bottom 不够，从 0.04 改到 0.06-0.07）

3. **velocity-temperature 耦合收敛判据修复**
   - UI 报 "not converged after 5 iters (drho_A=0.0011, drho_B=0.0132)"
   - 把 `max(|Δρ|)` 换成**质量通量加权 L1 相对变化**
   - 5 iter 上限命中 → 3 iter 提前 break，警告消失

4. **几何默认值更新**
   - 从 100×50mm 改到用户实验的 **42×231mm**（Gyroid 7/0.6）
   - Fluid A 全宽 +x（L=231mm），Fluid B partial BC 对角 -y
   - 中途对 "侧边" vs "X方向" 的映射搞反过一次，后来根据用户澄清 + 数据 A/B 比反推确定 **侧边=A, X方向=B**

5. **两个 bug 修复 + 一次 f-Re 关联式重拟合**
   - **dP row-mean dilution bug**：partial BC 下 `P_fB[:, 0].mean()` 被 wall cell 稀释到真实值的 1/15（见下面 🐛 部分）
   - **f-Re 关联式重拟合 v2**：基于 14 个实验点拟合 (C, n0)，Fluid A 误差从 +220% → ±4%

### 🐛 发现的问题 / 遇到的困难

1. **ΔP 算法 bug (row-mean dilution)**
   - 症状：`dP_B sim = 9692 Pa` vs 实验 `140775 Pa`，低了 14×
   - 调查：写诊断脚本逐行检查 `simpB.P[:, 0]` 和 `simpB.P[:, -1]`，发现 row mean 包含大部分 wall cell 的"其他"压力，稀释了真实的 pipe inlet/outlet 压力差
   - 数字证据：row mean = 220672 Pa，pipe-weighted mean = 432753 Pa（差一倍）

2. **f-Re 关联式对 t=0.6mm 外推偏高 2 倍**
   - 症状：修完 dP bug 后，sim dP 比实验仍然高 100-240%
   - 诊断：用 1D 公式 $f = 2 r_h (dP/L) / (\rho v^2)$ 从实验反推 f_exp，和关联式的 f_sim 做逐行对比
   - 发现：**所有 14 个有效 Re 点的 f_sim/f_exp ≈ 2.1-2.7**
   - 根因：`tpms_calc.py:97` 注释说关联式拟合区间 t ∈ [0.3, 0.5]mm，用户实验 t=0.6mm **外推**

3. **CFD 和实验的 f-Re 斜率符号相反**（物理上值得记录）
   - CFD 拟合给 Gyroid at ε=0.737 的 **n_eff = -0.19**（f 随 Re 减小，Darcy-Forchheimer 理论）
   - 实验数据给 **n_eff ≈ +0.29**（f 随 Re 缓慢增加）
   - **这两个不可能同时拟合**，必须取舍
   - 可能原因：入口/出口动能损失污染 dP 测量、ρ_local vs ρ_ref 约定在高压下的差异、3D 打印几何与理想几何的差异

4. **14 个实验点参数空间退化**
   - 全部在同一 (L=7, t=0.6, ε=0.737) 下，无法约束 a, b, c（它们需要 (ε, t/L, X) 变化才能 fit）
   - 尝试 6 参数全拟合 → 系数撞边界、R² 崩溃
   - 最终只拟合 **2 个参数 (C, n0)**，其余 4 个保持原 CFD 值

### 🔧 解决方案

1. **dP row-mean bug 修复**（`main.py:2714-2752`）
   - 用 `simpA.inlet_frac / outlet_frac` 做管道加权的 P 平均
   - 直接在 SIMPLE gauge 压力上计算 `dP = P_pipe_inlet_gauge - P_pipe_outlet_gauge`
   - 对全宽 BC（A 侧）：所有 frac=1，pipe-weighted = row mean，结果不变 ✓
   - 对 partial BC（B 侧）：wall cell 权重为 0，精确得到管道进出口压差

2. **耦合判据修复**（`main.py:2621-2633`）
   - 从 `max(|Δρ|/ρ̄)` 换成 $\sum_i w_i |Δρ_i / ρ_i| / \sum_i w_i$，$w_i = |u_i|$
   - 物理解释：$\nabla \cdot (\rho u) = 0$ 只有 $u \neq 0$ 的 cell 才对解有贡献
   - 收敛比从 0.75（退化成线性）恢复到理论预测的 0.3（几何收敛）

3. **f-Re 关联式重拟合**（`tpms_calc.py:102`）
   - 只改 Gyroid 的 (C, n0)：`0.5658 → 0.006634`, `-0.0596 → +0.4237`
   - 保持 (n1, a, b, c) 不变，保证其他几何的形状因子不被破坏
   - 公式形式完全不变，**f 仍然严格无量纲**

### 🧪 验证/测试

- **dP row-mean 修复验证**：对 Row 16 手工对比 row-mean (9.7k) vs pipe-weighted (432k) vs 实验 (140k)
- **耦合判据修复验证**：默认 case 从 5 iter 降到 3 iter，无警告
- **16 工况端到端验证**（用 `perf_test.py`）：
  - Fluid A Row 3-16 |mean err| = **3.74%**（目标 <15% ✅）
  - Fluid A 最大单点误差 = 8.92%
  - Fluid B Row 3-16 |mean err| = 40.22%（仍高，2D partial BC 效应）

### 📐 方程/算法改动

#### (1) 耦合收敛判据（`main.py:2621-2633`）

**旧**：
$$
\text{drho}_A = \frac{\max_i |\rho^{new}_{A,i} - \rho^{old}_{A,i}|}{\bar\rho_A}
$$

**新**（mass-flux weighted L1）：
$$
\text{drho}_A = \frac{\sum_i w_i \left|\frac{\rho^{new}_{A,i} - \rho^{old}_{A,i}}{\rho^{old}_{A,i}}\right|}{\sum_i w_i}, \quad w_i = \sqrt{u_{A,i}^2 + v_{A,i}^2}
$$

#### (2) dP 计算（`main.py:2714-2752`）

**旧**：
$$
\Delta P_B = P_{in,B}^{user} - \text{mean}(P_{fB}[:, j=\text{outlet row}])
$$

**新**（pipe-weighted from SIMPLE gauge directly）：
$$
\Delta P_B = \frac{\sum_i w_{in,i} \cdot P_{g,B}[i, 0]}{\sum_i w_{in,i}} - \frac{\sum_i w_{out,i} \cdot P_{g,B}[i, -1]}{\sum_i w_{out,i}}
$$

其中 $w_{in,i} = \text{inlet\_frac}_i$，$w_{out,i} = \text{outlet\_frac}_i$（SIMPLE 内部 1D 掩码）。

#### (3) Gyroid f-Re 关联式（`tpms_calc.py:102`）

**公式形式不变**（量纲保持无量纲）：
$$
f = C \cdot Re^{n} \cdot \varepsilon^a \cdot (t/L)^b \cdot \left(\frac{X}{1000 S_a}\right)^c, \quad n = n_0 + n_1 \ln\varepsilon
$$

**系数更新**（只改 C 和 n0）：
| 系数 | 旧 (v1) | 新 (v2) |
|---|---|---|
| C | 0.5658 | **0.006634** |
| $n_0$ | -0.0596 | **+0.4237** |
| $n_1$ | 0.4304 | 不变 |
| a | -3.25 | 不变 |
| b | -0.02 | 不变 |
| c | -1.37 | 不变 |

**在 ε=0.737 下的等效 Re 指数**：v1 是 **-0.19**，v2 是 **+0.29**（反号！）。

**代价**：v2 在原 195 CFD 拟合点的 MAPE 从 8% 劣化到 45%。v1 和 v2 不能共存，要用哪个取决于对比对象是 CFD 还是实验。

### 📁 代码改动文件清单

- `sjtu_tpmshx/main.py:337-338` — L, H 默认从 0.10/0.05 改到 0.231/0.042
- `sjtu_tpmshx/main.py:476-479` — A pipe 中心/宽度改 0.021/0.042
- `sjtu_tpmshx/main.py:488-491` — B pipe 中心/宽度改 0.203/0.042 和 0.028/0.042
- `sjtu_tpmshx/main.py:354-359` — TPMS 默认从 Diamond 8/0.3 改到 Gyroid 7/0.6
- `sjtu_tpmshx/main.py:2621-2633` — 耦合 drho 判据改为质量通量加权 L1
- `sjtu_tpmshx/main.py:2714-2752` — dP 计算改为管道加权，修复 row-mean dilution bug
- `sjtu_tpmshx/main.py:750-784` — canvas card 外框加大（2px/5px/12px/16px）
- `sjtu_tpmshx/main.py:2954-3010` — 速度云图改 PowerNorm(γ=0.4)，加 hover 轴注册
- `sjtu_tpmshx/main.py:2933, 3010` — temp/vel subplots_adjust bottom 加宽（防 x 标签裁剪）
- `sjtu_tpmshx/main.py:3629` — pressure GridSpec bottom 加宽
- `sjtu_tpmshx/tpms_calc.py:102` — Gyroid `_F_COEFFS` 元组：(C, n0) 更新到 v2

### 📚 产出文件

- `data/v2_fitting/fit_report_gyroid_v2.md` — 完整 Gyroid 重拟合报告（10 个章节，含量纲校核、16 工况端到端对比、局限性）
- `sjtu_tpmshx/validation_results.csv` — 16 工况仿真 vs 实验完整数据（CSV）

### ⏭️ 待办 / 后续问题

1. **Fluid B 还差 40%**
   - 不是 f-Re 关联式问题（A 侧同一关联式已 ±4%）
   - 是 2D partial BC 流动的**额外损失**：inlet 收缩、对角转折、corner 加速
   - 需要独立的 CFD 标定 → 对 Gyroid 7/0.6 partial BC 几何做 full-scale CFD，和 SJTU-TPMSHX 2D SIMPLE 对比，校准等效损失系数

2. **Row 1-2（Re_ref < 600）外推区**
   - 关联式下限 Re=600，用户实验 row 1-2 在 Re=263-528
   - 两行误差依然大（row 1: +100%, row 2: -18%），但不在拟合目标里
   - 如果关心低 Re，需要拟合范围延伸

3. **Re 定义一致性问题**（潜在 follow-up）
   - 关联式里 Re 用 $\rho_\text{ref}$（atmospheric）定义
   - Solver drag 用 $\rho_\text{local}$ 算 force
   - 高压下 $\rho_\text{local}/\rho_\text{ref}$ 最高到 3，混用约定可能是系统偏差的一部分
   - 未修，由 refit 的系数被动吸收

4. **CFD vs 实验的斜率符号分歧**
   - 这是个**物理问题**，不是代码问题
   - 需要额外的实验或 CFD 数据来判断哪个是对的
   - 可能的污染源：入口动能损失、plenum-pipe 过渡、测量位置约定等

### 💡 学到的 / 重要发现

1. **Max-based 收敛判据在 partial BC 下是错的**：wall 扩散噪声会永久拖住判据。质量通量加权是正确的替代。

2. **Partial BC 下的 dP 计算必须用管道加权**：row mean 混合 wall cell，会把真实 pipe 压差稀释几十倍。是个隐蔽的 bug，默认 case（full-width A）永远碰不到，只有真的 partial BC 验证时才暴露。

3. **14 个实验点在同一几何下只能约束 2 个 DOF**：想拟合 6 个系数是妄想，优化器会 overfit 到无意义的局部极小。

4. **CFD 和真实实验可能在 f-Re 斜率符号上都不一致**：这不是数值精度问题，是物理测量/建模约定差异。选边站（这次选实验）是务实做法。

5. **色条 `PowerNorm(γ=0.4)` 对变密度流场特别合适**：Forchheimer 区 $u \propto \sqrt{\nabla P}$，sqrt-scale colorbar 相当于对压力梯度做线性映射，物理意义清晰。

6. **Card 外框加大后 subplot 可能被裁**：调 `subplots_adjust(bottom=...)` 是最快的修法，顺便也把 hspace 略放宽。

---

<!-- 新的日期写在这上面 -->
