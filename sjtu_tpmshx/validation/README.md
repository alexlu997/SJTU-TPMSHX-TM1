# 验证工具

[中文](README.md) | [English](README.en.md)

现行入口、所需数据和运行方法见[工具导航](../../docs/tools.md)。
从仓库根使用 `.venv-path` 指定的解释器运行模块；数据位于本地 `data/raw_data/`。

- [cases/](cases/)：Nu、换热器和守恒验证。
- [hx_experiments.py](hx_experiments.py)：现行实验工具共享读取。
- [df_refit/](df_refit/)、[sco2_cfd/](sco2_cfd/)、[sco2_exp/](sco2_exp/)：现行闭合验证与显式离线拟合。
- [cf_aniso](cf_aniso/README.md)：待方向分辨 CFD 数据的研究工单与拟合模板，尚未标定。
- [原 CSV 状态说明](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/5c517b415be0adbfc7bbfd205a3dba07fe8792a8/sjtu_tpmshx/validation/_CSV_STATUS.md)：历史数值和版本语境，全文按固定 Git 保存；GCI 原表、Shanghai 主基准及有效测试保留，已退役的旧诊断表见[退役索引](../../docs/history/retired-tools.md)。

验证保留原成员、门槛和失败；导入成功、收敛、守恒与实验精度分别判断。
Python MMS A3/A4/B4 执行命令已在 0.2 退役；[原入口](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/v0.1.0/sjtu_tpmshx/validation/cases)保留历史接口。
当前[原生 MMS 测试](../tests/native/test_temperature_mms.py)执行 C++ 内核，检查制造场、逐网格收敛、有限误差及下列门槛。
`1d/2d/3d` 表示三维内核中的制造场变化维度，不表示不同后端。

| 验证范围 | 保留的门槛 |
| --- | --- |
| A3：非保守格式，1d/2d/3d 制造场 | A/B/固体的 L2 阶数分别 ≥ 1.5/1.5/1.8；各相 R² ≥ 0.999；网格 30 的各相相对 L2 < 1% |
| A4：非保守格式，3d 区域 | 两侧出口阶数 ≥ 0.8；侧壁固体阶数 ≥ 1.5；各相内部阶数 ≥ 1.8，最细网格内部相对 L2 < 1% |
| 当前物理面入口：两种格式，1d/2d/3d 制造场 | 一次内核 sweep 与独立有限体积响应的归一化差 < 1e-12；入口相邻单元保持为未知量 |
| B4：保守格式，3d 制造场 | 各相 L2 阶数 ≥ 1.8，R² ≥ 0.99 |

各细化组还要求最细网格的各相相对 L2 < 1%。网格 20 的制造场检查保留相对 L2 < 2% 和 Linf < 3 K。
三个读取冻结 MMS CSV 的测试及其专用数据已[移入固定历史](../../docs/history/README.md#mms-reference-retirement)。
原 A4 单元温度钉定判据保留历史含义；当前物理面入口检查保持不变。
旧 2026-05 索引的原文保留在
[固定历史](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/validation/README.md)。
