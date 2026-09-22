"""Frozen-value regression for the 2D + 3D continuous-field evaluators.

NOTE ON "C7": in this file's history comments, "B3 C7" is the 2026-06-13
shared-QUANTIZATION dedup work item — NOT the research ledger's C7 (the F2
convergence criterion, 2026-07-12). The two collided by accident; dated
context disambiguates each mention.

Pins the exact (Q_neg, dP, mass) outputs of ``evaluate_design`` (2D) and
``evaluate_design_3d`` (3D) on fixed decision vectors, captured on master
BEFORE the B3 C7 shared-quantization dedup. C7 moves the per-cell
(L, t) quantization key from Python ``round()`` to ``np.round`` inside the
shared ``solvers.continuous_field.props_from_Lt_fields`` helper; both are
round-half-even and should agree on the 0.05/0.01-quantized grid, but a
key shift of 1e-4 mm would feed different ``tpms_calc.compute`` inputs and
move the result at >=1e-6. This test is the gate that catches exactly
that — the NON-UNIFORM cases exercise the multi-unique-pair scatter path
(a uniform field has cache_size==1 and would not gate the rounding).

rel=1e-12 (not exact ==): same-machine numba is deterministic, but the
tolerance absorbs trailing-ULP float-repr noise while still catching any
rounding-key / ordering change (which moves results far above 1e-12).
The manual historical golden diagnostics have a separate capture/check
workflow. Investigate any mismatch in the configured environment; changes
to these references follow the documented, user-approved disposition.

Marked ``slow`` (each eval is a full SIMPLE x2 + LTNE solve).
"""
from __future__ import annotations

import warnings

import numpy as np
import pytest

warnings.filterwarnings('ignore', category=UserWarning)

from sjtu_tpmshx.models.continuous_field import uniform_field
from sjtu_tpmshx.optimization.evaluator import evaluate_design
from sjtu_tpmshx.optimization.evaluator_3d import evaluate_design_3d

pytestmark = pytest.mark.slow

# 2026-09-14: legacy convergence retired across all consumers. Same inputs,
# bounds and budgets; old ec1c73e with only F2 enabled reproduces the new fields
# and tuples. Preserve the original four failures and values in the architecture
# report; do not treat the change as new experimental/physical qualification.
# The original comparison tolerance stays unchanged.
_REL = 1e-12

# Lighter solver settings (mirror tests/test_evaluator_sanity.py:_FAST_CFG).
# Preserve the resolved geometry bounds used to capture these references.
# New searches use 0.3..0.6 mm; these historical vectors were clipped at 0.5.
_FAST_CFG = {'max_iter_simple': 800,
             'max_iter_energy': 1500, 'tol_energy': 0.5, 'n_rho_loops': 1,
             't_bounds': (0.3, 0.5)}

_CFG_3D = {'Nx_3d': 10, 'Ny_3d': 6, 'Nz_3d': 3, 'max_outer_3d': 2,
           'max_iter_energy': 800, 'tol_energy': 0.5, 't_bounds': (0.3, 0.5)}

# Non-uniform 16D decision vector: [L_flat(8), t_flat(8)] (mm), L > t.
# n_ctrl=(4,4) symmetric_y → 8 L + 8 t. Spatially-varying ⇒ many unique
# quantized (L, t) pairs ⇒ exercises the scatter rounding C7 touches.
_X_NONUNIF = np.array([5.0, 6.0, 7.0, 8.0, 5.5, 6.5, 7.5, 6.0,
                       0.40, 0.45, 0.50, 0.55, 0.42, 0.48, 0.52, 0.46])

