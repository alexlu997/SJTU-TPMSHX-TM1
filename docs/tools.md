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
| [profile_compute](../benchmarks/profiling/profile_compute.py)、[profile_evaluator](../benchmarks/profiling/profile_evaluator.py) | 内置 nominal design → 同目录 `*_baseline.prof` / 文本 | `python -m benchmarks.profiling.profile_compute` 或 `profile_evaluator`；均测现有 2D screening evaluator，不是 GUI/full 模型或完整 BO |
| [CFD 工况清单](../sjtu_tpmshx/runs/tools/asym_build_cfd_worklist_xlsx.py) → [nTop 表达式](../sjtu_tpmshx/runs/cfd_asym/asym_ntop_expressions_html.py) | 内置几何/流体 + 可选旧 `water-cfd-raw.xlsx` → XLSX → HTML | 顺序运行下方两条命令；两个工具共用输出目录。该旧工作簿目前存在；缺文件时 `r1_water_ref` 页保留跳过说明，不补造锚点 |
| [asym CFD/诊断工具](../sjtu_tpmshx/runs/cfd_asym/)、[diagnostics/](../sjtu_tpmshx/runs/diagnostics/) | 脚本声明的几何、场/CFD 文件 → 研究结果 | `python -m sjtu_tpmshx.runs.<子目录>.<模块名>`；Fluent/vault 等外部依赖按各工具声明，未作为默认安装或本轮运行能力 |
| [scripts/](../scripts/) | 固定服务器环境/测试选择 → 测试日志 | PowerShell/shell 平台入口；服务器地址、目录和已预置解释器按脚本参数设置，不自动安装依赖 |
| [poc/](../poc/) | 内置简化问题 → 对应测试/实验结果 | `test_ltne_enthalpy_1d_optionB.py` 仍导入其中实现；保留为实验及测试依赖，不是生产求解入口 |
| [reports/](../reports/README.md) | 历史测量、模型拟合及研究运行结果 | 现行验证输出保留；已结束的试验见历史索引。正式运行模型资源的归属见架构说明 |
| [D76 Nu 验证](../sjtu_tpmshx/validation/cases/validate_sco2_d76.py) | 6 个固定 D-7-6 工况/私有 Excel → Q 对照 | `python -m sjtu_tpmshx.validation.cases.validate_sco2_d76`；保留原 15% 最大误差门槛，退出码 0 通过、1 未通过 |
| [水 Nu 现存表验证](../sjtu_tpmshx/validation/cases/validate_water_nu_excel.py) | 1879 条 legacy 水 CFD 结果 → 逐行、拓扑、几何、Re 分段误差 | `python -m sjtu_tpmshx.validation.cases.validate_water_nu_excel --out .cache/water-nu-validation`；固定现行关联式，退出码 0 通过、2 精度未通过，数据错误直接报错 |
| [现行实验修正](../sjtu_tpmshx/validation/df_refit/fit_experimental_effective.py)、[跨数据集 cF 对照](../sjtu_tpmshx/validation/df_refit/cf_cross_fluid.py) | 实验原表 + 当前固定 CFD 基线 → `reports/df_refit/` 审查 CSV | `python -m sjtu_tpmshx.validation.df_refit.<模块名>`；共享 `validation/hx_experiments.py` 读取，不依赖旧 γ/RBF 拟合或六张旧系数表，不更新生产系数 |
| [sCO2 Nu 修正复核](../sjtu_tpmshx/validation/sco2_exp/fit_nu_correction.py)、[逐温度 Nu 报告](../sjtu_tpmshx/validation/sco2_exp/nu_bytemp_report.py) | sCO2 实验汇总 → 原锚定修正值 / 分温度 Nu 对照 | `python -m sjtu_tpmshx.validation.sco2_exp.<模块名>`；仅依赖现行 Nu、实验读取器及几何，不再运行旧压降模型 |
| [主计算测量](../sjtu_tpmshx/runs/tools/benchmark_main_compute.py) | 本地固定 `jobs` 清单（每项 `id/config`，可含 `reference/depth_m`）→ 每次运行独立的 Case/Result/metrics、日志和分段测量 | `python -m sjtu_tpmshx.runs.tools.benchmark_main_compute MANIFEST NEW_OUTPUT --warmup --repeat 5`；0=执行、状态及已声明流量检查通过，2=存在未合格结果，1=执行异常；不代表实验精度通过 |
| [历史 2D golden](../sjtu_tpmshx/runs/_out/_golden_2d.py) | 两组固定 Pipeline2D 配置 → 新的本地快照 / 与指定快照比较 | 手工历史诊断，非当前物理验收；`test_asym_porosity_2d.py` 仍使用其中的配置函数。用 `python -m sjtu_tpmshx.runs._out._golden_2d .cache/golden-2d-new.json` 保存新快照，保留原记录 |
| [历史 3D golden](../sjtu_tpmshx/runs/_out/_golden_3d.py) | `golden_3d.json` 与原始元数据 → 同环境历史对照 | 手工历史诊断，三组配置；不是当前跨平台验收。现行测试配置独立放在 [tests/cases_3d.py](../sjtu_tpmshx/tests/cases_3d.py)，不改写旧数值以消除差异 |

