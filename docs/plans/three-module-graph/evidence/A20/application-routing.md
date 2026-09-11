# Public application routing repair (A20 / I51 / I52 / I56)

Status: implementation and local acceptance in progress; no PR, remote CI or merge for this batch.
Base: ebec9db8e144aa0e2774948ba8b9fbfed3a9c0a1. Branch: codex/tm1/apps-repair.

GUI and legacy configuration CLI now use Pipeline2D/3D -> public prepare_case ->
public run_case -> public evaluate -> result-only application mapping. No old
whole-pipeline replay is hidden inside the public modules. The independent
prepare/solve/postprocess/run commands remain available through the main CLI.
Iteration and residual callbacks stay in RunControl, outside persisted records.
The application adapter obtains headline metrics from PerformanceResult and
maps the recorded raw/display fields, properties, diagnostics and warnings into
the existing ComputeResult. Archived application mapping imports neither
preprocessing, numerical solvers, Numba nor Qt.

Q stays W/m in 2D and W in 3D. Labels, CSV, history and comparison use that unit;
comparisons across different or unknown units are omitted. Outlet-temperature
cache is refreshed before either dimension's presentation. Published-result
mode, rather than an edited draft, controls result-tab availability. The 3D
sidebar cannot show residual samples left over from a previous 2D run.

## Local evidence and failure provenance

Environment: /private/tmp/sjtu-tm1-io-venv/bin/python; 73-package exact lock and
pip check passed. No shared environment was modified.

- L2 actual public API + original finalizer comparison + HDF5 mapping in a new
  process: first 2 failed (shadowed runtime-state name and absent optional audit
  coefficients), then 2 passed in 10.81 s, native exit 0 after producer fixes.
- Production-pipeline/UI-hook/CLI/cancellation group: first 4 failed, 70 passed;
  tests that injected a private mutable stage dictionary now inject at the
  actual backend runtime seam. Error identity and worker-join assertions remain.
  Complete cancellation file: 24 passed in 2.39 s, native exit 0.
- Warning, raw outlet, pressure envelope, asymmetric porosity, port alignment
  and Richardson regressions: 130 passed, 3 deselected, 123 warnings in 9.07 s,
  native exit 0. Excluded tests are not claimed as passed.
- L2 real Main_Menu + actual compute worker, both dimensions, draft edits while
  running, Kelvin/Celsius output and actual CSV export: 2 passed in 8.01 s.
  This initial pass did not prove visible field rendering. Visual inspection
  subsequently identified the draft-mode tab gating defect and missing unit.
- The GUI harness initially blocked in a custom preflight dialog (terminated
  only its owned pytest process, native exit 143), then failed an incorrect
  title assumption (2 failures), a zero-width sentinel input (1 failure), and
  an assumption that existing solver warnings were errors (1 failure). The
  fixture now uses the existing bc_to_dict normalization, accepts only Warning
  preflight dialogs and retains all actual solver warnings and their counts.
- Visible-field test first passed 2D but failed 3D because optional eager slices
  were disabled. With TPMSHX_EAGER_3D_SLICES=1, both passed in 8.95 s, native 0.
  Offscreen PyVista panel remains disabled; these are 2D canvas / 3D mid-z slice
  checks, not evidence for interactive GPU volume rendering.

Logs and screenshots: .cache/tm1-apps/public-*.log, gui-{2,3}d.png,
gui-{2,3}d-preflight.txt, gui-{2,3}d-warnings.txt. Full fast-suite result and final
presentation verification will be appended once their native exits are known.
B20/B30 numbers are unchanged numerical references, not experimental Q acceptance.
B40's original failed baselines and M-B tracking remain unchanged.

Final GUI presentation check: 2 passed in 9.16 s, native exit 0
(`public-gui-presentation.log`). Both screenshots inspected: the 2D native
result remains visible with a 3D draft; the 3D mid-z slice remains visible with
a 2D draft. Sidebar units are W/m and W respectively. The 3D SIMPLE-A sparkline
is empty rather than showing the previous 2D run. The temperature slice panels
use a vertical layout on the existing narrow scroll canvas, and no longer call
the actually solved B field frozen. No new solve mode or threshold was added.
Graph validation passed 45 nodes / 110 edges; ruff passed the changed application,
module and integration-test trees. The first graph-tool invocation omitted the
required `validate` argument and exited 2; the corrected invocation passed.

## Full fast-suite snapshot

`fast-suite.log`: **5 failed, 2953 passed, 19 skipped, 82 deselected, 271 warnings**
in 426.56 s, native exit 1. All five failures asserted the old `Q [W]` CSV name
for a 2D result. The assertions now require `Q [W/m]` for 2D and retain `Q [W]`
for 3D. Every scalar, run-status, warning, extrapolation, array and non-object
archive assertion remains. This failed snapshot is not replaced by a claim of
full-suite success; the affected complete UI/export files are checked separately.
The first targeted follow-up command named a nonexistent test_cli.py (exit 4,
no tests ran); the corrected command uses test_cli_result_status.py.
Mypy passed all three changed controller/port files, native exit 0.

Targeted final repair and late presentation regression: **144 passed, 6 warnings**
in 36.85 s, native exit 0 (`ui-regressions-fixed-command.log`). This runs complete
I/O actions, UI layout hygiene, 3D publication state, worker handoff, run provenance,
pipeline contract and CLI result-status files. It covers the five failed CSV
assertions plus result-tab and display changes made during the full-suite run.
The full-suite failure remains recorded above; remote full/minimal CI is pending.