# ── frozen outputs captured on master pre-C7 (2026-06-13) ──
# 2D Q re-baselined 2026-06-24: the 2D-coupling-stability fix makes fluid B use
# 1st-order convection (no SOU) — needed because the SOU deferred correction
# destabilises the stiff outer coupling at fine grids (water dT_B oscillates).
# Effect is isolated to the energy Q[0] (~0.48% shift, deterministic); dP[1] and
# mass[2] are unchanged. See solvers/ltne_energy.py `_gs_full_chunk` fluid-B block.
#
# 2D re-baselined 2026-06-25: the 2D air solve switched to the MASS-FLUX inlet
# (hold inlet ρ·v constant, SIMPLESolver._apply_massflux_inlet — the 2D port of
# the 3D Bug-B fix, per-cell v_inlet_field[i] = G/ρ[i,0] = "Option A"). It pins
# the physical inlet throughput instead of letting it float with the
# compressible inlet density, fixing the velocity-inlet grid drift (Shanghai 2D
# dP RMSRE 35.8%→8.4%, ≈ 3D). Verified the entire drift here is attributable to
# it: with massflux_inlet=False both tuples reproduce the prior frozen values to
# rel=1e-9. Q[0] and dP[1] move (deterministic); mass[2] (geometry) is unchanged.
# Per-cell (Option A) vs lateral-mean (Option B) differs only at rel≤2e-6 here
# (inlet density near-uniform on a full-face inlet). Old: (-8536.46.., 11140.60..)
# / (-7992.76.., 8246.63..).
#
# 2D Q re-baselined 2026-06-25 (#2): the ENERGY SOU deferred correction is now
# face-consistent — each shared face uses F_face=0.5*(Fx_P+Fx_nbr) so the
# correction telescopes globally instead of injecting spurious energy on the
# compressible (non-uniform-velocity) fluid-A field (audit: 2d-sou-not-
# conservative). ONLY Q[0] moves (the energy field): +0.035% uniform / +0.022%
# nonuniform; dP[1] (SIMPLE pressure) and mass[2] (geometry) are bit-identical.
# Old Q: -8168.931136825195 / -7734.528734545178.
#
# 2D re-baselined 2026-06-28 (N2): the MOMENTUM SOU deferred correction is now
# face-consistent too — each face's minmod limiter is scaled by THAT face's flux
# (Fw west, Fe east; Fs/Fn) so it telescopes instead of using one cell-flux for
# both faces (audit N2, the momentum analog of the 2026-06-25 energy fix). Now
# BOTH Q[0] (energy depends on velocity) AND dP[1] (SIMPLE pressure) move at
# TRUNCATION level (~6e-7 / 2.3e-5 uniform; mass[2] geometry bit-identical). The
# SOU is a minmod-limited high-order correction sub-dominant to the Forchheimer
# drag, so Shanghai 2D validation is UNCHANGED (RMSRE_dP 8.35% / Q 2.51%).
# Old: (-8171.756522905283, 10057.99677021549) / (-7736.238110417324, 7584.5716386808235).
# re-baselined 2026-06-30: gamma_df K moved from the SmoothDF Dh² trend to the
# CFD-refit surface (c_F unchanged). dP[0] and Q[1] move (K shifts the Darcy term
# and, via the velocity field, the h_v coupling); mass[2] (geometry) is unchanged.
# See gamma_df.py K UPDATE note + openspec/changes/df-coeffs-cfd-refit.
#
# 2D NONUNIF re-baselined 2026-07-02 (R1, openspec solver-efficiency-r1-r4):
# SIMPLESolver.solve() gained the 3D-style lowre early-exit (velocity-stability
# gated). The nonuniform eval's SIMPLE solve now exits at the plateau instead of
# burning max_iter_simple, so the frozen iterate shifts at plateau-noise level:
# Q[0] 1.4e-4, dP[1] 6.5e-4 rel; mass[2] (geometry) bit-identical. Deterministic.
# The UNIFORM case reaches the strict residual tol before the early-exit fires
# and is unchanged. Old: (-7724.45529028308, 8027.234654920353).
# re-baselined 2026-07-06 (B2): chi_S switched from the uncalibrated 1.0 to
# the unit-cell homogenization fit chi_s_eff(type, eps) (~0.59-0.83 over the
# production window) — K_ss drops ~35% at typical eps, weakening axial solid
# conduction. Q[0] moves (2D +0.07..0.12%, 3D -0.10..-0.35%); 2D dP[1] and
# all mass[2] are BIT-IDENTICAL (K_ss enters the energy solve only); 3D dP
# shifts ~1e-4 rel via the rho(T) outer coupling. Env TPMSHX_CHI_S=1.0
# reproduces the old tuples. Old: (-8155.898092263062, ...), (-7725.544448374041,
# ...), (-7847.064062565555, 18179.20973508683, ...), (-10066.289384156315,
# 5968.569070037876, ...).
# re-baselined 2026-07-06 (A3): 2D LTNE convection switched to SIGNED
# shared-face fluxes (temperature-form consistent, Patankar; the cell-local
# |u|-magnitude scheme mismatched fluxes across faces on non-uniform
# eps*rho_cp*u fields). ONLY Q[0] moves (2D uniform -0.049%, nonuniform
# -0.034%); dP[1] and mass[2] are BIT-IDENTICAL (energy solve only). 3D
# tuples untouched (3D kernel already conservative). Old Q:
# -8165.653571275229 / -7731.140029573464.
# re-baselined 2026-07-09 (M2, VANS ∇ε momentum): 2D momentum kernels now
# carry the ε-ratio flux factors (ε-divided VANS form; ledger B5). ONLY the
# NONUNIFORM 2D tuple moves (Q +0.027%, dP −0.107%, mass bit-identical) —
# uniform ε keeps r ≡ 1.0 exactly, so the uniform tuple and both goldens are
# bit-identical to the pre-M2 baselines (verified via golden_2d/3d_preM2
# capture). Old nonuniform: (-7728.475410596369, 8022.029234363068, ...).
#
# RE-BASELINED 2026-07-12 (ledger C8 — a real BUG, not a scheme change): the 2D
# evaluator was passing `P_ref_abs = P_inA / P_inB`. `P_ref_abs` is the OUTLET
# absolute pressure (the pp equation pins the outlet row at Pp=0 and never
# corrects its P), so this anchored the OUTLET at the INLET pressure and floated
# the whole field up by Δp. The compressible density was therefore wrong
# everywhere, by a factor that GROWS with Δp/P_in.
#
# For an OPTIMIZER that is not just a magnitude error, it is a RANKING
# distortion: high-Δp designs were mis-scored against low-Δp ones, which is
# precisely the comparison the optimizer exists to make. Every historical 2D
# Pareto front was produced under it.
#
# Both 2D tuples move (the 3D ones are untouched — 3D always seeded the outlet
# correctly via `run_stack_3d._seed_p_ref`):
#     uniform    Q  -8161.68 -> -8573.83 (+5.05 %)   dP 10661.11 -> 11320.61 (+6.19 %)
#     nonuniform Q  -7730.60 -> -8046.72 (+4.09 %)   dP  8013.42 ->  8429.88 (+5.20 %)
# mass[2] is bit-identical in both (geometry only).
# Old: (-8161.676768977079, 10661.113158337937, ...) /
#      (-7730.600183907583, 8013.423850696896, ...).
#
# 2D NONUNIF re-baselined 2026-07-13 (ledger C11 audit): (i) P_ref_abs is now
# RE-SEEDED from the solver's ACTUAL graded drag after override_simple_K_cF /
# set_K_cF_field (the constructor seed used the uniform mean geometry — the
# C8 outlet-anchor mechanism surviving on the graded branch); (ii) the graded
# eps_field push now refreshes the Brinkman μ/ε (was left on the scalar mean
# ε). Both are guarded on genuine non-uniformity, so the UNIFORM tuple is
# bit-identical (verified). Q +0.29%, dP −0.39%, mass bit-identical.
# Old nonuniform: (-8046.721764144899, 8429.876589408981, ...).
# NONUNIF re-baselined 2026-07-13 (#2, smooth_df._geom purity fix): the DF
# smooth-base geometry cache now evaluates AT its rounded 3-decimal key
# instead of at the caller's exact floats (pre-fix, the cached value depended
# on which caller hit the key first — order-dependent, ~0.14% cF drift shown
# by test_df_projection_equivalence under per-test xdist). The 0.05/0.01-
# quantized per-cell (L, t) carry ULP tails (k*0.05 accumulation), so rounding
# them moves eps_f/D_h at ULP level and the solved tuples at truncation level:
# 2D Q 1.2e-6 / dP 1.5e-6, 3D Q 3.9e-7 / dP 2.2e-5 rel; mass BIT-IDENTICAL
# (both dims). UNIFORM tuples bit-identical (6.0/0.4 and 4.0/0.6 are exactly
# representable → round is an identity). Projector baseline JSON recaptured
# in the same change. Old: (-8023.328438019232, 8397.055931922105, ...) /
# (-10759.937887695394, 5859.926835485792, ...).
# V2: production D-F changed from experimental gamma_df to the geometry-only
# water+sCO2 CFD table. Q and dP change; geometry mass remains bit-identical.
# 2026-09-07: accepted outlet closure/full end-CV changes made the old pins
# stale already at G=cef75a5. Actual face mass * cp(Tin) then changes |Q| by
# -0.0031863% / -0.0071319% versus G; measured G/A dP and mass agree.
# The accumulated historical drift is not attributed to this inlet fix alone.
# 2026-09-11: user-approved reference disposition after controlled B40
# history comparisons. Inputs, budgets and tolerance remain unchanged.
# Historical tuples and 4/4 failures are preserved under
# docs/history/README.md. This is numerical regression
# evidence, not physical acceptance or closure of the overall B40 gate.
# 2026-09-11: user-approved native air integral-enthalpy transport Q update.
# Previous references and subsequent 2/4 failure remain in B40 evidence.
# 2026-09-14 discretization v2: each momentum SOU face uses its own flow
# direction. Restoring only the prior kernels reproduces both old tuples at
# the original 1e-12 tolerance. Same inputs, bounds, budgets and masses.
# Prior uniform: (-8019.434130581629, 4675.147979229178, 3.446685791015626).
# Prior nonuniform: (-7507.811193372061, 4052.0456347246245, 3.6729327392578126).
# This shares the approved SOU numerical-reference revision. Search policy
# and the independent historical B40 disposition remain as recorded.
# 2026-09-15: shared stable model-h damping and SOU on both 2D fluids.
# Independent evaluator captures and three-process comparisons use unchanged
# inputs/budgets/_REL. Prior tuples and failures are retained in
# docs/history/README.md; no historical B40 gate is revised.
_FROZEN_2D_UNIFORM = (-8060.095418774442, 4675.0113541092605, 3.446685791015626)
_FROZEN_2D_NONUNIF = (-7546.534378624765, 4051.9767509675603, 3.6729327392578126)
# re-baselined 2026-07-09 (M2b): evaluate_3d now installs the PER-CELL
# eps_field (xmod-eps-field-3d-evaluator closed) + 3D momentum carries the
# guarded VANS ε-ratio factors. ONLY the NONUNIFORM 3D tuple moves — and by
# a REAL margin (Q −3.18%, dP −1.82%, mass bit-identical): that is the
# mean-ε approximation error the retired warning flagged, now corrected.
# Uniform 3D is bit-identical on this case (use_eps=0 guard path). Old
# nonuniform: (-10056.123672085494, 5968.430162466379, ...).
#
# 3D re-baselined 2026-07-12 (ledger C10): evaluate_3d's LTNE convective ρcp
# now uses SIMPLE's LOCAL ρ instead of `air_density(T, P_in)` — density at the
# INLET pressure over the whole domain, the pre-2026-06-09 behaviour the
# production pipeline (`run_stack_3d` variable_rho_cp) fixed long ago. Fluid A
# uses its re-solved ρ(P_local, Ta); fluid B (frozen, solved once cold) uses
# its solved ρ AS-IS so ρ·u stays the mass flux SIMPLE-B actually conserved.
# Q moves by a REAL margin (uniform −23.34%, nonuniform −10.51%): that is the
# size of the old inlet-P ρcp error on these dense (dP ≈ 18/6 kPa) designs.
# dP and mass are BIT-IDENTICAL (ρcp enters the energy solve only). Same
# commit: sB's per-cell eps_field is now mirrored along y (reverse-y mapping
# fix — an identity for these symmetric_y designs) and both solvers refresh
# _mu_eff_field to the installed per-cell ε (production pattern; moves the
# nonuniform dP at 1.4e-7 rel via the sub-dominant Brinkman term, uniform
# bit-identical). The same commit also fixes the OUTER-LOOP μ/ε refresh
# denominator (scalar ε → per-cell eps_field — the old line re-broke the
# per-cell install every outer iteration), which moves the NONUNIFORM tuple
# a further 1.5e-8 rel (uniform bit-identical: eps_field ≡ scalar there).
# Old: (-7819.313135202607, 18176.77875067786, ...) /
# (-9736.62293019604, 5859.925022099803, ...).
# 3D NONUNIF re-baselined 2026-07-13 (#2): see the smooth_df._geom purity
# note above the 2D constants — same change, same mechanism.
# Six-face outlet closure: old/new original configs both exit legacy tol at
# 10 iterations (rankings-only, not F2 convergence). Boundary fluxes change;
# keep the original inputs, budgets and _REL. Geometry mass is unchanged.
# Old uniform: (-9968.94601218934, 7546.892661164707, ...).
# Old nonuniform: (-10850.667870259445, 2879.2940311398415, ...).
# Previous complete-end-CV/wall references were unconverged observations:
# uniform (-7209.103274428575, 7519.596015609637, 6.323593139648438);
# nonuniform (-8672.919843820628, 2871.31457245229, 3.675970458984375).
# 2026-09-11 explicit approval: update only 3D Q/dP for native air h(T).
# Original inputs/budgets, masses and tolerance remain unchanged. New legacy
# convergence does not establish F2 or experimental accuracy. Old failures
# and boundary evidence remain in B40/3d-model-h-validation.md.
_FROZEN_3D_UNIFORM = (-6226.343494178779, 9173.850936483974, 6.323593139648438)
_FROZEN_3D_NONUNIF = (-7464.2909880375955, 3441.8758132098023, 3.675970458984375)


