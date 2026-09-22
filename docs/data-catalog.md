# 原始数据目录与文件名对照

2026-09-12 目录整理。原始文件位于本地 `data/raw_data/`，由私有
SJTU-TPMSHX-data 仓库承载；本页只记录路径和用途，不包含原始测量值。
本次移动、重命名 13 个 Excel，并按用途归类 CFD CSV 和随附说明。
重命名保留工作簿内容、工作表名称、公式、公式缓存、单位和原有数据标记；
水工况计划的单独修订及原件备份见下文。

## 分类

```text
data/raw_data/
├── experiments/
│   ├── air/           空气试件台架实验汇总
│   ├── water_air/     水—空气整机实验及水侧压损整理表
│   └── sco2/
│       └── d76/       D7、壁厚 0.6 mm 的现用整理版及数值版
├── cfd/
│   ├── water/         现存水 CFD 历史结果
│   └── sco2/          超临界 CO2；仍按 Diamond/Gyroid 分目录
├── archive/           普通 CO2、旧水压损表、sCO2 处理公式及 REFPROP 附件
└── plans/
    └── water/         水 CFD 工况计划，不是计算结果
```

## 命名规则

基本顺序为 `工质_对象_用途_日期或版本.xlsx`，目录先区分实验、CFD 结果和计划。
`D`/`G` 为 Diamond/Gyroid，`DG` 为两种结构；`7-t0p6` 表示胞元 7 mm、
壁厚 0.6 mm，`hx` 表示整机换热器。日期仅沿用原文件中明确记录的实验日期，
不以文件修改时间猜测数据日期。

`legacy` 表示保留的历史来源，`values_v1`/`formulas`/`arranged`/`processing`
用于区分现存数值版、公式版和整理布局，不表示数据正确性或版本优先级。
下表的旧路径、新路径均相对于 `data/raw_data/`。

