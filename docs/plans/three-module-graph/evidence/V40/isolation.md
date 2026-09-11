# V40 isolation and minimal-runtime evidence

Source base: 222382bbcd0b333f457538cc12621273368a86c2, isolated branch
`codex/tm1/v40-isolation-repair`. No numerical implementation changes.
V40 remains running: actual minimal CI, independent review and merge are pending.

The actual public 2D and 3D solvers run in two threads after sequential
references. A third concurrent invocation shares the 2D Case and is cancelled
at the initial execution check. All three enter their run-local scope before
the barrier releases. The test compares native fields, boundary fluxes,
pressure evidence, convergence status, offline metrics and original Case
contents. It verifies detached result arrays and isolated progress. A callback
records the same warning key with three distinct notices, including the
cancelled call, proving registry isolation alongside unchanged physical notices.
This is a real numerical concurrency test with an artificial warning probe;
it does not prove cancellation during a later numerical iteration.

Configured interpreter: `/private/tmp/sjtu-tm1-io-venv/bin/python` via
`.venv-path`. Exact lock: 73 active packages matched; pip check passed. No
environment installation. Numerical resources: OPENBLAS_NUM_THREADS=1,
OMP_NUM_THREADS=1, NUMBA_NUM_THREADS=1; three outer Python threads. Matplotlib
and XDG caches are local. The CI integration step uses the same thread limits.

Command: `python -m pytest
sjtu_tpmshx/tests/integration_tm1/test_state_isolation.py -q --timeout=600
--timeout-method=thread`.

- Initial L2 test: 1 passed in 97.72 s, native exit 0 (`.cache/v40/isolation.log`).
- Final version with warning probe: 1 passed in 14.13 s, native exit 0
  (`.cache/v40/isolation-final.log`). These are correctness checks, not timing
  benchmarks; the second run had warmed compilation caches.
- Ruff and diff check passed. Workflow YAML parsed.

## Minimal runtime: configured, not yet executed

The CI job creates a full locked producer environment and runs the existing
real 2D/3D three-process tests. Their result and expected metric files remain
on the job filesystem. A different minimal venv then checks its exact lock,
pip compatibility, absence of installed Numba/Qt, and module imports. It
evaluates both actual result files and compares every metric specification,
status, reason and available value. Both W/m and W must occur. Missing producer
files fail the test. A final import check covers actual evaluation.

Local collection of the minimal-only test: 1 skipped, native exit 0 because
the local environment is full and no CI producer directory was supplied.
This is explicitly not minimal-runtime acceptance. Only the actual CI run can
supply that evidence. The job has no artifact upload; no result files are
published. The proposed upload variant was rejected by automatic approval
review and was never applied; the accepted local-file handoff removes that
external data transfer.
