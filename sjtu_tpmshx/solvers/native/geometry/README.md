# Native geometry library

This target owns the standard, CO2-table and asymmetric geometry calculations.
It has no link dependency on the full solver, CoolProp, Eigen, SuperLU or AMGCL.
The build uses generated model data and the C++ standard runtime.
The library does not call Python, NumPy or scikit-image at runtime.
The Python application uses a thin C ABI binding.
There is no runtime compiler, source download or numerical fallback.

## Build and interfaces

The standalone entry is [CMakeLists.txt](CMakeLists.txt).
The full [dependency pilot](../dependency-pilot/CMakeLists.txt) adds the same target directory.
It does not define a second geometry implementation.

| Target | Interface or check |
| --- | --- |
| `tpmshx_geometry` | Static C++ calculation core. |
| `tpmshx_geometry_c` | Static C ABI library linked to that core. |
| `tpmshx_geometry_shared` | Shared C ABI library linked to that core. |
| `geometry_c_static` | Independent C11 caller linked to the static C ABI. |
| `geometry_c_shared` | The same C11 caller linked to the shared C ABI. |
| `geometry_kernel_smoke` | C++ caller for direct geometry rules and synthetic inputs. |

The public C interface is [geometry_c_api.h](../include/tpmshx/geometry_c_api.h).
The C++ interface is [geometry.hpp](../include/tpmshx/geometry.hpp).
The [C caller](../tests/geometry_c_smoke.c) checks fields, ownership, errors and unchanged outputs after failure.
The [C++ caller](../tests/geometry_kernel_smoke.cpp) checks inclusive counts and injected model or node data.
A caller result is separate from full numerical, platform and desktop acceptance.

Use the [configured project interpreter](../../../../README.md) from the repository root.
The [build script](../../../../engineering/scripts/build_native_dependencies.py) has these actions:

| Action | Scope |
| --- | --- |
| `fetch-cmake` | Fetch and check only the existing locked CMake tool. |
| `build --component geometry` | Generate model data, then configure and build this standalone target. |
| `verify --component geometry` | Check the locked CMake version and run the three callers. |
| `publish --component geometry` | Build, verify and publish only geometry with `geometry-build.json`. |

Set `--python-lock` to the active interpreter's exact lock when it differs from the default base lock.
Build and CLI verification retain the lock and pip compatibility checks.
The build script uses Python for these checks and model-data generation.
The generated input is `.cache/native-deps/generated/tpmshx/model_coefficients.hpp` by default.
Set `TPMSHX_MODEL_INCLUDE_DIR` when configuring CMake with another generated include directory.
The geometry target does not configure or build the solver dependencies.

Standalone outputs go under `.cache/native-deps/build/geometry-<host>`.
Full pilot outputs go under `.cache/native-deps/build/pilot-<host>`.
The shared library is `libtpmshx_geometry_shared.dylib` on macOS arm64.
It is `tpmshx_geometry_shared.dll` on Windows x64.
Both C callers and the kernel caller are placed beside the shared library.

Source publication uses `sjtu_tpmshx/solvers/native/lib/<host>`.
A changed geometry library keeps its previous library and metadata under `previous/`.
Geometry-only publication does not replace solver or run-state files.
The runtime loader override is `TPMSHX_GEOMETRY_LIBRARY`.
Desktop packaging uses a separate prebuilt input, `TPMSHX_NATIVE_GEOMETRY_LIBRARY`.
It places the geometry library beside the solver library under the bundle's `native/` directory.

## Upstream sources

The port uses the scikit-image **0.26.0** release:

