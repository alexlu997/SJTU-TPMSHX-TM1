# Existing experiment migration regression: in progress

## Shanghai 3D fixed-16 result

Baseline `5f1cafb` and candidate `ae6f236` both completed 16/16 with native
exit 0 at the existing 20x10x3 mesh and max_outer=12. All configs are equal;
all rows report convergence. Maximum absolute differences are Q 2.274e-12 W,
dP_A 1.456e-11 Pa, dP_B 5.685e-14 Pa, Tout_A 1.137e-13 K and
Tout_B 1.706e-13 K. The largest relative difference is 8.471e-16.
Local captures/logs are `shanghai-3d-migration-v1` in each worktree;
the comparison is `.cache/shanghai-3d-comparison.json`.

Warnings are text-identical for 15/16. Row 1 retains all seven warnings with
the same side, stage, layout, extrema indices and outside counts. Only printed
extrema change in the last digits (air minimum 386.6748508845845 versus
386.6748508845846; water maximum 56.62509142717523 versus 56.62509142717519).
No warning context is lost in this 3D pair. This records migration differences;
it does not establish experimental accuracy or close B40.

## Shanghai 2D fixed-16 result

Both third attempts completed all 16 rows with native exit 0. Baseline
`5f1cafb0c7e461a8c30a8ea96920ce03a828e412` and candidate
`0ee79146d8de4da24379c91a44f2e59e1e0b52ca` have exactly equal unrounded
Q (W/m), both pressure drops (Pa), both outlet temperatures (K), and configs
in all 16 rows. All 16 report convergence; all 19 common diagnostic keys
are unchanged and none are lost. Local evidence is
`.cache/shanghai-pair-comparison.json` and the two `shanghai-migration-v3`
directories; earlier failed attempts remain preserved.

Warnings match in 15 rows. Row 1 exposed loss of the inlet B/scalar context
when preparing static properties. The preparation fix restores that context;
its regression fails before the fix and passes afterward (3 preparation tests,
native exit 0). This metadata repair does not alter the property calculation.

Using the existing measured total mass and inlet-cp experimental Q definition,
both revisions give Q RMSRE 0.02498361703128195 and bias 0.01382220143706865;
pressure-drop RMSRE is 0.6812256468519793 and bias -0.6794263886624797.
These are experimental errors, not an accuracy acceptance claim. In particular,
exact migration equivalence does not cure the pressure discrepancy.

The chronological attempt record below is retained; its pending statements
describe those earlier attempts. 3D and fixed-166 comparisons remain pending.

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

## Fixed sCO2 set located and checked

The preserved fixed-166 source is
`/Users/luwenhuan/.codex/worktrees/4393/SJTU-TPMSHX/.cache/p5-nu-calibration/fixed-166/frozen-launch-01/manifest.json`.
A current read confirms 166 unique jobs and 166 matching immutable config
snapshots. Each dimension retains Diamond 43 (33 train / 10 holdout) and
Gyroid 40 (31 train / 9 holdout), with the original job order, explicit
geometry, parameter version and reference records. This is the intended
subsequent migration pair; it has not been rerun here. The source configs,
references and measured values remain local and are not committed.

The distinct hot-side fixed-95 pressure membership must not replace this
Q set. Migration comparison must use the preserved config snapshots, not
rebuild membership via `--all-valid`. Historical Q accuracy failures remain
separate from any new before/after equivalence result.
