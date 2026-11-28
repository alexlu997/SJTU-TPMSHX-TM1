<a id="主体源码tm1"></a>

# Python source and public entries

[中文](README.md) | [English](README.en.md)

This directory contains the public `tm1` package.
Run commands from the repository root so imports load the current checkout.
See the [setup guide](../docs/first-run.en.md) for setup, public examples, and startup steps.
The [architecture](../docs/architecture.md) defines module boundaries and physical constraints.

## Four computation entries

| File | Public entry | Responsibility |
| --- | --- | --- |
| [python/compute.py](compute.py) | `compute` | Validate configuration and run the three stages. Return `CaseData`, `FieldResult`, and `PerformanceResult`. |
| [python/preprocess/api.py](preprocess/api.py) | `prepare_case` | Prepare the physical grid, ports, design fields, model resources, and portable execution inputs. |
| [python/solvers/api.py](solvers/api.py) | `run_case` | Consume `CaseData`, execute the C++ saved stage through Python bindings, and return native fields and run status. |
| [python/postprocess/api.py](postprocess/api.py) | `evaluate` | Evaluate metrics, physical balances, applicability, and qualification from `FieldResult` without rerunning the solver. |

```text
compute -> preprocess.api.prepare_case -> CaseData -> solvers.api.run_case -> FieldResult
                                                                       -> postprocess.api.evaluate -> PerformanceResult
```

`compute` also manages stage progress, cancellation, elapsed times, and warnings.
Current full computations support rectangular 2D and cuboid 3D domains.
See [examples](../examples/three_module/) and the [data contract](../docs/contracts/three_module_v1/README.md) for public inputs and file transport.
See [capabilities](../docs/capabilities.en.md) for approximation modes and extension status.

### Active native stage bindings

All four computation stages call the active post-consolidation C ABIs directly, with no fallback to retired Python numerical paths:

