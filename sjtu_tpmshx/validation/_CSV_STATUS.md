# Shanghai 3D validation CSV provenance — READ BEFORE CITING ANY CSV

> Codex 2026-05-19 review point #5: old CSVs in this dir are mutually
> inconsistent (different ε-contract eras + roughness eras). This file is
> the single source of truth for which numbers are live vs obsolete.
> Do **not** rename the CSVs (report/scripts reference them by name) —
> consult this table instead.

| CSV | dP RMSRE | Q RMSRE | Era | Status |
|-----|----------|---------|-----|--------|
| `shanghai_3d_baseline.csv` (7/12, regenerated) | **4.88%** | **2.12%** | **PRODUCTION Pipeline3D (solved water-B) + F2 convergence + gamma_df (CFD-refit K) + mass-flux inlet + face-extrap Δp, Nz=3 gate grid** | **CURRENT canonical (gate grid 20×10×3)** — trajectory: 9.82 (6/12 v1.4.0, cell-centre Δp + smooth-trend K) → 5.05 (6/30 face-extrap Δp) → 5.28 (6/30 CFD-refit K) → 5.28 (7/06 A2 criteria) → 4.93/2.12 (7/12 gate runner → production pipeline, water SOLVED — section (a) below) → **4.88/2.12 (7/12 F2 three-gate default — section (b))**. Frozen-B kernel era reproducible via `--runner kernel`. Pinned in `tests/test_shanghai_regression.py` (4.88/2.12). |
| `shanghai_3d_baseline_a1_{16x8x4,32x16x8,64x32x16,128x64x32}.csv` (7/06, **gitignored**) | 5.19 / 6.46 / 8.09 / 8.70% | 3.44 / 3.07 / 2.94 / 2.88% | same era as canonical; all-axis r=2 grids | **A1 grid-convergence study** — per-case Richardson (finest triplet): Δp floor ≈9.6% (median p 1.59, 12/16 extrapolable), Q ≈2.8% (p 1.23). Source of the README grid-converged ≈10% headline + [历史网格收敛图](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/d3ba040de0d43fce8e9b485396a5b660c2d87c5f/assets/grid-convergence.png). Regenerate: `validate_shanghai_3d_real.py --nx N --ny N/2 --nz N/4 --suffix _a1_NxN/2xN/4`, then `runs/tools/plot_grid_convergence.py`. |
| `shanghai_3d_baseline_gammadf_routing_check.csv` (6/12) | **7.19%** | **3.22%** | rbf backend + mass-flux inlet, Nz=3 | **rbf reference** (pre-v1.4.0 default; also the bit-identical routing regression check). Reproduce: `TPMSHX_DF_METHOD=rbf`. |
| `shanghai_3d_baseline_nz10_massflux.csv` (6/09) | **8.69%** | **3.33%** | rbf backend + mass-flux inlet, **Nz=10** | **rbf Nz=10 reference** (opt-in `TPMSHX_DF_METHOD=rbf`). |
| `shanghai_3d_baseline_gammadf_nz10.csv` (6/30) | **12.06%** | **3.30%** | gamma_df (smooth-trend K era) + mass-flux inlet, cell-centre Δp, Nz=10 | **SUPERSEDED as README headline source (7/06)** — README now quotes the grid-converged ≈10% floor from the A1 rows above. Kept as the 6/30 Nz=10 cell-centre snapshot (its face-extrap counterpart, 7.03%, was the old README ★; CSV not retained). |
| `shanghai_3d_baseline_pytest_h3.csv` (regenerated per run) | — | — | whatever HEAD defaults are | scratch output of `tests/test_shanghai_regression.py::test_shanghai_3d_baseline` (opt-in); pinned values live in the test (**4.88/2.12** since 7/13 F2 re-baseline; 4.93/2.12 at the 7/12 gate switch; 5.28/3.21 in the frozen-B kernel era; tol ±5%/±10%). |
| `shanghai_3d_baselineplhub_switch.csv` (gitignored) | 7.19% | — | rbf era snapshot | referenced in `df_surrogate/surrogate_v3.py` docstring (smooth-trend K comparison); kept for that citation. |

