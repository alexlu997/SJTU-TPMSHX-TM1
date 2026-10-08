<a id="原始数据目录与文件名对照"></a>

# Raw data catalog and filename mapping

[中文](data-catalog.md) | [English](data-catalog.en.md)

The directory was reorganized on 2026-09-12. Local `data/raw_data/` is held in the private SJTU-TPMSHX-data repository. This page records paths and purposes, not raw measurement tables. The reorganization moved and renamed 13 Excel workbooks. It also classified CFD CSV files and accompanying notes.

Renaming kept workbook contents, sheet names, formulas, cached formula values, units, and existing data flags. A separate water worklist revision and original backup are described below.

<a id="分类"></a>

## Categories

```text
data/raw_data/
├── experiments/
│   ├── air/           Air specimen test summaries
│   ├── water_air/     Water–air exchanger tests and water pressure-drop tables
│   └── sco2/
│       └── d76/       Current arranged and numeric D7 / 0.6 mm wall versions
├── cfd/
│   ├── water/         Existing historical water CFD results
│   └── sco2/          Supercritical CO2, still grouped by Diamond/Gyroid
├── archive/           Ordinary CO2, old water dP, sCO2 formulas, REFPROP files
└── plans/
    └── water/         Water CFD worklists, not simulation results
```

<a id="命名规则"></a>

## Naming rules

The basic order is `fluid_object_purpose_date-or-version.xlsx`. Directories first separate experiments, CFD results, and plans. `D`/`G` mean Diamond/Gyroid. `DG` means both. `7-t0p6` means a 7 mm cell and 0.6 mm wall. `hx` means the complete exchanger.

Dates come only from explicit experimental dates in source files. Modification timestamps do not show data dates.

`legacy` identifies a kept historical source. `values_v1`, `formulas`, `arranged`, and `processing` distinguish numeric, formula, and arranged versions. They do not rank correctness or precedence. Both path columns below are relative to `data/raw_data/`.

