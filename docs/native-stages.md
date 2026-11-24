# Native stage interfaces

[中文](native-stages.zh-CN.md) | [English](native-stages.md)

## Active C ABI

Preparation ABI 3, Quick Design v2, 2D saved stage ABI 5, and 3D saved stage ABI 3 define the active computation C interfaces.
Result ABI 3 defines the independent evaluation interface.
All preparation and saved-run descriptors are flat structs with one top-level `(abi_version, struct_size)` header and no nested `values` chain.
All stage numeric buffers use `float64`, and zone labels use `int32`.
The libraries export no earlier version of these stage operations.

| Stage | Active C entries |
| --- | --- |
| 2D preparation (ABI 3) | `tpmshx_preparation_2d_{uniform,continuous,zoned,sigmoid}_{capacities,resolve_flow,prepare_case}_v1`, `tpmshx_preparation_2d_stripe_prepare_case_v1`, `tpmshx_query_inlet_properties_v2`, `tpmshx_preparation_sigmoid_lut_{create,release}_v7`, `tpmshx_preparation_df_experiment_scope_v1`, `tpmshx_preparation_collect_range_v1` |
| 3D preparation (ABI 3) | `tpmshx_preparation_3d_{continuous,spatial}_{capacities,resolve_flow,prepare_case}_v1` |
| Quick Design preparation | `tpmshx_prepare_quick_design_v2`, `tpmshx_quick_pressure_fractions_v2`, `tpmshx_quick_prepared_release_v2` |
| 2D stage run (saved ABI 5) | `tpmshx_stage_run_2d_abi_version`, `tpmshx_run_saved_case_2d_v5`, `tpmshx_stage_run_2d_{create,restore}_saved_v5`, `tpmshx_stage_run_2d_{advance_step,finish,phase,snapshot,take_result,release_run,release}_v1`, `tpmshx_stage_run_2d_{records,execution_view,get_capture,zone_temperatures,report}_v1`, `tpmshx_stage_borrow_mesh_v1`, `tpmshx_stage_port_windows_fit_2d_v1`, `tpmshx_stage_run_2d_check_experiment_v4` |
| 3D stage run (saved ABI 3, capture ABI 2) | `tpmshx_stage_run_3d_abi_version`, `tpmshx_stage_capture_3d_abi_version`, `tpmshx_run_saved_case_3d_v3`, `tpmshx_stage_run_3d_{create,restore}_saved_v3`, `tpmshx_stage_run_3d_{advance_step,finish,phase,snapshot,take_result,release_run,release}_v1`, `tpmshx_stage_run_3d_{records,execution_view,get_capture,report}_v1` |
| Raw stage-result queries | `tpmshx_full_{2,3}d_abi_version`, `tpmshx_full_2d_get_{energy_evidence,energy_update_scale,energy_effective_settings,model_enthalpy_evidence,last_closure_ranges,physical_heat_ledger,property_sampling,model_h_iterations,flow_methods}_v1`, `tpmshx_full_3d_get_{energy_evidence,energy_update_scale,energy_effective_settings,bootstrap_trace,model_enthalpy_evidence,last_closure_ranges,physical_heat_ledger,property_sampling,model_h_iterations,model_h_acceleration}_v1`, `tpmshx_run_state_release_v1` |
| Recipe identity and defaults | `tpmshx_temperature_algorithm_v1`, `tpmshx_model_h_algorithm_v1`, `tpmshx_energy_algorithm_version_v1`, `tpmshx_full_enthalpy_defaults_v1` |
| Quick Design run | `tpmshx_solver_abi_version`, `tpmshx_run_quick_design_v2`, `tpmshx_quick_run_ranges_v2`, `tpmshx_quick_run_temperature_algorithm_v1`, `tpmshx_quick_run_release_v1` |
| Result stage (ABI 3) | `tpmshx_result_stage_query_v3`, `tpmshx_result_stage_{evaluate,applicability,physical_balance,qualification,release}_v1` |

