<a id="主体源码sjtu_tpmshx"></a>

# Python source and public entries

[中文](README.md) | [English](README.en.md)

This directory contains the public `sjtu_tpmshx` package. Existing scripts use the same import names. See the [project README](../README.en.md#first-run) for setup, public examples and startup steps.
Run commands from the repository root. The [architecture](../docs/architecture.md) defines module boundaries and physical constraints.

## Four computation entries

| File | Public entry | Responsibility |
| --- | --- | --- |
| [python/compute.py](compute.py) | `compute` | Main computation entry. Validate configuration and organize three stages. Return CaseData, FieldResult and PerformanceResult. |
| [python/preprocess/api.py](preprocess/api.py) | `prepare_case` | Prepare the actual grid, boundaries, design fields, model resources and portable execution inputs. |
| [python/solvers/api.py](solvers/api.py) | `run_case` | Consume CaseData. Run the C++ numerical solver through Python bindings. Return native fields and run status. |
| [python/postprocess/api.py](postprocess/api.py) | `evaluate` | Organize metric evaluation and qualification from FieldResult. Do not run the solver again. |

```text
compute -> preprocess.api.prepare_case -> CaseData -> solvers.api.run_case -> FieldResult
                                                                       -> postprocess.api.evaluate -> PerformanceResult
```

`compute` also manages stage progress, cancellation, elapsed times and warnings.
`python/postprocess/api.py` sends full 2D/3D and Quick Design evaluation and independent queries to the native result stage.
`python/cpp_interface/_native_result_stage.py` adapts evidence, NumPy events and returned objects. `python/postprocess/export.py` exports results.
Current full computations support rectangular 2D and cuboid 3D domains.
See the [examples](../examples/three_module/) and [data contract](../docs/contracts/three_module_v1/README.md) for public inputs and file transport.
The [capabilities](../docs/capabilities.en.md) list approximation modes and extension status.

The [native stage SDK](../docs/native-stages.md) provides a separate C++ call sequence.
Its initial complete path supports uniform symmetric 2D air/air with prescribed velocity.
Preparation v2 adds all 16 ordered air/water/sCO2/CO2 pairs for uniform symmetric 2D geometry and prescribed velocity.
Preparation v3 adds independent capacity, inlet-flow resolution and complete preparation for uniform 2D total mass flow.
It reuses the physical inlet grid and keeps preliminary records separate from final preparation evidence.
Run v2 supports uniform four-fluid preparation, including resolved total mass flow.
Preparation v4 supplies continuous XY fields and full local drag to run v3. Run v1 keeps its air/air CFD scope.
Preparation v5 adds raw air/air stripes and rectangles at prescribed velocity, CFD drag and zero delta.
Its separate thermal geometry and row drag preserve the existing discrete rules.
Preparation v6 adds raw air/air sigmoid controls and a reusable native LUT with production-resolution cold construction.
It retains separate thermal geometry and row drag without discrete smoothing.

Preparation v8 adds capacity, flow resolution and complete fixed-flow preparation for these air/air spatial inputs.
It retains the physical grid and geometry, resolves speeds before transfer calculations, and owns copied regions, controls and LUTs.
Typed domain/port inputs and separate preliminary evidence remain explicit.
Preparation v9 connects symmetric spatial Python preparation, capacity and resolution through typed host-cache hooks.
`python/cpp_interface/preparation_host.py` shares cache and evidence transport; misses calculate in the native stage.
Python retains LUT storage. Native code builds missing tables at the original geometry checkpoint.

Preparation v10 adds the existing nonzero-delta uniform air/water and air/air spatial modes at prescribed speed.
It carries nominal thermal-side tuples separately from design and cell thermal geometry, with the existing split and N128 geometry calculation.
Continuous fields, CO2/sCO2, experimental models and total mass flow keep their existing limits. Earlier C layouts and scopes remain unchanged.
Complete continuous XY and stripe preparation use v11 when available.
The preparation library returns the pore porosity or the A-side hydraulic radius for each stripe. The adapter uses the geometry library with supported older preparation binaries.
Complete uniform, rectangle and sigmoid cases use v10. Uniform and continuous XY capacity and resolution use v7 with v3 and v4 results, respectively.
Spatial capacity and resolution use v10 with v9 result views and releases.
Public ZoneConfig and sigmoid combination queries retain standalone consumers until separate migration passes.
They keep supplied properties and custom sigmoid controls.
`python/cpp_interface/native_preparation.py` is the native adapter. Its replaced Python preparation sequence and row D-F projection are retired.
Independent preparation references remain under `development/tests`; `python/physical_models/zone_units.py` owns saved zone-unit conversion.
CaseData and saved-file contracts stay unchanged. Native failures propagate without another preparation route.

Separate 3D preparation v1 accepts raw symmetric uniform inputs at prescribed speeds for all 16 ordered fluid pairs.
It retains physical grids, typed ports, six directions, the cell cap and existing CFD/experimental limits.
Side porosity is already split; base K/cF fields and side application factors remain separate.
Separate 3D flow v2 adds capacity queries, total-flow resolution and complete preparation with one geometry calculation.
Continuous 3D v3 prepares raw XY extrusion and XYZ controls, with capacity queries and total-flow resolution.
Spatial v4 adds XY grid rectangles and existing global offset rules with separate side porosity and thermal geometry.
Native 3D run/capture connects those prepared families and saved views to the same `Full3DRun` lifecycle.
The result owns complete raw fields and evaluation evidence after preparation and run release.
Python full 3D execution uses this saved-input lifecycle through `full_3d_stage.py`.
`full_3d_stage.py` publishes the current result. `full_3d_capture.py` decodes earlier results.
Native capture supplies application reductions and optional audit outlet weights.
Python 3D preparation uses host v5 with shared typed cache callbacks.
Air-field scalar observations select at most eight values per side; full raw-array records keep all cells.
`python/preprocess/three_d/preparation.py` assembles immutable CaseData from the owned native result.
The replaced `shared/models/grid_3d.py` and `asym_split.py` helpers are retired.
`tests/python/preparation_3d_reference.py` keeps the independent numerical reference.
Memory use near the cell cap and real 3D BO need separate acceptance.

2D execution uses the selected library's complete saved native lifecycle, including checkpoints and complete result capture.
Saved descriptor v2 adds nominal side geometry and accepts discrete and sigmoid fields; saved v1 remains unchanged.
Python selects v2 first, then v1 for symmetric uniform or continuous inputs. Archived libraries without the applicable protocol retain their existing interface.

Current public saved 2D/3D runs copy applicability groups and required records before the native result is released.
`python/solvers/applicability_evidence.py` keeps saved inlet fields and scalar types in native order, with constraints from C when present.
The public API publishes these groups without repeating classification.
Python combines complete case notices and run `nu-evidence` warning records into `scope_notes`; independent C++ stages keep their native notes.
Direct and archived-runtime paths retain `capture_applicability`. Capture failures do not select that path.
`python/solvers/execution_record.py` publishes the completed native method and sampling records.
The native result stage decides qualification.

Standalone `shared/models/tpms_calc.compute` uses the same native inlet-property combination as complete preparation.
Python keeps geometry selection, shared caches, mutable result copies, the per-call K_ss query, object conversion and warning policy.
`python/cpp_interface/inlet_properties.py` transports the twelve typed query values and shares range observations with the preparation adapters.
The [inlet-property query](../docs/native-stages.md#inlet-property-query) exposes the same calculation to C and C++ callers without a grid or solver.

Quick Design preparation v2 accepts typed raw inputs and provides a separate pressure query without thermal grid or design-field arrays.
Python uses `_native_quick_prepare.py` for fixed host protocols and copies native output into CaseData.
The replaced `shared/models/quick_design.py` is removed. Defaults come from `python/model_configs/model_parameters_v1.json` and generated C++ constants.
The native-double v1 contract and the existing LTNE model remain available.
Python execution calls the native run stage with saved prepared data. The native result stage owns Quick Design metrics.
Preparation and result host operations keep the existing Python type, cache, warning and event protocols.
The Python entries above retain all current modes.

## Edit numerical functions

Use this table to find the C++ owner of a numerical rule.
`python/data_types/` defines public input/output contracts. Python bindings pass types and arrays.

| Responsibility | C++ files and representative functions |
| --- | --- |
| Cell geometry, chi and solid conductivity | [geometry.cpp](../geometry/geometry.cpp): `standard_geometry`, `solid_conductivity`; [asym_geometry.cpp](../geometry/asym_geometry.cpp) |
| Grids and physical ports | [grid.cpp](../geometry/grid.cpp): `uniform`, `wall`; [ports.cpp](../geometry/ports.cpp): `port_overlap_1d`, `port_fractions_1d` |
| Continuous fields, sigmoid, LUTs and zones | [field_continuous.cpp](../geometry/field_continuous.cpp); [field_sigmoid.cpp](../geometry/field_sigmoid.cpp); [field_lut.cpp](../geometry/field_lut.cpp); [zones.cpp](../geometry/zones.cpp) |
| Properties and Nu closures | [fluid_properties.cpp](../numerics/fluid_properties.cpp): `PropertyEvaluator::evaluate`, `fluid_nusselt`; [preparation_properties.cpp](../preprocess/preparation_properties.cpp) |
| Scalar inlet-property combination | [preparation_case.cpp](../preprocess/preparation_case.cpp): `query_inlet_properties`, `inlet_property_values`; [preparation_case_c_api.cpp](../preprocess/preparation_case_c_api.cpp): `tpmshx_query_inlet_properties_v1` |
| Fixed DF, corrections, projection and prescribed flow | [preparation_df.cpp](../preprocess/preparation_df.cpp): `fixed_df`; [preparation_df_corrections.cpp](../preprocess/preparation_df_corrections.cpp); [preparation_df_projection.cpp](../preprocess/preparation_df_projection.cpp); [preparation_flow.cpp](../preprocess/preparation_flow.cpp): `inlet_capacity_2d`, `inlet_speed` |
| Full 2D/3D and Quick Design | [full_2d.cpp](../solver/full_2d.cpp): `solve_full_2d`; [full_3d.cpp](../solver/full_3d.cpp): `solve_full_3d`; [quick_design_driver.cpp](../solver/quick_design_driver.cpp): `solve_quick_design` |
| Metrics, physical balances, zone statistics and checks | [result_metrics.cpp](../postprocess/result_metrics.cpp): `pressure_face`, `boundary_enthalpy_duty`; [result_balance.cpp](../postprocess/result_balance.cpp): `mass`, `energy`, `zone_std`; [result_checks.cpp](../postprocess/result_checks.cpp): `collect_range`, `strict_certificate` |
| Complete stage preparation and execution | [preparation_case.cpp](../preprocess/preparation_case.cpp): `prepare_case_2d`, `prepare_zoned_flow_case_2d`, `prepare_thermal_sides`, `prepare_case_3d`; [stage_run.cpp](../solver/stage_run.cpp): `tpmshx_run_case_2d_v1/v2/v3`, `tpmshx_stage_run_2d_create_v1/create_saved_v1/create_saved_v2`; [stage_capture_2d.cpp](../solver/stage_capture_2d.cpp): `tpmshx_stage_run_2d_get_capture_v1`, `tpmshx_stage_run_2d_records_v1`; [stage_run_3d.cpp](../solver/stage_run_3d.cpp): `tpmshx_run_case_3d_v1`; [stage_capture_3d.cpp](../solver/stage_capture_3d.cpp): `capture_3d`, `tpmshx_stage_run_3d_get_capture_v1`, `tpmshx_stage_run_3d_records_v1` |
| Quick Design stage preparation and execution | [quick_design_prepare_v2.cpp](../preprocess/quick_design_prepare_v2.cpp): `tpmshx_prepare_quick_design_v2`, `tpmshx_quick_pressure_fractions_v2`; [quick_design_prepare.cpp](../preprocess/quick_design_prepare.cpp): kept v1; [quick_design_run.cpp](../solver/quick_design_run.cpp): `tpmshx_run_quick_design_v2` |
| Stage evaluation and qualification | [result_stage.cpp](../postprocess/result_stage.cpp): `evaluate`, `evaluate_applicability`, `evaluate_physical_balance`, `evaluate_qualification` |

Geometry uses geometry ABI 1 and field ABI 2. The preparation library keeps its ABI 1 loader and adds the versioned Quick preparation v2 contract. Results use result ABI 2.
Start at the drivers above for SIMPLE, pressure and energy implementations. See [C++ interfaces](../docs/cpp-migration.md) for their boundaries.
Python keeps configuration, DTOs, I/O, caches, NumPy event handling, the GUI, searches and offline research.
The native result stage owns full evaluation and qualification. Python preserves source data and host notices, and interprets execution records.
See [retained Python responsibilities](../docs/architecture.md#retained-python-responsibilities) for their exact scope.

### Rebuild after a change

After changing C++ functions or compiled model data, pass the [current environment checks](../README.en.md#first-run).
Rebuild and publish the four libraries from the repository root. Then restart the process.
The commands below use the base lock. If `.venv-path` selects a BO environment, use `bo-macos.txt` or `bo-windows.txt` from `engineering/requirements/`.
For a new build cache, run `fetch` as shown in [First run](../README.en.md#first-run).
Use the same cache for the commands below.

macOS:

```sh
PYTHON="$(head -n 1 .venv-path)"
"$PYTHON" engineering/scripts/build_native_dependencies.py publish --python-lock engineering/requirements/base.txt
```

Windows (PowerShell):

```powershell
$tm1Python = Get-Content .venv-path -TotalCount 1
& $tm1Python engineering/scripts/build_native_dependencies.py publish --python-lock engineering/requirements/base.txt
```

See [C++ builds](../docs/cpp-migration.md#native-geometry-core) for separate component publication and retained checkpoint runtimes.

<a id="三模块主线"></a>
<a id="支撑模块与应用入口"></a>

## Python directories

| Directory | Responsibility and boundary |
| --- | --- |
| [preprocess](preprocess/) | Preprocessing and explicit offline model preparation. |
| [solvers](solvers/) | Solver API, prepared-data adapters and Python C++ bindings. The [solver directory](../solver/) contains the C++ implementation. |
| [postprocess](postprocess/) | Metrics, physical audits, qualification and exports from recorded results. |
| [data_types](data_types/) | Configuration, prepared cases, fields, and performance results. |
| [file_io](file_io/) | Read and write case, result, metric and checkpoint files. |
| [run_control](run_control/) | Cancellation, progress, warnings, environment and runtime selection. |
| [physical_models](physical_models/) and [model_configs](model_configs/) | Model queries and their versioned parameters. |
| [cpp_interface](cpp_interface/) | Call the compiled libraries. [solver_library](cpp_interface/solver_library/) also supports direct calls and saved native runs. |
| [applications](applications/) | [GUI](applications/gui/), [CLI](applications/cli/), [Quick Design](applications/design/), [Bayesian optimization](applications/optimization/) and [run recovery](applications/execution/recovery.py). |
| [development](development/) | Validation, diagnostics and examples for developers. Automated tests are in [tests/python](../tests/python/). |

GUI implementation is in [python/applications/gui/main.py](applications/gui/main.py). CLI implementation is in [python/applications/cli/main.py](applications/cli/main.py).
Package-level [python/main.py](main.py), [python/cli.py](cli.py) and [python/desktop.py](desktop.py) keep short startup entries.
Use `python -m sjtu_tpmshx.main` or `python -m sjtu_tpmshx.cli`. Computation code calls the four entries above directly.

Root [engineering](../engineering/) holds scripts for builds and checks, packaging configuration and requirements locks.
[docs/contracts](../docs/contracts/) holds public file contracts. `.github/workflows/` holds CI configuration.
The [repository index](../docs/README.en.md) describes the other root directories.
