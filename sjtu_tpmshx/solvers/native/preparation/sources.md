# Preparation arithmetic sources

The preparation model keeps the original Python and NumPy operation order.
The native code does not call either runtime.
The physical coefficients remain in the project model resources.

| Source | Native use and changes | Notice |
| --- | --- | --- |
| [CPython 3.13.2 `_Py_c_quot`](https://github.com/python/cpython/blob/v3.13.2/Objects/complexobject.c#L86) | The weak complex quotient in `src/fluid_properties.cpp` keeps division after each numerator. The port uses `std::complex` storage and project error handling. It does not copy the Python object interface. | [Complete release license](../licenses/python-v3.13.2-LICENSE.txt) |
| [NumPy 2.5.4 complex divide](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/umath/loops.c.src#L2032) | The strong complex quotient in `src/numpy_complex_divide.hpp` keeps the reciprocal and multiplication order. Preparation and result calculations use the same pure helper. | [BSD-3-Clause notice](../licenses/numpy-LICENSE.txt) |
| [NumPy 2.5.4 complex log10](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/umath/funcs.inc.src#L386) | Complex log10 scales each logarithm component by the original `LOG10E` constant. The macOS double path calls the system C11 `clog` through private `src/model_complex_log.c`. Other paths use `std::log`. The port does not include the FreeBSD complex-log fallback. | [BSD-3-Clause notice](../licenses/numpy-LICENSE.txt) |
| [NumPy 2.5.4 maximum](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/umath/loops_minmax.dispatch.c.src#L45) | The Reynolds floor in `src/preparation_properties.cpp` keeps the AArch64 mixed-zero rule and the x86 equal-value rule. It does not include a NumPy dispatch layer. | [BSD-3-Clause notice](../licenses/numpy-LICENSE.txt) |

The original notices must accompany source and binary distributions that contain these subsets.
The macOS arm64 quotient keeps the fused expressions in the locked Python and NumPy binaries.
Other supported targets keep separate operations. Global floating-point options stay unchanged.
The independent Python references remain under `development/tests/`.
They do not call the native formulas that they check.

## Scalar inlet-property combination

`src/preparation_case.cpp::inlet_property_values` owns the existing scalar sequence for standalone queries and complete preparation.
It calls the existing property, Re/Pr, Nu, surface-transfer, fixed DF, pressure-gradient and pore-conductivity implementations.
It preserves their order, scalar kinds, floating-point events and source range records.
Raw queries retain the previous complex Nu and H_sf intermediates and Python property-conversion failures.
Complete preparation keeps its existing physical guards.

`query_inlet_properties` accepts supplied geometry scalars and creates no mesh or solver state.
`src/preparation_case_c_api.cpp` exposes `tpmshx_query_inlet_properties_v1` with twelve typed inline values and no owner.
Optional v3 callbacks retain synchronous observations and host-object checks; both cache hooks must be NULL.
`shared/models/tpms_calc.py` keeps public calls, shared caches, geometry selection and the per-call material query.
`shared/models/_native_preparation_case.py` owns query transport and the range policy shared with preparation adapters.
The frozen combination in `development/tests/property_reference.py` supplies independent numerical expectations.
The [external fluid caller](../../../../examples/cpp/prepare_fluids_2d.cpp) uses `stages.hpp` to query all four fluids with only the preparation library.
No physical model, coefficient source or external numerical dependency is added.

## Spatial flow stages

`src/preparation_case.cpp` owns raw spatial capacity, resolution and complete fixed-flow preparation.
`prepare_spatial_inlet_geometry` uses the existing zone/sigmoid geometry and port cores before any speed-dependent closure.
`prepare_capacities` and `resolve_speeds` reuse `src/preparation_flow.cpp` for capacity and target arithmetic.
Final preparation retains the physical grid, spatial geometry and per-call cache, with the original requested-grid observations.
Discrete design smoothing, sigmoid LUT geometry, thermal geometry and row D-F keep their separate owners and operation order.
`src/preparation_case_c_api.cpp` exposes v8 inputs and owned views without changing earlier C layouts.
The [external spatial flow caller](../../../../examples/cpp/prepare_spatial_flow_2d.cpp) uses installed headers and only the preparation library.

## Spatial host cache transport

V9 adds typed geometry and inlet probes without changing v1-v8 layouts.
Its spatial model carries the actual conductivity value and scalar kind.
The original configuration comparison can accept different nominal and spatial values through narrow-scalar equality.
Spatial material uses the accepted spatial value; nominal calculations keep their original value.
The probes carry actual L/t, scalar kinds, fluid state and optional Nu selection.
`preprocess/native_preparation.py` uses the existing shared cache owners for
lookup, publication and evidence transport. It does not call numerical cache functions.
`ZonedCache` uses those hooks when supplied; native code calculates each miss.
The original per-call cache remains available for independent native callers.
The LUT hook exchanges tables at each path's original geometry checkpoint.
Python owns disk/memory I/O. `build_sigmoid_lut_2d` owns missing-table construction.
The [external cache caller](../../../../examples/cpp/prepare_spatial_cache_2d.cpp)
checks all six v9 operations, typed probes and copied LUT lifetime.
Public zone/sigmoid combination queries retain standalone consumers.
Their later migration must preserve supplied properties and custom controls.

## Existing offset geometry

V10 adds the existing nonzero-delta uniform and spatial preparation modes.
`prepare_thermal_sides` calls the existing asymmetric geometry owner with its N128 index.
It runs at the original thermal checkpoint and keeps nominal sides separate from design and cell thermal geometry.
The owned complete result adds two thermal-side tuples and retains the existing split fraction.
Capacity and fixed-flow entries keep their previous delta rejection and validation order.
Earlier C layouts and scopes stay unchanged. No physical model is added.
The [external offset caller](../../../../examples/cpp/offset_2d.cpp) prepares, runs and evaluates the existing modes through installed headers.
