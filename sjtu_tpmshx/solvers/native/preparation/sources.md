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

## 3D preparation

The separate `prepare_case_3d` sequence in [preparation_case.cpp](../src/preparation_case.cpp)
uses the existing grid, geometry, property and DF cores.
It retains the production 3D physical `(x,y,z)` order, six axis maps,
typed port arithmetic and the resolved cell cap.
Its uniform side porosity is already split. Base K/cF fields remain unscaled;
side evidence records the CO2 or experimental application factors.
The sequence keeps A then B inlet properties, air-only bulk Nu observations,
then DF application evidence. Existing state and calibration limits remain.
The raw C interface owns returned buffers and accepts v1 event callbacks.
Python production preparation and its host cache hooks remain separate consumers.
The separate 3D flow v2 uses the same static geometry and speed-dependent finish steps.
It reuses `inlet_capacity_3d` and `inlet_speed` from `preparation_flow.cpp`.
Capacity queries omit speed-dependent work. Complete preparation preserves one geometry and the original evidence order.
Continuous v3 samples raw XY or XYZ controls through `field_continuous.cpp` on the final physical grid.
`have_ctrl_z` preserves the XYZ rule when its control count is one.
Raw and thermal geometry retain separate evaluation order and unit conversions.
The existing geometry and DF owners provide full local fields without 2D row projection.
Air range observations reuse `reynolds_point` with the original scalar and array types.
Spatial v4 uses `zones::assign` on physical XY centres, then `gaussian_sigma2` on L and t separately.
It extends those fields along z and retains the separate thermal SI round trip.
`asym::prepare_from_index` supplies the existing nominal split and thermal side/reference geometry.
`asym::split_porosity` applies each fraction to local symmetric total porosity.
Capacity uses the corresponding side field. Base DF and solid conductivity keep the existing symmetric geometry.
The raw owner copies rectangle inputs and keeps borrowed nested views with null owners.
The v1/v2/v3 C layouts and their original scope remain unchanged.
These interfaces add no 3D solve or capture and do not switch Python production preparation.
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
Public zone/sigmoid combination queries retain standalone and offset consumers.
Their later migration must preserve supplied properties and custom controls.