Each preparation family also exports its matching `*_flow_release_v1` and `*_case_release_v1` functions.
A library missing a required active entry is a deployment error; Python does not select an archived runtime or fallback route.
Saved-stage entries define the active C SDK, for Python and for C and C++ callers.
Raw stage-result queries read the `raw` result that a stage result borrows. Release only the stage result.
The solver library exports no direct full-solve, run-continuation, or per-driver C entry.
See [C++ migration history](history/cpp-migration-history.md) for retired `v1`–`v11` ABI records.

## Stage pipeline, ownership, and units

The C++ call sequence in `include/tpmshx/stages.hpp` is `prepare_case`, `run_case`, then `evaluate`.
Preparation computes physical grids, ports, fields, and model evidence.
The solver runs that prepared state, and the result library evaluates recorded evidence independently.

Store the prepared owner in a variable before you pass it to `saved_case`, `SavedCase2D`, or `SavedPreparedCase3D`.
Use `const auto saved = saved_case(prepared);` to keep the complete descriptor.
Pass `saved` when you start or restore a `Run2D` or `Run3D`.
A raw 2D or 3D C record copied from `saved` still borrows storage from the original descriptor.
Keep the prepared owner and original descriptor alive and unchanged until successful result transfer or run release.
Keep the callback functions and their context valid until you release the run.
The one-shot `run_case` accepts a temporary prepared owner or saved descriptor.
For example, `run_case(prepare_case(input, options), control)` transfers the result before the temporary owner expires.

- **Units**: design inputs (`cell_length_mm`, `wall_thickness_mm`) use mm; saved physical design fields use m. Keep the mm-to-m-to-mm order when forming transport and closure ratios. Heat uses W/m in 2D and W in 3D; mass flow uses kg/s; temperature uses K; pressure uses Pa(abs).
- **Array layout**: requested and actual grid counts stay distinct fields. Physical 2D fields use shape `(nx, ny)` in C order; 3D fields use `(nx, ny, nz)` in C order; flow fields use `(cross, stream)` order per side.
- **Single-owner release**: every owned output has one outer `owner` pointer; nested views have null owners. Release each owned result through the library that created it after the last view use. Scalar-only queries (`tpmshx_query_inlet_properties_v2`, `tpmshx_quick_pressure_fractions_v2`) return values and need no release.
- **Disjoint buffers**: output, failure, diagnostic, and error buffers must not overlap inputs, callbacks, or any live view owned by a result. Overlapping calls return invalid status without mutating result or diagnostic storage.
- **Library boundaries**: preparation and solver link their separate locked CoolProp static libraries; the result library links no preparation, solver, CoolProp, or Qt code.
- **Result ABI 3 queries**: `tpmshx_result_stage_query_v3` accepts flat `tpmshx_stage_input_v3` with borrowed `float64` arrays, `int32` labels, and raw C-string mode/unit labels. It delivers floating-point events before returning, and the Python adapter emits `RuntimeWarning` for divide-by-zero, overflow, and invalid values.

After a completed 2D or 3D stage run, copy evidence from the live result before releasing it:

- `tpmshx_stage_run_{2d,3d}_records_v1`: property samples, last closure ranges, temperature model records, energy relations, SIMPLE stop reasons, and 3D drag summaries.
- `tpmshx_stage_run_{2d,3d}_execution_view_v1`: applied thermal controls, energy evidence, update scale, model-h records, and sCO2 runtime notices.
- `tpmshx_stage_run_{2d,3d}_report_v1`: scalar execution report containing resolved grid, fluids, executed states, property samples, and model-h balances.

Python combines case notices and run `nu-evidence` warnings into `scope_notes` in order without duplicates.
The independent result stage decides metric availability and qualification.

## Inlet-property query

`InletPropertyQuery` and `query_inlet_properties` in `stages.hpp` expose the scalar inlet-property combination through `tpmshx_query_inlet_properties_v2` in `preparation_case_c_api.h`.
Pass topology, `L` and `t` in mm, inlet velocity, temperature, pressure, hydraulic diameter in m, single-stream porosity, and optional sCO2 Nu selection.
The query calculates no geometry, grid, ports, or solver fields.
It evaluates four-fluid properties, Nu, and fixed CFD drag in their production order; `exact_co2_drag` selects fixed CO2 drag factors independently of supplied geometry.

