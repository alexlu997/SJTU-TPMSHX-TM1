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

## Spatial flow stages

`src/preparation_case.cpp` owns raw spatial capacity, resolution and complete fixed-flow preparation.
`prepare_spatial_inlet_geometry` uses the existing zone/sigmoid geometry and port cores before any speed-dependent closure.
`prepare_capacities` and `resolve_speeds` reuse `src/preparation_flow.cpp` for capacity and target arithmetic.
Final preparation retains the physical grid, spatial geometry and per-call cache, with the original requested-grid observations.
Discrete design smoothing, sigmoid LUT geometry, thermal geometry and row D-F keep their separate owners and operation order.
`src/preparation_case_c_api.cpp` exposes v8 inputs and owned views without changing earlier C layouts.
The [external spatial flow caller](../../../../examples/cpp/prepare_spatial_flow_2d.cpp) uses installed headers and only the preparation library.
