# B40 reference disposition — proposed, not approved

2026-09-11. No frozen reference or tolerance has been changed. This proposal
addresses deterministic regression references only. Approval would not close
B40, assert physical accuracy, authorize merge/release, or replace the original
two-outer-call failure with a larger-budget run.

## Proposed change

Preserve the original four tuples, original 4/4 failures, NaN and native-exit
provenance as historical evidence. Update only the active four reference
tuples in `test_evaluator_frozen_values.py` to the corrected numerical method,
using the unchanged input, iteration budget and `pytest.approx(rel=1e-12)`
(including its existing default absolute tolerance of 1e-6).

| Case | Proposed Q objective W/m | Proposed dP Pa | Unchanged mass kg/m |
| --- | ---: | ---: | ---: |
| 2D uniform | -8085.955349708075 | 4675.147979229178 | 3.446685791015626 |
| 2D nonuniform | -7561.252334176324 | 4052.0456347246245 | 3.6729327392578126 |
| 3D uniform | -7209.103274428575 | 7519.596015609637 | 6.323593139648438 |
| 3D nonuniform | -8672.919843820628 | 2871.31457245229 | 3.675970458984375 |

The 3D references remain **unconverged original-budget observations**. Keep
that state explicit in the associated regression evidence. The independent
engineering-budget evidence must remain separate; no converged value from it
is substituted into this table. The 2D legacy convergence flags likewise do
not become F2 or physical-accuracy claims.

## Why a reference change is technically justified

The old 3D heat values are reproduced before `5adb61d`. The change replaces
pinned/copied endpoint layers with complete endpoint control volumes. Saved
full-domain boundary/source reductions show substantial old energy defects
that disappear after the change, including in the separate converged-budget
comparison. Returning to the old endpoint method to recover its Q would
restore that demonstrated defect. See `end-cv-investigation.md`.

Both remaining 3D differences and the full two 2D differences reproduce
exactly across `bc69d31` → `d61e341`, with unchanged prepared geometry and
properties. The wall/outlet momentum patch implements the declared stationary
no-slip exterior and actual outlet-neighbour coupling. Existing independent
flux/equation and Brinkman analytic checks provide numerical-method evidence;
347 relevant checks passed with native exit 0. See `wall-investigation.md`,
`2d-history-investigation.md` and `method-verification.md`. This is evidence
for the method change, not an attribution to platform noise.

## Conditions retained after approval

Run the four active frozen tests on the then-current candidate and preserve
their native exit. Preserve all historical observations in the evidence
package; do not edit the old failure record. Keep numerical convergence,
discrete fluid/solid energy, migration equivalence and physical accuracy as
separate verdicts. B40 remains failed/open until its remaining acceptance
requirements are explicitly satisfied. A green frozen test cannot close it.

Affected whole-exchanger physical acceptance after the wall change is still
pending in the inherited model documentation. This proposal does not waive
that requirement or create a new physical acceptance threshold. If updating
regression references must wait for that acceptance, leave the active pins
unchanged and retain the four failures in the meantime.

The decision requested is only whether to apply the four reference updates
above under these retained conditions. General commit/push authorization does
not authorize this decision; the Goal specifically reserves reference changes
for explicit approval.
