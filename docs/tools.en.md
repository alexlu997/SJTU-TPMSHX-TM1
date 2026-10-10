<a id="工具入口与复现边界"></a>

# Tool entry points and reproduction boundaries

[中文](tools.md) | [English](tools.en.md)

Run all commands from the repository root. Use the absolute interpreter on the first line of `.venv-path`. First follow [README checks](../README.en.md#first-run) for the applicable lock and `pip check`. Keep caches in this worktree's ignored `.cache/`. In the table, `python` means that interpreter, not system Python.

The README defines public compute entry points and formal Case/Result handoff. These tools do not replace mainline acceptance.

MMS A3/A4/B4 and GCI create a separate `.cache/validation/<tool>-<run-ID>/` by default. It contains CSV files, reports, and metadata. `--out-dir` selects another directory. A3 also supports `--out_csv`, `--orders_csv`, and `--report`. A4 supports the first two. B4 supports `--out_csv`.

Explicit relative file paths resolve from the current working directory. Reference CSV files, orders, and historical metadata under `sjtu_tpmshx/validation/` stay. Before solving, tools reject writes there, including symlinks that point there. Other explicit output directories can be reused. Use the default separate directory to keep each run.

`validate_sco2_exp_q --csv` also validates reference-directory protection for CSV and `.meta.json` before solving. The shared provenance CSV writer and this entry stage CSV/metadata in the target directory. They replace the group only after all writes succeed. Write or replacement exceptions keep the previous group. This does not cover power failure or concurrent writers to one target. With explicit `sidecar=False`, the shared writer also removes an previous sidecar to prevent stale metadata on reload.

A4 applies inlet temperature at the physical face. Adjacent cell temperatures stay unknowns. Inlet-layer L2/Linf stay discretization diagnostics. The strict inlet gate compares the first corner-cell response from one real kernel sweep against an independent finite-volume balance. Its normalized error is `abs(T_kernel-T_FV)/abs(T_FV) < 1e-12`.

This does not mean each inlet-cell error is zero. Existing convergence, finiteness, and regional order gates stay. The previous fixed CSV criterion pinned cell temperatures. It supports historical comparisons, not current physical-face boundary evidence.

GCI now uses T2 and T4, with offset local openings and no B-side experimental correction. Historical experimental entries such as T4_H8 are retired. Previous H8 tables cannot show current T4 accuracy. See [retirement notes](history/retired-tools.md#b-侧局部开口实验修正退役2026-09-22). Apparent order is solved from actual grid ratios and three results. Oscillation, nonfinite values, or no positive order make the result unacceptable.

No assumed second order is substituted. Failure of C.3 tolerance sensitivity also returns nonzero.

Conservation audit T1 uses co-directed streams. The former crossflow T1 table is not its reference. Mass deviation uses actual inlet/outlet fluxes, without temperature-change compensation. Diagnostic failures stay in outputs and return nonzero. Current conservation requires strict global and cellwise residuals below 1%, including each control volume and physical inlet face.

Missing or nonfinite certificates fail. Source coupling and mass checks stay separate. The former 5% heuristic excluded first/last layers. That rule and surface budgets inferred from cell temperatures are retired. Historical CSV files and failures stay unchanged.

Numerical conservation is not experimental accuracy acceptance.

The independent Shanghai lumped dual-Nu comparison uses crossflow as primary and counterflow for sensitivity. Run `python -m sjtu_tpmshx.validation.cases.validate_shanghai_lumped_dual_nu`. By default, CSV and provenance metadata go to a new `.cache/validation/shanghai-lumped-dual-nu-*` directory. `--out-dir` can select a directory. It no longer overwrites `data/shanghai_lumped_dual_nu.csv`.

`benchmark_sou_3d` uses current `pressure_face_v1` face-extrapolated pressure drops. Previous cell-center outputs keep only their historical definition.

`asym_pyfluent_runner` is an incomplete pressure-drop research template.
Mesh units, periodic pairs, fluid cell-zone assignment and initialization need configuration for the actual mesh and Fluent version.
It reads pressures after a fixed iteration count, without a convergence acceptance gate.
It does not set up conjugate heat transfer. PyFluent is outside the default locked environment.

| Tool | Input → output | Command and scope |
| --- | --- | --- |
| [examples/](../examples/) | Public JSON/YAML configuration → Case/Result/metrics | Real 2D/3D CLI examples in README. First-run entry within current support. |
| [runs/smokes/](../sjtu_tpmshx/runs/smokes/) | Built-in examples → console and declared diagnostics | `python -m sjtu_tpmshx.runs.smokes.<module>`. Headless GUI requires `QT_QPA_PLATFORM=offscreen`. |
| [runs/demos/](../sjtu_tpmshx/runs/demos/) | Built-in 3D cases → console/visualization | `python -m sjtu_tpmshx.runs.demos.<module>`. Interactive graphics require a desktop. Examples do not extend applicability. |
| [CFD worklist](../sjtu_tpmshx/runs/tools/asym_build_cfd_worklist_xlsx.py) → [nTop expressions](../sjtu_tpmshx/runs/cfd_asym/asym_ntop_expressions_html.py) | Built-in geometry/fluid and optional private `water_DG_cfd_results_legacy.xlsx` → XLSX → HTML | Run the two commands below in order with one output directory. Missing local water data leaves a skip explanation in `r1_water_ref`, without invented anchors. |
| [Asymmetric CFD tools](../sjtu_tpmshx/runs/cfd_asym/), [diagnostics/](../sjtu_tpmshx/runs/diagnostics/) | Declared geometry and field/CFD files → research results | `python -m sjtu_tpmshx.runs.<subdirectory>.<module>`. Fluent and private input files need separate preparation. The PyFluent template's incomplete steps are listed above. |
| [scripts/](../scripts/) | Configured environment and test selection → logs | Two PowerShell test entries. Repository path comes from script location. Interpreter comes from `.venv-path`. `-LockFile` selects the lock. No automatic dependency installation. |
| [D76 Nu/ε-NTU historical Q](../sjtu_tpmshx/validation/cases/validate_sco2_d76.py) | Six fixed D-7-6 cases/private Excel → smooth-CFD Nu and lumped Q | `python -m sjtu_tpmshx.validation.cases.validate_sco2_d76`. Keeps the 15% maximum absolute relative Q error gate. Exit 0 passes. 1 fails. It does not validate current effective Nu coefficients. |
| [Existing water Nu table](../sjtu_tpmshx/validation/cases/validate_water_nu_excel.py) | 1879 legacy water CFD rows → row/topology/geometry/Re-band errors | `python -m sjtu_tpmshx.validation.cases.validate_water_nu_excel --out .cache/water-nu-validation`. Fixed current correlations. Exit 0 passes. 2 fails accuracy. Data errors raise. |
| [Current experimental corrections](../sjtu_tpmshx/validation/df_refit/fit_experimental_effective.py), [cross-dataset cF](../sjtu_tpmshx/validation/df_refit/cf_cross_fluid.py) | Experimental workbooks and fixed CFD baseline → review CSV files in `.cache/reports/df_refit/` | `python -m sjtu_tpmshx.validation.df_refit.<module>`. Shared `validation/hx_experiments.py` reader. No previous γ/RBF fit or six retired coefficient tables. Production coefficients stay unchanged. |
| [sCO2 CFD base Nu fit](../sjtu_tpmshx/validation/sco2_cfd/fit_nu_sco2.py) | Original CFD tables → research base fits and geometry/pressure leave-one-out results | `python -m sjtu_tpmshx.validation.sco2_cfd.fit_nu_sco2`. Original cleaning and validation stay. No automatic effective-coefficient replacement. Previous experimental anchoring is [historical](history/legacy-models.md#sco2-nu-旧锚定路线2026-09-20). |
| [Main compute measurement](../sjtu_tpmshx/runs/tools/benchmark_main_compute.py) | Local fixed `jobs` list with `id/config` and optional `reference/depth_m` → separate Case/Result/metrics, logs, and stage measurements | `python -m sjtu_tpmshx.runs.tools.benchmark_main_compute MANIFEST NEW_OUTPUT --warmup --repeat 5`. 0 passes execution/status/declared-flow checks. 2 means unqualified results. 1 means execution errors. It does not show experimental accuracy. |
| [F2 tolerance costing](../sjtu_tpmshx/validation/cases/price_f2_convergence_3d.py) | Historical costing cases → separate `.cache/validation/f2_pricing-*/` CSV | `python -m sjtu_tpmshx.validation.cases.price_f2_convergence_3d --mom-tol 1e-3,1e-4,1e-5 --cases 1,8,16`. Scans F2. `--out` supports an output protected against frozen-path writes. Its full-side ports cannot replace local-port main-compute evidence. |

Run the GUI checks without solving separately:

```bash
python -m sjtu_tpmshx.runs.smokes.smoke_ui_offscreen
python -m sjtu_tpmshx.runs.smokes.smoke_ui_screenshots --output .cache/ui-smoke-screenshots
```

Both require Qt offscreen. They use temporary session and appearance directories under `.cache/`, then remove temporary state without overwriting user preferences. Screenshot output also defaults to `.cache/ui-smoke-screenshots`. Missing required widgets/options, unsuccessful navigation, Qt callback exceptions, or failure to close the window return 1. Screenshot save failure also returns 1.

Only completed checks without these failures print PASS and return 0. Screenshots cover the main window, 2D/3D modes, and Optimization. Without computation results, the results page check shows entry availability only. It does not show result rendering acceptance. Offscreen checks do not show native 3D rendering, desktop frame rates, or numerical correctness.

Main-compute measurement uses a monotonic clock. Solve time includes native result capture. Internal SIMPLE calls can overlap and cannot be summed as total duration. RSS is sampled each 0.5 seconds with local `ps`. Sampling failures are explicit.

This tool does not replace first-frame or desktop interaction measurements. Organize first-run, disk-cache, and same-process warm measurements separately. Each run keeps actual jobs, data revision, budgets, and native exit states. Previous fixed lists stay in the [history index](history/README.en.md).

Current Gyroid HX air calibration uses April 1 straight-channel data. Cases 2–16 fit one-dimensional sF with fixed K0. April 7 data is for transfer checks between channel connections only. `fit_experimental_effective` writes review tables with source, sheet, and row, then validates packaged coefficients. Complete 2D/3D validation calls `benchmark_main_compute` directly and reads sF through the production resource.

See [model resources](model-resources.en.md) for formulas, inputs, and applicability. History keeps candidates and research outputs.

Historical sCO₂ fixed-166 snapshots, including 83 3D baseline cases, use crossflow local ports, experimental resistance, and **previous Nu multipliers D=1.77/G=1.07**. Membership, experimental denominators, and original errors stay. They are not relabeled as current-coefficient validation. See [model resources](model-resources.en.md#sco2-有效-nu-系数) for current total Ceff, provenance, and new paired results. Different parameters, grids, or tolerances cannot be mixed to claim improvement.

Default `validate_sco2_exp_q.py` uses counterflow, CFD resistance, and base Nu: a separate physical review configuration. `--all-valid` also reselects members through the current reader. Reproduce the previous baseline with the saved fixed manifest, formerly `workloads.json`, and matching raw data. Select fixed IDs with `--jobs`, for example `--jobs sco2-009-Diamond-8-2d shanghai-01-3d`. Use history to locate previous evidence. Do not regenerate membership from current readers.

The new output directory must not exist. Select current sCO₂ coefficients explicitly through `sco2_effective_nu_config()` or the GUI. Retired `fit_nu_correction`/`nu_bytemp_report` are not current recalculation entries. Changing Nu JSON alone does not rebuild strict solve settings or the previous fixed manifest.

The shared `validation.sco2_exp.load_sco2_exp` reader keeps measured endpoint enthalpy/Q, heat balance, quality flags, mean-temperature properties/Re, and reduced resistance quantities. It no longer derives wall temperature from the midpoint of stream mean temperatures to report h/Nu. Associated `ok_dT` and previous CLI summaries are retired. Raw measurements stay unchanged. The historical denominator was not replaced with another heat-transfer-coefficient definition.

Shanghai production validation uses one constructor for port/wall meshes. Grid counts include all refined cells. The 2D entry uses `84×24`. 3D defaults to `92×14×10` when explicit grid arguments are absent. Historical mesh studies stay in [history](history/README.en.md).

Explicit 3D `--nx/--ny/--nz` keep a selected grid. `--port-wall-refine` enables port/wall refinement. Former `--wall-refine` uses a different six-wall refinement. They cannot be enabled together. The actual grid always comes from this result's prepared grid.

See [architecture](architecture.md) for common F2 and physical boundaries. History keeps previous architecture regressions and experimental errors. Invalid `tol_simple` and the optimizer launcher's previous `--tol` are retired. Importing previous cases explicitly reports that this field is ignored. Actual F2 momentum and mass convergence thresholds stay. MMS energy-solver `--tol` is a separate valid parameter and is not retired.

Both complete Shanghai dimensions use approved April 1 local water ports. The upper inlet spans `x=133–175 mm`. The lower outlet spans `x=7–49 mm`. Both cross the `42 mm` depth. Velocity uses experimental total mass flow, current model side pore area, and inlet density. Both dimensions use current production paths.

The previous kernel and `--runner/--profile/--eta/--disp-c` options are retired. The D76 3D pressure-drop entry depended on that kernel and is also retired. Its [historical results](history/retired-tools.md#剩余历史入口整理2026-09-22) are separate from the kept six-case D76 Nu check.

Shanghai 2D CSV `Q_sim` keeps experimental mass flow/inlet-cp semantics. New `Q_native` keeps main-compute W/m. Native 3D Q is W. Compare definitions separately without replacing previous experimental thresholds. 2D validation uses only the current production path.

It reports accuracy without adding an experimental-error threshold. Nonfinite or unconverged results return nonzero. By default, 3D production validation keeps each requested member. Missing, failed, nonfinite, unconverged, or invalid final-pressure results cannot pass. Original RMSRE thresholds stay 12% for pressure drop and 6% for heat duty.

Intermediate pressure clipping counts are diagnostic. Early clipping does not reject a recovered valid final state. Explicit `--no-gate` produces a report only, not acceptance.

Formal files and GUI exports stage a file group before publication. Write/publication errors restore the previous successful files. A 2D export over a same-name 3D CSV also removes the previous NPZ to prevent mixed results. Each target permits only one writer. Sudden power loss has no file-group atomicity guarantee.

A remaining `.tm1-publish-*` directory identifies an incomplete attempt. Its `previous/` contains recovery files, not successful output. Current exceptions keep the recovery location. Prefer a separate directory for each run.

<a id="公开模块扩展示例"></a>

## Public module extension examples

Run these commands at the repository root with the interpreter that passed environment checks. They require no private raw data:

```bash
PYTHON="$(head -n 1 .venv-path)"
export MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg"
export NUMBA_NUM_THREADS=2 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
"$PYTHON" -m examples.three_module.external_design examples/three_module/design_case.json .cache/examples/design
"$PYTHON" -m examples.three_module.parameter_scan .cache/examples/scan
"$PYTHON" -m examples.three_module.design_field_call .cache/examples/field
```

In PowerShell, read `.venv-path` and use `& $tm1Python` with the same arguments. Root README defines environment variables.

- [external_design](../examples/three_module/external_design.py) accepts [DesignCase JSON](../examples/three_module/design_case.json). Units are K, absolute Pa, kg/s, and W. `dPlim_h/c` are ΔP/P_in fractions. It runs forward evaluation for fixed Diamond 7/0.5 mm geometry, without automatic sizing to input Q. Output Q is total W.

  Exit 0/2 means converged/unconverged. The GUI table loader instead uses K/kPa and kW. Table headings are not JSON field names.
- [parameter_scan](../examples/three_module/parameter_scan.py) screens two air velocities in 2D. Each case saves Case/Result/metrics. The root output directory contains `summary.json`.
- [design_field_call](../examples/three_module/design_field_call.py) compares original and explicitly changed effective solid-conductivity fields. It saves the same files per case and shows Q changes. It computes no adjoint or gradient.

Each case has `case.yaml` with `case.h5`, `results.h5`, and `metrics.json`. The latter two examples reuse `air_2d.json`. Q is W/m. See `summary.json` and result files for convergence and applicability states. Script exit 0 does not mean each case converged. Both use the full solve API without extending model applicability.

<a id="定尺与优化结果"></a>

## Sizing and optimization results

Quick-sizing CSV/XLSX headers have surrounding whitespace removed. Each physical input field can appear one time. Duplicate columns fail during loading.

Quick sizing decides feasibility from final per-case recalculation. Failed cases stay in details. The final-acceptance column identifies nonconvergence, nonfinite values, unmet temperature/duty targets, or excess pressure drop. Only candidates that pass final acceptance enter best-candidate selection.

The current GUI uses `multi_condition_optimizer` with qLogNEHVI, qLogNParEGO, or Sobol. It optimizes mean heat-transfer percentage improvement and two-side relative pressure loss across conditions. Both objectives stay separate. `optimization.json` records complete controls, conditions, zero-based candidate indices, failure reasons, and native batch directories. Only candidates with complete numerical admission enter training and the Pareto set.

Default initial count is 16, configurable from 1–256. Total candidate budget is `n_init + n_iter*q_batch`, plus one uniform baseline batch. Each batch contains all conditions.

2D uses XY controls. 3D uses independent XYZ controls. Loading a selected design keeps its complete field. Imported total mass flow is converted to inlet velocity using current geometry, openings, and inlet density, followed by complete physical checks. Previous GUI velocity fields still need basic format validation. They no longer determine physical applicability for these imported conditions.

After baseline success, archived conditions contain converted baseline velocities. Each candidate recomputes velocities using its own full field. Baseline failure keeps original inputs and per-case failure reasons.

Previous air/air `optimizer_qnehvi`, multi-seed runners, frozen-B 3D recalculation, and dedicated profiling entries are retired. Fixed source stays in the [history index](history/retired-tools.md). The current multi-condition optimizer requires a new run directory. Existing directories are rejected to keep configurations and evaluation records.

Historical `pareto_*.csv` and `history*.csv` can still export geometry through `export_ntop_csv`. The original `config.json` is required. Named decision columns are restored in numerical order. Missing, duplicate, or nonfinite columns fail explicitly. Failure states in matching `*_status.json` stay in export metadata.

Geometry export does not reevaluate the previous model. The public nTop API/CLI stages and publishes `Lfield.csv`, `tfield.csv`, and `provenance.json` as a group. Write failure keeps the previous complete geometry. Numerical precision, coordinates, and original control provenance stay unchanged.

<a id="数据与研究工具"></a>

## Data and research tools

The CFD-worklist-to-nTop default directory is ignored `sjtu_tpmshx/runs/_out/asym_cfd/`. If `TPMSHX_TOOL_OUT_DIR` is set, use the same value for both commands:

```bash
python -m sjtu_tpmshx.runs.tools.asym_build_cfd_worklist_xlsx
python -m sjtu_tpmshx.runs.cfd_asym.asym_ntop_expressions_html
```

Former `water-cfd-raw.xlsx` is now `data/raw_data/cfd/water/water_DG_cfd_results_legacy.xlsx`. It is only this research tool's declared previous recipe anchor. The [data catalog](data-catalog.en.md) maps all names. Formal offline processing still requires missing `Water-CFD/水数值模拟数据.xlsx`. These files cannot substitute for each other.

Two asymmetric CFD kappa research paths use different denominators. `ingest_cfd_kappa` uses the current symmetric predictor. `asym_postproc_kappa` uses paired r=1 CFD. Their kappa values cannot be mixed directly. The importer uses piecewise linear interpolation over sorted nodes. It does not guarantee monotonic data or enforce an r=1 anchor.

The registry exists only in the current process. Explicit `kappa_KcF` supports research evaluation. It is not integrated into formal solve preparation. An environment variable does not automatically change full 2D/3D or GUI computations. Previous accuracy figures in work orders are historical references.

Current validation must record its own versions, inputs, and results.

Water Nu validation independently uses actual mass flow from the existing legacy table, current N=128 geometry, and table properties. It recalculates velocity, Re, and Pr. Reference Nu is `mean(Core2_Nu, Core3_Nu) × Dh_current / Dh_excel`. Each topology requires RMSRE ≤ 10% and absolute mean signed relative error ≤ 5%. Each present row enters the denominator.

D_7_3/4/5 keep separate flags. The [data catalog](data-catalog.en.md#水-nu-现存表验证2026-09-12) records measured 2026-09-12 results and limits.

Performance files and research reports can use fixed filenames. Keep useful outputs before another run. Import checks show package resolution only. Data availability, real execution, convergence, energy/mass, and experimental accuracy require separate acceptance. History contains B40, fixed-166, and frozen references.

[Capabilities](capabilities.en.md) records current M-A/M-B status. The [historical model index](history/legacy-models.md) collects retired models, six coefficient tables, publication/comparison scripts, and reports. Original failures stay unchanged.

The [retired tool index](history/retired-tools.md) records completed 703/704/624 work, fixed M1/M2 experiments, and previous performance reproduction scripts.
They are no longer current rerun entry points.
