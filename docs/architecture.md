# SJTU-TPMSHX-TM1 architecture

[中文](architecture.zh-CN.md) | [English](architecture.md)

## System overview and layers

Version 0.2 uses C++ as the only numerical backend.
Full 2D, full 3D, and Quick Design run on macOS arm64 and Windows x64; Linux x86_64 supports independent result evaluation only.
Production domain shapes are limited to rectangular 2D and cuboid 3D domains.
Three explicit public stages connect every application entry point:

```text
applications -> preprocess.api -> CaseData -> solvers.api -> FieldResult
                                                          -> postprocess.api -> PerformanceResult
                         data_types / physical_models / model_configs / file_io / run_control
```

Four independent C++ shared libraries own all production numerical work:

- **Geometry (`geometry/`)**: geometry ABI 2 and field ABI 3 for TPMS cell geometry, chi/Kss, grids, ports, splines, sigmoid fields, LUTs, and zones.
- **Preparation (`preprocess/`)**: preparation ABI 3 and Quick Design preparation v2 for properties, Nu closures, fixed D-F, 2D/3D preparation, and scalar inlet queries.
- **Solver (`solver/`)**: saved 2D stage ABI 5, saved 3D stage ABI 3 (capture ABI 2), and Quick Design run v2. It also owns SIMPLE flow, model-h, temperature, and T-SOU conservative energy.
- **Result (`postprocess/`)**: result ABI 3 (`float64` arrays and `int32` zone labels) for metrics, physical balances, applicability checks, zone statistics, and qualification.

