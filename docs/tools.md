# 工具入口与复现边界

全部命令从仓库根目录执行，Python 使用 `.venv-path` 第一行的绝对解释器。
先按 [README](../README.md#first-run) 检查对应锁和 `pip check`；缓存使用本工作树
忽略的 `.cache/`。下表中的 `python` 表示该解释器，不是系统 Python。
公开计算入口与正式 Case/Result 文件交接仍见 README；这些工具不替代主线验收。

| 工具 | 输入 → 输出 | 运行方式与状态 |
| --- | --- | --- |
| [examples/](../examples/) | 公开 JSON/YAML 配置 → Case/Result/metrics | README 真实 2D/3D CLI 示例；当前支持范围内的首次运行入口 |
| [runs/smokes/](../sjtu_tpmshx/runs/smokes/) | 内置样例 → 控制台及脚本声明的诊断文件 | `python -m sjtu_tpmshx.runs.smokes.<模块名>`；GUI 无显示运行须用 `QT_QPA_PLATFORM=offscreen` |
| [runs/demos/](../sjtu_tpmshx/runs/demos/) | 内置 3D 工况 → 控制台/可视化 | `python -m sjtu_tpmshx.runs.demos.<模块名>`；交互图形依赖桌面，示例不扩大支持域 |
| [703 项目](../projects/703-sCO2-D76/README.md) | 历史 D-7-6 工况/私有 Excel → 控制台 Q、压降、原生门槛结果 | 9 个研究脚本的包导入已恢复；工况、历史标定及缺失输入见项目说明 |
| [704 项目](../projects/704-Aircooler-10kW/README.md) | `build_cases()`/计算缓存 → 控制台、XLSX、HTML | 2 个研究脚本；报告默认在 `.cache/aircooler-10kw/`，保留历史解释模板 |
| [profile_compute](../benchmarks/profiling/profile_compute.py)、[profile_evaluator](../benchmarks/profiling/profile_evaluator.py) | 内置 nominal design → 同目录 `*_baseline.prof` / 文本 | `python -m benchmarks.profiling.profile_compute` 或 `profile_evaluator`；均测现有 2D screening evaluator，不是 GUI/full 模型或完整 BO |
| [CFD 工况清单](../sjtu_tpmshx/runs/tools/asym_build_cfd_worklist_xlsx.py) → [nTop 表达式](../sjtu_tpmshx/runs/cfd_asym/asym_ntop_expressions_html.py) | 内置几何/流体 + 可选旧 `water-cfd-raw.xlsx` → XLSX → HTML | 顺序运行下方两条命令；两个工具共用输出目录。该旧工作簿目前存在；缺文件时 `r1_water_ref` 页保留跳过说明，不补造锚点 |
| [asym CFD/诊断工具](../sjtu_tpmshx/runs/cfd_asym/)、[diagnostics/](../sjtu_tpmshx/runs/diagnostics/) | 脚本声明的几何、场/CFD 文件 → 研究结果 | `python -m sjtu_tpmshx.runs.<子目录>.<模块名>`；Fluent/vault 等外部依赖按各工具声明，未作为默认安装或本轮运行能力 |
| [M1/BO runs](../sjtu_tpmshx/runs/run_m1_uniform_vs_graded.py)、[M2 rerank](../sjtu_tpmshx/runs/run_m2_rerank_m1.py) | 原始决策向量/3 份 `pareto_final.csv` → 研究结果 | `python -m sjtu_tpmshx.runs.<模块名>`；依赖额外 BO 栈，须按 README 对应锁环境运行。M2 会写回 `reports/m1_uniform_vs_graded/m2_rerank.*`，复现时使用隔离工作树 |
| [scripts/](../scripts/) | 固定服务器环境/测试选择 → 测试日志、远端结果拉取 | PowerShell/shell 平台入口；服务器地址、目录和已预置解释器按脚本参数设置，不自动安装依赖 |
| [poc/](../poc/) | 内置简化问题 → 对应测试/实验结果 | `test_ltne_enthalpy_1d_optionB.py` 仍导入其中实现；保留为实验及测试依赖，不是生产求解入口 |
| [reports/](../reports/README.md) | 历史测量、模型拟合及研究运行结果 | 保留原始失败与数值；M2 仍读取其 CSV。正式运行模型资源的归属见架构说明 |
| [水 Nu 现存表验证](../sjtu_tpmshx/validation/cases/validate_water_nu_excel.py) | 1879 条 legacy 水 CFD 结果 → 逐行、拓扑、几何、Re 分段误差 | `python -m sjtu_tpmshx.validation.cases.validate_water_nu_excel --out .cache/water-nu-validation`；固定现行关联式，退出码 0 通过、2 精度未通过，数据错误直接报错 |
| [现行实验修正](../sjtu_tpmshx/validation/df_refit/fit_experimental_effective.py)、[跨数据集 cF 对照](../sjtu_tpmshx/validation/df_refit/cf_cross_fluid.py) | 实验原表 + 当前固定 CFD 基线 → `reports/df_refit/` 审查 CSV | `python -m sjtu_tpmshx.validation.df_refit.<模块名>`；共享 `validation/hx_experiments.py` 读取，不依赖旧 γ/RBF 拟合或六张旧系数表，不更新生产系数 |
| [sCO2 Nu 修正复核](../sjtu_tpmshx/validation/sco2_exp/fit_nu_correction.py)、[逐温度 Nu 报告](../sjtu_tpmshx/validation/sco2_exp/nu_bytemp_report.py) | sCO2 实验汇总 → 原锚定修正值 / 分温度 Nu 对照 | `python -m sjtu_tpmshx.validation.sco2_exp.<模块名>`；仅依赖现行 Nu、实验读取器及几何，不再运行旧压降模型 |
| [A1 绘图](../sjtu_tpmshx/runs/tools/plot_grid_convergence.py)、[benchmark A](../benchmarks/archive/benchmark_a.py) | 原 A1 CSV/benchmark JSON → 历史图表/对比 | 历史复现入口；原输入目前缺失，不能据脚本存在声称原测量可复现，也不能用 synthetic 文件替代 |

CFD 清单到 nTop 的默认目录为 `sjtu_tpmshx/runs/_out/asym_cfd/`（Git 忽略）。
设置 `TPMSHX_TOOL_OUT_DIR` 时，两次命令须使用同一个值：

```bash
python -m sjtu_tpmshx.runs.tools.asym_build_cfd_worklist_xlsx
python -m sjtu_tpmshx.runs.cfd_asym.asym_ntop_expressions_html
```

旧 `water-cfd-raw.xlsx` 已归类为
`data/raw_data/cfd/water/water_DG_cfd_results_legacy.xlsx`，仅是此研究工具声明的
旧 recipe 锚点；完整新旧名称见[数据目录](data-catalog.md)。正式离线流程要求的
`Water-CFD/水数值模拟数据.xlsx` 仍缺失，两者不能互相替代。

水 Nu 验证单独使用现存 legacy 表的实际质量流量、当前 N=128 几何和表内物性，
重算速度、Re、Pr；参考值为 `mean(Core2_Nu, Core3_Nu) × Dh_current / Dh_excel`。
每个拓扑分别要求 RMSRE ≤ 10%、平均有符号相对误差绝对值 ≤ 5%；所有实有行
均进入分母，D_7_3/4/5 保留单独标记。2026-09-12 的实测结果与边界见
[数据目录](data-catalog.md#水-nu-现存表验证2026-09-12)。

性能文件和研究报告可能使用固定文件名；重测前保留有用的旧产物。
导入检查只证明包路径可解析；数据存在、真实执行、收敛、能量/质量及实验精度分别验收。
历史 B40、fixed-166、M-A/M-B 状态和冻结参考仍以原记录为准。

已退役的旧模型、六张系数表、专属发布/比较脚本及历史报告统一从
[历史模型索引](history/legacy-models.md) 查询；原失败结果不改写为通过。
