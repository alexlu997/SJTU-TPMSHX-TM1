# C++ migration and ABI history

[中文](cpp-migration-history.zh-CN.md) | [English](cpp-migration-history.md)

This document records historical C++ migration stages, retired ABI versions, and past numerical qualification results.
See [C++ integration](../cpp-migration.md), [native stages](../native-stages.md), and [architecture](../architecture.md) for current supported behavior.
Original historical counts, tolerances, and failure verdicts stay unchanged here.

## Solver migration stages (version 0.1 to 0.2)

Version 0.1 kept both Python and C++ numerical backends.
Its comparison criteria in [version 0.1 architecture](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/v0.1.0/docs/architecture.md) required 0.1% duty, pressure, and mass limits, plus a 0.01 K temperature limit.
Velocity differences had to stay within `1e-6 m/s + 1e-5 * u_inlet`.
Former Python/C++ comparisons in [version 0.1 migration notes](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/v0.1.0/docs/cpp-migration.md) stay historical evidence for those builds.
Version 0.2 retired the Python numerical backend, Numba/PyAMG dependencies, and Python-only research entries (`prepare_research_case` and `research_three_d_v1`).

| Stage | Historical implementation boundary | Required evidence before advancing |
| --- | --- | --- |
| 0: thermal operators | Independent native sweeps and energy-audit operators. The Python/C++ hybrid selector was retired. | Operator checks plus public field, flux, metric, handoff, cancellation, and error comparisons. |
| 1: complete thermal driver | Port Picard state, property refresh, EOS inverse, residuals, warm starts, and cooperative cancellation. | Fixed inlet, pressure, and grid inputs with unchanged A/B/solid equation and boundary-energy gates. |
| 2: flow and coupling | Port SIMPLE, pressure and mass corrections, and outer coupling for rectangular cases. | Momentum and fresh-density F2 gates, physical inlet-pressure, outlet-backflow, and energy checks. |
| 3: actual C++ backend | Consume `CaseData` and produce complete `FieldResult` without Python solver kernels. | Separate-process handoff, units, field locations, model provenance, and explicit rejection of unsupported modes. |
| 4: application and release | Expose the C++ backend through `solvers.api` for GUI, Quick Design, optimization, and offline postprocessing. | Matched-case checks and platform build and packaging evidence on macOS arm64 and Windows x64. |

### CoolProp binary inspection, 2026-09-21

On 2026-09-21, inspection of the local CoolProp 7.2.0 wheel showed C++ headers and an MIT license.
Its binary was a CPython Mach-O bundle, not a linkable `libCoolProp` library.
Standalone C++ linking failed with an unsupported Mach-O file type, and no independent archive existed in that environment.
No sources were downloaded during that inspection.
The project then adopted an isolated offline CoolProp 8.0.0 build defined in [dependencies-lock.toml](../../engineering/native_build/dependencies-lock.toml).

### Retired numerical paths and solver options

- **Frozen H-FOU, H-sweep C export, and T-FOU**: retired after T-SOU became the default conservative EOS energy algorithm. Historical `enthalpy_eos`, `sco2_enthalpy_eos`, FOU recipe 1, and SOU recipe 1/2 records stay readable.
- **Outer property Anderson**: retired under full 3D ABI 2. Fixed property relaxation and thermal Anderson stay active.
- **Single-A sCO2 execution**: retired. Archived results with `legacy_frozen_cp_single_a_cc_v1` keep their missing complete `h(P,T)` transport status.
- **Full3D true-h warm-up sweeps**: private G4 iteration rows and special staggered warm-up rows were retired; preparation now runs zero temperature sweeps before the EOS solve.
- **Variable-cp `m*cp*T` fullCC proposal**: retired after its physical-contract failure; replaced by strict integral `h(T)` model-h drivers.
- **Initial AMGCL pressure candidate**: failed full-case comparison and was replaced by SuperLU/COLAMD (<= 2,000 cells) and classical algebraic multigrid. AMGCL stays only for staggered-temperature projection.
- **Other retired solver options**: `SIMPLER` 2D branch, B-side partial-opening experiments (M4 scaling, participation mask, temperature freezing, H2 outlet suppression), `tol_simple`, and `TPMSHX_SIMPLE_TOL`. Also retired: `TPMSHX_TRUE_H_KERNEL` (`numba`, `cpp_sweeps_v1`), `energy_nan_hit`, Gaussian display filters, `postprocess.report`, and `postprocess.visualization`.

## 2026-11 C++ core migration milestones

In November 2026, six implementation stages moved remaining numerical kernels from Python into four independent C++ libraries:

