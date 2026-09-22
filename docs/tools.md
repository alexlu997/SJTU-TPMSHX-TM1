# 工具入口与复现边界

全部命令从仓库根目录执行，Python 使用 `.venv-path` 第一行的绝对解释器。
先按 [README](../README.md#first-run) 检查对应锁和 `pip check`；缓存使用本工作树
忽略的 `.cache/`。下表中的 `python` 表示该解释器，不是系统 Python。
公开计算入口与正式 Case/Result 文件交接仍见 README；这些工具不替代主线验收。

MMS A3/A4/B4 和 GCI 每次默认创建独立的 `.cache/validation/<工具>-<运行ID>/`，
保存本次 CSV、报告与元数据；可用 `--out-dir` 指定输出目录。A3 另支持
`--out_csv`、`--orders_csv`、`--report`，A4 支持前两项，B4 支持 `--out_csv`；
显式相对文件路径按当前工作目录解析。`sjtu_tpmshx/validation/` 内的参考 CSV、
阶数与历史元数据保留，工具在求解前拒绝向该目录写入，也拒绝指向它的符号链接。
显式指定的其他输出目录可以复用；需要保留每次结果时使用默认独立目录。

GCI 当前使用 T2 和 T4（偏置局部开口、无 B 侧实验修正）。历史 T4_H8 等实验入口
已退役，不能用旧 H8 表证明当前 T4 的精度；详见[退役说明](history/retired-tools.md#b-侧局部开口实验修正退役2026-09-22)。
表观阶数由实际网格比和三个结果求解；振荡、非有限或无法确定正阶数时记为
不可验收，不代入假定二阶。C.3 容差敏感性失败也使工具返回非零。
守恒审计的 T1 使用两侧同向流，旧交叉流 T1 表不作为该工况参考；质量偏差按
实际入口/出口通量报告，不以温度变化抵扣。诊断失败保留在输出中并返回非零。

| 工具 | 输入 → 输出 | 运行方式与状态 |
| --- | --- | --- |
| [examples/](../examples/) | 公开 JSON/YAML 配置 → Case/Result/metrics | README 真实 2D/3D CLI 示例；当前支持范围内的首次运行入口 |
| [runs/smokes/](../sjtu_tpmshx/runs/smokes/) | 内置样例 → 控制台及脚本声明的诊断文件 | `python -m sjtu_tpmshx.runs.smokes.<模块名>`；GUI 无显示运行须用 `QT_QPA_PLATFORM=offscreen` |
| [runs/demos/](../sjtu_tpmshx/runs/demos/) | 内置 3D 工况 → 控制台/可视化 | `python -m sjtu_tpmshx.runs.demos.<模块名>`；交互图形依赖桌面，示例不扩大支持域 |
| [profile_compute](../benchmarks/profiling/profile_compute.py)、[profile_evaluator](../benchmarks/profiling/profile_evaluator.py) | 内置 nominal design → 每次独立 `.cache/profiling/compute-*` 或 `eval-*` 下的 `*_baseline.prof` / 文本 | `python -m benchmarks.profiling.profile_compute` 或 `profile_evaluator`；均测现有 2D screening evaluator，不是 GUI/full 模型或完整 BO |
| [CFD 工况清单](../sjtu_tpmshx/runs/tools/asym_build_cfd_worklist_xlsx.py) → [nTop 表达式](../sjtu_tpmshx/runs/cfd_asym/asym_ntop_expressions_html.py) | 内置几何/流体 + 可选旧 `water-cfd-raw.xlsx` → XLSX → HTML | 顺序运行下方两条命令；两个工具共用输出目录。该旧工作簿目前存在；缺文件时 `r1_water_ref` 页保留跳过说明，不补造锚点 |
| [asym CFD/诊断工具](../sjtu_tpmshx/runs/cfd_asym/)、[diagnostics/](../sjtu_tpmshx/runs/diagnostics/) | 脚本声明的几何、场/CFD 文件 → 研究结果 | `python -m sjtu_tpmshx.runs.<子目录>.<模块名>`；Fluent/vault 等外部依赖按各工具声明，未作为默认安装或本轮运行能力 |
| [scripts/](../scripts/) | 固定服务器环境/测试选择 → 测试日志 | PowerShell/shell 平台入口；服务器地址、目录和已预置解释器按脚本参数设置，不自动安装依赖 |
| [D76 Nu 验证](../sjtu_tpmshx/validation/cases/validate_sco2_d76.py) | 6 个固定 D-7-6 工况/私有 Excel → Q 对照 | `python -m sjtu_tpmshx.validation.cases.validate_sco2_d76`；保留原 15% 最大误差门槛，退出码 0 通过、1 未通过 |
| [水 Nu 现存表验证](../sjtu_tpmshx/validation/cases/validate_water_nu_excel.py) | 1879 条 legacy 水 CFD 结果 → 逐行、拓扑、几何、Re 分段误差 | `python -m sjtu_tpmshx.validation.cases.validate_water_nu_excel --out .cache/water-nu-validation`；固定现行关联式，退出码 0 通过、2 精度未通过，数据错误直接报错 |
| [现行实验修正](../sjtu_tpmshx/validation/df_refit/fit_experimental_effective.py)、[跨数据集 cF 对照](../sjtu_tpmshx/validation/df_refit/cf_cross_fluid.py) | 实验原表 + 当前固定 CFD 基线 → `.cache/reports/df_refit/` 审查 CSV | `python -m sjtu_tpmshx.validation.df_refit.<模块名>`；共享 `validation/hx_experiments.py` 读取，不依赖旧 γ/RBF 拟合或六张旧系数表，不更新生产系数 |
| [sCO2 CFD 基础 Nu 拟合](../sjtu_tpmshx/validation/sco2_cfd/fit_nu_sco2.py) | 原 CFD 表 → 基础式研究拟合、几何/压力留一结果 | `python -m sjtu_tpmshx.validation.sco2_cfd.fit_nu_sco2`；保留原数据清洗与验证，不自动覆盖现行有效系数；旧实验锚定工具已移至[历史入口](history/legacy-models.md#sco2-nu-旧锚定路线2026-09-20) |
| [主计算测量](../sjtu_tpmshx/runs/tools/benchmark_main_compute.py) | 本地固定 `jobs` 清单（每项 `id/config`，可含 `reference/depth_m`）→ 每次运行独立的 Case/Result/metrics、日志和分段测量 | `python -m sjtu_tpmshx.runs.tools.benchmark_main_compute MANIFEST NEW_OUTPUT --warmup --repeat 5`；0=执行、状态及已声明流量检查通过，2=存在未合格结果，1=执行异常；不代表实验精度通过 |
| [F2 容差计价](../sjtu_tpmshx/validation/cases/price_f2_convergence_3d.py) | 历史计价工况 → 独立 `.cache/validation/f2_pricing-*/` CSV | `python -m sjtu_tpmshx.validation.cases.price_f2_convergence_3d --mom-tol 1e-3,1e-4,1e-5 --cases 1,8,16`；扫描 F2，`--out` 可指定受冻结路径保护的输出；该工具使用其声明的全侧端口，不能代替局部端口主计算证据 |

无求解 GUI 检查分别运行：

```bash
python -m sjtu_tpmshx.runs.smokes.smoke_ui_offscreen
python -m sjtu_tpmshx.runs.smokes.smoke_ui_screenshots --output .cache/ui-smoke-screenshots
```

两者要求 Qt offscreen 平台，并使用 `.cache/` 下的临时会话和外观目录，退出后
清理临时状态，不覆盖用户偏好。截图输出默认也在 `.cache/ui-smoke-screenshots`。
必需控件/选项缺失、页面未切换成功、Qt 回调异常或窗口关闭失败均返回 1；截图
保存失败同样返回 1。只有检查完成且无上述失败才打印 PASS、返回 0。截图包含
主窗口、2D/3D 模式和优化页；没有计算结果时结果页只检查入口存在，不伪装成
结果渲染验收。offscreen 检查不证明原生三维渲染、桌面交互帧率或数值正确性。

主计算测量的时间以单调时钟记录；求解时间包含原生结果捕获，内部 SIMPLE 调用
可能重叠，不能相加当作总耗时。RSS 每 0.5 秒通过本机 `ps` 采样，采集失败明确
记录；该工具不代替桌面首帧/交互测量。首次、磁盘缓存和同进程预热须分开组织。
每次测量保留实际工况清单、数据版本、预算和原生退出状态；旧固定清单见[历史索引](history/README.md)。

现行 Gyroid HX 空气标定使用 4 月 1 日直通数据，第 2–16 项拟合固定 K0 的
一维 `sF`；4 月 7 日数据只作接法迁移对照。`fit_experimental_effective`
重新输出带源文件、工作表和行号的审查表，并核对封装系数；完整二维/三维验证
直接调用 `benchmark_main_compute`，从正式系数入口读取 `sF`。
标定公式、输入字段和适用范围见[模型资源](model-resources.md)；旧候选和研究输出见历史索引。

历史 sCO₂ fixed-166 配置快照及其中 83 个三维工况基线使用交叉流局部端口、
实验阻力和**旧 Nu 倍率 D=1.77/G=1.07**。它们的成员、实验分母和原误差数字
继续保留，不改标为现行系数的验证。现行总 Ceff、标定来源和新配对结果见
[模型资源](model-resources.md#sco2-有效-nu-系数)；不同参数、网格或容差的结果不可
混在同一组中宣称改进。`validate_sco2_exp_q.py` 默认的逆流/CFD 阻力/基础 Nu
属于另一套物理复核配置，`--all-valid` 也会按当前读取器重新选择成员。复现旧基线时，
使用本地保存的固定 manifest（原 `workloads.json`）及匹配原始数据，
用 `--jobs` 选择其中的固定 ID；旧证据入口见历史索引，不从当前读取器重新生成成员；
例如 `--jobs sco2-009-Diamond-8-2d shanghai-01-3d`。新输出目录必须尚不存在。
新的 sCO₂ 有效系数通过 `sco2_effective_nu_config()` 或 GUI 显式选择，原
`fit_nu_correction`/`nu_bytemp_report` 不再作为现行重算入口；仅换 Nu JSON
不会自动重建严格求解设置或旧固定 manifest。

上海生产验证的端口/壁面网格由同一构造函数生成，网格数包含所有加密单元。
二维入口采用 `84×24`；三维无显式网格参数时采用 `92×14×10`。
历史网格研究见[历史索引](history/README.md)。三维显式
`--nx/--ny/--nz` 保留手选网格，`--port-wall-refine` 选择端口/壁面加密；
旧 `--wall-refine` 为另一种六面壁面加密，两者不能同时启用。
实际网格始终来自本次结果的准备网格。
当前共同 F2 和物理边界见[架构说明](architecture.md)；旧架构回归和实验误差见历史索引。
无效的 `tol_simple` 和优化启动器旧 `--tol` 已退役；旧工况文件导入时明确提示
忽略该字段，实际 F2 动量和质量收敛门槛继续保留。MMS 的能量求解 `--tol`
是独立的有效参数，不在此次退役范围内。
两维完整上海验证共用 4 月 1 日批次已确认的局部水口：上侧入口
`x=133–175 mm`，下侧出口 `x=7–49 mm`，贯穿 `42 mm` 深度。
速度按实验总质量流量、当前模型单侧孔隙面积和入口密度换算。
显式 `--profile/--eta/--disp-c` 仅适用于历史 kernel，生产分支在读取数据前拒绝。
上海二维 CSV 的 `Q_sim` 仍为原实验质量流量/入口比热口径，新列 `Q_native`
保留主计算 W/m；三维原生 Q 为 W。不同定义分别比较，不覆盖旧实验门槛。
二维验证只运行当前生产链，报告精度但不设新的实验误差门槛；非有限或未收敛
返回非零。三维生产验证默认保留全部请求成员，缺失、失败、非有限、未收敛或
最终压力状态无效均不能通过；原 RMSRE 压降 12%、换热量 6% 门槛不变。
迭代期间的压力裁剪计数只作诊断，不因早期裁剪而拒绝最终已恢复有效的状态。
显式 `--no-gate` 仅生成报告，不表示验收通过。

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
多种子根目录保存实际共同 `config.json` 和成功/失败种子状态；请求的种子未全部
完成时命令返回非零。Pareto 验证与 nTop 导出共用具名 CSV 列约定，缺少配置、
缺列、重复列或非有限值直接拒绝，不能回退默认工况后继续验证。

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

非对称 CFD 的两条 κ 研究路径使用不同分母：`ingest_cfd_kappa` 使用当前对称
预测器，`asym_postproc_kappa` 使用配对 r=1 CFD 参考。不可把两者的 κ 数字直接
混用；导入器按排序节点做分段线性插值，不保证数据本身单调或强制 r=1 锚点。
注册表仅在本进程有效，显式调用 `kappa_KcF` 可做研究求值；它尚未接入正式
求解准备流程，开启环境变量不会自动改变完整 2D/3D 或 GUI 计算。
工单中的旧精度数字是历史参考，现行验证须另行记录版本、输入与结果。

水 Nu 验证单独使用现存 legacy 表的实际质量流量、当前 N=128 几何和表内物性，
重算速度、Re、Pr；参考值为 `mean(Core2_Nu, Core3_Nu) × Dh_current / Dh_excel`。
每个拓扑分别要求 RMSRE ≤ 10%、平均有符号相对误差绝对值 ≤ 5%；所有实有行
均进入分母，D_7_3/4/5 保留单独标记。2026-09-12 的实测结果与边界见
[数据目录](data-catalog.md#水-nu-现存表验证2026-09-12)。

性能文件和研究报告可能使用固定文件名；重测前保留有用的旧产物。
导入检查只证明包路径可解析；数据存在、真实执行、收敛、能量/质量及实验精度分别验收。
历史 B40、fixed-166 和冻结参考从历史索引查阅，当前 M-A/M-B 状态见[能力范围](capabilities.md)。

已退役的旧模型、六张系数表、专属发布/比较脚本及历史报告统一从
[历史模型索引](history/legacy-models.md) 查询；原失败结果不改写为通过。

已结束的 703/704/624 工程、M1/M2 固定试验及旧性能复现脚本见
[退役工具索引](history/retired-tools.md)，不再列为当前目录的重跑入口。
