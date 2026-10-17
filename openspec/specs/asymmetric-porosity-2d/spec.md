# asymmetric-porosity-2d Specification

[中文](spec.zh-CN.md) | [English](spec.md)

## Purpose
Define the allocation and transport rules for asymmetric 2D porosity.
The shared geometry entry is `models/asym_split.py`.
Fluid and offset applicability stay subject to `docs/architecture.md`.
Version 0.2 uses `prepare_case → run_case → evaluate` with the native full 2D driver.
Prepared inputs contain total porosity and the geometry split; the native driver derives both side fractions.
The [version 0.1 specification](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/v0.1.0/openspec/specs/asymmetric-porosity-2d/spec.md) preserves the retired Python entry and kernel requirements.
## Requirements
### Requirement: 2D LTNE kernel accepts distinct per-side void fractions

The native 2D thermal driver MUST use distinct single-channel void fractions ε_A and ε_B where the selected physical route supports asymmetry.
Each fluid's convective transport MUST use its own channel void fraction.
The retired Python kernel names do not define current entry points.

#### Scenario: Asymmetric split solves without error

- **WHEN** a supported prepared 2D case has ε_A ≠ ε_B and ε_A + ε_B = ε at each cell (absolute tolerance 1e-9)
- **THEN** `run_case` uses the distinct fractions. Native convergence and failure reporting still apply

#### Scenario: Per-side weighting is applied in the kernel

- **WHEN** a cell has ε_A > ε_B
- **THEN** fluid A's advective coefficient in that cell is scaled by ε_A and fluid B's by ε_B (not by a shared ε/2)

<a id="scenario-over-allocation-and-under-allocation-are-rejected"></a>

#### Scenario: Invalid prepared splits are rejected

- **WHEN** the prepared split is nonfinite, outside 0 < split_A < 1, or differs from 0.5 for a declared symmetric case
- **THEN** native execution raises `ValueError`. Both fractions are derived from the same total ε and split; neither is halved again

<a id="requirement-symmetric-input-is-bit-identical-to-the-legacy-path"></a>

### Requirement: Symmetric input keeps the existing regression limits

For the symmetric case (ε_A = ε_B = ε/2, i.e. offset δ=0), the native split MUST remain 0.5.
Existing native symmetric and Shanghai regression checks MUST keep their numerical limits.
The original bit-identical comparison against the Python single-`eps_f_arr` path remains a version 0.1 requirement in the historical specification.

#### Scenario: Zero offset preserves symmetric-path parity

- **WHEN** the offset δ=0 (symmetric porosity, no per-side override supplied)
- **THEN** output arrays keep the symmetric path's values. Existing numerical equality and conservation checks stay in force

### Requirement: Per-side void fractions conserve total porosity

The per-side void fractions derived from the offset δ MUST sum to the configured total porosity ε at each cell.
The split MUST neither create nor destroy void fraction.

#### Scenario: Geometry split preserves the total

- **WHEN** the geometry split ratio s = split_A is applied to total ε
- **THEN** ε_A = ε·s and ε_B = ε·(1−s), and ε_A + ε_B = ε at each cell

### Requirement: 2D pipeline derives per-side porosity from the offset δ

The 2D preparation MUST derive the split from the offset-isosurface δ (`ComputeConfig.geometry.delta_levelset`).
It MUST use the same geometry split ratio as 3D preparation.
The native full 2D driver receives the prepared total ε and split. When δ=0, each side MUST use ε/2 exactly once.

#### Scenario: Nonzero offset drives an asymmetric run

- **WHEN** `ComputeConfig.geometry.delta_levelset ≠ 0`
- **THEN** the pipeline computes (ε_A, ε_B) = (ε·split_A, ε·(1−split_A)) and the 2D run uses asymmetric per-side porosity end-to-end

#### Scenario: Zero offset uses the symmetric path

- **WHEN** `ComputeConfig.geometry.delta_levelset = 0`
- **THEN** the prepared split is 0.5. Native execution uses ε/2 for each side without another factor of 0.5

### Requirement: 2D duty extraction weights mass flux by per-side void

The 2D dP/Q duty extraction includes mass flow and mass-weighted outlet temperature/enthalpy.
When δ≠0, it MUST weight each side's mass flux by that side's void fraction: ε_A for A and ε_B for B.
These fractions MUST match the per-side porosity handed to the kernel.
This keeps physical ṁ_A / ṁ_B and duty on the asymmetric geometry.

#### Scenario: Asymmetric duty weighting

- **WHEN** δ≠0 and the per-side outlet mass flux is computed
- **THEN** side A is weighted by ε_A and side B by ε_B.
  ṁ_A / ṁ_B reflect the actual per-channel void fraction, not a shared ε/2.
