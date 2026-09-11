# 3D B40: controlled end-CV comparison

2026-09-11. Inputs: `inputs.md`. Source before/after: `cef75a5` → `5adb61d`
(direct parent/child). Both checked the unchanged 71-package lock and pip
compatibility with the fixed historical interpreter. No source solver edits,
raw-data changes or frozen-pin changes. The prior fd2e001 original 3D tests
passed separately; both cases at cef75a5 also reproduce those pins.

## Original budget

Each case retains 10×6×3, outer=2, SIMPLE=300/1e-2, LTNE=800/.5, legacy
screening convergence. Both initial thermal input arrays (23/case) and both
initial flow arrays (60/case) are elementwise equal across these two commits.

| Case | Q magnitude before → after (W/m) | dP before → after (Pa) | mass (kg/m) |
| --- | --- | --- | --- |
| uniform | 9968.92699806532 → 7209.1160515172505 | 7546.892661221462 → 7519.335784053474 | 6.323593139648438, unchanged |
| nonuniform | 10850.753888768157 → 8672.928923969388 | 2879.2941880943804 → 2871.123022974717 | 3.675970458984375, unchanged |

All four instrumented runs exited 0; all returned converged=false, with two
thermal calls. A process exit of 0 means capture completed, not convergence.
Native fields/flow/pressure/control metadata are under each historical tree's
`.cache/b40-trace/<case>-native2/{capture.json,native.npz,summary.json}`.

The observed large heat-duty shift occurs at this reachable commit, before
TM1's split. The implementation changes pinned/copied fluid end-cell layers
to complete control volumes, physical inlet face temperature and half-cell
inlet diffusion. Q remains the actual core evaluator's integral
sum(h_vB*(Ts-Tb)*cell_volume), divided by .042 m only in the app wrapper.
It does not switch to the unrelated production report-enthalpy path.

Full-domain temperature-transport residuals from the six external faces,
normalized by max(abs(phase source),1 W):

| Case | A before → after | B before → after |
| --- | --- | --- |
| uniform | .2372296704 → 2.4214e-12 | .3394387309 → 7.0157e-13 |
| nonuniform | .1914418028 → 4.6347e-13 | .3368411373 → 2.1535e-14 |

Exact face values and W-valued sources are in `end-cv-original-budget.json`.
This common full-domain diagnostic is not the old interior-only strict
certificate: the old equations omit the pinned/copied end layers from that
certificate while the reported source integral includes the full volume.
The evidence supports an actual discrete boundary-treatment defect in that
old baseline, corrected by the historical end-CV change. It is not evidence
that all current B40 discrepancies are resolved: later Q and dP differences
between 5adb61d and 5f1cafb remain to be attributed separately.

## Independent engineering-budget experiment

The user explicitly approved supplemental relative chunk ΔQ<1e-4 and each
phase's full-boundary relative residual<1e-4 on 2026-09-11. These do not change
the original regression. The experiment retains geometry/grid, uses existing
verification budgets SIMPLE=800, LTNE=2000, outer cap=12, F2 mode, and explicit
q_rel_tol=1e-4. F2 keeps momentum<1e-4, local/global mass<1e-6, backflow<=.01,
two confirmations; outer ΔT<.5 K and LTNE max ΔT<.01 K remain unchanged.

| Case | Version | Q magnitude W/m | dP Pa | outer calls | numerical converged | A/B full-boundary relative residual |
| --- | --- | --- | --- | --- | --- | --- |
| uniform | cef75a5 | 8982.95869085432 | 9202.23943333696 | 5 | true | .2810462484 / .3510195433 |
| uniform | 5adb61d | 6449.47408970611 | 9176.005948728445 | 5 | true | 2.2710e-12 / 6.7613e-13 |
| nonuniform | cef75a5 | 9954.717759677877 | 3458.132659491499 | 4 | true | .2314422971 / .3375381174 |
| nonuniform | 5adb61d | 7731.674715129527 | 3445.899220235994 | 6 | true | 2.9496e-13 / 1.3584e-13 |

All four processes exited 0. Final relative chunk ΔQ ranges from 1.36e-16 to
4.39e-13, max thermal ΔT<=7.69e-11 K; outer ΔT is respectively .15227,
.06135, .48890 and .04399 K. Both versions meet these numerical stopping
conditions; the old solution fails the new full-domain energy condition.
Increasing budget therefore does not remove the boundary-treatment difference.
Exact energy reductions: `end-cv-engineering-budget.json`. Native captures use
the separate `<case>-engineering` directories, not the original-budget paths.

The solid has adiabatic exterior faces. Its summed fluid source is about
-4.2012/-5.5546 W before and -1.0675e-9/-1.5524e-10 W after for uniform/
nonuniform, also requiring separate solid-phase accounting in final acceptance.
This is temperature-form epsilon*rho_cp*u*T transport, not variable-property
true-enthalpy conservation or experimental accuracy. Those claims remain open.

## Capture/check provenance and review

The first uniform capture pair completed with identical scalar outputs and
exit 0 but omitted frame-local mappings on Python 3.13 (FrameLocalsProxy).
Those original directories remain preserved. The collector now explicitly
copies dict(frame.f_locals), asserts required native arrays, and records the
supplement as native2. It only observes the original functions; explicit
experimental overrides are recorded separately. No incomplete capture is
claimed as complete field/energy evidence.

`reduce_history.py` includes a runnable analytical advection/diffusion sign
check. It and `probe_history.py` pass Ruff; reductions exit 0. Independent
read-only review confirmed the captured projected faces, single-phase
porosity, outward signs and half-CV conduction match these cases. It did not
extend that conclusion to explicit inlet_flux, model-h, MMS or other boundaries.

B40 remains failed/open. Next: quantify remaining later historical drift,
complete 2D independent rows and current-candidate engineering qualification,
then propose any justified reference disposition for explicit user approval.

## Native pressure and mass supplement

Both JSON files now reduce all six exterior mass faces in native SIMPLE
coordinates, last thermal-input flow and final core-return flow separately.
They use the captured current rho_field*eps_field, not the cached pre-density
update coefficient. SIMPLE uses total void fraction here; a symmetric physical
fluid's mass is half the listed native rate. Pressure ranges include both gauge
P and P+P_ref_abs, and the actual cell-centre open-area pressure functional.
These are unprojected SIMPLE faces; the thermal diagnostic above separately
uses the capacity-projected faces actually consumed by LTNE.

At original budget, B dP remains exactly 2154.7002153378767 Pa (uniform) and
827.1947760461434 Pa (nonuniform) across the end-CV change. A dP changes from
5392.192445883585 to 5364.6355687155965 Pa and from 2052.099412048237 to
2043.9282469285736 Pa. This is consistent with frozen B flow and thermally
updated A flow. All individual pressure reductions reproduce captured core
report values. Native net mass imbalances remain explicitly recorded; they are
not erased by the thermal projection's small energy residual.

The later 136ff16 face-extrapolation correction is not the reported dP path:
these evaluators call extract_dP_weighted, not extract_dP_face_extrap. It cannot
be assigned as the cause of the remaining historical dP drift on this evidence.
Independent review of the pre-supplement documents/scripts and JSON found no
specific issue, with solid-phase normalization and current-candidate acceptance
still open. The new flow reduction has a runnable constant-flow/linear-pressure
check; it has not yet received that independent review.
