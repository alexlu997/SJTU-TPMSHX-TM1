# M-A final acceptance, 2026-09-11

PR #7 was normally merged after explicit user approval at 07:07:03 UTC.
Accepted main: `8ad9a55e9f0354d203337021903be5eaaab09b3b`.
PR candidate: `1f9bc07ee3f49565b250d7cc638ec4005024def4`.
The candidate and merged main have identical file trees (git diff empty).

- Candidate matrix [34570154000](https://github.com/alexlu997/SJTU-TPMSHX-TM1/actions/runs/34570154000): success.
- Candidate minimal environment [34570153963](https://github.com/alexlu997/SJTU-TPMSHX-TM1/actions/runs/34570153963): success.
- Main matrix [34572907461](https://github.com/alexlu997/SJTU-TPMSHX-TM1/actions/runs/34572907461): success.
- Main minimal environment [34572907401](https://github.com/alexlu997/SJTU-TPMSHX-TM1/actions/runs/34572907401): success.

The matrix covers macOS/Windows fast tests and real public 2D/3D integration.
Minimal CI produces real 2D/3D HDF5 results and evaluates them without Numba/Qt.
After merge the configured interpreter passed the 73-package lock checker and
pip check, both native exit 0. From the merged worktree root, with local
MPLCONFIGDIR/XDG_CACHE_HOME, the same interpreter ran:

```sh
/private/tmp/sjtu-tm1-io-venv/bin/python -m pytest -q sjtu_tpmshx/tests/integration_tm1/test_three_process.py sjtu_tpmshx/tests/integration_tm1/test_handoff_provenance.py
```

Result: 4 passed in 12.43 s, native exit 0. No PDE acceptance matrix was rerun
for this documentation-only closure. The fixed-166 comparison and earlier
numerical evidence retain their recorded source revisions and denominators.

The full independent implementation and 37-task-card review is retained in
[independent-review.md](independent-review.md). B40's four-case combined
technical disposition is in [3d-model-h-validation.md](../B40/3d-model-h-validation.md).
Both controlled reference updates were explicitly approved before execution.
Original frozen 4/4 failures, NaNs, missing/native exits and unconverged states
remain historical evidence. Legacy convergence, F2 qualification, Q-change,
mass balance, native boundary energy and experimental accuracy remain distinct.
2D single-loop outer false is preserved; original 3D screening budget is not
claimed F2-qualified. No whole-exchanger experimental accuracy is claimed for
these four cases. Missing real water CFD remains explicitly missing.

All 37 M-A states are done on this evidence; pre-merge statuses/reasons remain
in their state records. M-B's eight states are unchanged (7 planned, 1 running),
including real C++/OpenFOAM, providers/tensors and H30 work. See
[acceptance_document.md](../../acceptance_document.md) for V0.1 limitations.
This closure changes records only, not code, raw data, thresholds or references.
