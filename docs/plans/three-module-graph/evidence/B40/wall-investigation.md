# Remaining 3D historical drift: wall change

2026-09-11. Controlled direct parent/child comparison: bc69d31 → d61e341.
The original B40 geometry, controls and budget are unchanged. Both historical
checkouts pass their unchanged 71-package exact lock and pip check.
No source edits or frozen-reference edits were applied.

Uniform original-budget outputs (Q optimization objective W/m, dP Pa, mass kg/m):

- Before: (-7209.1160515172505, 7519.335784053474, 6.323593139648438).
- After: (-7209.103274428575, 7519.596015609637, 6.323593139648438).
- Both exit 0, outer calls 2, converged=false.

The before tuple exactly matches the earlier post-end-CV version 5adb61d.
All 139 captured shared thermal temperature/flow arrays compared between
5adb61d and bc69d31 are elementwise identical. All ten prepared geometry and
property arrays remain identical across the wall change. Thus this reachable
commit introduces the remaining uniform difference, rather than the unrelated
pressure-face extraction or production enthalpy reporting changes.

The changed momentum kernels include half-cell no-slip diffusion on exterior
walls and actual outlet treatment; these functions are in this evaluator's
SIMPLE path. This commit-level attribution does not isolate a single changed
term within the patch. The separately changed experimental D-F correction is
not sufficient evidence for attribution to that correction.

Saved captures: each historical tree's .cache/b40-trace/3d-uniform-native.
The six-face thermal and native pressure/mass reductions are in
wall-original-budget.json. These are original-budget observations, not
engineering or physical acceptance. Nonuniform comparison is complete (details below).
B40 remains failed/open and all original frozen pins remain unchanged.

Nonuniform original-budget outputs, in the same units:

- Before: (-8672.928923969388, 2871.123022974717, 3.675970458984375).
- After: (-8672.919843820628, 2871.31457245229, 3.675970458984375).
- Both exit 0, outer calls 2, converged=false.

Its before tuple also exactly matches 5adb61d; all 139 shared native
thermal-temperature/flow arrays match that version, and all ten prepared
geometry/property arrays are unchanged across the wall change. Both original
3D rows therefore have separate controlled evidence for the major end-CV
shift and the remaining wall-commit shift. Current-candidate engineering-budget
numerical convergence is now recorded in `current-engineering-budget.md`.
Single-term isolation, solid-phase and physical acceptance, and reference
disposition remain open.
