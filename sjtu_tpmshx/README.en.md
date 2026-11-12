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
Preparation v3 adds independent capacity, inlet-flow resolution and complete preparation for uniform 2D total mass flow.
It reuses the physical inlet grid and keeps preliminary records separate from final preparation evidence.
Preparation v4 adds canonical continuous XY fields and full local drag.
Preparation v5 adds raw air/air stripes and rectangles at prescribed velocity, CFD drag and zero delta.
Its separate thermal geometry and row drag preserve the existing discrete rules.
Preparation v6 adds raw air/air sigmoid controls and a reusable native LUT with production-resolution cold construction.
It retains separate thermal geometry and row drag without discrete smoothing.

Preparation v8 adds capacity, flow resolution and complete fixed-flow preparation for these air/air spatial inputs.
It retains the physical grid and geometry, resolves speeds before transfer calculations, and owns copied regions, controls and LUTs.
Typed domain/port inputs and separate preliminary evidence remain explicit.
Preparation v9 connects symmetric spatial Python preparation, capacity and resolution through typed host-cache hooks.
`preprocess/native_preparation.py` shares cache and evidence transport; misses calculate in the native stage.
Python retains LUT storage. Native code builds missing tables at the original geometry checkpoint.

The Python preparation entries use v7 with v3/v4 payloads for symmetric uniform and continuous 2D inputs, and v9 for air/air spatial inputs.
Nonzero-delta and 3D preparation keep their explicit existing routes.
Public ZoneConfig and sigmoid combination queries retain standalone and offset consumers until separate migration passes.
CaseData and saved-file contracts stay unchanged. Native failures propagate without another preparation route.
Run v2 consumes preparation v2 through the existing model-h or true-h driver.
Run v1 retains its air/air CFD scope.
The separate Quick Design path supports native double operating points and retains the existing LTNE model.
The Python entries above retain all current modes while stage migration continues.
