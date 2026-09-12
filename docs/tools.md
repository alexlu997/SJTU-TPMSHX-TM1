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
| [A1 绘图](../sjtu_tpmshx/runs/tools/plot_grid_convergence.py)、[benchmark A](../benchmarks/archive/benchmark_a.py) | 原 A1 CSV/benchmark JSON → 历史图表/对比 | 历史复现入口；原输入目前缺失，不能据脚本存在声称原测量可复现，也不能用 synthetic 文件替代 |

CFD 清单到 nTop 的默认目录为 `sjtu_tpmshx/runs/_out/asym_cfd/`（Git 忽略）。
设置 `TPMSHX_TOOL_OUT_DIR` 时，两次命令须使用同一个值：

```bash
python -m sjtu_tpmshx.runs.tools.asym_build_cfd_worklist_xlsx
python -m sjtu_tpmshx.runs.cfd_asym.asym_ntop_expressions_html
```

旧 `water-cfd-raw.xlsx` 仅是此研究工具声明的旧 recipe 锚点；正式离线流程要求的
`Water-CFD/水数值模拟数据.xlsx` 仍缺失，两者不能互相替代。

性能文件和研究报告可能使用固定文件名；重测前保留有用的旧产物。
导入检查只证明包路径可解析；数据存在、真实执行、收敛、能量/质量及实验精度分别验收。
历史 B40、fixed-166、M-A/M-B 状态和冻结参考仍以原记录为准。
