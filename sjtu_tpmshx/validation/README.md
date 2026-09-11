> [!WARNING]
> **SUPERSEDED (2026-07-13).** 本文最后系统更新于 2026-05-06，此后 gate runner、
> 收敛判据（F2，台账 C6-C9）、门禁数值（3D 4.88/2.12、2D 8.62/2.49）与部分脚本
> 均已变化，正文数字与文件清单不可再引用。**数字溯源以 `_CSV_STATUS.md` 为准**，
> 脚本清单以 [历史 validation 清单](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/d3ba040de0d43fce8e9b485396a5b660c2d87c5f/docs/atlas/validation.md)（2026-07-13 修订）为准。保留本文仅作
> 2026-05 时代的结构索引。

# Validation Scripts — Canonical Index

**Last updated:** 2026-05-06
**Maintainer:** alexlu997

---

## Canonical baselines (USE THESE)

| Entry point | Scope | Production metric | Status |
|-------------|-------|-------------------|--------|
| `validate_shanghai_lumped_dual_nu.py` | 16-case lumped ε-NTU, dual-Nu (air v4.1×1.28 + water Yan[6]) | **Q RMSRE 1.71%**, bias −1.27%, max 3.78% | 论文 baseline (paper) |
| `validate_shanghai_3d_real.py` | 16-case 3D SIMPLE + LTNE, Nz=10 | **Q 2.29% / dP 44.66%** | 3D production |

Both write outputs to `data/` and reference figures to `reports/figs/`. Both are forward predictions (no T_out leak; no test/train data leakage).

### Re convention pitfall (must know)
- Re uses **inlet manifold geometry** (Yan convention)
- A_tot uses **full-HX surface** (sheet HX topology)
- Mixing the two is a silent error — `_lumped_dual_nu.py` documents this in-line.

### Compressibility hard rule
All canonical scripts use `ρ = ρ(P, T)` (ideal gas). Never freeze ρ at inlet. Solver fix `simple_solver.py:_update_density` (2026-05-06 fix #1) clips P_abs ∈ [10 kPa, 1 MPa]; ρ derives from it.

---

## Other validation entry points (non-Shanghai, supportive)

- `mms_3d_air_air.py` + `mms_phase_a3_h_refine.py` + `mms_phase_a4_boundary.py` — V&V Standard tier MMS h-refinement (Phase A.2/A.3/A.4 closed 2026-05-04)
- `phase_c_gci.py` — ASME GCI calculation
- `audit_3d_conservation.py` — 3D mass/energy conservation audit
- `validate_chi_b_subset.py` — partial-B χ_B closure validation (per-cell mass-flux threshold)
- `posthoc_residual_correction.py` — residual correction for D-F closure (opt-in, env `TPMSHX_DF_RESIDUAL_CORR=1`)

---

## Legacy (`legacy/` — DO NOT USE for new work)

Moved 2026-05-06 (fix #5). Preserved for benchmark continuity + paper appendix reproducibility. See `legacy/README.md` for per-script status.

---

## Reproducibility checklist

Before claiming a validation result, confirm:

1. ☐ Compressibility: ρ=ρ(P,T) live (not frozen at inlet)
2. ☐ Re convention: Yan inlet manifold for Re; full-HX A_tot
3. ☐ Closure version: ConstDF-v1 D-F + Nu v4.1 + Yan[6] water
4. ☐ Excel input file commit hash recorded (Shanghai sheet path may shift on resave)
5. ☐ Output CSV contains `# script={file}, commit={sha}, date={ISO}` header
6. ☐ Numeric assertion in test (not "doesn't crash" — actually compares to baseline tolerance)

---

## Output convention

Canonical scripts write:
- Per-case CSV: `data/shanghai_validation_{lumped_dual_nu | 3d}.csv`
- Error figure: `reports/figs/shanghai_{lumped_dual_nu | 3d}_error.png`
- Summary log: stdout + `reports/<subdir>/<date>-shanghai-{topic}-CN.md`

Future fix (P1): write commit sha + script version into CSV header.
