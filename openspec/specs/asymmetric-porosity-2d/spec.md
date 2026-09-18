# asymmetric-porosity-2d Specification

## Purpose
2D 非对称孔隙率的分配与输运约束。当前共享几何入口为
`models/asym_split.py`；流体和偏移适用范围仍受 `docs/architecture.md` 约束。
## Requirements
### Requirement: 2D LTNE kernel accepts distinct per-side void fractions

The 2D LTNE solver `solve_full_domain` SHALL accept distinct per-side single-channel void fractions ε_A and ε_B and route them through both Gauss-Seidel kernel variants (the lexicographic `_gs_full_chunk` and the red-black `_gs_full_chunk_rb`), weighting each fluid's convective transport by its own channel void fraction. It SHALL NOT raise `NotImplementedError` when ε_A ≠ ε_B.

#### Scenario: Asymmetric split solves without error

- **WHEN** `solve_full_domain` is called with ε_A ≠ ε_B that satisfy ε_A + ε_B = ε at every cell (absolute tolerance 1e-9)
- **THEN** the split is accepted and both kernel variants use the distinct fractions; native convergence and failure reporting still apply

#### Scenario: Per-side weighting is applied in the kernel

- **WHEN** a cell has ε_A > ε_B
- **THEN** fluid A's advective coefficient in that cell is scaled by ε_A and fluid B's by ε_B (not by a shared ε/2)

#### Scenario: Over-allocation and under-allocation are rejected

- **WHEN** abs(ε_A + ε_B − ε) exceeds 1e-9 at any cell, or only one side is supplied
- **THEN** `solve_full_domain` raises `ValueError`; the split cannot lose half the transport capacity by being halved twice

### Requirement: Symmetric input is bit-identical to the legacy path

For the symmetric case (ε_A = ε_B = ε/2, i.e. offset δ=0), the solver SHALL produce output fields bit-identical to the existing single-`eps_f_arr` path. The 2D symmetric-path equality and Shanghai regression checks remain in force.

#### Scenario: Zero offset preserves symmetric-path parity

- **WHEN** the offset δ=0 (symmetric porosity, no per-side override supplied)
- **THEN** output arrays retain the symmetric path's values; existing numerical equality and conservation checks remain in force

### Requirement: Per-side void fractions conserve total porosity

The per-side void fractions derived from the offset δ SHALL sum to the configured total porosity ε at every cell, so the split neither creates nor destroys void fraction.

#### Scenario: Geometry split preserves the total

- **WHEN** the geometry split ratio s = split_A is applied to total ε
- **THEN** ε_A = ε·s and ε_B = ε·(1−s), and ε_A + ε_B = ε at every cell

### Requirement: 2D pipeline derives per-side porosity from the offset δ

The 2D preparation SHALL derive ε_A and ε_B from the offset-isosurface δ (`cfg['delta_levelset']`) using the same geometry split ratio as the 3D preparation. Runtime passes these prepared fractions to `solve_full_domain`. When δ=0 it SHALL use the default symmetric split of the full ε inside the kernel, without halving upstream.

#### Scenario: Nonzero offset drives an asymmetric run

- **WHEN** `cfg['delta_levelset'] ≠ 0`
- **THEN** the pipeline computes (ε_A, ε_B) = (ε·split_A, ε·(1−split_A)) and the 2D run uses asymmetric per-side porosity end-to-end

#### Scenario: Zero offset uses the symmetric path

- **WHEN** `cfg['delta_levelset'] = 0`
- **THEN** no per-side override is supplied; the kernel forms ε/2 once and uses the same array for both sides

### Requirement: 2D duty extraction weights mass flux by per-side void

The 2D dP/Q duty extraction (mass flow, mass-weighted outlet temperature/enthalpy) SHALL weight each side's mass flux by that side's void fraction (ε_A for A, ε_B for B) when δ≠0, consistent with the per-side porosity handed to the kernel, so that ṁ_A / ṁ_B and the resulting duty are physical on the asymmetric geometry.

#### Scenario: Asymmetric duty weighting

- **WHEN** δ≠0 and the per-side outlet mass flux is computed
- **THEN** side A is weighted by ε_A and side B by ε_B, and ṁ_A / ṁ_B reflect the actual per-channel void fraction (not a shared ε/2)