| Index | Value | Unit |
| --- | --- | --- |
| 0 | `rho` | kg/m³ |
| 1 | `mu` | Pa·s |
| 2 | `k_f` | W/(m·K) |
| 3 | `cp` | J/(kg·K) |
| 4 | `Pr` | dimensionless |
| 5 | `Re` | dimensionless |
| 6 | `Nu` | dimensionless |
| 7 | `K_df` | m² |
| 8 | `cF_df` | 1/m |
| 9 | `dP_per_L` | Pa/m |
| 10 | `H_sf` | W/(m²·K) |
| 11 | `K_ff` | W/(m·K) |

`tpmshx_preparation_inlet_query_result_v1` (`abi_version = 1`, `struct_size = sizeof(tpmshx_preparation_inlet_query_result_v1)`) returns 12 `float64` values (`double values[12]`).
This query allocates no owner and requires no release call.
Pass optional `tpmshx_preparation_callbacks_v1` with null cache hooks and `validate_grid_stage = 0` to record range, notice, and floating-point events synchronously.
Standalone Python `tpms_calc.compute` calls this entry through `python/cpp_interface/inlet_properties.py`, keeping geometry selection, shared caches, per-call `K_ss` lookup, and warning policy.

## Spatial total mass flow

Preparation ABI 3 provides `capacities`, `resolve_flow`, and `prepare_case` entries across all four 2D geometry families (`uniform`, `continuous`, `zoned`, `sigmoid`).
`tpmshx_preparation_2d_stripe_prepare_case_v1` also returns per-stripe A-side hydraulic radius:

- **Uniform (`FlowInput2D`)**: both topologies and all 16 ordered air/water/sCO2/CO2 fluid pairs, with CFD or eligible experimental D-F.
- **Continuous XY (`ContinuousInput2D`)**: takes spline controls (`n_ctrl_x`, `n_ctrl_y`, order 1–3, `symmetric_y`, bounds, and `L`/`t` decisions in mm) sampled at physical cell centres. It returns pore porosity, area density, hydraulic diameter, fluid conductivities, and full local `(cross, stream)` K/cF fields. Supports all 16 fluid pairs in CFD mode, CO2/CO2 fixed factors, and Shanghai Gyroid air-A/water-B continuous transfer in experimental mode.
- **Discrete zones (`ZonedFlowInput2D`)**: air/air stripes (`axis = 0` or `1`, sorted intervals) and rectangles (`axis = 2`, input order) with CFD drag. It projects raw `L`/`t` with transverse widths before predicting row D-F. It applies Gaussian smoothing (`sigma = 2`, `radius = 8`, reflect) to design porosity, conductivities, and volumetric transfer fields while keeping thermal geometry unsmoothed.
- **Sigmoid fields (`SigmoidFlowInput2D`)**: air/air CFD drag with 36 interleaved `L`/`t` controls and inlet/outlet transitions, without Gaussian smoothing. `build_sigmoid_lut` (`tpmshx_preparation_sigmoid_lut_create_v7` / `release_v7`) builds a reusable native 41×31 LUT at voxel resolution 256 from raw geometry.

Total mass-flow targets use kg/s and require a positive physical depth in m; 2D solver fields keep their per-unit-depth basis.
`capacities` integrates inlet design porosity, opening profile, physical widths, inlet density, and physical depth without evaluating obsolete speeds or Nu.
`resolve_flow` divides selected targets by capacities and validates resolved speeds; without targets, it copies the input without physical preparation.
`prepare_case` builds the physical grid and geometry once, resolves speeds before transfer calculations, and separates preliminary flow records (`flow.evidence`) from final preparation records (`prepared`).
`tpmshx_preparation_df_experiment_scope_v1` validates experimental D-F layout eligibility and HX campaign domain matching for both 2D and 3D preparation.

## Spatial host cache interface

