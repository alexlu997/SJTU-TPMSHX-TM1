# Approved 3D screening enthalpy repair: validation and reference proposal

Candidate `0773ef139192944d74c16335e8b9f5ede45919b0` changes only the prepared
3D air-air screen. The user explicitly approved existing native-mass air h(T)
transport for that path. Frozen cold B flow, geometry, inlet conditions and
budgets are retained. Other fluids and full experimental pipelines are unchanged.
The prior temperature/capacity equation and native-h boundary failures remain
in `native-3d-enthalpy.md`; approval did not erase those observations.

## Engineering-budget comparison

Both old and new runs use max_outer=12, SIMPLE 800, energy 2000, F2, Q-change
1e-4 and the existing outer 0.5 K threshold. Both new runs exit natively 0.

| Case | old Q magnitude W/m | new Q magnitude W/m | old dP Pa | new dP Pa | old/new outer calls |
| --- | ---: | ---: | ---: | ---: | --- |
| uniform | 6449.470707238928 | 6226.343494204938 | 9176.307996229752 | 9173.85093647082 | 5 / 2 |
| nonuniform | 7731.673259143576 | 7464.29098804774 | 3446.1217194864576 | 3441.8758132102334 | 6 / 2 |

All A/B momentum residuals are below 1e-4; local and global mass residuals
below 1e-6. New Q changes are 4.9734e-13 / 3.7460e-13; outer changes are
0.15878 / 0.13457 K. Controls, source and native exit are recorded in
`3d-model-h-controls.json`. All SIMPLE, thermal, outer and envelope flags pass.

Independent six-face native-mass integration plus inlet conduction minus
phase exchange gives relative A/B residuals 2.7721e-12 / 1.1518e-12 (uniform)
and 7.9254e-13 / 5.1857e-14 (nonuniform), versus the previous 3.67–5.02% gaps.
Solid global/L1 residuals are separately retained: L1 relative residuals
4.7606e-12 / 2.1464e-12. Physical total exchange is 261.5064 / 313.5002 W
for actual 0.042 m depth. The optimizer's Q and mass remain W/m and kg/m.

Reproduce with `probe_history.py --prepared-backend`, the controls above and
`.cache/b40-trace/current-3d-{uniform,nonuniform}-model-h`; use
`native_3d_enthalpy.py` for native h balance and `reduce_history.py` for solid
and raw mass/pressure. `3d-model-h-solid-and-flow.json` retains the latter's
temperature-form auxiliary too; that auxiliary is not the new h(T) certificate.
Two public cold-start/HDF5 boundary tests pass, native exit 0 (7.77 s).
Independent static review found no scope, mapping or data-handoff error;
the explicit F2/Q/solid values above supplement its stated test limitations.

## Original budget and proposed active references — not yet approved

The separate original-budget probes retain SIMPLE 300, energy 800 and max_outer=2
with legacy convergence. Both exit natively 0 and now report convergence under
those legacy criteria. That is not F2 qualification: pressure still differs
substantially from the engineering runs. Earlier original-budget unconverged
observations are not rewritten. Original native-h residuals are retained in
`3d-model-h-original-boundary.json`.

| Case | old Q objective W/m | proposed Q W/m | old dP Pa | proposed dP Pa | unchanged mass kg/m |
| --- | ---: | ---: | ---: | ---: | ---: |
| 3D uniform | -7209.103274428575 | -6231.317311633525 | 7519.596015609637 | 7581.970714729965 | 6.323593139648438 |
| 3D nonuniform | -8672.919843820628 | -7465.851654932007 | 2871.31457245229 | 2880.481482369124 | 3.675970458984375 |

Only these Q/dP components are proposed to change; both 2D tuples, masses,
inputs, budgets and tolerances stay unchanged. New h(T) temperatures also feed
the existing A density/pressure coupling, so dP changes are part of this model
repair. Actual unchanged-budget frozen regression gives 2 failed / 2 passed,
native exit 1 (`.cache/b40-3d-model-h-frozen-before.log`); retain this failure.
The matching three-process test must reflect the actual new reported status
and approved active references, while retaining old S40 data unchanged.

This proposal does not change pins until explicit approval and does not claim
experiment accuracy, final CI, full PR review, merge or M-A completion.

## Reference decision: approved 2026-09-11

The user explicitly confirmed the two Q/dP updates listed above. Only those
3D active Q/dP constants change; masses, 2D references, inputs, budgets and
tolerances remain unchanged. The three-process regression consumes the same
active constants and checks the observed legacy convergence/native exit 0.
Prior values, original failed runs and this proposal history are retained.
This decision does not establish experimental accuracy or close B40/M-A.

After the approved update, all four frozen regressions, four independent
three-process screening handoffs and two 3D native-h boundary tests pass:
10 passed in 14.27 s, native process exit 0. Log: `.cache/approved-3d-refs.log`.
Pre-update handoff captures are retained in
`.cache/tm1-optimization-before-approved-3d-refs`; historical evidence files
are unchanged. Current-head CI and final combined acceptance remain pending.