Shared coefficients, bounds, and defaults come from [model_parameters_v1.json](../python/model_configs/model_parameters_v1.json) and [preparation_df_v1.json](../python/model_configs/preparation_df_v1.json).
`engineering/scripts/generate_native_model_coefficients.py` generates native C++ headers from these files using only the Python standard library.
The [public headers](../include/tpmshx/), [C++ tests](../tests/cpp/), [C++ integration guide](cpp-migration.md#cpp-core-scope), and [native stage SDK](native-stages.md) define the native interfaces.
See [C++ migration history](history/cpp-migration-history.md) for retired version 0.1 Python solvers, retired `v1`–`v11` ABIs, and archived qualification records.

<a id="retained-python-responsibilities"></a>

## Retained Python responsibilities

Python owns public APIs, configuration, immutable DTOs, file I/O, caches, warning formatting, and application workflows under [python](../python/).
Numerical code stays free of Qt; GUI code lives only in `python/applications/gui/ui/` and `python/applications/gui/controllers/`.
The import-layering check maps source modules to their dependency owners and enforces these boundaries.

- **Public entry points**: `compute` ([python/compute.py](../python/compute.py)) orchestrates `prepare_case`, `run_case`, and `evaluate`, managing progress, cancellation, stage timings, and warnings. `applications/result_adapter.compute_result` and `to_compute_result` map `FieldResult` and `PerformanceResult` for GUI, CLI, and validation tools.
- **Input normalization and caches**: `python/cpp_interface/` loads the four native libraries on demand. It normalizes real inputs to `float64` and labels to `int32`, and emits fixed `RuntimeWarning` diagnostics. `python/physical_models/preparation_cache.py` owns the 32,768-entry geometry cache and 4,096-entry inlet-property cache; material conductivity and chi are never cached.
- **Configuration, I/O, and models**: `python/data_types/` owns `ComputeConfig`, `CaseData`, `FieldResult`, `PerformanceResult`, and `metric_spec`. `python/file_io/` owns YAML, HDF5, JSON, VTK, and checkpoint I/O. `python/physical_models/` and `python/model_configs/` own model queries, `zone_units.py`, and versioned resources.
- **Postprocessing and ledger helpers**: `python/postprocess/result_math.py` keeps the raw pressure query and public `compute_phase2a` conservation certificate. `python/solvers/physical_ledger.py` keeps the `ports_complete` check for injected ledgers.
- **Applications and research**: `python/applications/` owns GUI, CLI, Quick Design sizing, multi-condition BO, and run recovery. `python/preprocess/offline/` and `python/development/` own explicit offline fitting, validation, and diagnostic tools.
- **Compatibility alias resolver (`python/shared.py`)**: kept as a zero-duplication import hook for local `.cache/` paper and research scripts. It resolves historical `sjtu_tpmshx.shared.*` and `sjtu_tpmshx.solvers.backends.cpp.*` paths to their canonical module owners.
- **Independent test oracles**: pure-formula references (such as `tests/python/enthalpy_1d_reference.py`, `water_nu_reference.py`, `geometry_reference.py`, and `preparation_flow_reference.py`) stay under [tests/python](../tests/python/) and are excluded from runtime wheels.

Missing native libraries, ABI mismatches, or missing active symbols fail explicitly with no numerical fallback.

<a id="native-grids-and-design-fields"></a>

## Native grids and design fields

The geometry library (`tpmshx_geometry_shared`) owns grid generation, physical ports, level-set cell geometry, and spatial design fields.
See [geometry build and deployment](cpp-migration.md#native-geometry-core) for build paths and publication, and [fields-sources.md](../geometry/fields-sources.md) for fixed sources and BSD notices.

| Owner | Numerical contract |
| --- | --- |
| `grid.cpp`, `ports.cpp` | Uniform, aligned, wall, and port widths; GUI adaptive counts and 3D suggestions; six-direction axis maps; physical port overlap and profiles. |
| `field_continuous.cpp`, `continuous/xy_fitpack.c` | Nondegenerate XY splines using the restricted SciPy 1.18.1 FITPACK first-fit (`s = 0`) route. |
| `continuous/tensor_spline.cpp` | XYZ splines and singleton XY axes using sequential 1D fits and samples in x, y, z order. |
| `field_sigmoid.cpp`, `field_lut.cpp` | Ordered sigmoid blending, final clipping, and linear LUT interpolation (not a spline route). |
| `zones.cpp` | Ordered discrete zone assignment and `sigma = 2`, `radius = 8`, reflect Gaussian filtering in grid-index units. |

The geometry library exports geometry ABI 2 and field ABI 3 with distinct status codes:

| Protocol | Status 1 | Status 2 | Status 3 |
| --- | --- | --- | --- |
| Geometry, grids, and zones (ABI 2) | Invalid input | Domain error (`ZeroDivisionError`) | Runtime error |
| Continuous splines, sigmoid, and LUT (ABI 3) | Invalid input | Allocation failure (`MemoryError`) | Numerical or runtime error |

- **Level-set count index**: `geometry.cpp` and `asym_geometry.cpp` build an exact sorted-`|phi|` voxel and exposed-face count index. The cache holds two topology/resolution pairs (32 MiB plus 16 MiB `phi` grid at `N = 128`). Standard symmetric fields batch L/t arrays through the same formulas as scalar queries. Solid conductivity resolves explicit `chi`, then `TPMSHX_CHI_S`, then the native fit on each call.
- **Continuous fields (`zones.axis = "continuous"`)**: accept `x_decision` (`L` controls then `t` controls in mm), `n_ctrl_x`, `n_ctrl_y`, and optional `n_ctrl_z` (3D only). They also accept `symmetric_y`, `spline_order` (1–3), `L_bounds`, and `t_bounds` within `L = 4..8 mm`, `t = 0.3..0.6 mm`. XY controls in 3D extrude along z. Splines sample final physical cell centres without Gaussian smoothing. Continuous fields require symmetric channels (`delta = 0`). Both fluid sides consume full local K/cF arrays in SIMPLE coordinates.
- **Discrete zones (`x`, `y`, `grid`)**: stripe intervals must be finite and cover `[0, 1]` without gaps or overlaps (`1e-9` tolerance). In 2D, stripes and rectangles project raw L/t with transverse cell widths before row D-F prediction. They apply Gaussian smoothing to design fields while keeping thermal geometry unsmoothed. In 3D, XY grid rectangles smooth L and t separately and extrude along z.
- **CO2 model**: `co2_segment2_v1.json` supplies symmetric geometry for both sides when either side is CO2. Only CO2 sides apply fixed factors `K = K0 / 2.5`, `cF = 2.5 * cF0`, and Nu factor `1.28` (including the Nu floor), independently of `df_mode`.
- **Prescribed total mass flow**: `preprocess.api.prepare_fixed_mass_flow_case` and `prepare_inlet_mass_capacities` integrate local single-channel porosity times the normalized inlet velocity profile over the physical opening. Preparation multiplies that integral by inlet density, then divides prescribed `mass_flow_kg_s` by that capacity. 2D total-flow inputs require an explicit physical depth in m while keeping per-unit-depth solver units.

## Native preparation, solver, and evaluation stages

### Preparation and inlet queries

`preprocess/preparation_case.cpp` owns 2D and 3D case preparation (`tpmshx_preparation_2d_*_v1`, `tpmshx_preparation_3d_*_v1`) and the scalar inlet query (`tpmshx_query_inlet_properties_v2`).
`python/cpp_interface/preparation_host.py` shares unified `tpmshx_preparation_callbacks_v1` cache transport, range-record decoding, and D-F application decoding across 2D and 3D.
`tpmshx_preparation_df_experiment_scope_v1` shares experimental D-F layout and HX campaign-domain checks between 2D/3D preparation and static Python preflight.
See [preparation builds](cpp-migration.md#native-preparation-core) and [inlet-property query](native-stages.md#inlet-property-query).

### Full 2D, full 3D, and Quick Design execution

Python binds only the saved-stage lifecycle in `full_2d_stage.py` (ABI 5), `full_3d_stage.py` (ABI 3, capture ABI 2), and `quick_design.py` (run v2).
Both full bindings validate and borrow aligned `float64` case arrays via `tpmshx_stage_borrow_mesh_v1`.
They pass unset tolerances as absent so C++ resolves defaults from `model_parameters_v1.json`.
Before native release, they copy captured fields, records, execution views, and scalar reports.

- **SIMPLE flow (`Simple2DSolver`, `Simple3DSolver`)**: all fluids use the native F2 monitor (consecutive momentum, fresh-density local/global mass, and zero outlet-backflow checks). Explicit `convergence_mode = "legacy"` is rejected. Momentum faces use continuity's signed mass fluxes; transverse viscous faces use series half-cell resistance. Optional `SolverConfig.simple_velocity_relaxation` in `(0, 1]` defaults to `0.7` (2D) and `0.5` (3D).
- **2D fixed-density Anderson**: full 2D fixed-density sides use `simple_2d_fixed_density_anderson_v1`. Proposals consume one budget step and are accepted only when momentum residual does not increase, both mass gates pass, and outlet backflow is zero.
- **3D return certificate and coarse bootstrap**: 3D closes outlet fluxes after the final density update and rechecks all four F2 gates. `post_closure` rejects a failed final step. Coarse bootstrap is disabled by default in formal 3D runs; when enabled, `tpmshx_full_3d_get_bootstrap_trace_v1` publishes per-layer shapes, caps, and charged iterations into `diagnostics.coarse_bootstrap_trace`.
- **Internal 3D runtime owners**: `full_3d.cpp` separates `FlowRun`, `ThermalRun`, `TransportProperties`, `RangeRecorder`, and `SidePhysics`. Raw inlet-pressure transport properties are reused per cell only when temperature is unchanged (48 bytes per sampled side and cell).
- **Thermal routes**:

| Route | Implementation and scope |
| --- | --- |
| True enthalpy (T-SOU) | Default `temperature_sou` for any ordered pair containing CO2 or sCO2 in uniform or continuous geometry. Uses guarded HEOS PT updates, `0.6` whole-block Picard damping, and SOU recipe 2 six-sample Anderson proposals. Defaults: 2D `12000` (water) / `5000` (other) iterations; 3D `1500` iterations; `5` sweeps, `omega = 0.2`, `1e-8 K` update gate, `0.001` coupled and equation gates. Air/water sides use integral `h(T)` and CO2/sCO2 sides use HEOS `h(T,P)`. Full 3D performs zero temperature sweeps before each EOS solve. |
| Model enthalpy (model-h) | Air/water integral `h(T)` transport with signed mass faces, minmod SOU on both sides, and `MODEL_H_RELAXATION = 0.2`. 2D includes symmetric unzoned water/water; 3D (`Nz > 1`) includes all ordered air/water pairs (water/water and asymmetric geometry use the strict boundary contract). Both dimensions share the accelerated chunk owner (strict 3D: 5 sweeps/block, 16 Anderson samples; other calls: 25 sweeps/block, 6 samples). Optional `SolverConfig` overrides (`model_h_max_iterations`, `model_h_temperature_tol_K`, `model_h_q_relative_tol`) apply to main and refined calls. |
| Strict fullCC temperature | Air/water full 2D (`model_h_tface_sou_fou_strict_v3`) and full 3D `Nz = 1` / `Nz > 1` (`model_h_tface_sou_sou_strict_v3`) reuse strict model-h drivers with `<= 1e-7` complete-boundary ledgers. See [shared finite-volume consumers](cpp-migration.md#shared-finite-volume-temperature-consumers). |
| Quick Design | Prescribed-flow LTNE approximation (`quick_design_prepare_v2.cpp`, `quick_design_run.cpp`) with fixed analytical inlet pressure fractions, one const pass or two mean passes, and liquid-water guards after each pass. Length search (`solve_Lx`) accepts only cold-start converged feasible candidates. |

- **Result evaluation (`postprocess/result_stage.cpp`)**: `python/postprocess/api.py` routes full 2D/3D and Quick Design evaluation, applicability, physical balance, and qualification queries to `tpmshx_result_stage_query_v3`. Postprocessing reads only recorded evidence and never reruns a solver.

### Completed execution records

Completed full solves record `metadata.execution_record` (`full_execution_v1`), `input_resolution` (`prepared_input_v1`), `property_sampling` (`full_sampling_v1`), `model_h_iterations` (`model_h_iterations_v1`), and `enthalpy_update_normalization`.
Each record separates each side's flow/heat-transfer resource from its energy relation (`eos_h_TP`, `integral_cp_T`, `capacity_temperature`, or `prescribed_temperature`).
It also keeps thermal state labels separate from post-update final flow state labels.
`enthalpy_update_normalization` scales each fluid's h update by `max(cp_in * abs(dT_in), 1 J/kg)` independently of enthalpy origins.
Historical result files keep their original metadata without rewriting.

<a id="result-qualification-by-route"></a>

## Result qualification by route

Execution completion, solver convergence, metric availability, and optimization eligibility are separate facts.
`run_case` records native convergence; `evaluate` checks whether recorded evidence supports each metric.

| Route | Native convergence and final evidence | Additional consumer requirements |
| --- | --- | --- |
| 2D model-h | SIMPLE, outer coupling, main/fine thermal convergence and energy certificates, Richardson eligibility, and pressure envelope. | Multi-condition batches require both physical-boundary ledgers and main/fine gates. `Q` uses W/m; total-flow studies need an explicit depth. |
| 3D model-h | Final SIMPLE checks, thermal/outer convergence, finite fields, and pressure envelope. Source-free passes require strict energy gates. | Multi-condition batches independently verify `compute_phase2a` global/cell, source, and boundary certificates. |
| 2D/3D true-h | Native T-SOU solve with `0.001` equation/boundary gates, Kelvin gate, and property checks. Thermal evidence stays detached from any failed final flow post-update. | Inspect `true_h_balance` and convergence detail. Outside the air/water model-h optimizer contract. |
| Native full-compute CC | Strict model-h on accepted thermal mass faces with integral `h(T_face)` advective and Fourier powers, complete-boundary ratio `<= 1e-7`. | `model_enthalpy_temperature_v1` supports captured heat in W/m (2D) or W (3D). Distinct from product model-h optimizer eligibility. |
| Other temperature and research routes | Route-specific stopping rules, coefficient sampling, and recorded state. | Fixed-coefficient capacity transport and staggered/MAC research do not inherit fullCC integral-h qualification. |
| Quick Design | Explicit prescribed-flow sizing approximation. | Metrics and feasibility checks do not certify a full SIMPLE solve. |

In 2D model-h, stable heat and temperature changes trigger nonlinear A/B/solid cell balances.
Each phase's max cell residual normalized by average cell exchange (floor `1 W/m`) must be `<= 1%`.
In source-free 3D model-h, stable changes trigger the strict certificate (`<= 1%` global/cellmax residual and LTNE source imbalance over `max(abs(Q_sA), abs(Q_sB), 1 W)`).
The first water model-h pass yields to flow after at most 250 sweeps and halves the trial interval if water leaves the liquid range.
Outer field stability cannot end the loop while the last thermal pass is unconverged.
See [capabilities](capabilities.en.md), [model applicability](model-resources.en.md), and [data provenance](data-catalog.en.md) for separate physical scope.

## Physical balance evidence

Full results store physical heat audits under `boundary_fluxes.energy` (`physical_heat_ledger_v1`), `boundary_fluxes.temperature`, and `boundary_fluxes.fine` (2D refined grid).
Records keep signed outward advection and diffusion, source integrals, phase residuals (`RHS - diag * state`), solved-phase flags, and prescribed-B reservoir power in W/m (2D) or W (3D).
`postprocess.api.evaluate_physical_balance` evaluates mass inflow/outflow/divergence, phase residual norms, signed external power, and residual-minus-external-power mismatch without solver or EOS calls.
Missing or cancelled evidence stays unavailable; readers never fabricate a zero balance.

<a id="captured-parameter-limits"></a>

## Captured parameter limits

Prepared cases store original model bounds and inlet samples in `applicability_inputs`; completed full solves store `applicability_evidence_v1`.
Saved 2D and 3D runs copy native applicability groups and required records before release, and combine case notices with run `nu-evidence` warnings into `scope_notes`.
3D air-field scalar observations select at most eight samples per side (original notices, extrema, and last sample) while full raw-array records keep every cell.

`postprocess.api.evaluate_applicability(result)` checks inlet and last local correlation inputs (including `Re` before its floor) without solver or EOS calls:

- For positive original bounds `[L, U]`, the allowed parameter interval is `[0.9 * L, 1.1 * U]`.
- Any sample outside that interval fails the range check (the rule is not a fraction of cells).
- Geometry bounds stay fixed; water HX lower speed `0.10 m/s` permits `0.09 m/s`.
- Missing required evidence returns `unverified`; old files without evidence return `unavailable`.

## Common result verdict

`postprocess.api.evaluate` writes `result_qualification_v1` into `PerformanceResult.qualification`; `evaluate_qualification(result, metrics)` reproduces it from saved evidence.
Execution, convergence (including finite checks on raw main `Ta`/`Tb`/`Ts` and recorded fine temperatures), physical balance, parameter limits, metric availability, and design eligibility have separate states.
The `design` conclusion requires all recorded gates to pass; unresolved joint sCO2 P/T/Pr and wall heating/cooling coverage keeps `model_scope` and `design` as `unverified`.
The separate `optimization` verdict permits sCO2 studies by deferring only that known sCO2 model-scope gap when all execution, convergence, physical, parameter-limit, and metric gates pass.

## Persistent interfaces and physical state

- **`CaseData`, `FieldResult`, `PerformanceResult`**: arrays crossing stage contracts are detached and immutable; metadata-only updates can share contiguous immutable byte buffers with separate headers. `data_types.metric_spec` enforces metric families, units, and definition versions across JSON, GUI, and multi-condition aggregation.
- **Display aliases (`postprocess.result_display`)**: Qt-free module owning field units, axes, 2D display aliases, and zone statistics. Temperature and pressure aliases keep raw cell values; 3D display aliases share immutable buffers.
- **Public thermal and pressure definitions**: full thermal metrics use `native_boundary_v1`. `Q` is `abs(Q_A)` on the main grid, `Q_A`/`Q_B` are signed heat loss, and outlet temperature is mass-flux weighted. 2D Richardson duties stay separate as `Q_richardson_A/B`. Full pressure drop uses `pressure_face_v1` (extrapolated final SIMPLE pressure at physical inlet/outlet faces, weighted by geometric open area).
- **Air inlet-pressure shooting (`numerics/pressure_reference.cpp`)**: iterates the outlet-cell anchor with a bounded `P^2` update until physical inlet open-area mean pressure matches `P_in` within `1e-4` relative error. Explicit `p_in_shooting = False` / `TPMSHX_P_IN_SHOOT = 0` is a diagnostic override that cannot certify convergence. Incompressible routes anchor the physical inlet-face open-area mean directly to `P_in`.
- **2D inlet profile (`PartialBCConfig.uniform_inlet_2d`)**: selects geometric overlap without the historical four-cell taper. Desktop fixes this flag to `True`; scripted API configs keep the historical taper when `False`.

<a id="native-3d-continuation"></a>

## Native 2D and 3D continuation

`Full2DRun.advance_step` and `Full3DRun.advance_step` expose inner SIMPLE, thermal, and controller step boundaries using the shared typed archive in `full_run_state.cpp` (native state format 2).
Snapshots cover initial and post-update SIMPLE calls, model-h selections (including Anderson history and water startup retries), temperature chunks, EOS Picard iterations, and 2D refinement grids.
Restore rebuilds derived matrices and views without repeating charged iterations; it requires the exact same native build, platform, prepared inputs, and numerical controls.

- **CPU thread limit (`RunControl.cpu_threads`)**: optional runtime-only limit (native default up to 8 logical CPUs) that can change on restore. Used by T-SOU parallel EOS evaluation and two-fluid sweeps, 3D model-h wavefront line sweeps, and paired 2D SIMPLE workers (`1` serializes). Recorded in `runtime_resources`.
- **Checkpoints and recovery**: `SolverCheckpoint` (`full_2d_continuation_v1` / `full_3d_continuation_v1`) writes atomically via `python/file_io/solver_checkpoint_io.py`. `applications.execution.recovery` owns run directories, fixed-snapshot hard-link sharing (`file_io.file_snapshot`), `PausedRun` (CLI Ctrl+C exit code 3; GUI 60 s interval), and `failed-result.h5` preservation if postprocessing fails.

### Cooperative cancellation

Full native entry points check cancellation before packing inputs or loading a native library (`run_control.cancellation.CancelledError`).
2D polls each SIMPLE iteration and LTNE chunk (including Richardson); 3D polls each SIMPLE iteration, momentum/pressure sub-step, and LTNE chunk; T-SOU polls each Picard iteration.
Active linear solves or chunks finish before returning; there is no forced thread kill, and cancelled runs never publish results.

### Multi-condition batches and Bayesian optimization

`applications.optimization.multi_condition` evaluates ordered condition batches using `compute_prepared_run` with 60 s checkpoints and `resume_condition_batch` for recovery into a new directory.
Default `workers = None` selects at most 4 native worker processes with at least 2 CPU slots each.
It splits the total CPU limit, keeps input order, and uses one manager process for pause and cancel.
`run_multi_condition_optimization` supports `qLogNEHVI`, `qLogNParEGO`, and `Sobol` to maximize `(heat_gain_percent, -pressure_ratio)` from complete accepted batches.
With `mass_requirements`, it runs `qLogNEI` or `Sobol` for constrained core-mass minimization, including optional per-condition `T_out`/`P_out` limits and `allow_nu_re_extrapolation`.
`resume_multi_condition_optimization` copies the archive to a new directory and verifies `optimization-input.json`, Sobol sequences, and saved proposals before continuing.
nTop CSV export writes XY or XYZ coordinates with full control provenance.

<a id="ui-structure"></a>

## UI structure

- **User storage and startup**: `python/applications/gui/controllers/user_storage.py` stores preferences, sessions, and history in platform user directories via atomic temp-file replacement. `python/desktop.py` configures writable caches before loading Qt. Existing sessions restore full input snapshots; Shanghai defaults apply only to new workspaces.
- **Preflight and retired settings**: Compute captures one `ComputeConfig` before grid preflight, speed advice, 3D size confirmation, and worker launch. Preflight shares `python/physical_models/grid.py` with preparation. Retired `wall_refine_3d` (extra six-wall layers) is rejected when enabled for new preparation; `ComputeConfig.from_dict(..., prepared_grid=True)` supports replay, continuation, and geometry export ([retirement record](history/README.en.md#six-wall-grid-retirement)). Saved polygon presets are rejected.
- **Preset and partial import**: Copy-as-Python, reproducible links, saved-input menus, and drag-and-drop share one preset decoder. Unwrapped `line_edits` and legacy flat configs merge only supplied fields into the captured current inputs before cross-field validation.
- **Workbench modules**: `builders_canvas.py` assembles the workbench, `mixins/tab_view.py` owns tab routing, and `panel_vis_3d.py` owns PyVista rendering (cell centres plus boundary points). `background_tasks.py` prepares 3D modules in one window-owned QThread while keeping widget, Matplotlib, and OpenGL work on the GUI thread. `field_factory.py` owns value labels, `fmt.py` formats qualification reasons, and `typography.py` selects native Qt and publication Matplotlib/VTK fonts.
- **Result cache and exports**: `ResultCache` owns one published `ComputeResult` for the active dimension; failed or cancelled runs keep the prior accepted result. 3D NPZ exports write temperatures (K), velocity components/magnitudes (m/s), display pressures `P_fA`/`P_fB` (Pa), `L_mm`/`t_mm` (mm), `dx`/`dy`/`dz` (m), and legacy `vmag`/`P_kPa` aliases.
- **Resumable validation CLI**: `development.validation.cases.validate_sco2_exp_q` freezes selected members and publishes `partial.csv` and `state.json` atomically after each member. It supports `--resume-run` on identical verified inputs and exits 130 on cancellation.

## Physical invariants

Change these constraints only as an explicit physical-model revision with direct validation:

1. **Compressible air**: air uses the ideal-gas density path; never substitute a constant-density or isothermal shortcut.
2. **Porosity is split one time**: symmetric callers pass full porosity and the solver forms half-porosity streams. For nonzero `delta_levelset`, `preprocess/preparation_case.cpp` computes `eps_A` and `eps_B` summing to full porosity; kernels do not halve them again. Effective fluid conductivity is `K_ff_i = eps_i * k_i` (`eps_total/2 * k_i` when symmetric; offset factor `2 * split_i` applies once).
3. **Mass-flux inlet**: compressible air uses the mass-flux inlet in 2D and 3D; solver velocities are interstitial, not superficial.
4. **Darcy-Forchheimer ownership**: `physical_models.df_surrogate.predict.predict_K_cF()` is the pure geometry baseline (bilinear interpolation on `4..8 mm` by `0.3..0.6 mm` from water+sCO2 CFD, independent of Re or fluid). Production exposes only **CFD smooth-wall** (generic default) and **Experiment calibration** (one fixed reviewed factor per side applied before SIMPLE). Retired `gamma_df` and `rbf` modes raise an error ([legacy models](history/legacy-models.md)).
5. **Nusselt ownership**: full runs evaluate Nu in [fluid_nusselt_ratio](../numerics/fluid_properties.cpp#L174) and [nu_point](../numerics/fluid_properties.cpp#L371), wrapped by [nu_correlations.py](../python/physical_models/nu_correlations.py). `python/model_configs/sco2_effective_nu.json` (`sco2_effective_nu_config()`) is the sole sCO2 effective-Nu resource (`alpha_D`/`alpha_G` as total `Ceff` applied once before the Nu floor; see [model resources](model-resources.en.md#sco2-有效-nu-系数)). The [2D](../solver/full_2d.cpp#L539) and [3D](../solver/full_3d.cpp#L877) solvers compute local Re and Nu from cell-centered pore velocity magnitude `sqrt(uc^2 + vc^2 [+ wc^2])`.
6. **Compressible envelope**: `python/physical_models/envelope.py` rejects nonfinite states, pressure `<= 1000 Pa`, and `Mach >= 1`. Positive subsonic fields must also satisfy the inlet-pressure gate to converge.
7. **Pressure reference**: on ideal-gas sides, `P_ref_abs` anchors outlet cells and local absolute pressure is `P_ref_abs + P`. Use geometric open-area means at physical port faces for inlet-pressure correction and diagnostics.
8. **Units**: prepared contracts use K, Pa, and m; closures expecting mm receive explicit boundary conversions without changing persisted SI fields.
9. **Port boundary**: 2D supports `±x`/`±y` and 3D adds `±z`. Non-opening exterior faces are stationary no-slip walls with half-cell viscous wall flux (including `z±` in 3D). Primary and staggered opening fractions come directly from raw rectangle overlap on the actual grid.
10. **True-enthalpy ownership**: any pair containing CO2 or sCO2 uses conservative T-SOU with signed staggered face mass fluxes and boundary enthalpy duties. Each sCO2 side uses **280–700 K, 7.9–16 MPa absolute** at inlets and local states. The off-by-default `TPMSHX_SCO2_COMPRESSIBLE` research switch updates local-pressure properties only on the 3D A side and does not qualify a two-sided compressible model.
11. **Current TM1 limit**: CO2 and sCO2 reject discrete zones and nonzero `delta_levelset`; symmetric continuous fields are supported. For `Nz > 1`, end cells impose `T_in` at open inlet faces with half-cell conduction and zero gradient at outlets.
12. **Experiment-correction applicability**: air core-specimen calibration covers `L = 6..8 mm`, `t = 0.3..0.5 mm`. HX-effective mode (`7/0.6 mm`, `0.182 x 0.042 x 0.042 m`, `delta = 0`, fixed `K = K0`) uses frozen `sF` values. Frozen `sF` values are: sCO2 `6.313005350332494` (D) / `7.608907691857889` (G), and water `4.8928` (D, 6.84% RMSRE) / `4.1989` (G, 0.93% RMSRE, `u >= 0.10 m/s` fit). Air uses `1.8024228153853061` (D) / `2.649010286988306` (G, `shanghai-air-straight-20260401-v1`, runtime calibration window `8.027855328062564..22.446874107951544 m/s`). Approved application windows (`hx_application_velocity_bounds()`, D/G, m/s): water `0.0139648..0.254055` / `0.0162341..0.225876`; air `3.88324..22.7599` / `3.91282..24.5467`; sCO2 `0.434925..2.53961` / `0.381408..2.47046`. Leaving calibration windows emits run-local extrapolation notices. See [model resources](model-resources.en.md).

## Extension points

- Add a fluid in `python/physical_models/fluid_props.py`, its Nu closure in `python/physical_models/nu_correlations.py`, and its versioned resource in `python/model_configs/`.
- Add user-facing configuration fields to `python/data_types/compute_config.py` first, then adapt once at the UI boundary.
- Keep one production path per dimension; avoid factories or wrappers for single implementations.

## Local data

Raw experiment and CFD data live outside Git under `data/raw_data/`:

```text
data/raw_data/
├── experiments/{air,water_air,sco2}/
├── cfd/
│   ├── water/
│   └── sco2/{Diamond,Gyroid}/
├── archive/{co2,water_air,sco2}/
└── plans/water/
```

Do not rename dataset directories or workbooks without updating their loader registry and caller tests together.
See the [data catalog](data-catalog.en.md) for filename mappings and water pressure conventions.
