# Independent result core: sources and interfaces

The standalone CMake project builds `tpmshx_result_shared` with C++17 and system libraries.
It does not use solver state, geometry, preparation, CoolProp, Eigen, SuperLU or AMGCL.
It needs no generated model headers. Linux x86_64 support applies to this component only.
The full application retains its macOS arm64 and Windows x64 platforms.

## Numerical owners

| Source | Responsibility |
| --- | --- |
| `src/result_core.cpp` | Checked typed byte views, scalar storage and platform precision metadata. |
| `src/result_arithmetic.cpp` | Private typed arithmetic and reductions used by named result calculations. |
| `src/result_complex_sqrt.c` | Private macOS C11 calls to the system complex square root, matching NumPy's original system calls. |
| `src/result_metrics.cpp` | Pressure faces, duties, mass flow, outlet values, integrated mass and Quick Design metrics. |
| `src/result_balance.cpp` | Independent signed mass and energy balances, residual norms and zone statistics. |
| `src/result_checks.cpp` | Range observations, qualification predicates, envelope helpers and physical mass bounds. |
| `src/result_stage.cpp` | Full metric selection, definitions, statuses, applicability, physical balances and qualification. |
| `src/result_stage_c_api.cpp` | Owned stage reports, borrowed evidence and versioned host event/error control. |
| `src/result_c_api.cpp` and family C interfaces | Versioned C functions with checked buffers and ordered floating-point diagnostics. |

Python retains DTOs, type and shape adaptation, original object identity, NumPy event handling and file I/O.
The result stage owns full 2D/3D evidence selection, status and reason text.
The stage also owns Quick Design metric arithmetic. V3 retains typed intermediate values and fixed named host operations for existing Python object, exact integer and final conversion protocols.
The four public computation entries remain unchanged.
Independent original numerical references stay under `development/tests/`.
Production result calculations do not call those references.

## Original numerical rules and notices

The port retains the original operation order, intermediate dtype and scalar versus array behavior.
It does not link or call NumPy or the Python runtime.