| Original path | New path | Purpose and distinction |
| --- | --- | --- |
| `20260401-上海电气天然气加热器实验工况.xlsx` | `experiments/water_air/water-air_G7-t0p6_shanghai_experiment_20260401.xlsx` | Gyroid HX straight-air calibration, cases 2–16, and whole-exchanger comparison. The air specimen training set still rejects Shanghai sources. |
| `20260407-上海电气天然气加热器实验工况 -调换进出口-G_7_6.xlsx` | `experiments/water_air/water-air_G7-t0p6_shanghai_experiment_ports-swapped_20260407.xlsx` | On 2026-09-15, the user confirmed exchanged air/water channels with unchanged specimen and other hardware. Air uses staggered openings. Water uses the former straight-air channel. See [pressure diagnosis](history/README.en.md#2026-09-18-历史材料整理). |
| `20260609-水直空气侧-D_7_6.xlsx` | `experiments/water_air/water-air_D7-t0p6_experiment_water-straight_20260609.xlsx` | D7/0.6 water–air experiment. |
| `7-6-Water-dp.xlsx` | `experiments/water_air/water-air_DG7-t0p6_hx_water-dp_with-air-temperature.xlsx` | Water pressure-drop table. The D sheet also contains air inlet temperature. The current water HX reader uses this table. |
| `换热器压损——20260407-G-7-6+20260609-D_7_6.xlsx` | `archive/water_air/water-air_DG7-t0p6_hx_water-dp.xlsx` | Another pressure-drop table without the additional D-sheet air temperature column. It is not merged with the preceding table. |
| `试验记录表_整理版.xlsx` | `experiments/air/air_DG_specimen_experiment_summary.xlsx` | Electrically heated air specimen tests, including CFD comparison columns. These are not water CFD results. |
| `sCO2-Experient.xlsx` | `experiments/sco2/sco2_DG7-t0p6_hx_experiment_summary.xlsx` | D/G sCO2 exchanger summary, with separate column mappings for each topology. |
| `D-7-6实验数据-sCO2.xlsx` | `experiments/sco2/d76/sco2_D7-t0p6_hx_experiment_arranged.xlsx` | Original `整理版`/`无公式` layout, 47 columns. |
| `D-7-6-sCO2/D-7-6实验数据-V1.xlsx` | `experiments/sco2/d76/sco2_D7-t0p6_hx_experiment_values_v1.xlsx` | Original V1, `无公式` sheet, 48 columns. |
| `D-7-6-sCO2/D-7-6实验数据-formula.xlsx` | `archive/sco2/d76/sco2_D7-t0p6_hx_experiment_formulas.xlsx` | Original formula version, including REFPROP external links and caches. |
| `D-7-6-sCO2/D实验数据-超临界二氧化碳.xlsx` | `archive/sco2/d76/sco2_D7-t0p6_hx_experiment_processing.xlsx` | Original `实验数据处理` sheet, 49 columns. |
| `TPMS水_关联式拟合CFD工况.xlsx` | `plans/water/water_DG_cfd_worklist.xlsx` | 1880 planned cases, including geometry, reference properties, and mass-flow formulas. |
| `water-cfd-raw.xlsx` | `cfd/water/water_DG_cfd_results_legacy.xlsx` | 1879 historical results. W01600 is closed as missing and will not be filled. Existing source concerns stay separate. |

Other moves were `CO2-CFD/` to `archive/co2/` and `sCO2-CFD/` to `cfd/sco2/`. All 8 CSV filenames and contents stayed unchanged. `D-7-6-sCO2/REFPROP.XLA` moved with the formulas to `archive/sco2/d76/`. `说明.txt` moved to `experiments/water_air/water-air_DG_hx_source-notes.txt`, with its text kept.

<a id="上海第-12-工况热量参考修正2026-09-30-归档"></a>

## Shanghai case 12 heat reference correction, archived 2026-09-30

Data commit `2bdebc125ea9878bfe329deadc981dbafe0e1921`, referenced by `data-revision.txt`, includes the existing April 1 workbook formula correction. The previous workbook stays in data commit `06172513d1ca5effa55f7e204544a87d7cabf2b6`. Its contents match the earlier declared version `1dcf916ed4468d8c365253f6e88d03b1546ecdfe`.

`Sheet1!AH14` changed from `1011*I13/I14*F14*(AC14-AD14)` to `1011*K14/I14*F14*(AC14-AD14)`. I13 is the previous case's planned air flow. K14 is this case's measured air flow. The correction restores the same-row reduction formula used by the other 15 cases. Air Q changed from 2535.868061 W to 2730.294062 W.

The formula `AL14=AI14/AH14` stayed unchanged. Its cached ratio changed from 0.886265572 to 0.823154029.

A cell-by-cell formula/cache comparison across all three sheets found only these two changes. F/H mass flows, temperatures, pressures, pressure drops, and water heat references for all 16 fixed cases stayed unchanged. All heat formulas were also recalculated arithmetically. Solver inputs still use nominal F/H mass flows. Experimental heat reduction still uses measured/planned flow ratios K/I and L/J.

This version record changes no sensor, cp=1011 J/(kg·K), calibration coefficient, or experimental acceptance threshold. It does not show heat loss as the cause of the hot/cold duty difference.

<a id="水-cfd-计划孔隙率修订2026-09-12"></a>

## Water CFD worklist porosity revision, 2026-09-12

The user approved current `compute_geometry("Diamond", 7, t, N=128)` values of `epsilon/2` for D_7_3, D_7_4, and D_7_5. The respective values are 0.417083740234375, 0.3896484375, and 0.363372802734375. Updated ranges are `几何D_L汇总!E14:E16` and `推荐CFD工况总表!H566:H706`. The shared-formula structure stays. The 141 related recommended mass-flow formulas in column T were recalculated. Dh, properties, Re labels, case membership, and all other cells keep their previous values.

The complete original worklist stays beside it as `water_DG_cfd_worklist_before_porosity_20260912.xlsx`. Historical CFD inlet mass flows must be traced through that copy and the legacy results. New recommended flows in the revised plan are not the actual historical inlet flows. The revision uses current model conventions. It does not validate the original CFD mesh geometry. Historical CFD results, existing fit coefficients, and the W01600 missing-data closure stay unchanged.

<a id="已结案缺项"></a>

## Closed missing case

On 2026-09-12, the user closed `W01600 / G_7_5 / Re=3000 / Tref=325 K / Twall=375 K` as missing, without replacement. The planned row `推荐CFD工况总表!A1601:Y1601` stays. No result is invented. Missing data does not show a computation failure. Coverage stays 1880 planned and 1879 present.

The original main fit contains 439/440 cases. G_7_5 contains 46/47. Existing developing-region coefficients already use that geometry's 46 records. This change removes no other data and performs no refit.

<a id="水-nu-现存表验证2026-09-12"></a>

## Existing water Nu table validation, 2026-09-12

The check used all 1879 rows and 40 geometries in `cfd/water/water_DG_cfd_results_legacy.xlsx`. Inputs used actual historical `mdot_in_kg_s`, current N=128 side porosity/Dh, and workbook rho/mu/cp/k. Velocity is `mdot/(rho*epsilon_side*L_cell²)`, from which Re and Pr are recalculated. Reference Nu is `mean(Core2_Nu, Core3_Nu) × Dh_current/Dh_excel`. Neither the previous Um column nor new worklist recommendations replace actual mass flow. Current coefficients stay fixed without refitting.

Thresholds were set before execution: RMSRE ≤ 10% and absolute mean signed relative error ≤ 5%, separately for each topology.

| Topology | Rows | RMSRE | Mean signed bias | Verdict |
| --- | ---: | ---: | ---: | --- |
| Diamond | 940 | 9.9965% | +1.1424% | Pass, close to the threshold |
| Gyroid | 939 | 10.6243% | +0.6079% | RMSRE failed |

Overall acceptance stays failed. The native exit code was 2. Re spans 99.55–50871.92, inside the current correlation range of 90–51000. Below Re=500, D/G RMSRE is 17.42%/17.53%. Gyroid RMSRE is 12.41% for 1000≤Re<3000 and 12.24% for Re≥30000. Error is not confined to one geometry.

D_7_3/4/5 stay in the main denominator, with RMSRE values of 12.67%/6.65%/8.24%. No points were removed, thresholds relaxed, or production coefficients changed. W01600 stays closed as missing.

Reproduce the check with `validation/cases/validate_water_nu_excel.py`. Detailed local evidence from `water-nu-validation-20260912/` is in private `20260912-prior-task-evidence.tar.gz`. It includes the report, summary, and row/geometry/Re-band CSV files. Local `.cache/ARCHIVE.md` records the archive location. The former `.cache/` subdirectory is no longer an active entry.

This validates the current correlation against existing data. It neither reconstructs the missing revised source's historical fit nor shows independent experimental validation.

**Coefficient selection is closed: on 2026-09-12, the user chose to keep the original correlations.** Diamond keeps `Nu = 0.3201·Re^0.6679·Pr^(1/3)`. Gyroid keeps `Nu = 0.3941·Re^0.6435·Pr^(1/3)`. Same-form refit candidates were not adopted. Their comparison is in `water-nu-refit-20260912/` within the same private archive. Measured errors, the 10% threshold, and exit code stay unchanged.

Unchanged coefficients do not convert the accuracy check into a pass. This round does not pursue coefficient replacement.

<a id="现行实验工具读取解耦2026-09-12"></a>

## Separation of current experimental readers, 2026-09-12

`validation/hx_experiments.py` owns 7/0.6 water–air HX loading, column mapping, quality flags, and approved A/L/reference-Re conventions. `fit_experimental_effective` and `cf_cross_fluid` call it directly. The previous gamma tool was retired after reader separation. Its source and outputs stay in the [historical model index](history/legacy-models.md). Cross-dataset cF inversion now selects rows only by raw data quality. It no longer selects rows according to solvability of previous gamma pressure predictions.

Before/after checks found identical air D/G 18/16 and water D/G 18/16 rows and properties. All four experimental correction CSV files matched. The cF comparison kept 156 rows, with 0 additions or removals. Counts were air D/G 15/15, water 16/15, and sCO2 51/44. Maximum relative numerical difference was 1.20e-15, consistent with floating-point rounding.

Both current tools finished with exit code 0 in a new process with previous gamma/RBF modules and six coefficient tables disabled. Comparisons and logs are in the private archive's `hx-experiment-decouple-20260912/`. This separation kept the then-current joint K/cF, experimental sF, quality flags, velocity applicability, and pressure conversion conventions.

<a id="gyroid-hx-空气标定来源更新2026-09-16"></a>

## Gyroid HX air calibration source update, 2026-09-16

`AIR_BOOKS["Gyroid"]` now selects the April 1 straight-air workbook. The original one-dimensional fixed-K0 fit uses `Sheet1` rows 4–18, cases 2–16. It reads nominal mass flow from F, mean AC/AD temperatures, and AE/AF gauge pressures. The existing 2000 Pa filter stays. Case 1 is still read and included in the complete comparison. Calibration entries and per-row reviews record source file, sheet, and Excel row.

The April 7 exchanged-channel workbook stays a transfer check and previous-coefficient source comparison. Load it explicitly with `load_air_cases("Gyroid", source=(relative_workbook_path, "Sheet1"))`. Diamond air, water, and sCO2 source files and calibration choices stay unchanged.

This change affects only the separate 7/0.6 mm HX correction. The air specimen isolation guard in `df_surrogate.load_data` stays active. Shanghai whole-exchanger data does not enter that training table. See [calibration provenance and applicability](model-resources.en.md) for coefficients and limits.

<a id="读取行为与版本边界"></a>

## Reader behavior and version boundaries

- `validation/water_exp.py` lists the specified workbooks by their **new filenames**. Gauge pressure becomes absolute pressure one time. Original pressure columns, negative drops, and duplicate-row flags stay. Matching checks in `harness/_harness.py` use the updated paths.
- Shared Shanghai and D76 water–air `Sheet1` readers stop at the last case number. Footer sensor corrections, calculation notes, and empty rows do not become cases. Original order, columns, and values stay. Missing case temperatures or pressures still raise through existing checks. Rows are not silently removed.
- Current D76 sCO2 six-case Nu validation, Gate A, reads the arranged version. V1 stays the historical source for previous 2D/pressure holdouts. Those entries are in the [retirement index](history/retired-tools.md), not current validation. Layouts differ. Path reorganization does not show physical acceptance.
- The air specimen training set keeps the Shanghai source guard. The separate HX calibration source is described above.
- Loaders, validation scripts, private-data test checks, Shanghai configuration, and post-copy server file checks were updated together. Historical reports and frozen provenance can keep previous filenames, traceable through this table.
- Existing REFPROP links in two workbooks point to the original Windows add-in location. This reorganization recalculated or changed neither links nor caches. Classification does not show installation of that add-in on this computer.
- `Water-CFD/水数值模拟数据.xlsx`, referenced by the 2026-07-23 revision record, is missing. Its reader requirements and missing state stay. The legacy file cannot impersonate it or become an automatic fallback. This reorganization does not rank the revised source as more correct. It changes no water CFD values, fits, members, or thresholds.
- `data-revision.txt` pins the corresponding private repository commit. Layout and worklist revisions were saved and pushed as `01b62ad09e487857b05b42c01c5c62288ebd0b4b`. All 23 original files matched the preceding version byte for byte. The `before_porosity` copy keeps the original worklist. More archival produced `1dcf916ed4468d8c365253f6e88d03b1546ecdfe`. 24 data files matched the organized version byte for byte.

More water-data investigation must use original W identifiers and field definitions. Directory structure, naming, and algebraic consistency do not replace evidence for original CFD geometry, mesh, convergence, or physical applicability.

<a id="非现用原件归档2026-09-12"></a>

## Archival of inactive originals, 2026-09-12

Eight originals moved to `raw_data/archive/`: four ordinary-CO2 CSV files, D76 formula/processing versions, REFPROP.XLA, and the older water pressure-drop table. Current readers do not reference these paths. The `with-air-temperature` table contains the previous pressure table's useful content, but the original stays. D76 formulas and external links were not recalculated. The 1071 formulas without cached values are not numerical inputs.

`arranged` stays the current Gate A input. `values_v1` keeps historical 2D/holdout provenance. Their different layouts prevent merging. Original water/air/sCO2 experiments, current CFD, revised water worklist, and complete original worklist stay available. This catalog or fixed private data versions give access to all originals.
