# Existing experiment migration regression: in progress

2026-09-11. The original B20/B30 migration baseline is `5f1cafb`. A separate
worktree `/private/tmp/sjtu-tm1-real-exp-baseline` now preserves that checkout;
its configured 71-package interpreter passes the exact lock and pip check.
Current candidate uses its existing 73-package IO environment; the lock diff adds only h5py and PyYAML; all 71 shared package pins are
unchanged. Both configured interpreters are Python 3.13.

Original Shanghai and sCO2 experiment workbooks were located under
`/Users/luwenhuan/Documents/ChatGPT/SJTU-TPMSHX-data/raw_data`. Both worktrees
link only their ignored `data/raw_data` to that source. Source data are not
modified or committed. Output stays in each worktree's `.cache`.

The paired baseline/current runs have started; the reproducible observer is
`probe_shanghai.py`, invoked through runpy from each repository root.
The first running set is all 16 Shanghai rows through the existing real
`_run_one_case_pipeline` entry, not the measured-water-temperature kernel
path. The observer retains unrounded Q/dP/Tout, full config, diagnostics,
warnings and the existing experiment-comparison row separately for each case.
Exceptions remain failed rows, and any exception makes the process exit 1.
NaN diagnostic entries are preserved in the local scientific JSON; these
are not formal result-archive files or evidence of successful execution.

No completion or accuracy claim is made yet. Next pair the baseline with the
current candidate using the same fixed rows/data/config and compare unrounded
metrics and status before comparing experimental error. Continue the existing
3D and fixed sCO2 sets afterward; do not replace fixed denominators by a fresh
valid-row selection or infer experimental accuracy from migration equivalence.

The first paired attempts both exited 1 before solving: the generic loader
validated trailing worksheet rows after the declared 16-case set, encountering
NaN water state at index 16. Original logs/provenance remain under
`.cache/shanghai-migration*`. The observer now reads exactly the canonical
first 16 rows (`skiprows=2,nrows=16`) and applies the same absolute-water-pressure
conversion/state validation to every selected row. This is fixed-row selection,
not a valid-row filter or a changed denominator. The second paired attempts
use separate `.cache/shanghai-migration-v2` outputs and logs. Completion remains
pending; no failed attempt is counted as a successful solve.

The second pair reached solving but its observer called the nonexistent
`ComputeConfig.to_dict()`. The first recorded baseline row preserves this
AttributeError. Both runs were deliberately interrupted after diagnosis and
returned native exit 130; their partial results are not accepted. The observer
now uses stdlib `dataclasses.asdict`, checked against an actual ComputeConfig
with JSON serialization before restarting. The third paired runs use separate
`.cache/shanghai-migration-v3` outputs/logs. No solver, input row, physical
validation or convergence threshold was changed to fix the observer.