主计算测量的时间以单调时钟记录；求解时间包含原生结果捕获，内部 SIMPLE 调用
可能重叠，不能相加当作总耗时。RSS 每 0.5 秒通过本机 `ps` 采样，采集失败明确
记录；该工具不代替桌面首帧/交互测量。首次、磁盘缓存和同进程预热须分开组织。
工况成员、实际数据版本、测量预算及节点状态见[本阶段计划](plans/main-compute-20260913.md)。

本阶段 sCO₂ 使用用户确认的 fixed-166 配置快照：交叉流局部端口、实验阻力、
Nu 倍率 D=1.77/G=1.07。`validate_sco2_exp_q.py` 默认的逆流/CFD 阻力/基础 Nu
属于另一套物理复核配置，`--all-valid` 也会按当前读取器重新选择成员。复现本阶段时，
按计划的私有证据索引取得 `workloads.json`，使用 `--jobs` 选择其中的固定 ID；
例如 `--jobs sco2-009-Diamond-8-2d shanghai-01-3d`。新输出目录必须尚不存在。

上海生产验证的端口/壁面网格由同一构造函数生成，网格数包含所有加密单元。
二维入口采用 `84×24`；三维无显式网格参数时采用 `92×14×10`。
精度研究状态见[本轮记录](accuracy-performance-20260914.md)。三维显式
`--nx/--ny/--nz` 保留手选网格，`--port-wall-refine` 选择端口/壁面加密；
旧 `--wall-refine` 为另一种六面壁面加密，两者不能同时启用。
实际网格始终来自本次结果的准备网格。
两维完整上海验证共用 4 月 1 日批次已确认的局部水口：上侧入口
`x=133–175 mm`，下侧出口 `x=7–49 mm`，贯穿 `42 mm` 深度。
速度按实验总质量流量、当前模型单侧孔隙面积和入口密度换算。
显式 `--profile/--eta/--disp-c` 仅适用于历史 kernel，生产分支在读取数据前拒绝。
上海二维 CSV 的 `Q_sim` 仍为原实验质量流量/入口比热口径，新列 `Q_native`
保留主计算 W/m；三维原生 Q 为 W。不同定义分别比较，不覆盖旧实验门槛。

正式文件和 GUI 导出先写暂存文件组，再发布；写入或发布异常时恢复上次成功文件。
二维覆盖同名三维 CSV 时也移除旧 NPZ，避免串用。单目标只允许一个写入者；突然
断电不保证文件组原子性。遗留 `.tm1-publish-*` 表示未完成尝试，`previous/` 中为
恢复文件，不能把它当作成功输出；当前异常会保留恢复位置。新运行优先用独立目录。

## 公开模块扩展示例

以下命令从仓库根执行，复用已通过环境检查的解释器，无需私有原始数据：

```bash
PYTHON="$(head -n 1 .venv-path)"
export MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg"
export NUMBA_NUM_THREADS=2 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
"$PYTHON" -m examples.three_module.external_design examples/three_module/design_case.json .cache/examples/design
"$PYTHON" -m examples.three_module.parameter_scan .cache/examples/scan
"$PYTHON" -m examples.three_module.design_field_call .cache/examples/field
```

PowerShell 读取 `.venv-path` 后使用 `& $tm1Python` 和相同参数，环境设置见根 README。

- [external_design](../examples/three_module/external_design.py) 接收
  [DesignCase JSON](../examples/three_module/design_case.json)：温度 K、绝压 Pa、
  质量流量 kg/s、Q 为 W，`dPlim_h/c` 为 ΔP/P_in 分数。它对脚本中固定的
  Diamond 7/0.5 mm 几何做正向计算，不按输入 Q 自动定尺；输出 Q 为总 W。
  返回码 0/2 分别表示收敛/未收敛。GUI 表格 loader 的温压列另用 K/kPa，Q 列用 kW，
  不能把表格列名直接当成这个 JSON 的字段。
- [parameter_scan](../examples/three_module/parameter_scan.py) 对两个空气速度运行 2D
  筛选；每个工况保存 Case/Result/metrics，根输出目录保存 `summary.json`。
- [design_field_call](../examples/three_module/design_field_call.py) 对比原始场和显式
  修改的有效固体导热场，按工况保存相同文件并确认 Q 随输入变化；没有伴随或梯度计算。

各工况都有 `case.yaml` 与伴随 `case.h5`、`results.h5`、`metrics.json`。
后两个示例的 Q 为 W/m，收敛与物理状态看 `summary.json` 和结果文件；
脚本退出 0 不代表每个筛选工况均收敛。示例不扩大模型适用域。

## 定尺与优化结果

快速定尺以最终重算逐工况判定可行性；失败工况仍保留在明细中，`终验` 列说明
未收敛、非有限值、温度/热量未达标或压降超限。只有通过终验的候选参与最优选择。

BO 的 `history.csv` 保留全部评估的数值，包括训练所用惩罚值；配套
`history_status.json` 按同一行序记录从 1 开始的评估序号、`valid/failed` 和原因。
多种子输出对应 `history_merged.csv` 与 `history_merged_status.json`。
API 的 `history_errors` 与 `history_X/history_F` 逐行对应，成功行为 `None`。
`pareto_*.csv` 仅含未被拒绝的候选；全失败时文件仅有表头。显式从历史行导出几何时，
导出元数据保留该行的评估状态。筛选通过不代表通过实验验证或生产求解验收。

## 数据与研究工具

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

已结束的 703/704/624 工程、M1/M2 固定试验及旧性能复现脚本见
[退役工具索引](history/retired-tools.md)，不再列为当前目录的重跑入口。