All 2D and 3D preparation entries accept one unified flat callback struct: `tpmshx_preparation_callbacks_v1` (`PreparationCallbacks` in `stages.hpp`).
Initialize `abi_version = TPMSHX_PREPARATION_CASE_ABI_VERSION` (1) and `struct_size = sizeof(tpmshx_preparation_callbacks_v1)`.

- **Event and observation hooks**: `event`, `observe_range`, and `observe_notice` report diagnostics, range records, and notices (including geometry extrapolation reasons) synchronously on the caller thread.
- **Host validation hooks**: `validate_host_input` and `validate_grid_stage` (`0` or `1`) keep Python object-check order without numerical values. `validate_grid_stage = 1` requires non-null `validate_host_input`.
- **Cache hooks (`action = 0` lookup, `action = 1` publish)**: `geometry_cache`, `inlet_cache`, `geometry_cache_at`, `inlet_cache_at`, and `sigmoid_lut_cache` exchange completed values with host caches. On a hit (`hit = 1`), the host returns borrowed read-only views that stay valid until the stage call returns. On a miss (`hit = 0`), C++ computes values and publishes read-only views that the host copies before callback return.
- **Family hook rules**: untyped (`geometry_cache`, `inlet_cache`) and keyed (`geometry_cache_at`, `inlet_cache_at`, `sigmoid_lut_cache`) hooks cannot be combined. Uniform and continuous 2D accept untyped hooks only; zoned, sigmoid, and stripe 2D accept keyed hooks only. 3D accepts `geometry_cache_at` and `inlet_cache_at` only and rejects `sigmoid_lut_cache` and `validate_grid_stage != 0`.
- **Isolation rules**: callbacks do no numerical preparation. Returned views must not overlap output, failure, or error storage. A nonzero callback return stops the stage immediately so Python can re-raise its saved exception.

`python/cpp_interface/preparation_host.py` and `native_preparation.py` connect these hooks to the shared 32,768-entry geometry cache and 4,096-entry inlet-property cache in `python/physical_models/preparation_cache.py`.
Python keeps disk/memory LUT storage; on a LUT miss, C++ builds the native 41×31 table at voxel resolution 256.
The [spatial cache example](../examples/cpp/prepare_spatial_cache_2d.cpp) tests these typed callbacks outside Python.

## Existing offset geometry

Nonzero level-set offset (`delta_levelset != 0`) is supported at prescribed inlet speeds for uniform air/water pairs and air/air uniform, stripe, rectangle, and sigmoid modes.
Continuous fields, CO2/sCO2 fluids, experimental D-F models, capacity queries, and prescribed total mass flow reject nonzero `delta_levelset`.

When `delta_levelset != 0`, the N128 asymmetric geometry core computes `split_a` and sets `thermal.have_side_geometry = 1`.
It fills two four-value `side_geometry` tuples: side area density, side hydraulic diameter, and their nominal reference values.
Nominal thermal-side geometry stays separate from design porosity, solid conductivity, and cell thermal fields; the stage does not calculate a separate offset model per zone.
The [offset example](../examples/cpp/offset_2d.cpp) prepares, runs, and evaluates uniform, stripe, rectangle, and sigmoid offset cases end to end.

## Uniform 3D preparation

`preparation_case_3d_c_api.h` provides two flat 3D preparation families covering all supported 3D geometries:

- **Spatial and uniform 3D (`SpatialInput3D`, `tpmshx_preparation_3d_spatial_{capacities,resolve_flow,prepare_case}_v1`)**: `geometry_mode = 0` prepares uniform 3D cases (both topologies, all 16 fluid pairs, CFD or eligible experimental D-F). `geometry_mode = 2` prepares XY grid rectangles with optional global `delta_levelset` (air/water CFD scope). Rectangles use domain fractions, later rectangles replace earlier matches, and uncovered cells use nominal `L`/`t`. Gaussian smoothing applies to `L` and `t` in grid-index units, and fields extrude along z.
- **Continuous 3D (`ContinuousInput3D`, `tpmshx_preparation_3d_continuous_{capacities,resolve_flow,prepare_case}_v1`)**: `have_ctrl_z = 0` prepares XY extrusion controls. `have_ctrl_z = 1` prepares true XYZ controls (`L` values then `t` values, z fastest), sampled at physical cell centres with optional y symmetry.