- **Model data consolidation**: [PR #275](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/275) consolidated shared constants into `model_parameters_v1.json` and generated C++ headers.
- **Native geometry core**: [PR #276](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/276) introduced `geometry/` (geometry ABI 2).
- **Native grids and design fields**: [PR #277](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/277) moved grids, ports, continuous splines, sigmoid fields, LUTs, and zones into `tpmshx_geometry_shared` (field ABI 3).
- **Native preparation core**: [PR #278](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/278) created `preprocess/` with independent preparation CMake targets.
- **Native result core**: [PR #279](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/279) created `postprocess/` with independent Linux/macOS/Windows evaluation.
- **Consumer cleanup**: removed obsolete GUI interpolation imports, `shared/models/grid_3d.py`, `asym_split.py`, `shared/models/quick_design.py`, Python 2D preparation sequences, and `tpms_calc._compute_cached` numerical code.

### Incremental stage ABI evolution (2026-11, retired on 2026-11-23 and 2026-11-24)

During the 2026-11 migration, 2D and 3D stage entries grew incrementally before consolidation:

| Retired series | Incremental versions before 2026-11-23/24 consolidation |
| --- | --- |
| 2D preparation v1–v6 | v1 uniform symmetric air/air; v2 16 fluid pairs and scalar tags; v3 uniform total flow; v4 continuous XY; v5 stripes/rectangles; v6 sigmoid and LUT. |
| 2D preparation v7–v11 | v7 `GridKinds2D` narrow-scalar tags; v8 spatial total flow; v9 typed cache callbacks; v10 nonzero `delta_levelset` side geometry; v11 pore porosity and stripe hydraulic radius. |
| 3D preparation v1–v5 | v1 uniform 3D; v2 3D total flow; v3 continuous XY/XYZ 3D; v4 XY grid rectangles and global offset; host v5 shared cache callbacks. |
| 2D and 3D stage runs | 2D one-shot runs v1–v4, saved descriptors v1–v4, and 3D one-shot runs v1–v2 (replaced by flat saved 2D v5 and 3D v3). |
| Quick Design v1 and host ops | Native-double v1 preparation/run, 14 unused `quick_*` C entries, `QuickProtocols` callbacks, and a 30-operation raw-object host callback table. |

## 2026-11-23 and 2026-11-24 ABI consolidation and cleanup (D1 to D4)

| Phase | Date | PR or commit | Summary of retired interfaces and changes |
| --- | --- | --- | --- |
| Phase 1 | 2026-11-23 | [PR #357](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/357) | Cleaned test layout and retired unused development scripts. |
| Phase 2 | 2026-11-23 | [PR #358](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/358) | Consolidated the C ABI to active entries, removing 2D/3D preparation v1–v11 precursors, Quick Design v1, 2D runs v1–v4, and 3D runs v1–v2. Also removed direct solves before 2D v6 / 3D v5, result query v2, `tpmshx_result_platform_info_v1`, and 14 unused `quick_*` C entries. |
| Phase 3A | 2026-11-23 | [PR #359](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/359) | Normalized result core to `float64` and `int32` labels under Result ABI 3 (`tpmshx_stage_input_v3`); retired `QuickProtocols` callbacks. |
| Phase 3B | 2026-11-24 | [PR #360](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/360) | Normalized preparation, geometry, field, and Quick Design APIs to `float64` and retired weak-scalar/`binary16` emulation. Also retired Quick raw-object host callbacks and full-pipeline test references while keeping pure-formula test oracles. |
| Phase 3C | 2026-11-24 | [PR #362](https://github.com/alexlu997/SJTU-TPMSHX-TM1/pull/362) | Flattened preparation and saved stage-run C structs (no nested `values` chains) and unified callbacks into `tpmshx_preparation_callbacks_v1`. Moved 2D/3D preparation families to clean `v1` names and standardized 2D saved ABI 5 and 3D saved ABI 3. |
| Phase 4 | 2026-11-24 | `c774b2c1` / `dbd34a53` | Retired Python direct full drivers (`NativeFull2DDriver`, `NativeFull3DDriver`, `prepared_*`), removed retired manifest nodes, and shortened the native CI path. |
| Phase 5 | 2026-11-24 | D4 docs | Rewrote current architecture, native-stages, C++ integration, and `python/README` docs to describe only active post-D4 interfaces; archived historical logs here. |

## Historical numerical qualification records

These historical records keep their original numbers and verdicts.
Later code repairs do not turn historical failures into passes.

- **Strict inlet resistance/moment smoke**: 60 configurations across 6 directions and 10 coefficient/boundary families validated local rows and ledgers, not global PDE grid order.
- **N3 layered protocol**: passed independent operator checks, `K = 0` analytic checks, and 84 accepted axial-order segments from 20 unique rows across 42 metrics. It also passed original absolute-error gates for 6 actual 64³ manufactured-solution groups. Rates from 32³ to 64³ stayed reported trends and did not show global second order for arbitrary 3D flows.
- **Original MMS populations (pre-N3)**: the original 6-group MMS population passed 0 of 6 groups. The original axial population passed 4 of 6 groups and failed 2.
- **N5 consumer populations**: 12 deliberately capped consumer requests returned successfully and passed 14 recorded-stage arithmetic audits. Of these, 0 of 12 product requests converged and 2 of 14 thermal stages converged. The separate normal-budget population passed all 3 complete steady consumers (2D main/fine, 3D `Nz = 1`, 3D `Nz > 1`) and all 4 thermal-stage audits.
- **Prior steady candidate**: passed 2 of 3 steady consumers and failed 2D main/fine gates.
- **Historical 24³ capped 3D case**: the historical Python/native comparison returned `converged = False`; cross-backend agreement did not establish convergence.
- **Legacy 83-case record**: stays a historical record and does not transfer experimental validation to later native ports.
