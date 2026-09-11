# 2D boundary diagnostic: unresolved conservation gap

2026-09-11. User-authorized B40 closure scope is historical attribution,
numerical regression, convergence, mass and boundary-energy verification.
No whole-exchanger experiment is added for these four cases. Experimental
accuracy remains unclaimed. This supplement preserves every original failure
and the separately approved four-reference update.

Offline reduction of the retained `post-wall` native captures uses
`reduce_2d_boundary.py`; no PDE was rerun. These are the two cases whose
outputs exactly reproduce the current approved original-budget references.
The source SHA is stored in `2d-boundary-diagnostic.json`. A later change to
file/in-memory declaration validation does not alter these solver equations.

| Quantity | uniform | nonuniform |
| --- | ---: | ---: |
| Final relative delta Q | 1.17585e-12 | 3.64940e-13 |
| SIMPLE native boundary mass relative imbalance A | 3.83690e-5 | 3.28999e-5 |
| SIMPLE native boundary mass relative imbalance B | 2.09225e-5 | 1.71803e-5 |
| A boundary energy minus exchange, W/m | 1934.399088 | 1705.167165 |
| B boundary energy minus exchange, W/m | 2324.615727 | 1912.379803 |
| Solid global residual, W/m | -1.65465e-7 | -4.54799e-8 |
| Solid L1 residual, W/m | 1.67969e-7 | 4.66980e-8 |

Mass values use the saved SIMPLE staggered boundary velocities and boundary
rho*epsilon. Its total-porosity convention is twice each physical fluid's
mass flow; relative imbalance is unaffected. Four signed boundary totals are
retained separately in JSON. The converged Q change is measured directly,
not inferred from `q_rel_tol=null` or the legacy convergence flag.

The energy reduction includes all four boundary advective terms, inlet
half-cell conduction and full-domain interphase sources. The inlet capacity
uses the actual `inlet_flux_A/B` supplied to the kernel. The current 2D
constant-property temperature kernel explicitly implements
`div(F*T) - T*div(F)` with interpolated cell-centre capacity fluxes. The
saved fields have a nonzero capacity-flux divergence. Its integrated
`T*div(F)` term explains the 1705–2325 W/m gap: after subtracting that term,
A/B equation residuals are about 1.7e-7/1.4e-10 W/m (uniform), and
3.5e-8/1.1e-10 W/m (nonuniform). This establishes the equation accounting;
it does **not** establish physical boundary energy conservation. The gap is
about 23–29% of the exchange magnitude and cannot be hidden by reporting only
the small corrected residual.

B40 therefore remains failed/open under the newly clarified scope, with a
concrete 2D boundary-energy issue replacing the vague pending-physical-scope
wording. Next work must trace the capacity-flux mapping and the discrete
transport choice, preserve this failed diagnostic, and validate an actual
remedy under the existing authorized numerical scope. No threshold or
reference is changed by this diagnostic.

Independent static review by `b40_review` confirms the face averaging, inlet
capacity substitution, signs and half-cell conduction for these full-opening
forward-inlet cases. The T div(F) term is the equivalent nonconservative term
of the discrete operator, not a separately added source in the implementation.
The reducer is not a general inlet-backflow certificate. The review confirms
that the small corrected residual cannot close the boundary-energy gap.
