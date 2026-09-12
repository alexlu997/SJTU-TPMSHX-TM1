# 703 — sCO2 PCHE / 预冷器评估（D-7-6 晶胞）

项目合作交付：合作方 **703** 的 sCO2 印刷电路板换热器（PCHE）/ 预冷器评估。几何采用 **D-7-6**（Diamond，L=7.0 mm / t=0.6 mm）TPMS 晶胞及其对应参数。

这些是历史研究驱动脚本，调用 `sjtu_tpmshx` 的共享模型及求解器，并保留当时的工况、局部实验标定和研究近似。下表的泄漏、误差及可信度说明属于原评估，不能作为当前 TM1 的全模型验收结论。

## 脚本一览

| 脚本 | 用途 |
|---|---|
| `size_sco2_703.py` | Method-A 定尺：给定工况反推 PCHE 尺寸（DEVICES / design_device）。 |
| `validate_sco2_703_3d.py` | METHOD iii：3D 场跑（sCO2 双侧全泛化）。逆流；报 dP + 热侧焓 duty。⚠ 3D 有 B 侧守恒泄漏，coupled duty 不可信——用下面的 2D coupled。 |
| `validate_sco2_703_coupled.py` | 2D 双活耦合求解（imbalance −1.9%）——可信的耦合 duty。 |
| `validate_sco2_703_field.py` | 场跑（复用 `size_sco2_703` 的定尺结果）。 |
| `validate_sco2_precooler_phasec.py` | 预冷器 Phase-C 评估。 |
| `precooler_nu_sensitivity.py` | 预冷器 Nu 关联式敏感性扫描。 |
| `validate_sco2_d76.py` | **Gate A**：sCO2 Nu 闭合 vs D-7-6 实验（集总双-Nu ε-NTU）。Gate：max\|Q 误差\|<15%。 |
| `validate_sco2_d76_2d.py` | D-7-6 2D 场验证。 |
| `validate_sco2_d76_dP_holdout.py` | D-7-6 ΔP holdout（导入 `validate_sco2_d76_2d` 的 `_run_case` / `XLSX` / `GOLD`）。 |

## 输入、输出与运行

从仓库根目录运行；`python` 必须替换为 `.venv-path` 第一行的绝对解释器，先通过锁检查及 `pip check`。Matplotlib/Qt 缓存使用本工作树忽略的 `.cache/`。脚本将仓库根加入模块路径，并导入 `sjtu_tpmshx.*`；同目录兄弟脚本保留在一起。

- Gate A 读取 `data/raw_data/experiments/sco2/d76/sco2_D7-t0p6_hx_experiment_arranged.xlsx`，逐项核对列标题，输出 6 工况及原门槛判定。2026-09-12 恢复入口后实际运行 max\|Q 误差\|=15.9%，原 15% 门槛 **FAIL**（退出 1）；没有调整工况或容差。
- 2D 与 ΔP holdout 读取 `data/raw_data/experiments/sco2/d76/sco2_D7-t0p6_hx_experiment_values_v1.xlsx`，holdout 复用 2D 脚本的路径。该原 V1 文件存在；此前“文件缺失”的说明有误。它与 Gate A 的整理版列定义不同，各自保留原列映射。
- 其余驱动使用脚本内 `DEVICES` 或固定工况，结果输出到控制台。部分历史温压超出当前 sCO2 物性域；保留域拒绝，不能通过开启外推把这些研究脚本改记为验收通过。

```bash
python -u projects/703-sCO2-D76/validate_sco2_d76.py            # 快速 Gate A
python -u projects/703-sCO2-D76/validate_sco2_703_coupled.py    # 历史耦合研究入口
```

当前正式运行与支持范围见[项目 README](../../README.md)和[架构说明](../../docs/architecture.md)。
