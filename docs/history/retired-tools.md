# 退役工程、试验与工具索引

2026-09-12 按用户确认将已结束的工程、M1/M2 固定试验及历史资料移出当前树。
原文件固定保存在已合并提交 [b1af7ed](https://github.com/alexlu997/SJTU-TPMSHX-TM1/commit/b1af7edcea5796aa955aa8fae1785be3c1b57e1d)，
原数值、失败、被否原因及未实施事项不改写。常规设计/优化与现行验证继续保留。

第一批移出 141 个文件；D76 现行 Nu 验证另迁入
[validation/cases/validate_sco2_d76.py](../../sjtu_tpmshx/validation/cases/validate_sco2_d76.py)，
保留六个工况、表头校验、15% 门槛和原退出语义。原工程脚本中的旧
`SCO2_CF_SCALE=3.39` 不移入现行计算链。

| 原路径 | 文件数 | 固定历史入口 |
| --- | ---: | --- |
| `projects/703-sCO2-D76/` | 9 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/projects/703-sCO2-D76/) |
| `projects/704-Aircooler-10kW/` | 3 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/projects/704-Aircooler-10kW/) |
| `projects/624-Retrodict/` | 2 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/projects/624-Retrodict/) |
| `reports/m1_uniform_vs_graded/` | 98 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/reports/m1_uniform_vs_graded/) |
| `openspec/changes/df-coeffs-cfd-refit/` | 3 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/openspec/changes/df-coeffs-cfd-refit/) |
| `openspec/changes/a2-3d-physical-g/` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/openspec/changes/a2-3d-physical-g/) |
| `openspec/changes/evaluator-envelope-authority/` | 3 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/openspec/changes/evaluator-envelope-authority/) |
| `reports/shanghai-validation/` | 2 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/reports/shanghai-validation/) |
| `reports/solver-efficiency-r1-r4/` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/reports/solver-efficiency-r1-r4/) |
| `benchmarks/archive/benchmark_a.py` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/benchmarks/archive/benchmark_a.py) |
| `benchmarks/benchmark_snapshot_a.md` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/benchmarks/benchmark_snapshot_a.md) |
| `benchmarks/benchmark_snapshot_b.md` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/benchmarks/benchmark_snapshot_b.md) |
| `constraints-devbox-2026-07-11.txt` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/constraints-devbox-2026-07-11.txt) |
| `docs/ARCHITECTURE-AUDIT-2026-07.md` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/docs/ARCHITECTURE-AUDIT-2026-07.md) |
| `docs/DF-CALIBRATION-AUDIT-2026-07.md` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/docs/DF-CALIBRATION-AUDIT-2026-07.md) |
| `docs/history/PROJECT_MANUAL.md` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/docs/history/PROJECT_MANUAL.md) |
| `docs/history/devlog.md` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/docs/history/devlog.md) |
| `docs/history/upgrade-2026-07.md` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/docs/history/upgrade-2026-07.md) |
| `docs/history/v2-readme.md` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/docs/history/v2-readme.md) |
| `poc/poc_1d_ltne_strict_conservation.py` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/poc/poc_1d_ltne_strict_conservation.py) |
| `scripts/port_retest_pull.sh` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/scripts/port_retest_pull.sh) |
| `scripts/port_retest_server.ps1` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/scripts/port_retest_server.ps1) |
| `scripts/port_retest_server.sh` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/scripts/port_retest_server.sh) |
| `sjtu_tpmshx/runs/run_m1_uniform_vs_graded.py` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/runs/run_m1_uniform_vs_graded.py) |
| `sjtu_tpmshx/runs/run_m2_rerank_m1.py` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/runs/run_m2_rerank_m1.py) |
| `sjtu_tpmshx/runs/run_port_dim_retest.py` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/runs/run_port_dim_retest.py) |
| `sjtu_tpmshx/runs/tools/plot_grid_convergence.py` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/runs/tools/plot_grid_convergence.py) |
| `sjtu_tpmshx/tests/test_port_result_pull.py` | 1 | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/tests/test_port_result_pull.py) |

M1/M2 的三个固定 Pareto 输入与消费者、端口维数复测试验一同退役。
普通 qNEHVI、快速设计和通用测试服务器入口仍在当前树。
A1/benchmark A 的旧输入原已缺失，历史代码不代表可在当前目录完整重跑。
原 validation 与 reports 索引也可在上述提交的同名路径查阅。

当前模型及数据约定见[架构](../architecture.md)和[数据目录](../data-catalog.md)；
旧 RBF/γ 模型与更早的资料见[模型退役索引](legacy-models.md)和[历史总索引](README.md)。

## 多边形计算退役

公开 Compute 已拒绝 Hexagon/Octagon；删除旧计算实现和三角剖分，保留
`unstructured_mesh.hexagon/octagon` 供旧预设查看、保存和流体输入展示。

| 原路径 | 固定历史入口 |
| --- | --- |
| `sjtu_tpmshx/ui/polygon_calc.py` | [原实现](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/ui/polygon_calc.py) |
| `sjtu_tpmshx/solvers/polygon_fvm.py` | [原实现](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/solvers/polygon_fvm.py) |
| `sjtu_tpmshx/solvers/unstructured_mesh.py` | [原实现](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/solvers/unstructured_mesh.py) |

## SIMPLER 试验退役

2D 默认 SIMPLE 保留；删除 SIMPLER 选择参数、伪速度核和专属 benchmark/test/spec。
旧 `coupling` / `simpler_relax_p` 参数不再接受，传入会报错。
原比较的两个网格上加速比为 0.46×、0.59×，没有性能收益；原结论和数值保留如下。

| 原路径 | 固定历史入口 |
| --- | --- |
| `openspec/specs/simpler-coupling-2d/spec.md` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/openspec/specs/simpler-coupling-2d/spec.md) |
| `reports/simpler-coupling-2d/CONCLUSIONS.md` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/reports/simpler-coupling-2d/CONCLUSIONS.md) |
| `reports/simpler-coupling-2d/benchmark_simple_vs_simpler_2d.csv` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/reports/simpler-coupling-2d/benchmark_simple_vs_simpler_2d.csv) |
| `sjtu_tpmshx/runs/benchmark_simpler_2d.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/runs/benchmark_simpler_2d.py) |
| `sjtu_tpmshx/tests/test_simpler_coupling_2d.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/tests/test_simpler_coupling_2d.py) |