`CaseInput3D` requires three positive lengths, three grid counts (`Nz >= 2`), active ports on both sides, and an explicit cell cap.
The C++ default cap is 2,000,000 cells; memory checks near that cap and real 3D BO stay separate acceptance gates.
The host resolves configuration and environment limits before calling C++.
All six flow directions (`±x`, `±y`, `±z`), full faces, partial ports, optional second transverse windows, uniform grids, and `port_wall_refine` grids are supported.
Physical fields have `(nx, ny, nz)` C-order shape; opening masks use `(cross1, cross2)` order; each side records its axis permutation and reverse flag without reversing physical widths.

Side porosity is already split in the prepared output (do not halve it again).
For nonzero `delta_levelset`, local total porosity is multiplied by each side's global split fraction, and nominal thermal side/reference tuples are stored separately.
Returned K/cF fields keep unscaled CFD values while side evidence records CO2 or experimental application factors separately.
Capacity integrates each side's actual inlet porosity, open area, and density; complete fixed-flow preparation builds geometry once and resolves speeds before speed/model checks.
Air-field scalar range observations keep at most eight selected samples per side (original notices, extrema, and last sample) while full raw-array records keep all cells.
`python/preprocess/three_d/preparation.py` assembles immutable `CaseData` from native views and releases the native owner through `preparation_host.py`.

## Run continuation

`stage_run_c_api.h` connects flat `SavedCase2D` (`tpmshx_stage_saved_case_2d_v5`, ABI 5) and `RunRequest2D` (`tpmshx_stage_run_request_2d_v4`) to `Full2DRun`.
Confirm `tpmshx_stage_run_2d_abi_version() == 5` before calling any 2D saved-stage entry.
`SavedCase2D` borrows a validated prepared view, flow grids, design fields, model references, nominal thermal-side tuples, and experimental settings without preparing the case again.

- **One-shot run**: `tpmshx_run_saved_case_2d_v5` runs to completion in C++ and transfers an owned `tpmshx_stage_run_result_2d_v1` (release with `tpmshx_stage_run_2d_release_v1`).
- **Step and checkpoint lifecycle**: `tpmshx_stage_run_2d_create_saved_v5`, `restore_saved_v5`, `advance_step_v1`, `finish_v1`, `phase_v1`, `snapshot_v1`, `take_result_v1`, and `release_run_v1`. Snapshots (`tpmshx_run_state_v1`, release with `tpmshx_run_state_release_v1`) own independent storage. Restoration requires the exact same build, prepared inputs, and numerical controls; only positive `cpu_threads` can change.
- **Validation and capture helpers**: `tpmshx_stage_borrow_mesh_v1` validates and borrows aligned `float64` widths and thermal geometry. `tpmshx_stage_port_windows_fit_2d_v1` validates cross-axis port windows, and `tpmshx_stage_run_2d_check_experiment_v4` validates experimental D-F applicability. `tpmshx_stage_run_2d_get_capture_v1` (`capture_summary`) returns copied thermal, Nu, duty, and pressure-clip scalars. `tpmshx_stage_run_2d_zone_temperatures_v1` summarizes main-grid zone temperatures without loading the result library.

A null `energy` pointer in `RunRequest2D` selects the default T-SOU recipe (`temperature_sou`, `1e-8 K` from `model_parameters_v1.json`).
Optional energy controls cannot be combined with `explicit_energy` or active `model_h` controls.
Cancellation returns status 6 and cannot publish a successful stage result; status 4 reports a solver envelope failure.

## Native 3D execution

`stage_run_3d_c_api.h` connects flat `SavedCase3D` (`tpmshx_stage_saved_case_3d_v3`, ABI 3) and `RunRequest3D` (`tpmshx_stage_run_request_3d_v1`) to `Full3DRun`.
Confirm `tpmshx_stage_run_3d_abi_version() == 3` and `tpmshx_stage_capture_3d_abi_version() == 2` before calling any 3D saved-stage entry.
`SavedCase3D` validates physical domain lengths, axis maps, port masks, model resources, and cell design fields before the first step without calling raw preparation.

