# 验证工具

[中文](README.md) | [English](README.en.md)

现行入口、所需数据和运行方法见[工具导航](../../docs/tools.md)。
从仓库根使用 `.venv-path` 指定的解释器运行模块；数据位于本地 `data/raw_data/`。

- [cases/](cases/)：Nu、换热器和守恒验证。
- [hx_experiments.py](hx_experiments.py)：现行实验工具共享读取。
- [df_refit/](df_refit/)、[sco2_cfd/](sco2_cfd/)、[sco2_exp/](sco2_exp/)：现行闭合验证与显式离线拟合。
- [cf_aniso](cf_aniso/README.md)：待方向分辨 CFD 数据的研究工单与拟合模板，尚未标定。
- [原 CSV 状态说明](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/5c517b415be0adbfc7bbfd205a3dba07fe8792a8/sjtu_tpmshx/validation/_CSV_STATUS.md)：历史数值和版本语境，全文按固定 Git 保存；MMS/GCI 原表、Shanghai 主基准及有效测试保留，已退役的旧诊断表见[退役索引](../../docs/history/retired-tools.md)。

验证保留原成员、门槛和失败；导入成功、收敛、守恒与实验精度分别判断。
Python MMS A3/A4/B4 执行命令已在 0.2 退役；[原入口](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/v0.1.0/sjtu_tpmshx/validation/cases)保留历史接口。
当前[原生 MMS 测试](../tests/native/test_temperature_mms.py)检查制造场、逐网格收敛、有限误差、阶数及物理入口响应，保留相关阈值。
读取仓内冻结 CSV 的测试只检查历史证据，不代表当前代码已重新完成数值 sweep。
旧 2026-05 索引的原文保留在
[固定历史](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/validation/README.md)。
