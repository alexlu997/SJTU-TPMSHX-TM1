# repo-ci Specification

[中文](spec.md) | [English](spec.en.md)

## Purpose
Define repository CI gates, installation, and exclusions for GitHub Actions and headless pytest. This specification originated in the `2026-07-02-cleanup-ci` archive, architecture scan batches D+F.

## Requirements

### Requirement: Headless CI gate on push/PR
The repository MUST provide `.github/workflows/ci.yml` for main pushes and pull requests.
Its platforms are macOS/Python 3.13 and Windows/Python 3.12 and 3.13.
Installation MUST use the common exact lock referenced by `requirements.txt`.
`engineering/scripts/ci_scope.py` selects the required tier from the complete change:

| Tier | Permitted change | Required work |
| --- | --- | --- |
| docs | Only the declared documentation paths | Document links, project commands, and all four summary gates with explicit skipped-job expectations |
| application | Only PRs with declared display files, icons, and documentation | Platform application tests, real module integration, BO, minimal postprocessing, and the matching native build |
| full | Other or mixed changes, main pushes with code changes, and manual runs | All application work and complete native qualification on each platform with Python 3.13 |

Main pushes with only declared documentation paths use the docs tier. Unknown or empty changes use full CI.

With `PYTHONHASHSEED=0`, Python 3.13 fast tests use `-m "not slow and not heavy"`, exclude `integration_tm1`, and run with `-n 2`.
`fast-0` uses `--dist load --maxschedchunk=1`; `fast-1` uses `--dist worksteal`.
The existing `ci_shard` plugin splits them into two independent jobs.
Each integration process runs all `tests/python/integration_tm1/` tests without marker filtering.
On Windows/Python 3.12, integration also runs the rendering and resume cases in `tests/python/_ci_windows_312.txt`.
Windows integration runs in separate jobs. macOS integration uses the `fast-0` runner. On the `full` tier, the macOS `fast-0` runner also runs BO in its own environment before it restores the solver library.
Fast tests and integration MUST produce separate reports when the platform runtime is ready.
Routine Qt tests use offscreen mode with the 3D panel disabled.
Actual rendering uses a separate native Qt process; the [verification guide](../../../docs/verification.en.md#qt-rendering) gives the platform requirements and evidence limits.
CI MUST NOT depend on ignored local data assets.

Fast jobs MUST use two workers and one BLAS/OMP/MKL/NumExpr thread. Each job MUST report its 30 slowest tests and skip reasons. JUnit XML MUST record individual statuses and durations. Test report artifacts stay available for 7 days.

Uploads cover reports, collection/shard lists, and resource records under `.cache/ci/`. They exclude native solver results and local data. The shared `tests/python/native/_ci_suite.txt` list MUST select native qualification modules. In full CI, Python 3.13 native shards also run `tests/python/native/_ci_stage_suite.txt`, including slow tests. Application shards MUST transfer these modules and keep the original full collection. New modules outside the lists MUST enter application tests.
The application tier allows omissions only for the shared native list. Fast stage cases stay in the application shards. Linux result builds run the independent numerical comparisons. Native shards and BO jobs can use a verified pair of matching runtime archives from a successful push to a main ancestor. The current commit must pass its own build and qualification. If the pair is unavailable or an input changed, tests wait for their platform build. Python 3.13 summaries MUST check complete and disjoint native shards and application coverage. Each summary MUST require its integration and BO reports. Windows/Python 3.12 uses these reports for compatibility.

Platform fast tests, real integration, and minimal postprocessing gates stay required. The four required checks are macOS 3.13, Windows 3.12, Windows 3.13, and minimal-postprocess. Speed improvements MUST NOT change numerical assertions or tolerances. Base and BO jobs MUST use the same platform/Python matrix. Both Windows versions use engineering/requirements/bo-windows.txt.
Minimal postprocessing waits for the macOS and Linux artifact producers and runs independently of Windows qualification.

#### Scenario: Integration is executed once per platform
- **WHEN** test sets from both fast shards and the separate integration process are combined
- **THEN** existing cases stay covered. Fast shards do not repeat the integration directory. New tests are recorded separately.

#### Scenario: Native tests run once per platform
- **WHEN** application shards transfer modules from the shared list to native shards
- **THEN** native shards must pass and cover their full collection. Combined coverage has no duplicates or gaps. Missing or failed manifests prevent a pass.
- **AND** tests for concurrent threads, process recovery, and result ownership stay in native shards with unchanged assertions

#### Scenario: Native dependencies are independently qualified
- **WHEN** native dependency jobs run on macOS or Windows with Python 3.13
- **THEN** one build job per platform fetches pinned source and CMake from `engineering/native_build/dependencies-lock.toml` and builds offline.
  Qualification jobs use the selected matching native artifacts and execute independent EOS/pressure, Quick Design, true-h, model-h, and SIMPLE callers.
  Independent formulas, discrete balances, manufactured solutions, component replay, and fixed historical references check complete drivers and public C interfaces. `TPMSHX_REQUIRE_NATIVE_DEPS_TESTS=1` makes missing required executables or libraries failures. Skips cannot substitute for acceptance.
- **AND** the native build job compiles the test bridges and runs the standalone callers. Python shards reuse the CMake-built bridges. Uploads include build logs and qualification XML. They exclude source archives, property tables, and local experimental data.

#### Scenario: CI green on a clean main
- **WHEN** the workflow runs on current main
- **THEN** the pytest subset has 0 failures and jobs pass. Skips are allowed where the applicable gate permits them.

#### Scenario: Environment-gated tests skip, not fail
- **WHEN** CI lacks local data assets or disables the 3D panel
- **THEN** the affected environment-gated tests skip instead of failing

### Requirement: Dead-reference cleanup with history preserved
Unusable historical benchmark scripts and retired polygon solver chains MUST leave the current tree. Fixed Git references in `docs/history/retired-tools.md` keep access. Kept tools MUST have real callers or verification uses. Non-product 3D demo and render showcase scripts MUST NOT stay in the current tree.

#### Scenario: No dangling runnable references
- **WHEN** non-comment references to `validation/legacy/validate_shanghai.py` are searched
- **THEN** only archives and documents refer to it. No script claims it is runnable.

### Requirement: openspec history hygiene
Git history MUST keep completed changes. `openspec/changes/` MUST contain only active changes, without duplicate archived copies.

#### Scenario: Active list reflects reality
- **WHEN** `openspec/changes/` is inspected. The directory can be absent when no proposal is active
- **THEN** only active changes stay. The default Python environment does not require OpenSpec CLI.

### Requirement: Pytest config single source
Root `pyproject.toml` MUST use `[tool.pytest.ini_options]` to set `testpaths = tests/python` and `--strict-markers`. It MUST register `slow`, `fast`, and `heavy`. Unregistered markers MUST cause collection errors.

#### Scenario: Bare pytest collects only the real suite
- **WHEN** `pytest --collect-only -q` runs at the repository root
- **THEN** all collected tests belong to `tests/python/`, without worktree copies

#### Scenario: Typo'd marker fails loudly
- **WHEN** a test uses an unregistered marker, such as `@pytest.mark.slwo`
- **THEN** pytest reports a collection error

### Requirement: Public interface type gate
The `[tool.mypy].files` setting in `pyproject.toml` MUST explicitly list public interfaces and data contracts. The list includes the current envelope implementation, three-module APIs, data objects, and compatibility entries with active consumers. `pyproject.toml` MUST enable checking of unannotated bodies for envelope, preprocessing API, solver API, postprocessing API, and postprocessing metrics. For each change that is not in the `docs` tier, the `scope` job in `.github/workflows/ci.yml` MUST run `ruff check .` and `engineering.scripts.check_types` with `--platform darwin` and `--platform win32` one time. The pytest shards MUST NOT run ruff or mypy again.

### Requirement: Parallel local gate
The complete local gate MUST support `pytest tests/python/ -q -n auto --dist loadscope`. Before Python starts, set `PYTHONHASHSEED=0` and single-threaded BLAS/OMP. Local documentation defaults to `--dist loadscope`. Worker count can be fixed to suit resources. Existing 128-core server scripts keep worksteal. The [verification guide](../../../docs/verification.en.md) defines the interpreter, environment checks, and full command. The common dependency lock includes pytest-xdist.

#### Scenario: Parallel full suite green
- **WHEN** `pytest tests/python/ -q -n auto --dist loadscope` runs with `PYTHONHASHSEED=0`
- **THEN** all actual tests enter acceptance, with 0 failures. Skips keep reasons. Historical timings are not speed promises for other machines.

### Requirement: Slow-marking policy — studies out, invariant gates in
`slow` identifies research or redundant equivalence checks. The same path must keep inexpensive coverage. Physical invariants MUST NOT become `slow` solely because they take time. `heavy` is a separate duration category. Markers are maintained per test. Physical invariants MUST NOT be removed, and exclusions MUST NOT expand merely to get passing CI.

Existing strict energy conservation, asym δ=0, and sizing checks stay in the full local gate. Fast CI excludes slow/heavy, then independently runs `integration_tm1`. Together they give continuous feedback but do not cover all expensive local numerical checks. The complete local gate without `-m` filtering stays the completion criterion.

#### Scenario: Fast subset materially faster
- **WHEN** CI parallelism or test grouping changes
- **THEN** there are 0 failures. Same-platform baseline and candidate timings record fast tests, integration, and total job wall time. Exclusions MUST NOT expand to improve speed.