| 原路径 | 新路径 | 用途与区别 |
| --- | --- | --- |
| `20260401-上海电气天然气加热器实验工况.xlsx` | `experiments/water_air/water-air_G7-t0p6_shanghai_experiment_20260401.xlsx` | Gyroid HX 空气直通标定源（第 2–16 项）及整机对照；空气小试件训练集仍拒绝上海来源，见下文 |
| `20260407-上海电气天然气加热器实验工况 -调换进出口-G_7_6.xlsx` | `experiments/water_air/water-air_G7-t0p6_shanghai_experiment_ports-swapped_20260407.xlsx` | 用户于2026-09-15确认：空气与水互换流道，试件及其他硬件不变；空气走错列开口、水走原空气直通流道。见[压力诊断](history/README.md#2026-09-18-历史材料整理) |
| `20260609-水直空气侧-D_7_6.xlsx` | `experiments/water_air/water-air_D7-t0p6_experiment_water-straight_20260609.xlsx` | D7/0.6 水—空气实验 |
| `7-6-Water-dp.xlsx` | `experiments/water_air/water-air_DG7-t0p6_hx_water-dp_with-air-temperature.xlsx` | 水侧压损整理；D 页另有空气进口温度列；现有水 HX 读取器使用此表 |
| `换热器压损——20260407-G-7-6+20260609-D_7_6.xlsx` | `archive/water_air/water-air_DG7-t0p6_hx_water-dp.xlsx` | 另一份压损整理；D 页没有附加空气温度列，不与上一表合并 |
| `试验记录表_整理版.xlsx` | `experiments/air/air_DG_specimen_experiment_summary.xlsx` | 电加热空气试件实验，含 CFD 对照列；不是水 CFD 结果 |
| `sCO2-Experient.xlsx` | `experiments/sco2/sco2_DG7-t0p6_hx_experiment_summary.xlsx` | D/G sCO2 整机实验汇总；保留两种结构各自的列映射 |
| `D-7-6实验数据-sCO2.xlsx` | `experiments/sco2/d76/sco2_D7-t0p6_hx_experiment_arranged.xlsx` | 原 `整理版`/`无公式` 布局，47 列 |
| `D-7-6-sCO2/D-7-6实验数据-V1.xlsx` | `experiments/sco2/d76/sco2_D7-t0p6_hx_experiment_values_v1.xlsx` | 原 V1，`无公式` 页，48 列 |
| `D-7-6-sCO2/D-7-6实验数据-formula.xlsx` | `archive/sco2/d76/sco2_D7-t0p6_hx_experiment_formulas.xlsx` | 原公式版，保留 REFPROP 外链及缓存 |
| `D-7-6-sCO2/D实验数据-超临界二氧化碳.xlsx` | `archive/sco2/d76/sco2_D7-t0p6_hx_experiment_processing.xlsx` | 原 `实验数据处理` 页，49 列 |
| `TPMS水_关联式拟合CFD工况.xlsx` | `plans/water/water_DG_cfd_worklist.xlsx` | 1880 条计划，含几何、参考物性和质量流量公式 |
| `water-cfd-raw.xlsx` | `cfd/water/water_DG_cfd_results_legacy.xlsx` | 1879 条历史结果；W01600 按缺测结案、不再补齐，已有来源疑点另行讨论 |

其他文件：`CO2-CFD/` → `archive/co2/`，`sCO2-CFD/` → `cfd/sco2/`，
8 个 CSV 的文件名和内容不变。`D-7-6-sCO2/REFPROP.XLA` 随公式移至 `archive/sco2/d76/`；
`说明.txt` 移至 `experiments/water_air/water-air_DG_hx_source-notes.txt`，原文保留。

## 水 CFD 计划孔隙率修订（2026-09-12）

按用户确认，`water_DG_cfd_worklist.xlsx` 的 D_7_3、D_7_4、D_7_5
单侧孔隙率采用当前 `compute_geometry("Diamond", 7, t, N=128)` 的
`epsilon/2`，依次为 0.417083740234375、0.3896484375、0.363372802734375。
更新 `几何D_L汇总!E14:E16` 和 `推荐CFD工况总表!H566:H706`，
保留原有共享公式结构；关联的 141 个 T 列推荐质量流量公式随之重算。
Dh、物性、Re 标签、工况成员和其余单元格沿用原值。

修改前完整计划保存在同目录的
`water_DG_cfd_worklist_before_porosity_20260912.xlsx`。
历史 CFD 入口质量流量应追溯该副本和 legacy 结果表；修订后计划中的
推荐质量流量不是当时实际采用的入口流量。此次修订采用当前模型约定，
不构成原 CFD 网格几何已核实的证明。历史 CFD 结果、现有拟合系数和
W01600 缺测结案保持原状。

## 已结案缺项

2026-09-12 用户确认：`W01600 / G_7_5 / Re=3000 / Tref=325 K / Twall=375 K`
按“缺测、不再补齐”结案。原计划 `推荐CFD工况总表!A1601:Y1601` 保留，
不补造结果，不将缺测解释为计算失败。覆盖率仍为计划 1880、实有 1879；
原主拟合成员实有 439/440，G_7_5 实有 46/47 条。现有发展段系数表已按
该几何的 46 条记录统计，本次不删除其它数据或重拟合系数。

## 水 Nu 现存表验证（2026-09-12）

使用 `cfd/water/water_DG_cfd_results_legacy.xlsx` 全部 1879 条、40 个几何，
实际历史 `mdot_in_kg_s`、当前 N=128 单侧孔隙率/Dh、表内 rho/mu/cp/k。
速度为 `mdot/(rho*epsilon_side*L_cell²)`，据此重算 Re、Pr；参考 Nu 为
`mean(Core2_Nu, Core3_Nu) × Dh_current/Dh_excel`。不使用旧 Um 列或修订计划
中的新推荐质量流量替代实际流量。固定现行系数，不重新拟合。

验收门槛在运行前确定：每个拓扑 RMSRE ≤ 10%，平均有符号相对误差绝对值 ≤ 5%。

| 拓扑 | 条数 | RMSRE | 平均有符号偏差 | 判定 |
| --- | ---: | ---: | ---: | --- |
| Diamond | 940 | 9.9965% | +1.1424% | 通过，接近边界 |
| Gyroid | 939 | 10.6243% | +0.6079% | RMSRE 未通过 |

整体暂未通过，原生退出码为 2。全部 Re 为 99.55–50871.92，处于当前关联式
90–51000 范围内。Re<500 时 D/G RMSRE 分别为 17.42%/17.53%；G 在
1000≤Re<3000 和 Re≥30000 时分别为 12.41%/12.24%，误差不只来自单个几何。
D_7_3/4/5 全部进入主分母，单组 RMSRE 分别为 12.67%/6.65%/8.24%。
未删点、未放宽阈值、未改生产系数；W01600 缺测结案保留。

复现入口为 `validation/cases/validate_water_nu_excel.py`。原本地详细证据
`water-nu-validation-20260912/`（report、summary、逐行/几何/Re 分段 CSV）
已保存在私有 `20260912-prior-task-evidence.tar.gz`，本机 `.cache/ARCHIVE.md`
记录归档位置；原 `.cache/` 子目录不再作为现存入口。
这是现行关联式对现存数据的验证；缺失修正版的来源记录仍保留，不据此声称
复现了历史修正版拟合或完成了独立实验验证。

**系数选择已结案：2026-09-12 用户确认继续采用原关联式，不替换。**
Diamond 保留 `Nu = 0.3201·Re^0.6679·Pr^(1/3)`，Gyroid 保留
`Nu = 0.3941·Re^0.6435·Pr^(1/3)`。同形式重拟合候选不采用，结果留作对照，
见同一私有归档中的 `water-nu-refit-20260912/`。上述实测误差、10% 门槛和退出码原样保留；
保留现行系数的决定不改写精度检验结果，本轮不再推进系数替换。

## 现行实验工具读取解耦（2026-09-12）

`validation/hx_experiments.py` 统一保存 7/0.6 水—空气 HX 的读取、列映射、
质量标记及已核定的 A/L/参考 Re 约定。`fit_experimental_effective` 与
`cf_cross_fluid` 直接调用它。旧 gamma 工具在完成读取解耦后已退役，
源码与旧输出见[历史模型索引](history/legacy-models.md)。
跨数据集 cF 反演只根据原始数据质量选样，不再根据旧 gamma 压降预测是否有解筛行。

实表前后对照：空气 D/G 18/16 行、水 D/G 18/16 行读取结果与属性逐值一致；
实验修正的四份 CSV 完全一致。cF 对照仍为 156 行，新增/删除成员均为 0；
空气 D/G 15/15、水 16/15、sCO2 51/44。数值最大相对差 1.20e-15，属于浮点舍入。
在新进程中禁用旧 gamma/RBF 模块和六张旧系数表，两个现行工具仍以退出码 0 完成。
本地对照与日志已存入上述私有归档的 `hx-experiment-decouple-20260912/`。
该次解耦保留当时的联合 K/cF、实验 sF、质量标记、速度适用域及压力换算约定。

## Gyroid HX 空气标定来源更新（2026-09-16）

`AIR_BOOKS["Gyroid"]` 现指向 4 月 1 日空气直通工作簿。原一维固定 K0
标定使用 `Sheet1` 第 4–18 行（第 2–16 工况）：F 列名义质量流量，
AC/AD 温度平均值，AE/AF 表压。保留 2000 Pa 的既有筛选规则；第 1 项仍
读取并列入完整对照。标定入口和每行审查结果记录原文件、工作表和 Excel 行号。

4 月 7 日互换流道工作簿继续作为迁移及旧系数来源对照，读取时显式传入
`load_air_cases("Gyroid", source=(工作簿相对路径, "Sheet1"))`。
Diamond 空气、水和 sCO2 的源文件及标定选择保持原状。

本次变更仅作用于独立的 7/0.6 mm HX 修正。`df_surrogate.load_data` 的
空气小试件训练集隔离守卫继续有效，上海整机数据不进入该训练表。
新系数和适用范围见[标定来源与适用范围](model-resources.md)。

## 读取行为与版本边界

- `validation/water_exp.py` 明确列出已确认压力口径的工作簿**新文件名**。
  表压到绝压仍仅换算一次，保留原压力列、负压损和重复行标记。
  `harness/_harness.py` 的同名判断与读取路径同步更新。
- 上海及 D76 水—空气 `Sheet1` 的共享读取入口只取到最后一个工况编号，
  不将表尾的传感器校正值、计算记录和空行作为实验工况。原工况的行序、
  列位置和数值保留；工况内部缺失温压仍由原检查报错，不作静默剔除。
- D76 sCO2 的现行六工况 Nu 验证（Gate A）读取整理版。原 V1 保留旧
  2D/压损 holdout 的历史来源；这些旧入口见[退役索引](history/retired-tools.md)，
  不列为当前验证。两版列布局不同，路径整理不代表物理验收通过。
- 空气小试件训练数据仍受上海来源隔离守卫保护；独立 HX 标定的来源见上文。
- 同步更新加载器、验证脚本、测试私有数据存在性检查、上海配置和服务器
  复制后的文件检查。旧文件名仍可出现在历史报告和冻结来源记录中，通过本表追溯。
- 两个工作簿已有的 REFPROP 外链指向原 Windows 加载项位置。本次不重算、
  不修订外链或缓存；文件归类不代表该加载项已在当前电脑安装。
- `Water-CFD/水数值模拟数据.xlsx` 是 2026-07-23 修订记录引用、现已缺失的
  来源。它的读取要求与缺失状态保留；不得用 `legacy` 文件冒充或自动回退。
  本次不判断修正版更正确，不改水 CFD 数值、拟合系数、数据成员或验收阈值。
- `data-revision.txt` 固定私有数据仓的对应 Git 提交。本次布局及计划修订已在
  `01b62ad09e487857b05b42c01c5c62288ebd0b4b` 保存并推送；23 份原始文件
  与修订前提交逐字节一致，原计划由 `before_porosity` 副本保留。
  非现用原件进一步归档后，最终数据版本为
  `1dcf916ed4468d8c365253f6e88d03b1546ecdfe`；24 份数据与整理版本逐字节一致。

继续查水数据时，应按原 W 编号与字段定义核验。目录、名称及表内代数自洽
均不替代原 CFD 几何、网格、收敛和物理适用性的证据。

## 非现用原件归档（2026-09-12）

8 份原件移至 `raw_data/archive/`：普通 CO2 的 4 个 CSV，D76 的公式版、
处理版与 REFPROP.XLA，及较旧的水压损整理表。现用读取器没有引用这些路径。
旧水压损表的有效内容已被 `with-air-temperature` 表包含，但原件仍保留；
D76 公式和外链不重算，1071 个无缓存公式不作为数值输入。

`arranged` 继续供现行 Gate A 读取，`values_v1` 保留历史 2D/holdout 来源，
两者列布局不同，不能合并。原始水/空气/sCO2 实验、现行 CFD、修订水计划及
修订前完整计划继续保留，全部原始内容可通过本目录或固定私有数据版本追溯。