- **One-shot run**: `tpmshx_run_saved_case_3d_v3` advances to completion in C++ and transfers an owned `tpmshx_stage_run_result_3d_v1` (release with `tpmshx_stage_run_3d_release_v1`).
- **Step and checkpoint lifecycle**: `tpmshx_stage_run_3d_create_saved_v3`, `restore_saved_v3`, `advance_step_v1`, `finish_v1`, `phase_v1`, `snapshot_v1`, `take_result_v1`, and `release_run_v1`. Safe checkpoint phases are 1, 2, 6, 7, 8, 9, and 10 in thermal-first order. Restore requires the same build, prepared inputs, and numerical controls; positive `cpu_threads` can change.
- **Control defaults**: initial and warm SIMPLE budgets default to 2,000 and 600; thermal budget defaults to 20,000. Supply an explicit SIMPLE budget to override both flow budgets (for example 50,000 for full validation). Model-h and EOS control conflicts are rejected before flow.
- **Result ownership and evaluation**: the transferred result owns `raw`, generic `evidence`, and `evaluation` (`tpmshx_stage_input_v3`), which passes directly to `tpmshx_result_stage_query_v3`. Final SIMPLE fields supply pressure and display; the last completed thermal state supplies mass, thermal pressure, and energy (W and kg/s). `tpmshx_stage_run_3d_get_capture_v1` (`capture_summary(result, include_audit)`) returns cell counts, heat-source sum, pressure-clip count, Nu statistics, and optional audit outlet arrays.

C status codes are 0 (result transferred), 1 (invalid input), 2 (water state error), 3 (arithmetic error), and 4 (native failure).
Status 0 does not imply convergence.
A cancelled result keeps raw diagnostics with `raw.stop = 2` and no completed evaluation evidence.
Python full 3D execution binds this lifecycle exclusively in `python/cpp_interface/full_3d_stage.py`.

## Quick Design stage

`quick_design_stage_c_api.h` provides Quick Design preparation v2 and run v2 as flat `float64` C interfaces.
Quick Design is a prescribed-flow LTNE sizing approximation (`physical_validation=not_established`), not a SIMPLE solve.

### Preparation v2 and pressure query

`tpmshx_prepare_quick_design_v2` and `tpmshx_quick_pressure_fractions_v2` accept `tpmshx_quick_input_v2` (`abi_version = 2`, exact `struct_size`) with 13 `float64` scalar slots (`TPMSHX_QUICK_VALUE_COUNT`).
These slots hold cell length (mm), wall thickness (mm), span (m), length (m), height (m), solid conductivity (W/(m·K)), and tolerance.
The remaining slots hold two mass flows (kg/s), two temperatures (K), and two pressures (Pa(abs)).
Setting `have_height = 0` uses span as height.
Text fields (`topology`, `arrangement`, `property_mode`, `fluids[2]`) use explicit byte lengths.
Default grid counts (`(60, 40, 1)` crossflow, `(60, 1, 2)` counterflow), conductivity (`16 W/(m·K)`), tolerance (`1e-5`), and geometry resolution (`128`) come from `model_parameters_v1.json` and generated C++ constants.
Absent counterflow `q_relative_tolerance` and `chunk_iterations` stay marked absent (`0` in C, `None` in `CaseData`).

- Full preparation validates warm-start inputs, labels, positive scalars, shape, geometry/material, grids, inlet properties, cross-sections, analytical D-F pressure fractions, and SI design fields. Release `tpmshx_quick_prepared_v2` with `tpmshx_quick_prepared_release_v2`.
- `tpmshx_quick_pressure_fractions_v2` skips thermal grids and design-field arrays, treats every non-`cross` arrangement as counterflow, and returns `tpmshx_quick_pressure_v2` by value (no release needed).
- Both outputs record ordered `floating_events[4]` (A properties, A Prandtl, B properties, B Prandtl) and fitted empirical property `ranges`.
- Optional `tpmshx_quick_callbacks_v2` provides only `geometry_cache` and `eos_cache` hooks (lookup `action = 0`, publish `action = 1`; nonzero return stops with status 20). Callbacks transport completed values only and never execute numerical code.

