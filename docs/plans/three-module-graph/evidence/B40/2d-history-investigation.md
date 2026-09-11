# Two independent 2D frozen-value drift investigations

2026-09-11. Eight original-input, original-budget evaluations completed with
native exit 0, across `435b1d1`, `81dbccd`, `bc69d31` and `d61e341`. Each
checkout uses the unchanged 71-package lock and passes the lock checker and
pip check. The first pair directly brackets `81dbccd`; the second directly
brackets `d61e341`. Full inputs remain in `inputs.md` and the captured merged
controls are retained in `2d-history-comparison.json`.

| Case | Before Q objective W/m | After Q objective W/m | Before dP Pa | After dP Pa | mass kg/m |
| --- | ---: | ---: | ---: | ---: | ---: |
| uniform | -8085.955568764836 | -8085.955349708075 | 4675.147100112292 | 4675.147979229178 | 3.446685791015626 |
| nonuniform | -7561.25242589901 | -7561.252334176324 | 4052.044538218606 | 4052.0456347246245 | 3.6729327392578126 |

Here “before” is the common exact result at all three earlier versions;
“after” is `d61e341`. Each before tuple exactly reproduces its own frozen pin.
Each after tuple exactly reproduces its own original B40 failure observation.
Thus the entire observed Q/dP difference is introduced at the reachable wall
commit for each row independently. The original failure record and tolerance
remain unchanged; this is attribution, not approval to replace the pins.

## Excluded candidates and native evidence

`81dbccd` changes the segmented branch of `_aligned_grid`, but these full-face
cases use the unchanged early return with no interior breakpoints. Its new
model-h branch is also not selected: the screening call passes no model fluids
or full model mass faces. In the direct comparison, all 133 shared captured
arrays (uniform) and 134 (nonuniform) are elementwise equal. This includes
pressure, flow, prepared fields and final temperatures. The same counts and
equality hold from `81dbccd` to `bc69d31`.

Across `bc69d31` → `d61e341`, all 16 captured geometry/property and native grid
arrays remain equal in each case. Pressure and velocity differences are
already present at the thermal call; the resulting temperatures differ.
Maximum absolute pressure-field differences A/B are 0.0006720479877913021 /
0.000558540240945149 Pa (uniform) and 0.0011961907252953097 /
0.005002749343930191 Pa (nonuniform). The full selected field differences
and changed-array names are retained in the JSON. This evidence locates a
flow-state change, not a Q-only reporting change or a geometry remapping.

The reachable 2D momentum patch changes inlet tangential half-cell diffusion,
outlet tangential convection, and the final interior normal-velocity stencil's
connection to the actual outlet face. It also removes the old wall penalty
and unifies opening support. Full-face openings do not activate the old
blocked-face penalty. This is a commit-level causal result; separate term
contributions within that momentum patch have not been isolated. Do not call
the observed drift platform noise or attribute it to a production enthalpy
path that this screening evaluator does not call.

## Numerical status and remaining closure

All eight runs return SIMPLE A/B legacy convergence at 20 iterations and
thermal convergence at 1000 iterations. The source configuration remains
800 SIMPLE / 1500 thermal / one density loop. These legacy flags do not prove
F2 engineering convergence, complete boundary energy, or physical accuracy.
The probe records those flags separately from each native process exit.

Both rows now have a reproduced historical cause and unchanged geometry
evidence. Their closure still requires review of the relevant numerical
change and applicable physical evidence, then explicit approval of any
reference disposition. No frozen value or tolerance is edited. B40 remains
failed/open and this result alone cannot close M-A.

The runnable observer is `probe_2d_history.py`, invoked from each checkout
with its configured absolute interpreter through `runpy.run_path`. Raw
captures are `.cache/b40-2d-{uniform,nonuniform}` under the four historical
trees (`sjtu-tm1-b40-2d-pre`, `2d-post`, `pre-wall`, `post-wall`). It asserts
that final temperature, both pressure fields and prepared L fields were
captured. No source modification or experimental parameter override is used.

Independent read-only review (`b40_review`, 2026-09-11) checked this report,
the triage index, complete observer, key JSON inputs/outputs/status and the
original grid branch. No concrete issue was reported in that scope. The
review did not repeat PDE runs or array comparisons, and does not authorize
reference changes or B40 closure. Ruff and diff whitespace checks pass.