> **2026-06-30 cleanup:** the obsolete / trajectory-only snapshots were removed
> (25 files: 14 gitignored scratch + 11 git-tracked). The tracked ones —
> `*Nz10_postGfix*`, `*post-fix-mass-cons*`, `*Nz10_norris_1a*`, `*Nz10_baseline*`,
> `*bhatti_shah*`, `*_Nz10*`, `*phase7_h8_nz10*`, `*z20*`, `*fine_Nx40*` — are
> recoverable from git history before commit `<this cleanup>` if a trajectory
> number is ever needed. Only the 4 live rows above + the plhub snapshot remain.

## Current authoritative numbers (v1.4.0, 2026-06-12)
> **2026-06-30 — Δp extraction switched to 2nd-order face extrapolation**
> (`SIMPLESolver3D.extract_dP_face_extrap`, kernel runner / headline path). The old
> cell-centre reduction sampled P ~h/2 inside the inlet/outlet faces (O(h), ~1st-order)
> and *under-predicted* Δp. With the 2nd-order face reduction the **gamma_df** RMSRE_dP is
> **Nz=3 5.05% / Nz=10 7.03%** (was 9.82% / 12.06% cell-centre); Q unchanged (3.20% / 3.30%).
> The `shanghai_3d_baseline*.csv` rows above were generated with the cell-centre reducer
> (historical provenance); regenerate for the face-extrap numbers. The **pipeline** path
> (`stages_3d`, GUI) was ALSO switched to face-extrap — the **golden 3D gate was re-baselined**:
> only the `dP`/`dP_B` scalars and the `P_kPa`/`P_Pa_B` display fields (which are anchored on dP)
> changed; the physics solve (`Ta`/`Tb`/`Ts`/`vmag`/`Q`/`T_out`) is **bit-identical**. The dP
> reduction works for **any** flow direction (±x/±y/±z): `_resolve_axis_map` permutes streamwise
> onto solver axis 1 for all six dirs, and both reducers read that axis.
> **2026-06-30 — grid-converged headline.** An all-axis (r=2: 16/8/4 → 32/16/8 → 64/32/16)
> full-refinement Richardson pins the **grid-converged** gamma_df Δp RMSRE at **≈ 12 %**
> (finest 64-grid measured 9.70%, Richardson limit 12.1%, p_obs≈0.76) and Q at **≈ 3 %**
> (3.43→3.16→3.03%, clean 2nd-order). KEY: the production-grid Δp (Nz=10 face 7.03%) is
> **under-resolved** — both the cell-centre and the face reducers converge to the SAME continuous
> Δp as h→0 (cell-centre grid-converged ~12.8%, face ~12.1%); face-extrap only *accelerates*
> convergence, the floor is the geometry/closure model error (~12%). The README headline now
> quotes the grid-converged ≈12% / ≈3%; the shanghai regression test still pins the production
> Nz=3 value (now 5.28% — see K re-baseline below) as a config-specific guard.
> **2026-06-30 (#2) — gamma_df K re-baselined.** K moved from the SmoothDF D_h² trend (53% RMSRE,
> the +2.6pp vs rbf below) to a CFD-refit per-geometry surface (raw water CFD, 2-stage extraction,
> log-space TPS; `_prebuilt/df_cfd_coeffs.csv`). c_F UNCHANGED. Nz=3 dP **5.05%→5.28%**, Q 3.20→3.21%;
> water-side Δp (7-6 exp) Diamond 0.33→0.40 / Gyroid 0.62→0.68. Grid-converged ≈12% and the README
> headline are c_F-dominated → unchanged (K is a 1–6% Darcy correction in the air window). See
> `df_surrogate/gamma_df.py` K UPDATE + openspec/changes/df-coeffs-cfd-refit.
> **2026-07-06 (#2) — B2 χ_s homogenization fit.** K_ss now uses
> `chi_s_eff(type, ε)` (unit-cell periodic homogenization, ~0.65 at the
> Shanghai point vs the uncalibrated 1.0; `validation/chi_s_homogenization.csv`).
> The kernel gate is **insensitive** (frozen-B + convection-dominated: Q
> shifts ≤0.0002%, RMSRE identical to 2 decimals); evaluator-level Q moves
> 0.1–0.35%. Physical-correctness fix, not a gate-metric fix. The gate
> script previously bypassed χ_s entirely (inline `(1−ε)k_s`) — now wired.
> **2026-07-06 — A2 convergence criteria + A1 grid-study rerun.** The 3D SIMPLE
> mass residual is now inlet-mass-flux-relative (was absolute kg/s), the outer
> gate tracks Ta/Tb/Ts, and stall-exits report converged=False. Gate-grid
> numbers unchanged (5.28/3.21). The A1 rerun (4 grids, 16×8×4 → 128×64×32,
> per-case Richardson on the finest triplet) moves the grid-converged headline
> to **Δp ≈10% (floor 9.6%, median p 1.59) / Q ≈3% (2.8%)** — vs the 6/30
> 3-grid study's ≈12% (p_obs 0.76), which was measured under the old criteria
> and (for the figure) an earlier K; the attribution is mixed, both changed.
- **Production default (Pipeline3D solved-water + F2 + gamma_df, 2nd-order face Δp + CFD-refit K): Nz=3 gate dP 4.88% / Q 2.12%** — since 7/12, sections (a)/(b) below. Frozen-B kernel era (5.28/3.21, A2 criteria) reproducible via `--runner kernel`. Grid-converged ≈10% / ≈3% headline is from the A1 study (OLD kernel runner — re-run on the pipeline runner pending). Cell-centre+Dh²-K (legacy) was 9.82% / 12.06%.
  DF surrogate default = GammaDF multi-fidelity (`df_surrogate/gamma_df.py`) since 2026-06-12.
- **rbf backend reference (`TPMSHX_DF_METHOD=rbf`): Nz=3 dP 7.19% / Q 3.22%,
  Nz=10 dP 8.69% / Q 3.33%** — post 2026-06-04 mass-flux-inlet fix (which cut
  Nz=3 dP 17.43→7.19 by injecting the experimentally-correct air mass flow).
  The gamma_df−rbf gap (+2.6pp) is entirely the smooth-trend K; cF is
  gate-identical (534.8) by construction.
- **Clean no-leak Q (paper baseline): Q_air 1.73%** — lumped dual-Nu ε-NTU
  (`validate_shanghai_lumped_dual_nu.py`), surrogate-independent.
  Was 1.71% until f9a44a8 (2026-05-29, voxel N 256→128 default while
  `_C_COEFFS` stay N=256-fit; eps drift ≤0.21% per test_tpms_geometry_n128).
  Re-baselined 2026-07-13 after git-bisect on the migration server confirmed
  the shift is that commit, not environment (17ecec6→1.71%, f9a44a8→1.73%).
- rbf-side dP residual ~7% = true closure + geometry floor (the old "entrance
  convention" contributor was the velocity-inlet BC bug, fixed 2026-06-04;
  see memory `feedback_dp_gap_attribution`).

## ⚠️ 2026-07-12 (d) — 2D CONVERGENCE CRITERION REPLACED (legacy → F2), ledger C9

**2D's legacy `tol` was worse than 3D's — it was a TAUTOLOGY.**

`_mass_res_jit` is a PLANE-INTEGRATED flux defect. The pp solve drives the
per-cell divergence to zero, so every plane's mass flux telescopes to the inlet's,
and on a full-face outlet `max_j |Q_j − Q_in| / Q_in` has **nothing left to
measure**. Measured: **1.6e-15**. `tol` therefore fired at the `it >= 20`
minimum-iteration floor and **the solve stopped after 20 iterations** (3D ran 92).

Cost, on the production Pipeline2D (reference is hard: converged by 500 iterations
and then bit-stable out to 20 000):

```
dP_A:  production (20 iters/call)  -3.31 %   |  50 iters/call  -0.007 %  (1.24x wall)
```

Non-monotonic in velocity: −1.3 % at u = 1 m/s, peak **−3.4 %** at u ≈ 5–10, −0.2 %
at u = 40.

**2D needs F2 MORE than 3D did, and it is far cheaper** (3D: 2× wall for 0.2 %).

**The "164× LowRe speed-up would be undone" worry does not apply.** On a full-face
outlet the solve is not stopped by LowReExit at all — it is stopped by `tol` at
iteration 20; LowReExit never fires. The 164× (commit `9a01766`) was measured
against a **10 000**-iteration baseline; 20 → 50 is nowhere near it.

**The old 2D gate could not see this** — forcing its SIMPLE exit open moved its dP
RMSRE by 0.03 pp, while the same forcing on the production Pipeline2D moves dP by
3.4 %. It was kernel-direct and did not run `Pipeline2D`. Fixed in (c) below.

Same three gates as 3D (momentum + solved-cell continuity + global boundary mass);
`convergence_mode='f2'` is now the Pipeline2D default. F2 **rejects
`coupling='simpler'`** (SIMPLER solves the pressure directly — a different fixed
point; the "what SIMPLE drops is ∝ Pp" argument does not carry over unexamined).

**Re-baselined:** golden-2D compressible dP_A **+3.9…4.0 %** (air_air 14171 → 14722;
water_b 11990 → 12470). The PARTIAL side's dP_B barely moves (+0.002 %) — it exited
on the velocity criterion, not the tautological `tol`, so it was never badly
under-converged. Shanghai 2D gate **8.61 % → 8.62 %** (its cases happen to be
insensitive — which is exactly why it could not catch the defect).

Revert with `TPMSHX_CONV_MODE=legacy`.

---

## 🔴 2026-07-12 (c) — 2D PRODUCTION BUG: the outlet was anchored at the INLET pressure (ledger C8)

**A real bug in the shipped 2D code, not a scheme change.** `P_ref_abs` is the
**outlet** absolute pressure — the pp equation pins the outlet row at `Pp = 0` and
never corrects those cells' P, so the outlet's gauge pressure stays 0 for the whole
solve ⇒ `outlet P_abs ≡ P_ref_abs`, `inlet P_abs ≡ P_ref_abs + Δp`.

Every **production** 2D path was passing the **inlet** pressure:

| path | before | |
|---|---|---|
| `pipelines/stages_2d.py:485,500` | `P_ref_abs = P_in_abs` | ❌ |
| `optimization/evaluator.py:260,309` | `P_ref_abs = P_inA / P_inB` | ❌ |
| `validation/.../validate_shanghai_aligned.py` (the GATE) | 1D-seeded outlet pressure | ✅ |
| `pipelines/run_stack_3d.py:620` (3D) | `_seed_p_ref(P_out_sq, …)` | ✅ |

So the outlet sat AT the inlet pressure and the whole field floated up by Δp. The
compressible density was wrong everywhere, by a factor that **grows with Δp/P_in**.

Measured, Shanghai case 16 (experiment: 304.7 kPa in → 126.1 kPa out, Δp = 178.7 kPa):

```
before:  inlet 407.3 kPa -> outlet 304.7 kPa   Δp = 102.6 kPa   (-42.6 %)
                                  ^^^^^ the experiment's INLET pressure
after:   inlet 289.0 kPa -> outlet  98.1 kPa   Δp = 190.9 kPa   (+6.8 %)
kernel gate (which always did it right):       Δp = 191.4 kPa   (+7.0 %)
```

Error scales with Δp/P_in: case 1 (0.011) ≈ 1 % low; case 16 (0.59) 43 % low.

**Why it stayed invisible: the 2D gate is kernel-direct and seeded the outlet
correctly itself — it was validating a path production does not run.** (Structurally
the same failure as the old 3D kernel gate; see section (a) below.)

**For the OPTIMIZER this is a ranking distortion, not just a magnitude error** — the
error grows with Δp, so high-Δp designs were mis-scored against low-Δp ones, which is
exactly the comparison the optimizer exists to make. Every historical 2D Pareto front
was produced under it.

Fix: both production paths now seed `P_ref_abs` from the same 1D compressible
Forchheimer closed form 3D uses (`envelope.predict_outlet_p_sq`), with the same
(K, cF) the solver builds internally. Incompressible sides (water, sCO2 Phase-A) keep
`P_in` — ρ is frozen there, so only pressure GRADIENTS matter and the gauge level is
inert (verified: golden-2D `water_b.dP_B` moves −0.002 %).

**Re-baselined:** golden-2D compressible Δp **+9…11 %** (air_air dP_A +9.14 %,
dP_B +10.76 %; water_b dP_A +9.11 %); Q +0.1…0.3 %; water dP_B unchanged. Optimizer
`test_evaluator_frozen_values` 2D tuples (Q +4…5 %, dP +5…6 %; 3D untouched).

**A test was pinning the bug as a feature.** `test_2d_high_dp_inlet_anchored_not_falsely_flagged`
asserted that a **Δp ≈ 3 × P_in** operating point produces a VALID result — i.e. that a
point whose true outlet pressure is **−2 atm** is physical. It passed only because the
outlet never fell. It has been rewritten to assert the opposite: that operating point is
choked and must be REJECTED, exactly as 3D rejects it.

**Still open:** 2D has no pre-solve choke guard (ledger O1) — the seed clips
`P_out² ≤ 0` to a 1e4 Pa floor rather than raising; the post-solve envelope gate is what
catches it. And the seed is only an estimate, so the SOLVED inlet pressure ≠ the
specified `P_in` (case 16: 289.0 vs 304.7 kPa). 3D has the identical limitation. A
shooting loop on the seed would tighten both dims — not done.

---

## ⚠️ 2026-07-12 (b) — 3D CONVERGENCE CRITERION REPLACED (legacy → F2), ledger C6/C7

**`RMSRE_dP 4.93 % → 4.88 %`; `RMSRE_Q 2.12 %` unchanged.** Physics unchanged; the
*convergence criterion* changed, so the solve now stops later and closer to the
fixed point.

**What was wrong.** The legacy exit gated `tol` on `_mass_res_jit_3d`. That number
is a **boundary artifact**, not a convergence measure:

* `_build_pp_sparsity_3d` marks every open outlet cell `cell_kind = 1`, and
  `_assemble_pp_3d` **replaces** those cells' continuity equation with `Pp = 0` —
  a Dirichlet pressure-outlet BC over the whole face. Those cells are never solved.
* The residual is then evaluated against `rho_eps_field` — the *same array* the pp
  solve had just driven `div(rho_eps·u) = 0` against, before `_update_density`
  refreshed rho. So on every cell the pp equation *did* solve, it is ~0 by
  construction (measured 2.9e-17 with the outlet row excluded, direct-solve path).

⇒ the reported number was 100 % the outlet row's uncorrected transverse divergence.
It never reached `tol` on **any** of the 16 Shanghai cases (floor 7.9e-4 … 9.4e-4),
tripling `max_iter` moved it by **zero to the last bit**, and it scaled only with
`Nz`. What actually decided convergence was `LowReExit`'s *velocity-went-static*
heuristic — which fires while the momentum equation is still violated by 0.2–1.5 %.

**What replaced it (`convergence_mode='f2'`, the pipeline default).** Three
independent gates, each with its own tolerance, held for consecutive checks:

| gate | what it measures | default |
|---|---|---|
| `mom_tol` | `aP0·φ − (Σ a_nb·φ_nb + p_src)` — the SIMPLE fixed-point defect | `1e-4` |
| `mass_local_tol` | continuity over the cells the pp equation **solves** (`cell_kind == 0`), fresh rho, per-cell normalised | `1e-6` |
| `mass_global_tol` | `\|mdot_out − mdot_in\| / mdot_in` (+ `outlet_backflow_frac`) | `1e-6` |

A static velocity field now only **triggers a check**; it does not terminate.

**Measured cost** (`validation/cases/price_f2_convergence_3d.py` →
`reports/f2_pricing_3d.csv`; Shanghai 16 @ 20×10×3, wall excludes the JIT warm-up):

```
legacy     92 SIMPLE iters   0.217 s/case   exit=velocity   RMSRE dP 4.93 %  Q 2.12 %
f2 @1e-3  206 iters (1.74x)  0.377 s/case   exit=tol        RMSRE dP 4.87 %  Q 2.12 %
f2 @1e-4  234 iters (2.03x)  0.440 s/case   exit=tol        RMSRE dP 4.88 %  Q 2.12 %
f2 @1e-5  298 iters (2.57x)  0.557 s/case   exit=tol        RMSRE dP 4.88 %  Q 2.12 %
```

Judge by **wall time, not iteration count** — 2.5× the iterations is only 2.0× the wall.

**Coverage.** Shanghai 16 ✓ · golden air-air partial-BC 15³ / water-B / asym offset
(all `exit=tol`, every scalar moves **< 0.1 %** — an intentional golden-3D re-baseline)
✓ · AMG path 40×40×20 = 32 000 cells (`exit=tol`, `R_mom` = 8.8e-5, 2.10× wall) ✓ ·
**sCO2 not tested**.

**Scope.** 2D is untouched and stays **bit-identical** (its residual is a weaker,
plane-integrated metric and its LowRe early-exit has a 164× historical speed-up —
it needs its own pricing, ledger C7-Q4). The **optimizer deliberately stays on
`legacy`** (`core/evaluators.py` builds solvers directly and never sees this switch):
it produces rankings only, and Pareto picks are re-solved through the production
pipeline before any number is reported (ledger O2 / audit R3).

Revert with `TPMSHX_CONV_MODE=legacy` (reproduces 4.93 / 2.12 exactly).

---

## ⚠️ 2026-07-12 (a) — GATE RUNNER SWITCHED (frozen-B kernel → production pipeline)

**The canonical gate-grid numbers are now `RMSRE_dP 4.88 % / RMSRE_Q 2.12 %`**
(this section's switch produced 4.93 / 2.12; the F2 criterion above then moved dP to
4.88 %). Both were `5.28 / 3.21` before. Nothing in the physics changed — the *gate*
changed: it now runs the production `Pipeline3D` stack with the **water side SOLVED**,
instead of the kernel-direct runner with the water side **frozen**.

Why (full write-up in the `validate_shanghai_3d_real` module docstring):

1. **More accurate.** dP 5.28 → 4.88 %; Q 3.21 → **2.12 %** (a 34 % cut, and the
   first time 3D beats the 2D aligned kernel gate's Q RMSRE of 2.51 % — the
   ε-NTU LUMPED baseline is a different number, 1.71 %; early notes conflated
   the two).
2. **The frozen-B runner was fed part of the answer.** `Tb_prescribed` is built
   from the **measured** water outlet temperature (Excel col 25), and Q is
   `Σ h_vB·(Ts − Tb)·dV` — so Tb sets the driving force directly. That measured
   outlet temperature already encodes the true duty via the water enthalpy
   balance (0.0108 kg/s × 4180 × 5.42 K = **243.8 W**, vs the experimental
   AIR-side `Q_exp` of **248.4 W** — the same number inside the 2 % experimental
   closure error). Not a tautology (Q_exp is an independent air-side
   measurement), but the water field was pinned to truth rather than predicted.
   **The pipeline runner predicts it from scratch and still does better** — a
   method given LESS information giving a BETTER answer is the load-bearing part
   of this decision.
3. **The old gate validated a code path production never runs.** The GUI, the
   optimizer and the server batches all drive `Pipeline3D`.

Convergence of the new default (measured): all 16 cases converge the SIMPLE↔LTNE
outer coupling in **3 iterations**, none truncated. Cases 8 and 12–16
(u_A ≈ 22 m/s) log `A@init[stall]` — benign, and NOT the known clip-stall
mechanism (`p_clip_hits` = 0 everywhere): only the cold-start solve stalls, every
warm re-solve exits `'velocity'`, and the SIMPLE mass residual has a hard **≈8e-4
floor on every case** (disabling the early-exit and running 3× the iterations
moves it by nothing — case 16: 7.86e-4 → 7.86e-4, bit-identical). Consequence:
`tol = 1e-5` is 80× below an unreachable floor and **no Shanghai case has ever
exited via `'tol'`** — convergence is decided by the velocity-stability
criterion. The floor's root cause (discrete BC mass closure, most likely) is an
open item; it does not invalidate these numbers.

**The README headline (grid-converged Δp ≈ 10 % / Q ≈ 3 %) is NOT updated by
this**: that 4-grid Richardson study was run on the `kernel` runner and has not
been repeated on `pipeline`. Re-running it is a follow-up.

## To reproduce
- **Nz=3 default — production pipeline, water SOLVED** (canonical gate):
  `validate_shanghai_3d_real.py --nz 3`                              → **4.88/2.12**
- Nz=3 legacy frozen-B kernel:  `--runner kernel --nz 3`             → 5.28/3.21
- Nz=3 rbf reference (frozen-B): `TPMSHX_DF_METHOD=rbf --runner kernel` → 7.19/3.22
- Nz=10 rbf reference (frozen-B): `TPMSHX_DF_METHOD=rbf --runner kernel --nz 10` → 8.69/3.33
Both runners carry `pressure_clip_hits` + `pressure_state_valid`; Shanghai
n_invalid=0. (Before 2026-07-12 the pipeline runner hard-coded those two fields
to 0/1, which silently disabled its own pressure-validity exclusion — fixed.)
The SIMPLE solver's A+B low-Re early-exit (default on) makes the water-side solve
~24× faster with <0.01% effect on dP/Q (verified 2026-06-02; and see the residual
floor note above — the early-exit stops exactly where the solver would stop
anyway).

⚠️ `--runner pipeline` reported a hard-coded `pressure_clip_hits=0` /
`pressure_state_valid=1` until 2026-07-11, which made its own `n_invalid=0`
vacuous (the exclusion never ran). Fixed to read the real pipeline diagnostics;
the **kernel** gate runner — the one that produced 5.28/3.21 — was always
computing them for real, so the headline numbers are unaffected.

## Environment that reproduces these numbers (2026-07-11)
Until now this file recorded the physics provenance but **no version record**,
so "which numpy/numba produced 5.28/3.21" was unanswerable. Snapshot below is
the dev box; the full `pip freeze` is committed as
`constraints-devbox-2026-07-11.txt` (repo root).

- Python 3.12.10 (MSC v.1943, 64-bit), Windows
- numpy 2.4.4 · scipy 1.17.1 · numba 0.64.0 (llvmlite 0.46.0) · pyamg 5.3.0
- pandas 2.3.3 · joblib 1.5.3 · CoolProp 7.2.0 · PySide6 6.11.0
- torch 2.11.0+cu128 · botorch 0.17.2 · gpytorch 1.15.2 (optimizer stack only)

**Verified**, not merely captured: with `data/raw_data` present, the full suite
is green on this combo — `PYTHONHASHSEED=0 pytest sjtu_tpmshx/tests/ -q -n auto
--dist loadscope` → **1187 passed, 3 skipped, 0 failed**. That run exercised the
strictest pins: the exact-`==` DF golden gates (`test_df_backend_registry`,
`test_df_projection_equivalence`), the `rel=1e-12` frozen evaluator tuples, and
`test_df_source_parity` (XLSX-vs-prebuilt-CSV calibration, `rel=1e-6`) — the
last one normally **skips** for want of the gitignored Excel, so this is the
first recorded confirmation that the two calibration sources have not diverged.

This is *an* environment that reproduces the numbers; there is **no record**
that it is the one they were originally captured on (that record never existed).
`constraints-devbox-2026-07-11.txt` is a historical machine snapshot only; do
not use it to provision the current shared or BO server environment. Use
`requirements-lock.txt` or `requirements-lock-server.txt`, run the exact-lock
checker, and reproduce the gate before upgrading anything.

**Porting note:** the exact-`==` DF gates skip only when `CI=true`. On a server
running pytest by hand they *will* run, and cross-machine libm/FMA differences
shift the last ULP (`test_df_backend_registry.py:31` measured rel ~1e-13 on
ubuntu CI). A red there is expected drift, not a port bug — set `CI=true`, or
re-pin on the target machine.
