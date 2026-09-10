# Public runtime controls and presentation evidence

Source: coordinated G10/A20/I51/I52 changes on `2e5471c`, in the IO repair
worktree. This is an application prerequisite, not completed GUI wiring.
The exact 73-package environment and pip check passed again before execution.

RunControl now carries existing iteration labels and 2D SIMPLE residual
observations through callbacks. Backend callbacks do not import Qt and are
not part of either persistent record. Existing cancellation is retained.

Results preserve original display pressure and temperature separately from
raw thermal/property pressure. 3D physical cell velocities, speed and chi are
archived with units and axes. 2D optional smoothed velocities retain their own
display names. No display field is used in engineering metric reductions.

L2 checks, worktree-local MPLCONFIGDIR/XDG_CACHE_HOME:

- `pytest .../integration_tm1/test_2d_real.py`: 3 passed, 5 warnings in 7.62 s,
  native exit 0. Original B20 air numbers and both mixed-fluid nonconverged
  cases remain checked. New callback assertions observe both stream labels.
- `pytest .../integration_tm1/test_runtime_controls.py`: 1 passed in 1.22 s,
  native exit 0. Real B30 public execution, pre-execution cancellation, actual
  iteration sequence, progress, original display field equality at capture,
  and complete HDF5 field readback are checked.
- Ruff on affected code passed; `git diff --check` passed.

The new 3D test initially failed because its expected label confused the
zero-based final outer index with the iteration budget. A second version used
the optional user setting (`None`) rather than the resolved runtime budget;
that failure was repeated once while field checks were being added. These
native-exit-1 logs remain `controls-3d.log`, `controls-3d-fixed.log` and
`controls-display-3d.log` under `.cache/tm1-io`. The corrected assertion uses
the recorded runtime budget and completed index; no numerical threshold or
runtime default changed. The final log is `controls-display-3d-fixed.log`.

Public GUI, legacy config-only CLI, design and optimization wiring, remote CI
and minimal-install acceptance remain outstanding.
