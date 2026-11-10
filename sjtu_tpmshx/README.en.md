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
`postprocess/metrics.py` selects recorded evidence and calls the result core. `postprocess/export.py` exports results.
Current full computations support rectangular 2D and cuboid 3D domains.
See the [examples](../examples/three_module/) and [data contract](../docs/contracts/three_module_v1/README.md) for public inputs and file transport.
The [capabilities](../docs/capabilities.en.md) list approximation modes and extension status.

The numerical owners for standard, CO2 and asymmetric geometry, plus chi/Kss, are
[native/src/geometry.cpp](solvers/native/src/geometry.cpp) and
[native/src/asym_geometry.cpp](solvers/native/src/asym_geometry.cpp).
[shared/models/_native_geometry.py](shared/models/_native_geometry.py) uses ctypes to load the independent geometry ABI 1 library lazily.
It keeps Python public entries, types and caches without importing the solver backend.
Stage three puts grids, ports and six-direction axis mapping in
[grid.cpp](solvers/native/src/grid.cpp) and [ports.cpp](solvers/native/src/ports.cpp).
Pressure solvers and preparation use the same port implementation.
[field_continuous.cpp](solvers/native/src/field_continuous.cpp), the sigmoid/LUT cores and [zones.cpp](solvers/native/src/zones.cpp)
own design-field interpolation, zones and Gaussian filtering. They use the same geometry library.
Python keeps configuration, type/array adaptation, data objects, I/O, caches, GUI and BO orchestration.
The replaced Python numerical bodies are retired. Independent references serve development regression tests only.
Stage four puts properties and closures in [fluid_properties.cpp](solvers/native/src/fluid_properties.cpp) and `preparation_properties.cpp`.
The `preparation_df*.cpp` and `preparation_flow.cpp` sources own fixed DF, experiment corrections, projection, fixed-flow and design preparation mathematics.
[shared/models/_native_preparation.py](shared/models/_native_preparation.py) loads independent preparation ABI 1 on demand. Geometry ABI 1 and field ABI 2 stay unchanged.
Python keeps configuration, DTOs, I/O, caches, GUI/BO policies and offline fitting. Development references remain independent of production mathematics.
Stage five puts metrics, physical balances, zone statistics and numerical qualification checks in the independent C++ [result core](solvers/native/result/).
[shared/_native_result.py](shared/_native_result.py) loads result ABI 2 on demand. File reads load no solver, preparation or result library.
Python keeps evidence selection, status interpretation and file interfaces. The four daily entries stay unchanged.
Edit a numerical function in its C++ source, then rebuild and restart the process.
Numerical and platform acceptance for stage five is in progress. The six-stage goal remains incomplete.
See the [native result core](../docs/cpp-migration.md#native-result-core) for independent builds and four-library delivery.

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
