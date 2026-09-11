# Current candidate: independent engineering-budget experiment

2026-09-11, source `054dc96c92214872f2aeddcb5bcc1a6ae0cdb71c`.
The unchanged 73-package lock and pip check both pass (native exit 0).
The probe uses the public optimization entry and captures the prepared
screening backend actually reached by it. The only probe change adds explicit
`--prepared-backend` selection; solver source is unchanged.

Both rows retain the inputs in `inputs.md`. The independent experiment uses
`max_outer=12`, SIMPLE budget 800, thermal budget 2000, F2 convergence and
explicit `q_rel_tol=0.0001`, matching the historical engineering experiments.
Original-budget failures and frozen pins are unchanged.

| Case | Q objective W/m | dP Pa | mass kg/m | Outer calls | Native exit |
| --- | ---: | ---: | ---: | ---: | ---: |
| uniform | -6449.470707238928 | 9176.307996229752 | 6.323593139648438 | 5 | 0 |
| nonuniform | -7731.673259143576 | 3446.1217194864576 | 3.675970458984375 | 6 | 0 |

Both runs report SIMPLE A/B, LTNE inner and outer convergence true; the
envelope assessment also passes. Last outer temperature changes are
0.061345674049334775 K and 0.043977892452232936 K respectively, against the
unchanged 0.5 K criterion. This verifies the recorded numerical criteria,
not mesh independence or experimental accuracy.

The common six-face temperature-transport diagnostic gives relative residuals
A/B of 2.2663687919649956e-12 / 6.782318458944209e-13 (uniform) and
2.9338062014060947e-13 / 1.3233636564821419e-13 (nonuniform). Solid source sums
are -1.067974153556861e-9 W and -1.5552359400317073e-10 W. Full face values,
native mass fluxes and pressure states are in `current-engineering-budget.json`.
This is the discrete temperature-transport diagnostic; true-enthalpy and
experimental validation remain unestablished. Solid-phase acceptance remains
an outstanding requirement.

Raw diagnostic captures are under `.cache/b40-trace/current-3d-{uniform,nonuniform}-engineering`.
The probe asserts that thermal and backend temperature/coefficient arrays were
captured. Reduction self-checks pass. Both process handles completed with
native exit 0, separately from the captured solver convergence flags.

Together with `end-cv-investigation.md`, these results show that the large
old/new heat difference persists after the recorded numerical criteria are
satisfied. The original two-outer-call budget is insufficient for those
criteria. Neither observation authorizes changing the frozen references;
B40 and final M-A acceptance remain open.

Independent read-only review (`b40_review`, 2026-09-11) checked the wall and
current-budget reports, JSON result/status fields, probe change and triage
index. It found one stale wall-report statement about current-budget evidence;
that statement is corrected. No other concrete issue was reported in that
scope. The review did not rerun PDE or array-equality comparisons and is not
a review of the whole PR.
