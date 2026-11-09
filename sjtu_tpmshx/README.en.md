<a id="主体源码sjtu_tpmshx"></a>

# Main source package sjtu_tpmshx

[中文](README.md) | [English](README.en.md)

This package contains all TM1 core source. It includes the Python application and the C++ numerical backend under `solvers/native/`.
Read the [project README](../README.en.md#first-run) for setup, CLI examples and GUI startup.
Run commands from the repository root.
The [architecture](../docs/architecture.md) defines module boundaries and physical constraints.

<a id="三模块主线"></a>

## Three module flow

`compute` in [compute.py](compute.py) is the main computation entry. It validates configuration and calls the three public APIs below.
It returns `CaseData`, `FieldResult` and `PerformanceResult`. It also manages stage progress, cancellation, elapsed times and warnings.

```text
compute -> preprocess.api.prepare_case -> CaseData -> solvers.api.run_case -> FieldResult
                                                                       -> postprocess.api.evaluate -> PerformanceResult
```

| Module | Public entry | Responsibility |
| --- | --- | --- |
| [preprocess](preprocess/) | [api.py](preprocess/api.py): `prepare_case` | Prepare the actual grid, boundaries, design fields, model resources and execution inputs. |
| [solvers](solvers/) | [api.py](solvers/api.py): `run_case` | Consume CaseData. Call the C++ backend in `solvers/native/` through `solvers/backends/cpp/` bindings. Return native fields and run status. |
| [postprocess](postprocess/) | [api.py](postprocess/api.py): `evaluate` | Organize FieldResult metric evaluation. `metrics.py` holds metric formulas and reduction helpers. `export.py` exports results. Do not run the solver again. |

The [three module examples](../examples/three_module/) show real cases and file transport.
Current full computations support rectangular 2D and cuboid 3D domains.
See the [project README](../README.en.md) and [capabilities](../docs/capabilities.en.md) for approximation modes and extension status.

<a id="支撑模块与应用入口"></a>

## Shared modules and application entries

| Directory or file | Responsibility |
| --- | --- |
| [domain](domain/) | CaseData, FieldResult, PerformanceResult, run controls and input validation. |
| [io](io/) | YAML, HDF5 and JSON transport, with reader validation. |
| [models](models/) and [df_surrogate](df_surrogate/) | Shared geometry, properties, correlations and model resources. |
| [configs](configs/) | Configuration resources supplied with the package. |
| [compute.py](compute.py) | Main computation entry, three-module calls, stage progress and cancellation. |
| [workflows](workflows/) | File transport, run status, checkpoints and recovery. Reuse the main computation stages. |
| [solvers/native](solvers/native/) | C++ numerical source, independent C ABI, build files, native caller tests and license notices. |
| [main.py](main.py), [ui](ui/) and [controllers](controllers/) | GUI startup, presentation and controls. Use the public modules to organize computation. |
| [cli.py](cli.py) | CLI preparation, solving, postprocessing and complete runs. |
| [design](design/) and [optimization](optimization/) | Quick Design and parameter optimization applications. |
| [runs](runs/) | Demonstration, diagnostic and research tools. |
| [tests](tests/) and [validation](validation/) | Automated tests, numerical verification, experimental validation and related evidence. |

The [repository index](../docs/README.en.md) lists build files, tools and historical records.
