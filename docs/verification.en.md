# Local checks, CI and acceptance records

[中文](verification.md) · [English](verification.en.md) · [Project home](../README.en.md)

## Local environment and check commands

For local project execution, use the absolute interpreter on `.venv-path`'s first line.
If the task environment is missing or fails its checks, stop dependent work.
Use the [environment recovery workflow](collaboration.md#environment-recovery) under standing task authority.
Explain the impact and keep a recovery method before changes.
Pass the checks before switching pointers and resuming work.
Recovery uses the current applicable lock. Dependency version changes update declarations and exact locks together.
Shared environments contain locked dependencies only, without an editable project installation.
Do not modify an environment in use. Run from the current repository root.

```bash
PYTHON="$(head -n 1 .venv-path)"
"$PYTHON" -m sjtu_tpmshx.development.runs.tools.check_locked_environment
"$PYTHON" -m pip check
export MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg"
export QT_QPA_PLATFORM=offscreen PYTHONHASHSEED=0
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
"$PYTHON" -m ruff check .
"$PYTHON" -m engineering.scripts.check_types --platform darwin
"$PYTHON" -m engineering.scripts.check_types --platform win32
"$PYTHON" -m pytest tests/python -q -ra -m "not slow and not heavy" --ignore=tests/python/integration_tm1 -n 2 --dist worksteal --timeout=600 --timeout-method=thread --durations=30 --junitxml=.cache/ci/fast.xml
"$PYTHON" -m pytest tests/python/integration_tm1 -q -ra --timeout=600 --timeout-method=thread --durations=30 --junitxml=.cache/ci/integration.xml
# Complete local acceptance: no -m filter. Replace auto with a fixed worker count for available resources.
"$PYTHON" -m pytest tests/python -q -n auto --dist loadscope --timeout=600 --timeout-method=thread
```

PowerShell uses the same pytest arguments. Set the listed environment variables and call `& $tm1Python`. Provide a matching native library before tests.

On macOS and Windows with Python 3.13, CI splits fast test modules between two runners. Each runner uses two workers. `fast-0` uses `load --maxschedchunk=1` to limit work queued behind long sizing tests. `fast-1` uses `worksteal`. Each worker uses one BLAS and OMP thread. Windows integration runs in parallel with fast tests after the platform build. macOS runs integration in a separate process on the `fast-0` runner. Both platforms keep separate integration reports. Windows/Python 3.12 runs all integration tests and [compatibility cases](../tests/python/_ci_windows_312.txt) for actual rendering and 2D/3D resume.

<a id="qt-rendering"></a>

CI renders a real 3D volume in a separate Qt process. It checks field changes, PNG decoding, scaled images, application export, and closure. macOS uses Cocoa. Windows uses a fixed Mesa OpenGL software renderer. The pixel check explicitly skips macOS arm64 hosts with `Apple Software Renderer`. [PyVistaQt documents this rendering limit](https://github.com/pyvista/pyvistaqt/blob/v0.13.1/pyvistaqt/rwi.py). Full pixel checks on a physical Mac remain required locally for graphics dependency changes. The test artifacts include OpenGL details, process logs, and any generated PNG files and render reports. Physical Windows display acceptance remains separate.

Existing test helpers stay. `run_tests_fast.ps1` is development feedback only. Its `not heavy` subset differs from fast CI. The two PowerShell scripts validate the base lock by default. With an existing Windows BO environment, use `./engineering/scripts/run_tests_server.ps1 -LockFile engineering/requirements/bo-windows.txt`.

The same parameter is accepted by `run_tests_fast.ps1`. Tests start only after the selected lock and `pip check` pass. Scripts install nothing. A server lock does not permit unlisted packages.

Current macOS CI uses the `macos-15` arm64 image. GitHub [retired macOS 14 images](https://github.com/actions/runner-images/issues/13518) on 2026-11-02.
The protected summary check keeps its name, `tests (macos-14, 3.13)`. It still requires the current macOS jobs and all existing checks.
Branch protection and the required check set stay unchanged.

GitHub workflows use checkout v7, setup-python v7, upload-artifact v7, and download-artifact v8 for shard gates. Action runtimes do not change solver Python environments. The `minimal-postprocess` job in `ci` validates real files from a complete environment in a separate minimal environment. Base and separate BO runs cover macOS/Python 3.13 and Windows/Python 3.12 and 3.13. The `bo-tests` job runs on Windows for all runtime tiers and on macOS for the `application` tier. For the `full` tier on macOS, the `fast-0` test part runs BO first in its own environment. That step occurs before the part restores the solver library, and it keeps the BO environment variables local to the step. The macOS `full` tier then starts five jobs after its build: three native shards and two test parts. BO runs install platform-specific locks, validate environments, and explicitly import Torch/BoTorch/GPyTorch.

They run multi-condition optimizer tests, including both real Log acquisition functions. Base jobs keep the lock without BO and test missing-optional-dependency behavior. BO uploads JUnit reports and full collection manifests for 7 days, without solve data or environments.

<a id="published-native-images"></a>

### Published native image check

Python loads the native images from `sjtu_tpmshx/solvers/native/lib/<platform>/` in the current checkout.
A `TPMSHX_*_LIBRARY` variable can select another file. This check does not examine such a file.
To compare the published images with the export manifests, run one of these commands from the repository root:

```bash
"$PYTHON" engineering/scripts/build_native_dependencies.py verify-published
"$PYTHON" engineering/scripts/build_native_dependencies.py verify-published --directory <published directory>
```

The check does not build, load, or replace an image. It uses `nm` and `otool` on macOS.
On Windows, it uses `dumpbin`. Run it from a Visual Studio developer shell.
For each image, the check prints the inspected path, `source_commit`, and the number of `source_changes` from the build record.
A `WARNING: dirty build` line identifies an image that was built from a checkout with tracked changes.
A different source commit alone does not cause a failure.

The check fails when an image is missing or when its C exports differ from the manifest.
It also applies the import and dynamic dependency checks of the build verifier.
The manifests are `solver/solver.exports`, `preprocess/preparation.exports`, and `postprocess/result.exports`.
The Windows solver image does not export the six macOS SuperLU hooks. The check applies this exception.
Geometry has no export manifest. The check prints the geometry build record and does not compare its exports.
Use `--component geometry`, `preparation`, or `result` to check one image. On Linux, use `--component result`.

## CI scope and test shards

PRs and main pushes select checks through an [explicit path list](../engineering/scripts/ci_scope.py).

- `docs` applies to root README files, AGENTS, and Markdown files under `docs/` outside `docs/contracts/`. Check local links, anchors, and project module commands.
- `application` applies only to PRs with listed display and layout modules, icons, their tests, and optional documents. Run both platform builds, application tests, integration, BO, and real-file postprocessing.
- `full`: Solver, model, public interface, dependency, workflow, and all unlisted paths. Run the full matrix.

Only documentation changes can use the `docs` tier on main. Manual runs use `full`. Renames check both old and new paths. Unknown or empty change lists use the full matrix.
The full matrix has 27 jobs, including the independent Linux result-library builds.
Use full CI for timing comparisons and the relevant numerical studies for research acceptance.
Physical changes still require their extended numerical studies. Normal CI does not replace that evidence.

The `[tool.mypy].files` setting in `pyproject.toml` explicitly lists 19 files. Coverage includes configuration, controllers, CLI, the common workflow, current envelope implementation, three-module contracts/APIs, and the postprocessing metric entry. Deleted forwarding modules are excluded. `pyproject.toml` validates unannotated bodies in four boundary implementation modules. This does not show strict typing across each solver.

The `scope` job in `.github/workflows/ci.yml` runs `ruff check .` and `engineering.scripts.check_types` with `--platform darwin` and `--platform win32` one time for each change that is not in the `docs` tier. The pytest shards do not run ruff or mypy. Use the commands above for local checks.

The first pytest command excludes slow/heavy and `integration_tm1`. The second runs that complete integration directory one time. Neither replaces the third, complete local gate. Local commands run the unsharded subsets.

CI runs native qualification tests in native shards. The shared list is `tests/python/native/_ci_suite.txt`. Full CI on Python 3.13 also runs the stage modules in `tests/python/native/_ci_stage_suite.txt`, including their slow cases. Native pytest reads each list with `@<list-path>`. Application shards first record the full collection, then transfer these modules with `--ci-covered-modules=<list-path>`. Unlisted modules stay in application tests.

To reproduce an application shard, append `-p tests.python.ci_shard --ci-shard=0 --ci-manifest=.cache/ci/fast-0 --ci-covered-modules=tests/python/native/_ci_suite.txt`. For full CI on Python 3.13, also pass `--ci-covered-modules=tests/python/native/_ci_stage_suite.txt`. For shard 1, use `--ci-shard=1` with its own manifest directory. `tests/python/_ci_shard0.txt` lists modules for shard 0. Remaining application modules enter shard 1. Transfer and sharding occur after existing heavy markers and pytest filters.

The summary gate first checks complete, disjoint, successful native shards. It then combines application and native coverage against the original full fast collection. Duplicate or missing tests, missing workers, and failed records prevent a pass. Download all manifests for the same platform/Python combination, then run:

```bash
"$PYTHON" engineering/scripts/check_ci_shards.py .cache/ci/fast-0 .cache/ci/fast-1 --covered-by .cache/ci/native-*/native-manifest
```

Pass native shards in numeric order. Without `--ci-covered-modules`, local users can still check both complete fast shards separately.

Python 3.13 native qualification uses three shards on macOS and six on Windows. Each shard uses two workers with `loadscope`, which keeps each module or class in one worker. Measured case durations from the full matrix set the groups. Conservative energy tests keep each shared fixture parameter in one shard. Convergence, property, energy ledger and real replay checks for each parameter stay in one shard. Other modules keep their shared fixtures. Independent engineering-pair and 2D checkpoint cases can use complete node IDs.

Group lists are in `tests/python/native/`. macOS uses `_ci_macos_shard0.txt` through `_ci_macos_shard1.txt`. Windows uses `_ci_windows_shard0.txt` through `_ci_windows_shard4.txt`. Pass each list through `--ci-shard-modules=<list-path>` in numeric order. Unlisted cases enter the final automatic shard, 2 on macOS or 5 on Windows. Native engineering cases keep per-side physical models, convergence and energy limits. The 2D adapter tests compare fields, metrics, and callbacks with limited iterations.

Native jobs set `TPMSHX_REQUIRE_NATIVE_DEPS_TESTS=1`. Missing required libraries or callers fail the check. Test bridges link to the numerical targets from the platform CMake build. Native shards still run concurrency, process recovery and result ownership tests.

Independent formulas, discrete energy balances, manufactured solutions, component replay and fixed historical references replace Python solver comparisons. Retired iterators are not retained as a second solver.

Each platform calls the [native workflow](../.github/workflows/native.yml). It builds native libraries once with Python 3.13 and runs independent C/C++ callers. The native libraries do not link to a Python runtime. Python 3.12 and 3.13 use the same Windows build. Shards start after their platform build. Native, fast and integration tests use the same `native-build-<platform>` artifact from the current workflow run and source. The archive preserves executable permissions and includes runtime libraries, callers, and license notices. An exact CoolProp cache key binds platform, architecture, Python 3.13, toolchain image, the CoolProp inputs of the native dependency lock and `engineering/scripts/build_coolprop.py`. `build_coolprop.py cache-key --host <host>` prints the SHA-256 of the CMake version, generator, CoolProp pin, and host options. The digest also includes the CPM dependency pins and their patch files. SuperLU and AMGCL changes keep the cached archives. Project C++ and model coefficients rebuild on every run. Cache hits still require independent caller checks.

The `application` and `full` tiers both run the complete pilot build.
Archives include solver, geometry, preparation and result libraries and SDK comparison samples.
The separate `build --component result` step builds the result library before complete verification with the other libraries.
The full SDK check builds all C++ examples. It runs representative preparation, solve, resume, and postprocessing paths.
Linux minimal postprocessing starts when the macOS results and wheels and the Linux result libraries are ready. It can run in parallel with Windows qualification.
BO restores geometry, preparation and result libraries from the current platform build. It does not restore the solver library. It runs in parallel with that platform's other regression tests.

Build logs use `native-build-logs-<platform>`. Each shard uploads `native-dependencies-<platform>-py<version>-shard-<number>` with JUnit and `native-manifest`. Shard numbers are 0–2 on macOS and 0–5 on Windows. These artifacts are retained for 7 days.

Pass all shard manifests in numeric order to the same set checker. It verifies complete and disjoint selection and requires both `gw0` and `gw1` records per shard. Use `--serial` only for local serial tests with `controller` records. Native logs keep the 20 slowest tests and skip reasons.

Fast/integration logs keep the 30 slowest tests and skip reasons. Each group publishes separate JUnit and collection manifests as `test-reports-<platform>-py<version>-<fast-0|fast-1|integration>` for 7 days. Manifests include each pytest process's separate peak RSS. Process peaks cannot be summed as concurrent total peak. Statistics exclude ordinary child processes.

The three original `tests (<platform>, <version>)` required checks verify the expected job names and results for the selected tier.
The `docs` tier permits only the specified runtime jobs to be skipped. Document checks must pass.
Other tiers require successful builds, application, integration, BO, and postprocessing checks.
The `full` tier requires complete native coverage. The `application` tier permits only exact paths in the native module list to be omitted.
Each platform/Python summary also requires its BO and integration reports, successful collection records, and complete test counts.
The Windows/Python 3.12 summary uses these two reports for compatibility checks.
BO permits no skipped tests. Integration permits recorded individual skips, but a report with every test skipped must fail.
Unexpected failures, cancellations, skips, missing reports, or coverage gaps cannot pass.
The `minimal-postprocess` check stays separately required. In the `docs` tier, it only checks the expected job results.
Compare fast, integration, and full-job speed separately with same-platform baselines.

Local timing does not promise CI speedups. Acceptance skips keep specific reasons. Skipped capabilities are not passed.
Minimal-postprocess CI uses separate `engineering/requirements/postprocess.txt` and real 2D/3D files from another complete environment.
The independent `result-build` matrix runs on Ubuntu 24.04 and 26.04.
Each job fetches the locked CMake, builds the result library, checks the installed SDK, and runs independent numerical references.
Both builds must pass before the Ubuntu 24.04 `minimal-postprocess` job can run its file checks.
That job uses `result-build-linux-x86_64-ubuntu-24.04`; the Ubuntu 26.04 artifact remains separate.
The macOS integration step also supplies two public-example results and their metrics as `real-file-handoff` to that Linux minimal environment.
Both handoffs remain available for seven days and contain no private data.
The minimal job uses the prebuilt result library to read and evaluate real files from source and installed wheels.

Configuration alone does not show a CI pass.

## Collaboration and merge

Codex and Claude share the project rules in [AGENTS.md](../AGENTS.md). Use the
[collaboration workflow](collaboration.md) for task ownership, worktrees,
environments, synchronization, and handoff.

Public contract changes require downstream review. Solvers validate preprocessing configuration, units, and grids. Postprocessing validates native fields, boundary evidence, and states. Applications/file consumers validate metric definitions and file relationships. GUI and scheduling stay in `applications/gui/ui/` and `applications/gui/controllers/`. Model resources stay shared.

Each PR identifies affected interfaces, verification evidence, and reviewers. Current repository maintainer is `alexlu997`. Named module owners will be assigned when the additional colleague joins. Do not invent CODEOWNERS or describe model self-review as independent human approval.

The 2026-09-13 protection readback required PR updates, a branch current with main, and three GitHub Actions checks. They were `tests (macos-14, 3.13)`, `tests (windows-2022, 3.12)`, and `minimal-postprocess`. Rules also applied to administrators and prohibited force pushes/deletion. At least one non-author approval is planned when multiple people formally participate. At that recorded stage, required approval count was 0. GitHub is authoritative for actual state.

Windows supports Python 3.12 and 3.13. Protection keeps the preceding checks and adds `tests (windows-2022, 3.13)`, for four required checks. Other protections stay unchanged. Workflow edits do not automatically update GitHub protection settings. Before a merge, make sure that the required checks pass.

See [capabilities](capabilities.en.md) for current/open scope and [tools](tools.en.md) for measurements and reproduction boundaries.



## Data and historical evidence

Raw experiment/CFD data stays local under `data/raw_data/` and is not committed. [data-revision.txt](../data-revision.txt) records the matching version. [Model resources](model-resources.en.md) defines cleaning, fitting, and local output rules. Directories separate experiments, CFD results, and worklists. The [data catalog](data-catalog.en.md) maps Excel names, purposes, and reader constraints. Moving data requires corresponding loader and pressure-convention updates.

Optimization research scripts, per-case results, and exploratory reports stay in ignored `.cache/`, without code-repository commits or uploads. Keep long-term research evidence in a separate private archive. Git ignore rules are not backups. Local environments and `.venv-path` are also untracked and are reconstructed from versioned declarations and locks. Production optimization modules, regressions, CI workflows, locks, and usage/architecture documentation stay tracked.

Previous γ/RBF, SmoothDF, water developing-region, and previous sCO2 resistance models are retired. [Fixed history](history/legacy-models.md) keeps source/results. Current joint K/cF, original water Nu, and experimental D-F corrections stay. [Current effective coefficients](model-resources.en.md#sco2-有效-nu-系数) replace the previous sCO₂ anchored-gamma route and dedicated reports. Historical experimental errors stay unchanged. Missing current water CFD workbooks are not replaced by older files.

The [V2 README archive](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/docs/history/v2-readme.md) keeps original accuracy and physics descriptions. Previous image links are fixed to historical commits. The [history index](history/README.en.md) tracks removed images, optimization outputs, exploration, and Atlas snapshots. Those values do not show new acceptance of TM1 or current default CFD mode. Original B40 4/4 failures, nonconverged 3D screening, and other native failures stay. Thresholds and physical scope are not changed to fit results.

### Versions and validation scope

TM1 is maintained in [alexlu997/SJTU-TPMSHX-TM1](https://github.com/alexlu997/SJTU-TPMSHX-TM1). The original SJTU-TPMSHX/V2 repository is a source reference.

[v0.1.0](https://github.com/alexlu997/SJTU-TPMSHX-TM1/releases/tag/v0.1.0) is the first GitHub source release. It keeps both Python and C++ backends.
The 0.1 archives contain both solvers. Version 0.2 removes Python numerical iterators, their research entries and outer property Anderson. Fixed property relaxation, thermal acceleration and flow acceleration keep their existing rules. T-SOU (`temperature_sou`) is the default for the existing conservative EOS energy route. H-FOU and T-FOU execution is retired. Model-h and other temperature routes keep their physical contracts. Historical results remain readable; their checkpoints require the matching archived runtime. Build matching solver, geometry, preparation and result libraries before you run 0.2.

M-A merge acceptance for the rectangular 2D/3D three-module mainline is recorded. M-B extensions stay separately tracked. Historical B40 failures and physical applicability limits stay. See [capabilities and open work](capabilities.en.md) for current conclusions. The [fixed history index](history/README.en.md) keeps original plans, handoff records, and node evidence.

The 2026-10-05 candidate evidence keeps these limits. Ceff43 passed 19/43 and timed out on 24/43. The fixed population failed overall. fixed230 execution and indexing completed 230/230 in 93 minutes 18.5 seconds. Independent saved-state checks passed 229/230.

The first row was not evaluated because of an audit-tool error and was not retried. These checks do not show complete native configuration, iteration-history, F2, or experimental accuracy qualification.

At that historical check, source GUI evidence covered 2D/3D display and export.
Further visible checks awaited an unlocked Mac. They included cancellation, recomputation, menu save/reload, restart restoration, and outer iteration counts.
This paragraph records the 2026-10-05 status, not the desktop acceptance state of a later version. Merged PR #136 baseline `298761d2` passed macOS/Windows native CI. See the [CI record](https://github.com/alexlu997/SJTU-TPMSHX-TM1/actions/runs/37713153292). Earlier numerical failures stay attached to their original versions.

Engineering comparison, strict local regression, experimental accuracy, complete performance, and visible desktop acceptance keep separate thresholds. Folder startup and limited regression passes do not show full native qualification.
