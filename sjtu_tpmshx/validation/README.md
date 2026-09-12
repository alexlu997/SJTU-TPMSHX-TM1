# 验证工具

现行入口、所需数据和运行方法见[工具导航](../../docs/tools.md)。
从仓库根使用 `.venv-path` 指定的解释器运行模块；数据位于本地 `data/raw_data/`。

- [cases/](cases/)：Nu、换热器、制造解和守恒验证。
- [hx_experiments.py](hx_experiments.py)：现行实验工具共享读取。
- [df_refit/](df_refit/)、[sco2_cfd/](sco2_cfd/)、[sco2_exp/](sco2_exp/)：现行闭合验证与显式离线拟合。
- [_CSV_STATUS.md](_CSV_STATUS.md)：原 CSV 的历史数值和版本语境，不作为当前结果的新验收。

验证保留原成员、门槛和失败；导入成功、收敛、守恒与实验精度分别判断。
旧 2026-05 索引的原文保留在
[固定历史](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/validation/README.md)。
