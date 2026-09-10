# TM1 takeover and repair record — 2026-09-10

The user requested implementation of all findings in the takeover review.
The final objective remains M-A three-module independence and V0.1 M-B
tracking. The source plan, its 45 nodes and 110 dependencies are preserved;
the copied task cards describe requirements, not delivery evidence.

This directory's `state/*.json` records execution after takeover. The original
Downloads package remains a planning reference. The previous Codex task
`01a0871b-3d91-7c53-9f89-053a5a346b7f` remains historical evidence; this task
`01a08af6-c928-75a1-ba06-ba522bbd97a0` coordinates the requested repairs.

## Baseline and ownership

- Original numerical baseline: `5f1cafb0c7e461a8c30a8ea96920ce03a828e412`.
- TM1 main: `c7f013869e7127b35ac0c305376c13b3a834131b` (PRs 1–5 merged).
- Original PR 6: `c8cfb4664b3f1667e09fdf86f86f09445de2651c`, open and retained.
- Main CI run `34465137939`: success. PR 6 run `34465172896`: success.
  These are fast-subset CI results, not M-A acceptance.
- All six original TM1 worktrees were clean at takeover. The original
  SJTU-TPMSHX checkout and V2 remain read-only; TM1 changes never merge there.
- G10 repairs start in `codex/tm1/g10-repair`. The controller is the sole
  current writer. Node ownership from the original graph remains in force;
  old shared numerical files are changed only at their integration steps.
- One local numerical job at a time. No shared environment rebuild or
  dependency installation is included in an ordinary source patch.

## Corrections to earlier progress claims

PR 6 replays the old complete pipeline and ignores prepared grids, design
fields and model references. It is not independent solving. Its summary-only
conversion loses model metadata and cannot support independent postprocessing.
Its 2D heat-duty label must be W/m, not W. It has no production application
callers. The original implementation remains on its branch as review evidence;
it must not be merged as M-A delivery.

G10, E00 and B20/B30/B40 have useful partial work, not complete acceptance.
The new state records reopen only these affected baseline/contract tasks;
no node is marked done on the strength of an earlier summary or a merged PR.
M-A and M-B remain incomplete. Promises to keep working and repeated unchanged
CI snapshots are not implementation evidence.

## Evidence retained

- B20/B30 observation tables and their original inputs and budgets.
- B40 frozen regression: 4 failures out of 4, with original pins/tolerances.
- B30 NaN enthalpy diagnostics and 2D/3D mixed-fluid nonconvergence.
- Historical 3D adapter run without a verified native exit: unverified.
- Main run `34462326406` at `44cd551`: cancelled, never counted as success.

Repair order follows the graph: G10 and baseline/CI gaps, model and module
leaves, dimensional/application integration, formal file and independent
process verification, application routing, then Z00. M-B retains its original
required and staged capabilities; no requirement is removed to fit existing code.

## Shared model extraction ownership

The sole controller coordinates M00 with the I55 source reconnection in
`codex/tm1/m00-repair`. This bounded integration moves the existing pure model
implementations to `models` and reconnects their existing public module paths;
there is no second formula implementation. Numerical kernels and thread
initialization retain their existing behavior. This is partial M00/I55 work,
not acceptance of either node or of dependent module integration.
