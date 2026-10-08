<a id="主体源码sjtu_tpmshx"></a>

# Main source package sjtu_tpmshx

[中文](README.md) | [English](README.en.md)

This is the TM1 Python package. Read the [project README](../README.en.md#first-run) for setup, CLI examples and GUI startup.
Run commands from the repository root.
The [architecture](../docs/architecture.md) defines module boundaries and physical constraints.

<a id="三模块主线"></a>

## Three module flow

```text
application input -> preprocess -> CaseData -> solvers -> FieldResult -> postprocess -> PerformanceResult
```

| Module | Public entry | Responsibility |
| --- | --- | --- |
| [preprocess](preprocess/) | [api.py](preprocess/api.py): `prepare_case` | Prepare the actual grid, boundaries, design fields, model resources and execution inputs. |
| [solvers](solvers/) | [api.py](solvers/api.py): `run_case` | Consume CaseData. Run the numerical solver. Return native fields and run status. |
| [postprocess](postprocess/) | [api.py](postprocess/api.py): `evaluate` | Calculate metrics from FieldResult and export results. Do not run the solver again. |

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
| [pipelines](pipelines/) and [workflows](workflows/) | Script entries and workflow orchestration. |
| [main.py](main.py), [ui](ui/) and [controllers](controllers/) | GUI startup, presentation and controls. Use the public modules to organize computation. |
| [cli.py](cli.py) | CLI preparation, solving, postprocessing and complete runs. |
| [design](design/) and [optimization](optimization/) | Quick Design and parameter optimization applications. |
| [runs](runs/) | Demonstration, diagnostic and research tools. |
| [tests](tests/) and [validation](validation/) | Automated tests, numerical verification, experimental validation and related evidence. |

The [repository index](../docs/README.en.md) lists build files, tools and historical records.
