# Native stage interfaces

[中文](native-stages.zh-CN.md) | [English](native-stages.md)

## Scope

The native stage work adds independent preparation, execution and evaluation
interfaces. The existing Python entry points remain the production route until
the corresponding stage passes its acceptance checks. The current first-stage
preparation interface supports uniform, symmetric 2D air/air cases with a
prescribed inlet velocity. Other modes must report an error at that interface.
This limit does not remove any mode from the existing Python workflow.

Full 2D/3D Python evaluation now calls the native result stage. Independent applicability, physical-balance and qualification queries use that stage.
Quick Design metric arithmetic retains its current protocol owner. The public Python entry points and saved formats stay available.
The host query uses borrowed typed evidence and preserves deferred input errors. It delivers NumPy events before each primitive returns.
A callback error is handled at the original metric or qualification boundary. An uncaught host error retains its original Python object.
Published v1 C layouts and queries remain available. Release every output through the library that created it.

The C++ call sequence is `prepare_case`, `run_case`, then `evaluate`.
The caller supplies dimensions, design values, boundary conditions and controls.
The preparation library computes the physical fields. The solver library uses
that prepared state. The result library evaluates recorded evidence.

## Ownership and units

- Use the units in the input field names. The design input uses mm. Saved
  physical design fields use m. Preserve the existing mm-to-m-to-mm operations
  when the execution adapter makes its transport and closure inputs.
- The requested grid counts and the actual grid counts are different fields.
  Physical 2D fields have shape `(nx, ny)` and C order. Flow fields use the
  existing `(cross, stream)` order for each side.
- A successful C call returns one owner. All array and text views belong to
  that owner. Release it through the same library after the last use.
  Do not copy owners or free their buffers with a caller allocator.
- Callbacks receive borrowed event views on the caller thread. They do not
  perform numerical preparation. Keep event order, logger names and messages.
- The host owns case IDs, timestamps, file paths and Python object conversion.
  The native stages own physical rules, numerical defaults and evidence.
- Preparation and solver libraries use their separate locked CoolProp builds.
  The result library does not link preparation, solver, CoolProp or Qt.
- Existing low-level ABI versions remain available. A retained run library
  must not need a new preparation symbol to restore its saved run state.

## Build and install

Use the setup and locked dependency commands in [README](../README.en.md).
The new CMake entry only uses prepared local dependencies. It does not fetch
sources, install Python packages or replace published runtime libraries.

Generate the two model headers with the interpreter from `.venv-path`:

```sh
"$PYTHON" -m engineering.scripts.generate_native_model_coefficients \
  --output .cache/stages/generated/tpmshx/model_coefficients.hpp \
  --df-output .cache/stages/generated/tpmshx/preparation_df_data.hpp
```

Use the locked CMake executable. On macOS, supply the distinct preparation and
solver archives from the accepted native dependency cache:

```sh
"$CMAKE" -S sjtu_tpmshx/solvers/native -B .cache/stages/build \
  -DTPMSHX_NATIVE_DEPS_ROOT="$PWD/.cache/native-deps" \
  -DTPMSHX_MODEL_INCLUDE_DIR="$PWD/.cache/stages/generated" \
  -DTPMSHX_PREPARATION_COOLPROP_LIBRARY="$PWD/.cache/native-deps/build/coolprop-preparation-macos-arm64/libCoolProp.a" \
  -DTPMSHX_SOLVER_COOLPROP_LIBRARY="$PWD/.cache/native-deps/build/coolprop-macos-arm64/libCoolProp.a" \
  -DCMAKE_INSTALL_PREFIX="$PWD/.cache/stages/install"
"$CMAKE" --build .cache/stages/build --config Release --parallel 1
"$CMAKE" --install .cache/stages/build --config Release
```

Windows uses `-A x64` and the locked `Release/CoolProp.lib` archive for both
roles. Use the paths in the accepted dependency cache. The separate component
projects keep their existing compiler options and exported symbols.

Set `-DTPMSHX_COMPONENTS=result` for an independent result-only build. It does
not require model headers or EOS dependencies. Linux supports this component
only. An installation contains the selected shared libraries, C ABI headers,
CMake package configuration and applicable source notices.

An external C++ project can use the installed package:

```cmake
find_package(tpmshx CONFIG REQUIRED COMPONENTS result)
target_link_libraries(my_program PRIVATE tpmshx::result)
```

The [external result client](../examples/cpp/result_client.cpp) checks arrays and evaluates historical evidence through public headers.
The [complete 2D example](../examples/cpp/air_2d.cpp) starts with raw dimensions, conditions and boundaries.
It prepares, solves and evaluates the case without numerical fields from Python.
It does not start or link Python. Both examples use only installed public headers and shared libraries.
The Windows build copies the required DLLs beside each executable.

```sh
"$CMAKE" -S examples/cpp -B .cache/stages/examples \
  -DCMAKE_PREFIX_PATH="$PWD/.cache/stages/install"
"$CMAKE" --build .cache/stages/examples --config Release
"$CTEST" --test-dir .cache/stages/examples -C Release --output-on-failure
```

C++ preparation, run and evaluation objects can move but cannot copy.
The run result owns all evidence needed for evaluation. The caller can release the prepared object after `run_case`.
The C headers specify ownership and borrowed views for direct C calls.
A null metric request returns all metrics for the mode.
A selected metric retains its units, definition version, status and reason.
Independent applicability, physical-balance and qualification queries use the same result library.

After the dependency build, this check reuses component build directories and installs a temporary SDK.
It builds and runs external callers outside the source tree:

```sh
"$PYTHON" engineering/scripts/build_native_dependencies.py check-stages
```

Use the applicable environment lock. A BO environment needs its matching `--python-lock` option.
On Linux, add `--component result --python-lock engineering/requirements/postprocess.txt`.
The check retains logs and 2D comparison fields. It removes the temporary installation and external build directories.
This basic 2D path does not establish stage migration for fixed flow, other fluids, zones, 3D or Quick Design.
Python integration and checkpoint recovery have separate acceptance gates.
