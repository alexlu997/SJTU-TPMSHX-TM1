# 2D approved air integral enthalpy candidate

Solver candidate: `ae6f236d0346f373f434bb14a0e157eb6ce9255e`.
User approved all screening density-loop counts to use existing air cp(T)
integral enthalpy on 2026-09-11. This repairs the mismatch between native SIMPLE
mass transport and the previous temperature/capacity transport. It also retains
cross-flow and corrects the reversed B-axis mapping during density updates.
No new cp fit, physical fluid, reference tolerance or frozen value was introduced.

Both engineering probes preserve original geometry, air inlet conditions and
single density loop; use F2, 800 SIMPLE iterations, 2000 thermal iterations and
Q-change tolerance 1e-4. Both return native exit 0. Captures and logs are in
`.cache/b40-current-2d-{uniform,nonuniform}-model-h`. The reducer added alongside
this report is `native_2d_capacity.py --enthalpy`; its version is distinct from
the solver SHA above. The committed reduction is `native-model-h-balance.json`.

| Case | Q magnitude W/m | dP Pa | material mass kg/m | boundary residual A/B | relative Q change |
| --- | ---: | ---: | ---: | --- | ---: |
| uniform | 8019.236205524567 | 4675.011354108352 | 3.446685791015626 | 3.984e-12 / 2.030e-14 | 5.113e-13 |
| nonuniform | 7507.661718998576 | 4051.9767479034927 | 3.6729327392578126 | 3.845e-12 / 3.150e-14 | 6.001e-13 |

The independent reducer reconstructs native physical face mass, integrates the
existing cp polynomial directly, includes inlet half-cell conduction and compares
with signed solid-to-fluid exchange. It does not subtract a divergence correction
to obtain the reported residual. The auxiliary `native_T_div_mass_cp_W_per_m`
still means constant-inlet-cp T div(m), and is not an integral-enthalpy defect.
All four phase momentum residuals are below 1e-4 and local/global mass residuals
below 1e-6. Each fluid boundary residual is normalized by max(abs(exchange),1 W/m)
for the explicit one-metre depth and meets the approved 1e-4 threshold.

Independent read-only review confirms the formula, signs, physical face mapping,
inlet conduction, F2 and Q-change findings. Four public API/HDF5 cold-start tests
(uniform/nonuniform, one/three density loops) pass with native exit 0; their scope
is saved-field boundary transport. These tests do not establish multi-loop outer
convergence. Single-loop captures retain `outer_converged=false`; no required
multi-loop convergence claim is inferred from them.

B40 remains open: retain all historical failures and earlier temperature-form
evidence. This supplement does not approve replacement frozen values, final CI,
full multi-loop convergence, experimental accuracy or M-A completion.