- [Cython Lewiner implementation](https://github.com/scikit-image/scikit-image/blob/v0.26.0/src/skimage/measure/_marching_cubes_lewiner_cy.pyx).
- [Lookup tables](https://github.com/scikit-image/scikit-image/blob/v0.26.0/src/skimage/measure/_marching_cubes_lewiner_luts.py).
- [Input conversion, spacing and surface-area operations](https://github.com/scikit-image/scikit-image/blob/v0.26.0/src/skimage/measure/_marching_cubes_lewiner.py).
- [Release license](https://github.com/scikit-image/scikit-image/blob/v0.26.0/LICENSE.txt).

The algorithm is credited to Thomas Lewiner, Helio Lopes, Antonio Wilson Vieira and Geovan Tavares.
Thomas Lewiner wrote the original C++ implementation in 2002.
Almar Klein ported it to Cython in 2012. scikit-image adapted that port in 2016.
This project follows the 0.26.0 Cython implementation, not the older bundled C++ example.
That example has different near-zero and interpolation rules.

The area reduction uses NumPy **2.5.4** sources:

- [Real pairwise-sum helper](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/umath/loops_utils.h.src).
- [Addition reduction and its initial accumulator](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/umath/loops_arithm_fp.dispatch.c.src).
- [Array power dispatch](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/multiarray/number.c).
- [Release license](https://github.com/numpy/numpy/blob/v2.5.4/LICENSE.txt).

The applicable license for both excerpts is BSD-3-Clause.
Copyright 2009-2022 the scikit-image team.
Copyright (c) 2005-2025, NumPy Developers.
The complete notices are retained unchanged as
[scikit-image-LICENSE.txt](../licenses/scikit-image-LICENSE.txt) and
[numpy-LICENSE.txt](../licenses/numpy-LICENSE.txt).
Source distributions must retain their copyright, conditions and disclaimers.
Binary distributions must provide these notices in accompanying materials.
Do not use upstream names to endorse a derived product without permission.
These duties also apply to a geometry-only binary distribution.

## Local changes and numerical rules

The [scalar precision helper](../include/tpmshx/scalar_precision.hpp) keeps the original NumPy float16, float32 and float64 intermediate rounding in C++.
The binding sends cell, ratio and final-product precision metadata.
`standard_scalar_v1` rounds `L_mm/1000` and `L_m/N` at cell precision.
It rounds `t_mm/L_mm` and the first coefficient product at ratio precision.
The squared ratio term and the final threshold addition use double.
Batch L/t fields keep their existing float64 conversion.

Standard scalar porosity is a Python float.
Thus NumPy float16/32 conductivity can give `K_ss` the same dtype.
Array and CO2 porosity use float64, so their material results stay float64 for these conductivity inputs.
The core calculates `chi*(1-epsilon)` in double.
It casts that intermediate and conductivity to final-product precision before multiplication.
Python restores the output dtype and shape; it supplies no numerical fallback.
Formal nonzero asymmetric preparation keeps the original explicit Python-float conversion for L/t and length.
Its native arithmetic stays float64.

The local implementation is in [src/geometry](../src/geometry).
The cell state and ambiguity tests were translated from Cython to C++17.
Lookup data were decoded into signed-byte C++ tables without changing their dimensions or order.
The port keeps all 47 non-classic tables. It has no classic, mask, normal or value output mode.
It has no PLY support and does not remove degenerate faces.
C++ vectors own the internal mesh storage instead of the Cython allocation arrays.
The native pointer boundary adds explicit dimension checks.

The port retains cube order, corner numbering, vertex reuse and center-vertex weights.
Corner tests use strict positivity and double epsilon `2^-52`.
Upstream diagnostic branches still print and continue processing.
This includes the reachable near-zero case-13 diagnostic.
The internal mesh helper supports comparison; it is not an added public C mesh API.

The asymmetric wrapper first checks extrema from the original field values.
It skips MC when `level <= minimum` or `level >= maximum`.
Raw-array calls retain the original level scalar precision in that comparison.
The C ABI receives separate isosurface levels and array-comparison bounds.
The Python binding normalizes those scalars before it borrows a float64 buffer.
Masks, counts, surfaces, diameters and wall thickness remain native calculations.
Other inputs continue to the existing float32 conversion and MC logic.
The MC kernel performs its separate range check on the converted field.
This range comparison uses float32, as the original NumPy scalar comparison did.
The level remains double. Stored vertex coordinates remain float32.
The port restores NumPy axis order and the existing descent face order.
It retains duplicate vertices and zero-area triangles.
No periodic boundary is added.

Non-unit spacing promotes and scales vertex coordinates to double before area operations.
Exactly unit spacing retains the original float32 area path.
Each triangle uses the existing subtraction, cross product, square and square-root order.
The final sum keeps NumPy's eight lanes, 128-item blocks and recursive split aligned to eight elements.
The sum adds its subtotal to positive zero before division by two.
The port uses `std::sqrt`; NumPy can use a SIMD square-root operation.
Actual platform comparisons remain necessary.

CMake disables fast-math and contraction for this core on Clang/GCC.
It also disables builtin pow, sin and cos substitutions.
MSVC uses `/fp:strict`.
These options preserve the intended arithmetic; they do not prove cross-platform identity.
