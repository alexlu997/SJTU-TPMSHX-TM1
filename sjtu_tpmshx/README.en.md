<a id="主体源码sjtu_tpmshx"></a>

# Main source package sjtu_tpmshx

[中文](README.md) | [English](README.en.md)

All core source is in this package. See the [project README](../README.en.md#first-run) for setup, public examples and startup steps.
Run commands from the repository root. The [architecture](../docs/architecture.md) defines module boundaries and physical constraints.

## Four computation entries

| File | Public entry | Responsibility |
| --- | --- | --- |
| [compute.py](compute.py) | `compute` | Main computation entry. Validate configuration and organize three stages. Return CaseData, FieldResult and PerformanceResult. |
| [preprocess/api.py](preprocess/api.py) | `prepare_case` | Prepare the actual grid, boundaries, design fields, model resources and portable execution inputs. |
| [solvers/api.py](solvers/api.py) | `run_case` | Consume CaseData. Run the C++ numerical solver through Python bindings. Return native fields and run status. |
| [postprocess/api.py](postprocess/api.py) | `evaluate` | Organize metric evaluation and qualification from FieldResult. Do not run the solver again. |

```text
compute -> preprocess.api.prepare_case -> CaseData -> solvers.api.run_case -> FieldResult
                                                                       -> postprocess.api.evaluate -> PerformanceResult
```

`compute` also manages stage progress, cancellation, elapsed times and warnings.
`postprocess/api.py` sends full 2D/3D and Quick Design evaluation and independent queries to the native result stage.
`shared/_native_result_stage.py` adapts evidence, NumPy events and returned objects. `postprocess/export.py` exports results.
Current full computations support rectangular 2D and cuboid 3D domains.
See the [examples](../examples/three_module/) and [data contract](../docs/contracts/three_module_v1/README.md) for public inputs and file transport.
The [capabilities](../docs/capabilities.en.md) list approximation modes and extension status.

The [native stage SDK](../docs/native-stages.md) provides a separate C++ call sequence.
Its initial complete path supports uniform symmetric 2D air/air with prescribed velocity.
Preparation v2 adds all 16 ordered air/water/sCO2/CO2 pairs for uniform symmetric 2D geometry and prescribed velocity.
The full run path remains the v1 air/air CFD case.
The separate Quick Design path supports native double operating points and retains the existing LTNE model.
The Python entries above retain all current modes while stage migration continues.

## Edit numerical functions

Use this table to find the C++ owner of a numerical rule.
`shared/domain/` defines public input/output contracts. Python bindings pass types and arrays.

| Responsibility | C++ files and representative functions |
| --- | --- |
| Cell geometry, chi and solid conductivity | [geometry.cpp](solvers/native/src/geometry.cpp): `standard_geometry`, `solid_conductivity`; [asym_geometry.cpp](solvers/native/src/asym_geometry.cpp) |
| Grids and physical ports | [grid.cpp](solvers/native/src/grid.cpp): `uniform`, `wall`; [ports.cpp](solvers/native/src/ports.cpp): `port_overlap_1d`, `port_fractions_1d` |
| Continuous fields, sigmoid, LUTs and zones | [field_continuous.cpp](solvers/native/src/field_continuous.cpp); [field_sigmoid.cpp](solvers/native/src/field_sigmoid.cpp); [field_lut.cpp](solvers/native/src/field_lut.cpp); [zones.cpp](solvers/native/src/zones.cpp) |
| Properties and Nu closures | [fluid_properties.cpp](solvers/native/src/fluid_properties.cpp): `PropertyEvaluator::evaluate`, `fluid_nusselt`; [preparation_properties.cpp](solvers/native/src/preparation_properties.cpp) |
| Fixed DF, corrections, projection and prescribed flow | [preparation_df.cpp](solvers/native/src/preparation_df.cpp): `fixed_df`; [preparation_df_corrections.cpp](solvers/native/src/preparation_df_corrections.cpp); [preparation_df_projection.cpp](solvers/native/src/preparation_df_projection.cpp); [preparation_flow.cpp](solvers/native/src/preparation_flow.cpp): `inlet_capacity_2d`, `inlet_speed` |
| Full 2D/3D and Quick Design | [full_2d.cpp](solvers/native/src/full_2d.cpp): `solve_full_2d`; [full_3d.cpp](solvers/native/src/full_3d.cpp): `solve_full_3d`; [quick_design_driver.cpp](solvers/native/src/quick_design_driver.cpp): `solve_quick_design` |
| Metrics, physical balances, zone statistics and checks | [result_metrics.cpp](solvers/native/src/result_metrics.cpp): `pressure_face`, `boundary_enthalpy_duty`; [result_balance.cpp](solvers/native/src/result_balance.cpp): `mass`, `energy`, `zone_std`; [result_checks.cpp](solvers/native/src/result_checks.cpp): `collect_range`, `strict_certificate` |
| Complete stage preparation and execution | [preparation_case.cpp](solvers/native/src/preparation_case.cpp): `prepare_case_2d`; [stage_run.cpp](solvers/native/src/stage_run.cpp): `tpmshx_run_case_2d_v1`, `tpmshx_run_case_2d_v2`; [stage_capture_2d.cpp](solvers/native/src/stage_capture_2d.cpp) |
| Quick Design stage preparation and execution | [quick_design_prepare.cpp](solvers/native/src/quick_design_prepare.cpp): `tpmshx_prepare_quick_design_v1`; [quick_design_run.cpp](solvers/native/src/quick_design_run.cpp): `tpmshx_run_quick_design_v1` |
| Stage evaluation and qualification | [result_stage.cpp](solvers/native/src/result_stage.cpp): `evaluate`, `evaluate_applicability`, `evaluate_physical_balance`, `evaluate_qualification` |

Geometry uses geometry ABI 1 and field ABI 2. Preparation uses preparation ABI 1. Results use result ABI 2.
Start at the drivers above for SIMPLE, pressure and energy implementations. See [C++ interfaces](../docs/cpp-migration.md) for their boundaries.
Python keeps configuration, DTOs, I/O, caches, NumPy event handling, the GUI, searches and offline research.
The native result stage owns full evidence selection and qualification; Python adapts its outputs for applications.
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

## Six directory groups

| Directory | Responsibility and boundary |
| --- | --- |
| [preprocess](preprocess/) | Preprocessing and explicit offline model preparation. |
| [solvers](solvers/) | Solver API, prepared-data adapters and Python C++ bindings. [native](solvers/native/) holds C++ source, independent C ABI, build files and native caller tests. |
| [postprocess](postprocess/) | Metrics, physical audits, qualification and exports from recorded results. |
| [shared](shared/) | domain data contracts, models and df_surrogate models, io file transport, configs resources and shared helpers. |
| [applications](applications/) | gui interface and controllers, cli commands, design, optimization and execution recovery. result_adapter.py maps application results. |
| [development](development/) | Exactly three groups: tests for automated tests, validation for numerical and experimental checks, and runs for demonstrations, diagnostics and measurements. |

GUI implementation is in [applications/gui/main.py](applications/gui/main.py). CLI implementation is in [applications/cli/main.py](applications/cli/main.py).
Package-level [main.py](main.py), [cli.py](cli.py) and [desktop.py](desktop.py) keep short startup entries.
Use `python -m sjtu_tpmshx.main` or `python -m sjtu_tpmshx.cli`. Computation code calls the four entries above directly.

Root [engineering](../engineering/) holds scripts for builds and checks, packaging configuration and requirements locks.
[docs/contracts](../docs/contracts/) holds public file contracts. `.github/workflows/` holds CI configuration.
The [repository index](../docs/README.en.md) describes the other root directories.
