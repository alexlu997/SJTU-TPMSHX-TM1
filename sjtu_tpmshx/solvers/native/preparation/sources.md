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
These interfaces add no 3D solve, capture, grid zones or asymmetric preparation.
