<a id="桌面运行与可选打包"></a>

<a id="桌面软件构建与验证"></a>

# Desktop operation and optional packaging

[中文](desktop.md) | [English](desktop.en.md)

Normal delivery uses a project folder with Python/Qt, source, model resources, and a matching native library. Python and C++ are maintained backends. macOS arm64 and Windows x64 use the same interface. An `.app` is not required. Existing frozen packaging instructions stay below for explicit packaging needs.

<a id="source-folder"></a>

<a id="从项目文件夹运行"></a>

## Run from a project folder

Work from the repository root. Make sure that `.venv-path` starts with an existing absolute interpreter path on this host. Then run the [README environment checks](../README.en.md#环境与检查). The native library must match current adapters and headers. The source repository does not include local compiled outputs. See [C++ instructions](cpp-migration.md) for native dependency builds.

Keep these items in the project folder:

- Complete `sjtu_tpmshx/` source, including `configs/*.json`, `df_surrogate/_prebuilt/*.csv`, and interface resources.
- This host's `.venv-path`, the corresponding `requirements-lock*.txt`, usage examples, and operation instructions.
- A dynamic library that matches the source revision, platform, and ABI.
  Include `native/include/`, `native/dependencies-lock.toml`, `native/THIRD_PARTY_NOTICES.md`, and `native/licenses/`.
- Writable model-table and runtime-cache directories. Table files must stay outside dynamic-library and read-only resource directories.

The C++ commands below use the existing build process's output paths.

On macOS arm64:

```sh
tm1_python="$(sed -n '1p' .venv-path)"
export MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg"
export NUMBA_CACHE_DIR="$PWD/.cache/numba"
"$tm1_python" -m sjtu_tpmshx.main --backend python
```

To use C++, close that window and start with the matching library:

```sh
"$tm1_python" -m sjtu_tpmshx.main --backend cpp \
  --native-library "$PWD/.cache/native-deps/build/pilot-macos-arm64/libtpmshx_solver_shared.dylib" \
  --native-table-directory "$PWD/.cache/native-deps/tables"
```

On Windows x64 with PowerShell:

```powershell
$tm1Python = Get-Content .venv-path -TotalCount 1
$env:MPLCONFIGDIR = Join-Path $PWD '.cache/matplotlib'
$env:XDG_CACHE_HOME = Join-Path $PWD '.cache/xdg'
$env:NUMBA_CACHE_DIR = Join-Path $PWD '.cache/numba'
& $tm1Python -m sjtu_tpmshx.main --backend python
```

To use C++, close that window and start with the existing build output:

```powershell
$tm1Library = Join-Path $PWD '.cache/native-deps/build/pilot-windows-x64/tpmshx_solver_shared.dll'
$tm1Tables = Join-Path $PWD '.cache/native-deps/tables'
& $tm1Python -m sjtu_tpmshx.main --backend cpp --native-library $tm1Library --native-table-directory $tm1Tables
```

Replace the library path if it is stored elsewhere. The program does not search disks, compile libraries, download files, or install dependencies. The table directory must be writable. One native process uses one fixed table directory. CLI `run` and `solve` accept the same three backend options. For source operation, `TPMSHX_NATIVE_SOLVER_LIBRARY` does not replace explicit startup arguments.

The window's Compute Backend selection applies to the next ordinary computation, Quick Design, and optimization. Selection is locked during work and cancellation cleanup. Switching keeps published-result provenance and saved cases. Windows source startup requires an explicit library path. The macOS GUI also keeps its existing local folder-library default. CLI, independent C caller, and CI passes do not replace visible desktop acceptance on both platforms.

<a id="可选冻结打包"></a>

## Optional frozen packaging

`sjtu_tpmshx.desktop` starts the existing GUI and public three-module pipeline. `packaging/desktop.spec` uses PyInstaller to collect the interpreter, locked runtime dependencies, model configuration, DF table, and SVG icons. It excludes raw experimental data, research outputs, tests, and Office fonts. Default builds match `requirements-lock.txt` capabilities and exclude optional Torch/BoTorch dependencies. A complete BO distribution needs a separate lock and real optimization validation. Removing exclusions alone is insufficient.

Frozen Quick Design uses serial candidate search in one process to prevent child processes from starting another GUI. Source operation keeps its existing parallel path. The interface reports the actual execution mode.

The same spec can explicitly include a prebuilt unified native library. macOS uses `libtpmshx_solver_shared.dylib`. Windows uses `tpmshx_solver_shared.dll`. The library goes under `native/` in the package. Notices, native dependency lock, and complete licenses go under `licenses/native/`. Packaging downloads no dependencies, invokes no C/C++ compiler, and leaves Python as the default backend.

First build the native library through the existing native process. Complete its numerical qualification before packaging.

3D code uses targeted `vtkmodules` imports. Packaging excludes the former aggregate `vtk` entry, which loads all optional VTK modules. It keeps actual dependencies for PyVista, volume rendering, picking, transparency, and exports. After a VTK/PyVista version change, validate the import closure again. Do tests of 3D display and image/VTK export. Binary size alone is not a reason to delete a dependency.

Matplotlib explicitly collects Agg, QtAgg, SVG, and PDF backends for the GUI and three image export formats. Static import analysis alone misses vector backends selected dynamically by `savefig`.

macOS outputs an `.app`. Windows outputs a folder containing the executable and dependencies. Build on the target operating system. A macOS check cannot show Windows installation acceptance. See [PyInstaller usage](https://pyinstaller.org/en/stable/usage.html).

<a id="环境与构建"></a>

## Environment and build

Keep the shared solver environment and root `.venv-path` unchanged. With explicit authorization, install `requirements-lock-desktop.txt` in a separate build environment. It contains the original lock and pinned packaging tools. Save that environment's absolute interpreter path in `.cache/desktop-build/.venv-path`. Use it for the following modules from the repository root. Do not install build dependencies into the shared solver environment.

Before building, direct PyInstaller, Matplotlib, and general caches to ignored directories in this worktree. This avoids writing build caches to system user directories. On macOS:

```sh
export PYINSTALLER_CONFIG_DIR="$PWD/.cache/desktop-build/pyinstaller-cache"
export MPLCONFIGDIR="$PWD/.cache/desktop-build/matplotlib"
export XDG_CACHE_HOME="$PWD/.cache/desktop-build/xdg-cache"
```

On Windows PowerShell:

```powershell
$env:PYINSTALLER_CONFIG_DIR = Join-Path $PWD '.cache/desktop-build/pyinstaller-cache'
$env:MPLCONFIGDIR = Join-Path $PWD '.cache/desktop-build/matplotlib'
$env:XDG_CACHE_HOME = Join-Path $PWD '.cache/desktop-build/xdg-cache'
```

`PYINSTALLER_CONFIG_DIR` is PyInstaller's official build-cache variable. See [environment variables](https://pyinstaller.org/en/stable/man/pyinstaller.html#environment-variables). These settings apply to development-host builds. The desktop launcher manages installed-program startup caches, as described below.

```text
python -m sjtu_tpmshx.runs.tools.check_locked_environment requirements-lock-desktop.txt
python -m pip check
python -m PyInstaller --noconfirm --clean --distpath .cache/desktop-build/dist --workpath .cache/desktop-build/work packaging/desktop.spec
```

Without `TPMSHX_NATIVE_SOLVER_LIBRARY`, these commands keep the existing Python package. For a native candidate package, first set that variable to an absolute prebuilt library path for the target platform:

```sh
export TPMSHX_NATIVE_SOLVER_LIBRARY="/absolute/path/libtpmshx_solver_shared.dylib"
```

On Windows PowerShell:

```powershell
$env:TPMSHX_NATIVE_SOLVER_LIBRARY = 'C:\absolute\path\tpmshx_solver_shared.dll'
```

Then run the same PyInstaller command. A missing or empty explicit file, or an incorrect platform library name, fails the build. The library is never silently omitted. Only that prebuilt dynamic library and actual runtime dependencies are collected. Compilers, source trees, build directories, and property-table caches from `.cache/native-deps` are excluded.

Replace each example `python` with the absolute interpreter in the build pointer. Numba needs real source files to locate JIT caches. The spec collects and loads application modules as Python source files. This prevents archived relative code paths from breaking cache location when launched elsewhere. Before importing compute modules, the launcher directs JIT/Matplotlib caches to system user cache directories and calls `multiprocessing.freeze_support()`.

See [PyInstaller multiprocessing](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#multi-processing). Geometry-table caches also follow `XDG_CACHE_HOME`. Neither initial generation nor reuse writes to the program directory. Builds include only listed model resources and icons, without development-host sessions or caches.

<a id="选择原生候选后端"></a>

## Select the native candidate backend

Start a native candidate package with explicit `--backend cpp`. Without `--native-library`, a frozen program locates the platform library under its own `native/` directory. An explicit path always takes precedence. For source operation, use the host library path described above. No development-cache search, compilation, or backend substitution occurs.

These options construct this invocation's `RunControl`. They do not enter saved `CaseData` or physical configuration.

For example, run the packaged macOS executable directly:

```sh
"/path/SJTU-TPMSHX.app/Contents/MacOS/SJTU-TPMSHX" --backend cpp \
  --native-table-directory "/absolute/writable/path/native-eos-tables"
```

The same executable's `--cli run ...` and `--cli solve ...` accept these three host options. `--native-table-directory` selects a writable absolute path outside the package for sCO2 BICUBIC tables. It must not point to a read-only installation directory. One process fixes one table directory for its native library. Double-click startup without backend arguments still uses Python.

<a id="文件与状态"></a>

## Files and state

- Appearance preferences: `SJTU-TPMSHX-TM1` under the system user configuration directory.
- Sessions, presets, workspaces, and history: `SJTU-TPMSHX-TM1` under the system user data directory.
- GUI optimization results: `SJTU-TPMSHX-TM1/opt_runs` under Documents. Run status shows the actual path.
- Known user files in previous source directories are copied only when the destination file is absent. Originals stay.
- Packaged model/UI resources are read-only. Explicit CSV/NPZ/image exports follow the save-dialog path.

Ordinary computation, optimization, and Quick Design must finish their workers before closing the owning window or restarting. Cancellation is cooperative. It does not forcibly stop a thread before the numerical step ends. Optimization distinguishes normal completion, user cancellation, and execution failure. Valid candidates and run records already obtained stay.

Closing first saves current inputs. Save failure cancels closure by default. The user can continue editing, save configuration elsewhere, or explicitly discard and exit. Canceling closure does not interrupt active work. If session, preset, or workspace-marker encoding is damaged, the original is kept where possible as `.corrupt-<unique-ID>` beside it. Startup then uses defaults.

Rejected session JSON fields also keep an original copy. The notice gives the rejection reason and copy location. Non-object JSON roots are likewise isolated. Each rejection keeps a separate copy. After a read or isolation failure, saving retries protection of the original.

If backup still fails, the original is not overwritten. Close, workspace switch, and restart use the save-failure prompt. After directory permissions recover, saving can be retried. Saving a new session also works if the user has moved the original away.

<a id="交付验证"></a>

## Delivery validation

A successful build is only the first check. Copy the complete output outside the source tree. Launch it from another working directory. Do these checks:

1. Start the GUI. Do a check of fonts, icons, light/dark themes, parameter rail, and 3D rendering components.
2. Change preferences. Exit. Restart. Do a check of restoration. Make sure that no user-state files appeared in the program directory.
3. Run `--cli run INPUT OUTPUT --case-id CASE_ID` with public `air_2d.json` and `air_3d.json`. Keep exit codes, convergence, and metric support states.
4. Independently load results with `--cli postprocess RESULTS METRICS`. Make sure that Q units are W/m for 2D and W for 3D. Compare Q, pressure drops, and outlet temperatures with the same-version source baseline.
5. Complete a real GUI computation. Export CSV/NPZ. Do tests of close, cancellation, and restart protection during background work.

A native candidate package must repeat applicable calculations, cancellation, and error checks with explicit `--backend cpp`. Make sure that the copied package's library is loaded. Run without a C/C++ compiler. On macOS, use `otool -L` for dynamic dependencies. Use `otool -l` to record actual library/executable `LC_BUILD_VERSION minos`.

Use of Accelerate APIs available since macOS 13.3 does not prove a binary built with a newer SDK runs on 13.3. Declare minimum OS versions from final artifacts and target-system tests. Windows still requires real DLL, GUI, and export verification on Windows.

A locally ad-hoc-signed macOS build is not an Apple-notarized external distribution. Formal external release needs project signing credentials, notarization, and target-system verification. This document does not show availability of those credentials. Keep build logs, screenshots, installation runs, and numerical comparisons in ignored `.cache/`. Do not upload experimental data.