- NumPy 2.5.4 pairwise reduction and complex arithmetic rules use the existing
  [complete BSD notice](../licenses/numpy-LICENSE.txt).
  The reduction reference is `numpy/_core/src/umath/loops_utils.h.src`.
  Scalar promotion and diagnostics follow the locked Python-facing expressions.
  The shared complex quotient is in `src/numpy_complex_divide.hpp`.
  On Apple arm64, complex array square retains the original NEON component FMA sequence.
  This local rule does not enable general floating-point contraction.
  The fixed references are
  [NumPy complex multiplication](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/umath/loops_arithm_fp.dispatch.c.src#L228-L278)
  and [NEON arithmetic](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/common/simd/neon/arithmetic.h#L234-L284).
  Complex array square takes an explicit separate-product or FMA mode.
  The Python adapter reads NumPy's public square dispatch metadata; it does not calculate square values.
  `X86_V3` and the ASIMD baseline use FMA; `X86_V2` uses separate products.
  The fixed [loop targets](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/meson.build#L918-L928)
  and [baseline labels](https://github.com/numpy/numpy/blob/v2.5.4/meson_cpu/main_config.h.in#L305-L307) define this selection.
  Unknown targets produce a deployment error. Fresh-process tests also disable the optional x86 target.
  On Windows, complex square root retains the original NumPy Algorithm 312.
  The fixed references are the [Windows C99 exclusions](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/common/npy_config.h#L37-L52)
  and [square-root implementation](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/npymath/npy_math_complex.c.src#L321-L392).
  [Preparation sources](../preparation/sources.md) record its original source and local changes.
- CPython 3.13.2 compensated float summation uses the existing
  [complete release license](../licenses/python-v3.13.2-LICENSE.txt).
  The reference is `Python/bltinmodule.c`, `CompensatedSum` and the float path of `builtin_sum_impl`.
  The equivalent CPython 3.12.9 float path is also used by the supported Windows interpreter.
  The port accepts a finite sequence of binary64 values already converted at the original Python points.
  It retains correction order, nonfinite handling and the final correction condition.
  It does not implement Python's general iterable or arbitrary object summation.
- Existing project `scalar_precision.hpp` owns binary16 conversion.
  The result codec retains integers in integer storage and checks the actual extended floating format when used.

Keep these source records and complete notices with binary distributions.
The source distributions also retain the CMake project, export lists, headers and independent callers.

## C interface and ownership

Result ABI 2 is separate from the solver, geometry, field and preparation ABIs.
The query function keeps its `_v1` query signature and returns the library ABI number.
ABI 2 requires an explicit complex-square mode in the zone standard-deviation and power calls.
Mode 0 uses separate products; mode 1 uses component FMA. Other values fail before output publication.
The borrowed POD descriptions retain their `_v1` layouts.
The adapter rejects earlier library ABIs before binding numerical calls.
Its declarations are in `include/tpmshx/result_c_api.h` and the family and stage headers.
The stage host queries use separate v2 and v3 input declarations. They preserve published v1 and v2 C layouts.
V3 carries typed Quick operands and raw labels. Native code owns label comparisons and policy.
Fixed named host callbacks retain only Python value protocols at the native-selected operation.
Object equality and inequality use separate callbacks. String subclasses retain their original comparison operators.
Deferred conversion errors and NumPy callbacks are consumed at the original metric or qualification boundary.
Uncaught host exceptions return their original token. Stage outputs are released through their originating library.
Only the symbols in `result.exports` and `result.map` are public.
There is no public arithmetic opcode evaluator or callback that supplies complete metrics.

Arrays borrow typed bytes, shape metadata and signed byte strides for one call.
The descriptor states the storage extent, logical-zero offset, dtype, byte order and origin.
Negative strides and explicit byte order do not require conversion to binary64.
Callers own input and output storage. Kernels use compact temporary arrays with their actual dtype.
Failure does not commit numerical outputs. Writable buffers must not overlap other call buffers.
Readonly input views can share storage.

Status 1 means invalid C input, 2 means allocation failure, and 3 means runtime failure.
Status 4 carries the original numerical exception cause.
Ordered floating-point events precede a later numerical exception when the original expression did so.
The Python adapter applies the caller's NumPy error policy to these events.
Missing files, symbols or a wrong ABI remain deployment errors.
There is no numerical fallback or runtime compilation.

`shared/_native_result.py` loads the image only when a numerical call needs it.
Public imports and pure HDF/JSON reads do not load it.
Full evaluation and independent result queries require the current stage image, including queries with missing evidence.
A missing stage symbol is a deployment error. Missing physical evidence retains its original result status and reason.
Explicit object and arbitrary integer protocols remain at demonstrated Python-only conversion points.
These branches are selected before native execution; they do not handle a native failure.

## Build and verification

Use the absolute interpreter recorded in `.venv-path` with its exact environment lock:

```sh
tm1_python="$(sed -n '1p' .venv-path)"
tm1_lock=engineering/requirements/postprocess.txt
"$tm1_python" engineering/scripts/build_native_dependencies.py fetch-cmake --component result
"$tm1_python" engineering/scripts/build_native_dependencies.py publish --component result --python-lock "$tm1_lock"
```

Select the base or platform BO lock when that is the configured environment.
The build is offline after the fixed CMake tool is present.
Separate publication runs C static, C shared and C++ kernel callers, then checks exports and dynamic dependencies.
It writes `result-build.json` and retains a changed previous library with its matching record.
It does not build the solver or change a solver checkpoint identity.

Default source runtime paths are `solvers/native/lib/<host>/` under this package.
macOS uses `libtpmshx_result_shared.dylib`, Windows uses `tpmshx_result_shared.dll`, and Linux uses `libtpmshx_result_shared.so`.
Frozen applications use their `native/` directory.
`TPMSHX_RESULT_LIBRARY` can select an absolute prebuilt file.
Rebuild and restart the process after a C++ change.

Local builds, platform CI, original numerical comparisons, desktop operation and experimental validation are separate evidence.
See [implementation and retirement scope](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/main/docs/cpp-migration.md#cpp-core-scope).
