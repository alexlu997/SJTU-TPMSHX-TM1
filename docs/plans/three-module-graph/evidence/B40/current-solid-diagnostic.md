# Current 3D solid-phase discrete residual

2026-09-11. This supplements the saved `054dc96` engineering-budget runs;
no PDE was rerun. The current reducer evaluates the solid equation at the
last raw thermal return. Internal conduction uses the actual staggered
kernel's harmonic conductivity and half-sum centre spacing. Each internal
face contributes equal and opposite cell fluxes; exterior faces are adiabatic
and the two cases have no external solid source.

The source is `[h_vA*(Ta-Ts) + h_vB*(Tb-Ts)]*cell_volume`, positive into solid.
Residual is inward conduction plus that source, in W per cell. Normalization
is `max(abs(sum(Q_A_exchange)), abs(sum(Q_B_exchange)), 1 W)` over the full
domain. Both the absolute signed sum and L1 sum are reported so cancellation
cannot hide local defects. This normalizes a diagnostic; no new acceptance
threshold is introduced.

| Case | Max absolute cell residual W | Global relative residual | L1 relative residual |
| --- | ---: | ---: | ---: |
| uniform | 8.466935675882338e-11 | 3.942543602456907e-12 | 3.9577204632564935e-12 |
| nonuniform | 2.7306908425633002e-11 | 4.788910949495213e-13 | 1.8998187597396445e-12 |

Full values and units are in `current-solid-diagnostic.json`. Reproduce by
running `reduce_history.py` against the two saved current engineering-budget
directories described in `current-engineering-budget.md`, then selecting each
row's `solid_temperature_diagnostic`. Its two-cell analytic self-check verifies
the conduction sign and cancellation. The fixed environment checks, reducer
self-check and Ruff pass with native exit 0.

These results complete the local/global solid discrete residual calculation.
They do not establish true-fluid enthalpy, experimental accuracy or authorize
frozen-reference changes; final solid/physical acceptance and B40 remain open.

Independent read-only review (`b40_review`, 2026-09-11) checked the operator
against the staggered kernel and requested a reproducible reduction entry.
The entry was added and reviewed again: source, normalization and separate
global/L1 outputs pass that static review. The reviewer did not rerun PDE or
the reduction; the main task ran the reduction and self-check successfully.
