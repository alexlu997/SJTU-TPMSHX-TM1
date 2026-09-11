# Prepared-only 2D execution and first independent metrics

Base `8d3a4d0`, branch `codex/tm1/s20-repair`. Coordinated S20/R20/H10/I20
implementation; none of these nodes is marked done. Numerical runtime/coupling
move behind the Python backend, existing entry points share implementation,
and pure metric helpers move to `result_math`. True-h return adds native h and
face state without changing its numerical updates. Producer schema:
`schemas/three_module_v1/two_d.md`.

Environment: `/Users/luwenhuan/.venvs/sjtu-tpmshx-py313/bin/python`, worktree
root, 71-package exact lock and pip check pass. Pytest uses
`MPLCONFIGDIR=.cache/matplotlib XDG_CACHE_HOME=.cache`.

After `python -m pytest -q`:

- `sjtu_tpmshx/tests/solver_tm1/test_execution_2d.py sjtu_tpmshx/tests/test_import_layering.py`: 2 passed, native exit 0, 3.62 seconds. Prepared grid, design validation, unknown model rejection, deleted config snapshot and cancellation contract.
- `sjtu_tpmshx/tests/integration_tm1/test_2d_real.py --timeout=600 --timeout-method=thread`: initial B20 air run 1 passed, native exit 0, 14.13 seconds. Original five scalar observations match at rtol/atol 1e-10, actual grid 36x56, converged True. Both preprocessing functions are prohibited during execution.
- `sjtu_tpmshx/tests/test_outlet_temperature_2d.py sjtu_tpmshx/tests/test_true_h_ledger.py sjtu_tpmshx/tests/test_pipeline_reexports.py sjtu_tpmshx/tests/test_cooperative_cancel.py --timeout=600 --timeout-method=thread`: 47 passed, 10 preserved warnings, native exit 0, 116.36 seconds. Includes 2D/3D last-thermal ownership, cancellation/exception behavior and existing re-exports.
- `sjtu_tpmshx/tests/integration_tm1/test_2d_real.py sjtu_tpmshx/tests/postprocess_tm1 sjtu_tpmshx/tests/test_import_layering.py --timeout=600 --timeout-method=thread`: 6 passed, 5 preserved warnings, native exit 0, 9.66 seconds. B20 air plus both original mixed partial-port cases; independent Q/dP/Tout match original reporting scalars after those scalars are removed from postprocessing input. Mixed cases preserve False convergence and final-post ownership, and distinguish raw/display T.
- `sjtu_tpmshx/tests/solver_tm1/test_execution_2d.py sjtu_tpmshx/tests/preprocess/test_2d_tm1.py sjtu_tpmshx/tests/postprocess_tm1`: 5 passed, native exit 0, 1.60 seconds after freezing static inlet properties.
- `python -m ruff check sjtu_tpmshx`: pass, native exit 0.

The numerical test tolerances compare architecture behavior to the unchanged
historical B20 observations. They do not replace B40 pins or experimental
acceptance. H10 currently implements 2D; 3D, formal file/process handoff,
application routing, complete design-mode regression, independent review and
remote CI remain unfinished. Missing solid density explicitly leaves mass
unavailable. Existing failure provenance stays in earlier node evidence.

Subsequent checks:

- After static-property freezing, the real three-case selection plus import
  layering passed 4/4, native exit 0, 7.96 seconds.
- Adding prepared port-consistency validation exposed an intermittent initial
  import race: the real/native plus outlet selection returned 1 failed / 16
  passed, exit 1; isolated B20 reproduced an ImportError for ZoneConfig, exit 1.
  Two SIMPLE threads first-imported the old alias concurrently. Old model
  entry points now publish their exports before aliasing, and new backend
  imports use the canonical model package. A fresh-process concurrent-import
  check was added. No numerical formula, raw port fraction or acceptance
  tolerance changed to address the failure.
- Final model/native/layering selection:
  `sjtu_tpmshx/tests/models_tm1 sjtu_tpmshx/tests/integration_tm1/test_2d_real.py sjtu_tpmshx/tests/test_import_layering.py --timeout=600 --timeout-method=thread`
  passed 7/7 with 5 preserved applicability warnings, native exit 0, 9.04
  seconds. Repository ruff also passed with native exit 0.
