# Independent result core: sources and interfaces

The standalone CMake project builds `tpmshx_result_shared` with C++17 and system libraries.
It does not use solver state, geometry, preparation, CoolProp, Eigen, SuperLU or AMGCL.
It needs no generated model headers. Linux x86_64 support applies to this component only.
The full application retains its macOS arm64 and Windows x64 platforms.

## Numerical owners

| Source | Responsibility |
| --- | --- |
| `native/postprocess/result_core.cpp` | Checked contiguous `float64` array views, `int32` label views and diagnostic helpers. |
| `native/postprocess/result_arithmetic.cpp` | Private `float64` arithmetic and reductions used by named result calculations. |
| `native/postprocess/result_metrics.cpp` | Pressure faces, duties, mass flow, outlet values, integrated mass and Quick Design metrics. |
| `native/postprocess/result_balance.cpp` | Independent signed mass and energy balances, residual norms and zone statistics. |
| `native/postprocess/result_checks.cpp` | Range observations, qualification predicates, envelope helpers and physical mass bounds. |
| `native/numerics/scalar_range_samples.hpp` | Select scalar observations and collect extrema and bound counts. Preparation uses the same code. |
| `native/postprocess/result_stage.cpp` | Full metric selection, definitions, statuses, applicability, physical balances and qualification. |
| `native/postprocess/result_stage_c_api.cpp` | Owned stage reports, borrowed evidence and versioned host event/error control. |
| `native/postprocess/result_c_api.cpp` and family C interfaces | Versioned C functions with checked buffers and ordered floating-point diagnostics. |

`scalar_range_samples.hpp` is a private source dependency.
Preparation and result compile it separately; preparation does not link the result library.
`result_zone_capture.hpp` supplies the same checked zone query to the solver and result libraries.
The solver links the zone arithmetic statically.

Python retains DTOs, `float64`/`int32` input normalization, fixed `RuntimeWarning` diagnostics and file I/O.
The result stage owns full 2D/3D and Quick Design evidence selection, metric arithmetic, status and reason text.
The four public computation entries remain unchanged.
Independent original numerical references stay under `tests/python/`.
Production result calculations do not call those references.

## Original numerical rules and notices

The result core runs all metric, balance, zone and check calculations in IEEE-754 `float64` (`double`), with `int32` zone labels.
It does not link or call NumPy or the Python runtime.

- NumPy 2.5.4 pairwise reduction rules use the existing
  [complete BSD notice](../../engineering/native_build/licenses/numpy-LICENSE.txt).
  The reduction reference is `numpy/_core/src/umath/loops_utils.h.src`.
  `result_arithmetic.cpp` retains pairwise binary64 summation and `float64` element operations.
- CPython 3.13.2 compensated float summation uses the existing
  [complete release license](../../engineering/native_build/licenses/python-v3.13.2-LICENSE.txt).
  The reference is `Python/bltinmodule.c`, `CompensatedSum` and the float path of `builtin_sum_impl`.
  The equivalent CPython 3.12.9 float path is also used by the supported Windows interpreter.
  The port accepts a finite sequence of binary64 values already converted at the Python boundary.
  It retains correction order, nonfinite handling and the final correction condition.
  It does not implement Python's general iterable or arbitrary object summation.

Keep these source records and complete notices with binary distributions.
The source distributions also retain the CMake project, export lists, headers and independent callers.

## C interface and ownership

Result ABI 3 is separate from the solver, geometry, field and preparation ABIs.
The query function keeps its `_v1` query signature and returns `3`.
The adapter rejects earlier library ABIs before binding numerical calls.
Its declarations are in `native/include/tpmshx/result_c_api.h` and the family and stage headers.
Only the symbols in `result.exports` and `result.map` are public.
There is no public arithmetic opcode evaluator or callback that supplies complete metrics.

Arrays borrow contiguous `float64` buffers (`tpmshx_result_array_v2`: `data`, `rank`, `shape`) for one call.
Zone labels borrow contiguous `int32` buffers (`tpmshx_result_labels_v1`: `data`, `rank`, `shape`).
Callers own input and output storage. Kernels use contiguous `float64` temporary arrays.
Failure does not commit numerical outputs. Writable buffers must not overlap other call buffers.
Readonly input views can share storage.
`NaN` and `Inf` remain valid input values so historical `.h5` results can be evaluated.

`tpmshx_result_stage_query_v3` uses the flattened `tpmshx_stage_input_v3` descriptor with explicit `abi_version` and `struct_size` checks.
Quick Design operands and labels are passed by `float64` pointers and C strings; there are no per-operation Quick callbacks.
Deferred conversion errors and floating-point event callbacks are consumed at the original metric or qualification boundary.
Uncaught host exceptions return their original token. Stage outputs are released through their originating library.
Host callbacks do not own query state. Query exit clears deferred error references, including errors from input packing.
Deferred errors retain their exception objects, cause/context links and group members, without their earlier tracebacks.
Stage calls reject a wrong output size or an owner that was not released.
Those rejected calls leave borrowed inputs, the old output, error text and host diagnostics unchanged.

Status 1 means invalid C input, 2 means allocation failure, and 3 means runtime failure.
Status 4 carries the original numerical exception cause.
Ordered floating-point events precede a later numerical exception when the original expression did so.
The Python adapter emits `RuntimeWarning` for divide-by-zero, overflow and invalid-value events, and ignores underflow.
Missing files, symbols or a wrong ABI remain deployment errors.
There is no numerical fallback or runtime compilation.

`python/cpp_interface/_native_result.py` loads the image only when a numerical call needs it.
Public imports and pure HDF/JSON reads do not load it.
Full evaluation and independent result queries require the current stage image, including queries with missing evidence.
A missing stage symbol is a deployment error. Missing physical evidence retains its original result status and reason.
`python/cpp_interface/_native_result.py` rejects non-real arrays and booleans at the boundary before native execution.

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

Default source runtime paths are `native/lib/<host>/` under the repository root.
macOS uses `libtpmshx_result_shared.dylib`, Windows uses `tpmshx_result_shared.dll`, and Linux uses `libtpmshx_result_shared.so`.
Frozen applications use their `native/` directory.
`TPMSHX_RESULT_LIBRARY` can select an absolute prebuilt file.
Rebuild and restart the process after a C++ change.

Local builds, platform CI, original numerical comparisons, desktop operation and experimental validation are separate evidence.
See [implementation and retirement scope](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/main/docs/cpp-migration.md#cpp-core-scope).
