# Grid and design-field sources

The geometry library contains these numerical subsets. This is a source and modification record, not a platform acceptance report.
The [build record](README.md) defines targets, interfaces and runtime delivery.
The library does not link Python, NumPy, SciPy, Fortran, LAPACK or BLAS for these calculations.

## Fixed upstream sources

All SciPy links use **v1.18.1**. All NumPy links use **v2.5.4**.

| Subset | Primary source | Local use |
| --- | --- | --- |
| XY FITPACK | [dfitpack.c](https://github.com/scipy/scipy/blob/v1.18.1/scipy/interpolate/src/dfitpack.c), [dfitpack.h](https://github.com/scipy/scipy/blob/v1.18.1/scipy/interpolate/src/dfitpack.h) | Restricted first-fit bivariate interpolation with `s=0`, degrees 1–3 and default bounds. |
| One-dimensional knots and fit | [_bsplines.py](https://github.com/scipy/scipy/blob/v1.18.1/scipy/interpolate/_bsplines.py) | Degree-1 coefficients, degree-2/3 not-a-knot rules and collocation structure. |
| Basis and interval operations | [__fitpack.cc](https://github.com/scipy/scipy/blob/v1.18.1/scipy/interpolate/src/__fitpack.cc) | Restricted `_find_interval`, `_deBoor_D`, `_coloc_matrix` and `_evaluate_spline` rules. |
| Linear LUT | [_rgi.py](https://github.com/scipy/scipy/blob/v1.18.1/scipy/interpolate/_rgi.py), [_rgi_cython.pyx](https://github.com/scipy/scipy/blob/v1.18.1/scipy/interpolate/_rgi_cython.pyx), [_poly_common.pxi](https://github.com/scipy/scipy/blob/v1.18.1/scipy/interpolate/_poly_common.pxi) | Axis normalization, fast64/general arithmetic, singleton axes, interval selection and end-cell extrapolation. |
| Gaussian weights | [_filters.py](https://github.com/scipy/scipy/blob/v1.18.1/scipy/ndimage/_filters.py) | The existing sigma=2, order=0, truncate=4 weights and axis order. |
| Gaussian correlation | [ni_filters.c](https://github.com/scipy/scipy/blob/v1.18.1/scipy/ndimage/src/ni_filters.c), [ni_support.c](https://github.com/scipy/scipy/blob/v1.18.1/scipy/ndimage/src/ni_support.c) | Symmetric `NI_Correlate1D` pair order and reflect boundary extension. |
| Pairwise sum | [loops_utils.h.src](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/umath/loops_utils.h.src), [loops_arithm_fp.dispatch.c.src](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/umath/loops_arithm_fp.dispatch.c.src) | Existing shared pairwise reduction for geometry area and Gaussian normalization. |
| Scalar arithmetic and accumulation | [scalarmath.c.src](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/umath/scalarmath.c.src), [loops.c.src](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/umath/loops.c.src), [ufunc_object.c](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/umath/ufunc_object.c) | Scalar power and per-element narrow cumsum rules. The existing project precision helper supplies half rounding. |
| Raw overlap and clip | [loops_minmax.dispatch.c.src](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/umath/loops_minmax.dispatch.c.src), [clip.cpp](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/umath/clip.cpp) | NaN propagation and bounded clipping after original typed interval arithmetic. |
| Sigmoid exponential dispatch | [loops_exponent_log.dispatch.c.src](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/umath/loops_exponent_log.dispatch.c.src), [npy_simd_data.h](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/umath/npy_simd_data.h) | Scalar port of the float32 Cody-Waite and P5/Q2 FMA kernel, within the original clipped input domain. |

## Extraction and local changes

### XY

[src/continuous/xy_fitpack.c](../src/continuous/xy_fitpack.c) retains `fpback`, `fpbspl`, `fpbisp`, `fpgivs`, `fprota` and the interpolation branch of `fpgrre`.
The knot assembly follows the first-fit `fpregr` branch.
Smoothing search, continued fits, knot insertion and Python extension allocation are excluded.
The wrapper owns storage and checks dimensions before numerical access.

Givens operations contain explicit `fma` directions for the observed locked arm64 reference.
The XY C17 target alone permits implicit contraction on Clang/GCC.
This is a modified numerical subset, not an unchanged copy of the whole upstream file.
It does not establish Windows arithmetic identity.

### XYZ and singleton XY

[src/continuous/tensor_spline.cpp](../src/continuous/tensor_spline.cpp) uses fixed-size basis storage and project-owned band storage.
Derivative, periodic and general SciPy extension branches are excluded.
The scalar band solver uses partial pivoting. It does not copy or link LAPACK `gbsv` or vendor BLAS.
Each axis is fitted and sampled before the next axis, in x/y/z order.
Singleton axes repeat their values. Final bounds apply once after the complete interpolation route.
The exact constant branch remains separate.

XY and XYZ are distinct algorithms. Coefficient differences from LAPACK remain diagnostic evidence.
Existing raw spline `1e-13` and physical-polynomial `3e-14` checks do not establish bitwise identity or physical accuracy.

### Sigmoid and LUT

[src/field_sigmoid.cpp](../src/field_sigmoid.cpp) retains the original project sigmoid and ordered layer blending.
It reuses grid scalar precision operations. It does not replace the sequence with normalized layer weights.
Float16 exponential inputs use float exp and their original rounding; float64 uses double exp.
Float32 follows the actual NumPy dispatch. The adapter reads public `np.lib.introspect.opt_func_info` metadata.
X86_V3 and X86_V4 use the scalar port of the locked float32 FMA kernel. Other targets keep libm.
The core retains explicit FMA, float32 division and the original clipped [-50,50] domain.
It does not infer the mode from CPU or environment settings. No process-wide mode or callback is added.
Field ABI 2 passes this mode explicitly to the three sigmoid v2 functions.
It rejects older candidate field libraries before calling them. Geometry ABI 1 and its published signatures stay unchanged.
The Python adapter retains the supported exp warning policy and original call order.
It does not emulate every NumPy ufunc error mode.

[src/field_lut.cpp](../src/field_lut.cpp) implements the two-table linear query in the original corner order.
Each table keeps its own fast64/general path, selected before double-buffer conversion.
Current dtype, byte order and writability affect that choice.
The Python DTO captures axes/table references and retains its creating library.
In-place data changes remain visible. Attribute rebinding does not replace the captured references.
NPZ validation and cache I/O remain in Python. The native query adds no parameter clipping or fitted correction.

### Grids, ports and zones

[src/grid.cpp](../src/grid.cpp), [src/ports.cpp](../src/ports.cpp) and [src/zones.cpp](../src/zones.cpp) retain the original project rules.
These include ordered assignment, scalar promotion, allocation ties, compensated Python-float sum prefixes and endpoint compensation.
The pressure solver and preparation use one lightweight port owner.
No second solver or EOS dependency is introduced.

The Gaussian subset implements only sigma=2, order=0, radius=8 and reflect boundaries, with axis 0 before axis 1.
It retains the center term followed by far-to-near symmetric pairs.
Apple arm64 uses explicit fused pair accumulation to follow the observed locked filter.
Other platforms retain separate multiply/add operations. General grid/field targets disable implicit contraction and fast-math.
MSVC uses `/fp:strict`; explicit fused operations remain explicit.
The filter remains in grid-index units, including on a nonuniform mesh. Continuous splines do not use it.

## Notices and delivery

Retain the complete [SciPy BSD-3-Clause notice](../licenses/scipy-LICENSE.txt).
Retain the original [Peter J. Verveer ndimage notice](../licenses/ndimage-LICENSE.txt).
Retain the [NumPy BSD-3-Clause notice](../licenses/numpy-LICENSE.txt).
The [scikit-image notice](../licenses/scikit-image-LICENSE.txt) still applies to the marching-cubes subset.
These files keep their original copyright text, conditions and disclaimers.
Source distributions retain the notices. Binary distributions include them in accompanying materials.
Upstream names must not endorse a derived product without permission.
These duties also apply to a standalone geometry/design-field distribution.
See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) for the complete native component record.

No new runtime library, numerical framework, fallback or numerical callback into Python is added.
Independent development references do not supply production results.
Complete-case, supported-platform CI and final acceptance remain separate requirements.
Historical experimental conclusions and failed comparisons keep their original status.