- **Preparation (`native/preprocess/`, ABI 3)**: `python/cpp_interface/native_preparation.py` and `python/cpp_interface/preparation_host.py` bind the flat 2D and 3D `v1` family entries with unified `tpmshx_preparation_callbacks_v1`. `python/preprocess/two_d/preparation.py` builds the immutable 2D `CaseData` from arrays and metadata that the binding copies before release. `python/preprocess/three_d/preparation.py` builds the immutable 3D `CaseData` from arrays and metadata that the binding copies before release. `python/physical_models/zone_units.py` owns saved zone-unit conversion.
- **Inlet-property query**: `python/cpp_interface/inlet_properties.py` binds `tpmshx_query_inlet_properties_v2` for standalone `physical_models.tpms_calc.compute`. Python keeps geometry selection, shared caches, per-call `K_ss` lookup, and warning policy. See [inlet-property query](../docs/native-stages.md#inlet-property-query).
- **Full 2D and 3D execution (`native/solver/`)**: The solver hosts in `python/solvers/full_2d.py` and `python/solvers/full_3d.py` validate saved cases, select model and run controls, replay warnings, and build `FieldResult`. `python/cpp_interface/full_2d_stage.py` (saved 2D ABI 5) and `python/cpp_interface/full_3d_stage.py` (saved 3D ABI 3, capture ABI 2) bind only the saved-stage lifecycle and copy native outputs before release. This includes `tpmshx_run_saved_case_2d_v5`, `tpmshx_run_saved_case_3d_v3`, and their checkpoint create/restore entries through `python/cpp_interface/run_state.py` with host-supplied error maps. Both require `execution_view_v1`, `records_v1`, `report_v1`, and `get_capture_v1`; a library missing these entries fails as a deployment error.
- **Execution and applicability records**: Saved 2D/3D runs copy applicability groups and required records before native release. `python/cpp_interface/solver_library/stage_capture.py` copies native capture views, closure records, ledgers, and applicability selections. `python/solvers/stage_execution.py` links native reports to portable model roles, and `python/data_types/field_result.py` publishes `execution_record` (`full_execution_v1`) and `applicability_evidence` with `scope_notes`. `python/solvers/execution_record.py` assembles `full_execution_v1` only when a non-stage or test `FieldResult` omits it.
- **Quick Design (`quick_design_prepare_v2.cpp`, `quick_design_run.cpp`)**: The preparation host in `python/preprocess/quick_design.py` builds `CaseData` and supplies the sizing pressure query. The binding in `python/cpp_interface/quick_preparation.py` calls `tpmshx_prepare_quick_design_v2` and `tpmshx_quick_pressure_fractions_v2` with `tpmshx_quick_callbacks_v2`. The solver host in `python/solvers/quick_design.py` reads the saved case and builds its `FieldResult`. The binding in `python/cpp_interface/quick_design.py` calls `tpmshx_run_quick_design_v2` and copies native output before release. Defaults come from `python/model_configs/model_parameters_v1.json` and generated C++ constants.
- **Result evaluation (`native/postprocess/`, Result ABI 3)** uses `python/postprocess/api.py` for full 2D, full 3D, and Quick Design results. `python/cpp_interface/result_evaluation.py` calls `tpmshx_result_stage_query_v3` with `float64` evidence and `int32` labels. It reports native `RuntimeWarning` diagnostics and copies the output before release. `python/postprocess/evaluation.py` builds the metrics and public reports. `python/postprocess/export.py` exports results.

See the [native stage SDK](../docs/native-stages.md) for C and C++ callers outside Python.
See [C++ migration history](../docs/history/cpp-migration-history.md) for retired `v1`–`v11` entries and direct Python drivers.

## Edit numerical functions

Use this table to find the C++ owner of a numerical rule.
`python/data_types/` defines public input/output contracts, and `python/cpp_interface/` passes types and arrays.

| Responsibility | C++ files and representative functions |
| --- | --- |
| Cell geometry, chi, and solid conductivity | [geometry.cpp](../native/geometry/geometry.cpp): `standard_geometry`, `solid_conductivity`; [asym_geometry.cpp](../native/geometry/asym_geometry.cpp) |
| Grids and physical ports | [grid.cpp](../native/geometry/grid.cpp): `uniform`, `wall`; [ports.cpp](../native/geometry/ports.cpp): `port_overlap_1d`, `port_fractions_1d` |
| Continuous fields, sigmoid, LUTs, and zones | [field_continuous.cpp](../native/geometry/field_continuous.cpp); [field_sigmoid.cpp](../native/geometry/field_sigmoid.cpp); [field_lut.cpp](../native/geometry/field_lut.cpp); [zones.cpp](../native/geometry/zones.cpp) |
| Properties and Nu closures | [fluid_properties.cpp](../native/numerics/fluid_properties.cpp): `PropertyEvaluator::evaluate`, `fluid_nusselt`; [preparation_properties.cpp](../native/preprocess/preparation_properties.cpp) |
| Scalar inlet-property combination | [preparation_case.cpp](../native/preprocess/preparation_case.cpp): `query_inlet_properties`, `inlet_property_values`; [preparation_case_c_api.cpp](../native/preprocess/preparation_case_c_api.cpp): `tpmshx_query_inlet_properties_v2` |
| Fixed D-F, corrections, projection, and prescribed flow | [preparation_df.cpp](../native/preprocess/preparation_df.cpp): `fixed_df`; [preparation_df_corrections.cpp](../native/preprocess/preparation_df_corrections.cpp); [preparation_df_projection.cpp](../native/preprocess/preparation_df_projection.cpp); [preparation_flow.cpp](../native/preprocess/preparation_flow.cpp): `inlet_capacity_2d`, `inlet_speed` |
| Full 2D/3D and Quick Design | [full_2d.cpp](../native/solver/full_2d.cpp): `solve_full_2d`; [full_3d.cpp](../native/solver/full_3d.cpp): `solve_full_3d`; [quick_design_driver.cpp](../native/solver/quick_design_driver.cpp): `solve_quick_design` |
| Metrics, physical balances, zone statistics, and checks | [result_metrics.cpp](../native/postprocess/result_metrics.cpp): `pressure_face`, `boundary_enthalpy_duty`; [result_balance.cpp](../native/postprocess/result_balance.cpp): `mass`, `energy`, `zone_std`; [result_checks.cpp](../native/postprocess/result_checks.cpp): `collect_range`, `strict_certificate` |
| Complete stage preparation and execution | [preparation_case.cpp](../native/preprocess/preparation_case.cpp): `prepare_case_2d`, `prepare_zoned_flow_case_2d`, `prepare_thermal_sides`, `prepare_case_3d`; [stage_run.cpp](../native/solver/stage_run.cpp): `tpmshx_run_saved_case_2d_v5`, `tpmshx_stage_run_2d_create_saved_v5/restore_saved_v5`; [stage_capture_2d.cpp](../native/solver/stage_capture_2d.cpp): `tpmshx_stage_run_2d_get_capture_v1`, `tpmshx_stage_run_2d_records_v1`; [stage_run_3d.cpp](../native/solver/stage_run_3d.cpp): `tpmshx_run_saved_case_3d_v3`, `tpmshx_stage_run_3d_create_saved_v3/restore_saved_v3`; [stage_capture_3d.cpp](../native/solver/stage_capture_3d.cpp): `capture_3d`, `tpmshx_stage_run_3d_get_capture_v1`, `tpmshx_stage_run_3d_records_v1` |
| Quick Design stage preparation and execution | [quick_design_prepare_v2.cpp](../native/preprocess/quick_design_prepare_v2.cpp): `tpmshx_prepare_quick_design_v2`, `tpmshx_quick_pressure_fractions_v2`; [quick_design_run.cpp](../native/solver/quick_design_run.cpp): `tpmshx_run_quick_design_v2` |
| Stage evaluation and qualification | [result_stage.cpp](../native/postprocess/result_stage.cpp): `evaluate`, `evaluate_applicability`, `evaluate_physical_balance`, `evaluate_qualification` |

Geometry uses geometry ABI 2 and field ABI 3.
Preparation uses preparation ABI 3 and Quick Design preparation v2.
Results use result ABI 3.
See [C++ interfaces](../docs/cpp-migration.md) for solver internals and [kept Python responsibilities](../docs/architecture.md#retained-python-responsibilities) for the Python boundary.

### Rebuild after a change

After changing C++ code or compiled model data, pass the [current environment checks](../docs/verification.en.md).
Rebuild and publish the four libraries from the repository root, then restart the process.
If `.venv-path` selects a BO environment, replace `base.txt` with `bo-macos.txt` or `bo-windows.txt` from `engineering/requirements/`.
For a new build cache, run `fetch` from [First run](../docs/first-run.en.md#examples) first and reuse that cache below.

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

See [C++ builds](../docs/cpp-migration.md#native-geometry-core) for separate component publication and kept checkpoint runtimes.

<a id="三模块主线"></a>
<a id="支撑模块与应用入口"></a>

## Python directories

| Directory | Responsibility and boundary |
| --- | --- |
| [preprocess](preprocess/) | Preprocessing and explicit offline model preparation. |
| [solvers](solvers/) | Solver API, 2D/3D and Quick Design hosts, and execution and ledger helpers. C++ implementation is in [solver](../native/solver/). |
| [postprocess](postprocess/) | Metrics, physical audits, qualification, and exports from recorded results. |
| [data_types](data_types/) | Configuration, prepared cases, fields, and performance results. |
| [file_io](file_io/) | Read and write case, result, metric, and checkpoint files. |
| [run_control](run_control/) | Cancellation, progress, warnings, environment, and runtime selection. |
| [physical_models](physical_models/) and [model_configs](model_configs/) | Model queries and versioned model parameters. |
| [cpp_interface](cpp_interface/) | Native ctypes bindings. [solver_library](cpp_interface/solver_library/) holds the ctypes layouts and decoders of saved native runs. |
| [applications](applications/) | [GUI](applications/gui/), [CLI](applications/cli/), [Quick Design](applications/design/), [Bayesian optimization](applications/optimization/), and [run recovery](applications/execution/recovery.py). |
| [development](development/) | Validation, diagnostics, and developer tools. Automated tests live in [tests/python](../tests/python/). |

[Grid and geometry preflight](preprocess/preflight.py) reads a captured `ComputeConfig`. [Sensitivity screening](applications/design/sensitivity.py) evaluates one row at a time for air on side A.
The GUI shows preflight warnings, sweep progress, and the heatmap.

Old local scripts that use retired module paths must update their imports or use the recorded source revision.
Start applications with the root [main.py](../main.py). It routes the GUI to [applications/gui/main.py](applications/gui/main.py), the file stages to [applications/cli/stages.py](applications/cli/stages.py), `summary` to [applications/cli/main.py](applications/cli/main.py), `design` to [applications/design/cli.py](applications/design/cli.py), and `optimize` to [applications/optimization/cli.py](applications/optimization/cli.py).
Computation code calls the four entries above directly.
Root [engineering](../engineering/) holds build and check scripts, packaging configuration, and dependency locks.
[docs/contracts](../docs/contracts/) holds public file contracts, `.github/workflows/` holds CI workflows, and the [repository index](../docs/README.en.md) maps all root directories.