### Prepared execution and evaluation

`tpmshx_run_quick_design_v2` runs const (one pass) or mean (two passes) thermal iterations on supplied prepared fields with fixed analytical pressure fractions.
The returned `tpmshx_quick_run_result_v1` (release with `tpmshx_quick_run_release_v1`) owns all 15 fields, physical grid widths, pressure evidence, final-pass scalars, and pass range records (`tpmshx_quick_run_ranges_v2`).
`tpmshx_quick_run_temperature_algorithm_v1` returns the executed temperature recipe name.
Cancellation returns status 6 and publishes no result.
Python binds preparation in `python/cpp_interface/_native_quick_prepare.py`, execution in `python/cpp_interface/quick_design.py`, and Quick Design metrics through Result ABI 3 (`tpmshx_result_stage_query_v3`).

## Build, install, and SDK examples

The root CMake project builds and installs the stage SDK from prepared local dependencies without fetching sources or replacing published Python runtime libraries.
First generate the two model headers with the interpreter from `.venv-path`:

```sh
"$PYTHON" -m engineering.scripts.generate_native_model_coefficients \
  --output .cache/stages-sdk/generated/tpmshx/model_coefficients.hpp \
  --df-output .cache/stages-sdk/generated/tpmshx/preparation_df_data.hpp
```

Configure, build, and install with locked CMake on macOS (use `-A x64` and `Release/CoolProp.lib` for both CoolProp arguments on Windows):

```sh
"$CMAKE" -S . -B .cache/stages-sdk/build \
  -DTPMSHX_NATIVE_DEPS_ROOT="$PWD/.cache/native-deps" \
  -DTPMSHX_MODEL_INCLUDE_DIR="$PWD/.cache/stages-sdk/generated" \
  -DTPMSHX_PREPARATION_COOLPROP_LIBRARY="$PWD/.cache/native-deps/build/coolprop-preparation-macos-arm64/libCoolProp.a" \
  -DTPMSHX_SOLVER_COOLPROP_LIBRARY="$PWD/.cache/native-deps/build/coolprop-macos-arm64/libCoolProp.a" \
  -DCMAKE_INSTALL_PREFIX="$PWD/.cache/stages-sdk/install"
"$CMAKE" --build .cache/stages-sdk/build --config Release --parallel 1
"$CMAKE" --install .cache/stages-sdk/build --config Release
```

Pass `-DTPMSHX_COMPONENTS=result` for an independent result-only SDK (the only supported component on Linux x86_64).
External C++ projects consume the installed package with CMake:

```cmake
find_package(tpmshx CONFIG REQUIRED COMPONENTS result)
target_link_libraries(my_program PRIVATE tpmshx::result)
```

Build and test the installed SDK examples under `examples/cpp/` (`air_2d.cpp`, `uniform_2d.cpp`, `continuous_2d.cpp`, `offset_2d.cpp`, `resume_2d.cpp`, `prepare_spatial_cache_2d.cpp`, `run_3d.cpp`, `prepare_continuous_3d.cpp`, `prepare_spatial_3d.cpp`, `quick_design.cpp`, `prepare_quick_design.cpp`, `result_client.cpp`):

```sh
"$CMAKE" -S examples/cpp -B .cache/stages-sdk/examples \
  -DCMAKE_PREFIX_PATH="$PWD/.cache/stages-sdk/install"
"$CMAKE" --build .cache/stages-sdk/examples --config Release
"$CTEST" --test-dir .cache/stages-sdk/examples -C Release --output-on-failure
```

To run the automated out-of-tree SDK check after a dependency build:

```sh
"$PYTHON" engineering/scripts/build_native_dependencies.py check-stages
```

Add `--python-lock` for BO environments, or `--component result --python-lock engineering/requirements/postprocess.txt` on Linux.
The SDK check validates installed C/C++ interfaces; Python integration, checkpoint recovery, cell-cap memory checks, real 3D BO, and desktop acceptance remain separate gates.
