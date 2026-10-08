<a id="cf_aniso--斜流-forchheimer-方向因子标定方向分辨单胞-cfd-工单"></a>

# cf_aniso — directional Forchheimer calibration for oblique flow

[中文](README.md) | [English](README.en.md)

Status: **awaiting direction-resolved CFD data. Not calibrated**. The research matrix and proposed criteria below stay for reference. They do not show experimental or CFD validation of current directional coefficients. This documentation work does not start calibration.

The objective is a measured coefficient for the 2D momentum factor `cF_eff = cF·(1 + cf_aniso·ξ4)`. Here `ξ4 = 4n_x²n_y²` is the lowest-order cubic-symmetry invariant. It is 0 along a principal axis and 1 at 45°. The mechanism exists in four `_kernels_simple_2d.py` kernels. Default `cf_aniso = 0` is bit-identical to previous behavior.

Axial flow is unchanged for any coefficient. This work order supplies the missing coefficient value. B3 / IDEA-PORT-VALID are historical research identifiers. The [fixed history index](../../../docs/history/retired-tools.md) keeps the previous project.

<a id="一为什么需要"></a>

## 1. Motivation

Current experimental and smooth-CFD K/cF calibration data uses unidirectional flow along TPMS principal axes. With partial-port boundaries, flow spreads through the domain at arbitrary local angles.

- Darcy term: Gyroid/Diamond cubic symmetry implies a theoretically isotropic K tensor, so no correction is expected. This work also includes a check of that assumption. Nonconstant K(θ) requires review of the B3 full-tensor route.
- Forchheimer term: cubic symmetry does not make quadratic resistance isotropic. Oblique-flow bias is unknown. This work quantifies it.

<a id="二算例矩阵每拓扑-45-例"></a>

## 2. Case matrix: 45 cases per topology

| Dimension | Values | Purpose |
| --- | --- | --- |
| Topology | Gyroid first. Optional Diamond second | Start with the optimizer's current target. |
| (L, t), mm | (4.0, 0.3) / (5.5, 0.45) / (7.0, 0.6) | Training-hull corner, center, and corner. |
| Flow angle θ | 0° / 22.5° / 45° in xy | ξ4 = 0 / 0.5 / 1.0, evenly spaced in the invariant. |
| Superficial velocity u_sup | 2 / 5 / 8 / 11 / 15 m/s | Similar scale to existing air unit-cell CFD sweeps. |

The proposed angle method rotates geometry, not flow direction. Rotate TPMS level-set sampling coordinates around z by θ, then extract STL. Keep flow along +x to reuse periodic translation boundaries and mass-flow control. The original proposal used ideal-gas, pressure-based steady, periodic + mass-flow-rate settings. Before real CFD, validate rotated periodicity, domain dimensions, and mesh independence. The current [architecture](../../../docs/architecture.md) has not accepted this research setup as valid.

Use a single-fluid unit-cell case: only the A network, with ε_f = ε/2. This matches the original DF calibration convention.

<a id="三每例产出"></a>

## 3. Per-case outputs

Record five velocity points as (u_sup, dP/L), plus mean-field ρ and μ. Fill `results_template.csv`. Keep its existing column names.

<a id="四拟合跑-fit_cf_anisopy"></a>

## 4. Fitting with fit_cf_aniso.py

```bash
PYTHON="$(head -n 1 .venv-path)"
"$PYTHON" -m sjtu_tpmshx.validation.cf_aniso.fit_cf_aniso results.csv
```

The script performs three steps:

1. For each topology/L/t/θ, fit `dP/L = (μ/K)·u + ρ·cF·u²` to get K(θ) and cF(θ).
2. Do a check of K isotropy. K(θ)/K(0) should stay within ±5%. Larger differences trigger a warning and a recommendation to review B3 full tensors.
3. Fit `cF(θ)/cF(0) − 1 = a·ξ4(θ)` by least squares. Get one a per (L,t). Report mean and spread. Spread within ±0.05 supports one coefficient.

   Larger spread suggests an (L,t)-dependent cf_aniso field. The existing mechanism already supports cellwise cF, which limits extension work.

<a id="五结果落位"></a>

## 5. Result adoption

The script outputs candidate K/cF and directional coefficients without changing production parameters. After data becomes available, review velocity, direction, geometry, boundaries, and pressure-drop definitions before selecting an integration approach. The previous screener's cf_aniso configuration entry retired with the air/air screening chain. Retired `run_port_dim_retest.py` is no longer a runnable next step.

<a id="六在标定完成之前"></a>

## 6. Before calibration is complete

The former dimension comparison and ±0.3 sentinel sweep stay research proposals only. Relative comparisons cannot show cancellation of directional error or absolute Q/dP accuracy. New research needs independently defined actual entries and acceptance conditions.
