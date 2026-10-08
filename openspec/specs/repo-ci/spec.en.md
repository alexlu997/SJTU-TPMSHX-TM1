# repo-ci Specification

[中文](spec.md) | [English](spec.en.md)

## Purpose
Define repository CI gates, installation, and exclusions for GitHub Actions and headless pytest. This specification originated in the `2026-07-02-cleanup-ci` archive, architecture scan batches D+F.

## Requirements

### Requirement: Headless CI gate on push/PR
The repository MUST give `.github/workflows/ci.yml` for main pushes and pull requests. Its platforms are macOS/Python 3.13 and Windows/Python 3.12 and 3.13. Installation MUST use the common exact lock referenced by `requirements.txt`. With `PYTHONHASHSEED=0`, it runs `pytest sjtu_tpmshx/tests/ -m "not slow and not heavy" --ignore=sjtu_tpmshx/tests/integration_tm1 -n 2 --dist loadscope`. The existing `ci_shard` plugin splits fast tests into two independent jobs. A third job runs all `tests/integration_tm1/` tests without marker filtering. This job checks real module handoff and numerical behavior. Qt MUST use offscreen mode. The fast gate MUST disable the 3D panel. CI MUST NOT depend on ignored local data assets.

Fast jobs MUST use two workers, one BLAS/OMP/MKL/NumExpr thread, and at most two Numba threads. The independent integration job MUST use at most one Numba thread. Each job MUST report its 30 slowest tests and skip reasons. JUnit XML MUST record individual statuses and durations. Test report artifacts stay available for 7 days.

Uploads cover reports, collection/shard lists, and resource records under `.cache/ci/`. They exclude native solver results and local data. Each platform summary MUST validate that both fast shards are complete and disjoint. It MUST require successful test shards, integration, BO, and native dependency qualification jobs.

Platform fast tests, real integration, and minimal postprocessing gates stay required. The four required checks are macOS 3.13, Windows 3.12, Windows 3.13, and minimal-postprocess. Speed improvements MUST NOT change numerical assertions or tolerances. Base and BO jobs MUST use the same platform/Python matrix. Both Windows versions use requirements-lock-server.txt.

#### Scenario: Integration is executed once per platform
- **WHEN** test sets from both fast shards and the integration job are combined
- **THEN** existing cases stay covered. Fast shards do not repeat the integration directory. New tests are recorded separately.

#### Scenario: Native dependencies are independently qualified
- **WHEN** native dependency jobs run on macOS/Python 3.13 or Windows/Python 3.12 and 3.13
- **THEN** jobs fetch pinned source and CMake from `native/dependencies-lock.toml`. They build offline and execute independent EOS/pressure, Quick Design, true-h, model-h, and SIMPLE callers. Complete drivers and public C interfaces are compared with the same-version Python reference. `TPMSHX_REQUIRE_NATIVE_DEPS_TESTS=1` makes missing executables or libraries failures. Skips cannot substitute for acceptance.
- **AND** only the independent native job builds dependencies. Ordinary fast shards do not rebuild them. Uploads include build logs and qualification XML. They exclude source archives, property tables, and local experimental data.

#### Scenario: CI green on a clean main
- **WHEN** the workflow runs on current main
- **THEN** the pytest subset has 0 failures and jobs pass. Skips are allowed where the applicable gate permits them.

#### Scenario: Environment-gated tests skip, not fail
- **WHEN** CI lacks local data assets or disables the 3D panel
- **THEN** the affected environment-gated tests skip instead of failing

### Requirement: Dead-reference cleanup with history preserved
Unusable historical benchmark scripts and retired polygon solver chains MUST leave the current tree. Fixed Git references in `docs/history/retired-tools.md` keep access. Kept tools MUST have real callers or verification uses. The 3D demo MUST use public `load_result` to read actual fields and the L design field from an existing `FieldResult`. It MUST NOT keep private solving or the previous `sigmoid_field_3d` generator.

#### Scenario: No dangling runnable references
- **WHEN** non-comment references to `validation/legacy/validate_shanghai.py` are searched
- **THEN** only archives and documents refer to it. No script claims it is runnable.

### Requirement: openspec history hygiene
Git history MUST keep completed changes. `openspec/changes/` MUST contain only active changes, without duplicate archived copies.

#### Scenario: Active list reflects reality
- **WHEN** `openspec/changes/` is inspected. The directory can be absent when no proposal is active
- **THEN** only active changes stay. The default Python environment does not require OpenSpec CLI.

### Requirement: Pytest config single source
Root `pytest.ini` MUST set `testpaths = sjtu_tpmshx/tests` and `--strict-markers`. It MUST register `slow`, `fast`, and `heavy`. Unregistered markers MUST cause collection errors.

#### Scenario: Bare pytest collects only the real suite
- **WHEN** `pytest --collect-only -q` runs at the repository root
- **THEN** all collected tests belong to `sjtu_tpmshx/tests/`, without worktree copies

#### Scenario: Typo'd marker fails loudly
- **WHEN** a test uses an unregistered marker, such as `@pytest.mark.slwo`
- **THEN** pytest reports a collection error

### Requirement: Public interface type gate
`mypy-core-files.txt` MUST explicitly list public interfaces and data contracts. The list includes the current envelope implementation, three-module APIs, data objects, and compatibility entries with active consumers. `pyproject.toml` MUST enable checking of unannotated bodies for envelope, preprocessing API, solver API, and postprocessing metrics. This does not claim strict type coverage for all solvers. `test_type_gate.py` MUST check the list in fast tests. It MUST verify that `prepare_case`, `run_case`, and `evaluate` reject incorrect input types. CI MUST NOT add a duplicate mypy step.

#### Scenario: Wrong public input types are rejected
- **WHEN** mypy checks calls that pass strings to the three public APIs instead of their data objects
- **THEN** all three calls report argument type errors. Actual code in the list must still have zero errors.

### Requirement: Parallel local gate
The complete local gate MUST support `pytest sjtu_tpmshx/tests/ -q -n auto --dist loadscope`. Before Python starts, set `PYTHONHASHSEED=0`, `NUMBA_NUM_THREADS=2`, and single-threaded BLAS/OMP. Local documentation defaults to `--dist loadscope`. Worker count can be fixed to suit resources. Existing 128-core server scripts keep worksteal. The [root README](../../../README.en.md#环境与检查) defines the interpreter, environment checks, and full command. The common dependency lock includes pytest-xdist.

#### Scenario: Parallel full suite green
- **WHEN** `pytest sjtu_tpmshx/tests/ -q -n auto --dist loadscope` runs with `PYTHONHASHSEED=0`
- **THEN** all actual tests enter acceptance, with 0 failures. Skips keep reasons. Historical timings are not speed promises for other machines.

### Requirement: Slow-marking policy — studies out, invariant gates in
`slow` identifies research or redundant equivalence checks. The same path must keep inexpensive coverage. Physical invariants MUST NOT become `slow` solely because they take time. `heavy` is a separate duration category. Markers are maintained per test. Physical invariants MUST NOT be removed, and exclusions MUST NOT expand merely to get passing CI.

Existing strict energy conservation, asym δ=0, and sizing checks stay in the full local gate. Fast CI excludes slow/heavy, then independently runs `integration_tm1`. Together they give continuous feedback but do not cover all expensive local numerical checks. The complete local gate without `-m` filtering stays the completion criterion.

#### Scenario: Fast subset materially faster
- **WHEN** CI parallelism or test grouping changes
- **THEN** there are 0 failures. Same-platform baseline and candidate timings record fast tests, integration, and total job wall time. Exclusions MUST NOT expand to improve speed.