def _assert_tuple(got, frozen, label):
    assert len(got) == len(frozen), f"{label}: arity {len(got)} != {len(frozen)}"
    for i, (g, fz) in enumerate(zip(got, frozen)):
        assert float(g) == pytest.approx(fz, rel=_REL), (
            f"{label}[{i}] drifted: got {float(g)!r} vs frozen {fz!r}")


def test_frozen_2d_uniform():
    fc = uniform_field(6.0, 0.4, 'Diamond', 17.0, L_domain=0.10, H_domain=0.05)
    got = evaluate_design(x=None, cfg=dict(_FAST_CFG), fc=fc)
    _assert_tuple(got, _FROZEN_2D_UNIFORM, '2D-uniform')


def test_frozen_2d_nonuniform():
    got = evaluate_design(x=_X_NONUNIF.copy(), cfg=dict(_FAST_CFG))
    _assert_tuple(got, _FROZEN_2D_NONUNIF, '2D-nonuniform')


def test_frozen_3d_uniform():
    x_u = np.concatenate([np.full(8, 4.0), np.full(8, 0.6)])
    got = evaluate_design_3d(x_u, dict(_CFG_3D))
    _assert_tuple(got, _FROZEN_3D_UNIFORM, '3D-uniform')


def test_frozen_3d_nonuniform():
    got = evaluate_design_3d(_X_NONUNIF.copy(), dict(_CFG_3D))
    _assert_tuple(got, _FROZEN_3D_NONUNIF, '3D-nonuniform')
