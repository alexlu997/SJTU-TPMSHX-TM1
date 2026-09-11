<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/hero-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="assets/hero-light.svg">
  <img src="assets/hero-light.svg" alt="SJTU-TPMSHX — validated 2D/3D CFD solver for TPMS heat exchangers. Headline metrics: air-side Q RMSRE 1.73%, 3D pressure-drop RMSRE ~10% (grid-converged), 3D heat-duty Q RMSRE ~3%, MMS observed order p_obs ≥ 2.07." width="100%">
</picture>

<br><br>

![Python](https://img.shields.io/badge/python-3.12%20|%203.13-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-555555)
![V&V](https://img.shields.io/badge/ASME%20V%26V%2020-Standard%20Tier-2ea44f)
![Status](https://img.shields.io/badge/status-research%20%2F%20dissertation-orange)
![License](https://img.shields.io/badge/license-MIT-green)

🔗 **[github.com/alexlu997/SJTU-TPMSHX](https://github.com/alexlu997/SJTU-TPMSHX)**

</div>

> [!IMPORTANT]
> Research / dissertation code — APIs evolve and rough edges are expected.
> Porous-media CFD with LTNE energy, dual air/water Nusselt closures, and an
> ε-NTU lumped solver, benchmarked against the **Shanghai 16-case** experimental dataset.

---

## 🚀 Headline results

<div align="center">

| Metric | Value | Where |
|:------:|:-----:|:------|
| **Air-side Q** RMSRE | **1.73 %** | ε-NTU lumped dual-Nu, Shanghai 16-case |
| **Legacy 3D pressure drop** RMSRE | **≈ 10 %** | historical gamma_df air/water baseline, grid-converged |
| **Legacy 3D heat duty Q** RMSRE | **≈ 3 %** | historical gamma_df air/water baseline, grid-converged |
| **sCO2 V2 2D/3D Q parity** | **0.85 %** | fixed-CFD D-F + true enthalpy gate |
| **MMS** observed order `p_obs` | **≥ 2.07** | code verification, SOU 2nd-order (gate ≥ 1.5) |

</div>

> [!NOTE]
> The Shanghai 3D headline values below belong to the historical `gamma_df`
> air/water baseline. V2 deliberately replaces production K/cF with the
> water+sCO2 CFD table. V3 adds an optional, applicability-gated experimental
> effective correction on that same base; the old percentages must not be
> attributed to the default CFD mode.
>
> The **grid-converged** 3D Δp RMSRE vs the Shanghai cases is **≈ 10 %** (4-grid all-axis
> refinement 16×8×4 → 128×64×32, per-case Richardson on the finest triplet, median p ≈ 1.6,
> under the A2 normalized-residual convergence criteria, 2026-07-06) — a **geometry / closure
> floor**: SLM roughness is already embedded in the experiment-trained Darcy–Forchheimer
> closure, so no extra friction multiplier (that would double-count). Two things shape the
> *finite-grid* value: a **mass-flux** air-inlet BC (removes a compressible velocity-inlet
> artifact) and a **2nd-order face-extrapolated** Δp reduction (`extract_dP_face_extrap`,
> which removes the cell-centre O(h) half-cell offset and accelerates convergence). At the
> validation-gate grid (20×10×3) the face-extracted Δp reads ≈ 5.3 %, but that grid is
> under-resolved: refining all three axes raises the Δp RMSRE to the ≈ 10 % floor, and the
> cell-centre and face reducers converge to the same continuous-PDE Δp. (The 2026-06-30
> study read ≈ 12 % with p_obs ≈ 0.76, measured under the earlier convergence criteria and
> an earlier K surface; the current ≈ 10 % floor and cleaner p ≈ 1.6 reflect both the A2
> criteria and the CFD-refit K.) **Q** is a duty integral, independent of
> the Δp reduction, grid-converged at **≈ 3 %**. Δp functional order is verified in
> `tests/test_dp_face_extrap_order.py`, direction-invariance (any ±x/±y/±z flow axis) in
> `tests/test_dp_direction_invariance.py`.

> [!IMPORTANT]
> **Gate runner switched 2026-07-12 — the water side is now SOLVED, not frozen.**
> The validation gate used to run a kernel-direct path with fluid B prescribed from the
> **measured** water outlet temperature (`Tb_prescribed`). It now runs the production
> `Pipeline3D` stack — the same code the GUI, the optimizer and the server batches drive —
> with a real SIMPLE-B water solve. At the gate grid (20×10×3) that moves
> **Δp 5.28 % → 4.88 %** and **Q 3.21 % → 2.12 %** (the first time 3D beats the 2D aligned
> kernel gate's Q RMSRE of 2.51 % — the ε-NTU *lumped* baseline is a different number,
> 1.73 %). The old runner was partly *fed* the answer: the measured outlet
> temperature already encodes the true duty via the water enthalpy balance, and Q is
> `Σ h_vB·(Ts − Tb)·dV`, so Tb sets the driving force. The new gate predicts it from
> scratch and is still more accurate. Legacy numbers reproduce with `--runner kernel`;
> full rationale in `validation/_CSV_STATUS.md` and the gate script's docstring.
> **The grid-converged ≈ 10 % / ≈ 3 % above are *not* affected** — that 4-grid study was
> run on the old runner and has not yet been repeated on the new one.

> [!IMPORTANT]
> **3D convergence criterion replaced 2026-07-12 (ledger C6/C7) — `f2` is now the
> production default.** The old exit gated `tol` on a mass residual that turned out to be
> a **boundary artifact**: the pressure-correction equation *replaces* the continuity
> equation on the whole outlet face with a Dirichlet `Pp = 0`, and the residual was then
> evaluated against the very density array the pp solve had just zeroed itself against. So
> it never reached its tolerance (measured floor 7.9e-4 … 9.4e-4 on **all 16** Shanghai
> cases) and what actually decided convergence was a *velocity-went-static* heuristic —
> which declares success while the momentum equation is still violated by 0.2–1.5 %.
>
> The pipeline now gates on three independent residuals — **momentum**
> (`aP0·φ − Σa_nb·φ_nb − p_src`, the SIMPLE fixed-point defect), **solved-cell continuity**
> (fresh ρ, Dirichlet cells excluded), and **global boundary mass** (plus a backflow
> fraction) — each with its own tolerance, held for consecutive checks. `exit_reason ==
> 'tol'` now means the equations are satisfied, not that the field stopped moving.
>
> Measured cost: **≈ 2.0× SIMPLE wall time** at `mom_tol=1e-4`, for **Δp RMSRE 4.93 % →
> 4.88 %** (Q unchanged at 2.12 %). Verified on the full Shanghai 16, on all three golden
> configs (air-air partial-BC / water-B / asym offset — every scalar moves < 0.1 %) and on
> the AMG path (40×40×20). **The optimizer deliberately stays on the legacy criterion** —
> it produces rankings only, and Pareto picks are re-solved through this pipeline. Reproduce
> the pricing: `validation/cases/price_f2_convergence_3d.py` → `reports/f2_pricing_3d.csv`.
> Revert with `TPMSHX_CONV_MODE=legacy`.
>
> **2D got the same treatment (ledger C9) — and needed it MORE.** 2D's legacy `tol`
> gated a PLANE-INTEGRATED flux defect, which the pp solve makes **tautologically
> zero** on a full-face outlet (measured 1.6e-15). It therefore fired at the
> minimum-iteration floor and **stopped the solve after 20 iterations**, leaving Δp
> under-converged by **3.3 %**. Going to 50 iterations removes that for **1.24× wall**
> — a far better trade than 3D's. (The old 2D gate could not see it: it was
> kernel-direct and did not run the production pipeline.) golden-2D compressible Δp
> re-baselines **+3.9…4.0 %**; the partial-BC side barely moves, because it exited on
> the velocity criterion rather than the tautological `tol`.

<div align="center">

<img src="assets/grid-convergence.png" width="84%" alt="3D grid convergence, Shanghai 16-case: under all-axis refinement the Δp RMSRE climbs from ~5% to a ~10% geometry/closure floor while the validation-gate 20×10×3 grid (~5%) is under-resolved; Q clean-converges to ~3%.">

<sub>All-axis (r=2) refinement, 16×8×4 → 128×64×32, A2 normalized-residual criteria. **Δp** RMSRE climbs to a **≈ 10 % geometry / closure floor** (per-case Richardson, median p ≈ 1.6) — the validation-gate `20×10×3` grid (★, ≈ 5.3 %) is under-resolved. **Q** is a duty integral: grid-converged at **≈ 3 %**. Regenerate: `runs/tools/plot_grid_convergence.py`.</sub>

</div>

---

## 🧩 What it does

| Layer | Capability |
|-------|------------|
| **Geometry** | Diamond + Gyroid TPMS sheet HX, parameterised by cell size `a` and wall thickness `t` |
| **Closures** | Production Darcy–Forchheimer `K(L,t)` and `c_F(L,t)` from the fixed water+sCO2 CFD grid with bilinear interpolation; independent of fluid and Re · per-fluid Nusselt correlations · solid tortuosity **χ_s(type, ε)** |
| **2D solver** | SIMPLE (Patankar), air/water/sCO2 ordered pairs, custom ±x/±y ports, Brinkman–Forchheimer porous core |
| **3D solver** | full SIMPLE 3D **+** 3D pressure-correction Poisson solve (PPE; optional Helmholtz/MAC divergence-free LTNE projection) · **mass-flux inlet** (ideal-gas) by default |
| **Three-fluid V2** | All nine ordered air/water/sCO2 pairs · custom 2D/3D ports on every ± axis · any pair containing sCO2 uses direct CoolProp and conservative face-mass-flow true-enthalpy transport |
| **D-F V3 modes** | `CFD 光滑壁面（默认）`: unchanged geometry-only K0/cF0 · `实验标定`: fixed reviewed effective correction, only when every side matches its campaign/geometry/boundary domain; no Re dependence or silent fallback |
| **Lumped** | ε-NTU dual-Nu cross-flow — `validate_shanghai_lumped_dual_nu.py` |
| **Validation** | Current sCO2 V2 gate: selected CFD Δp error **8.41 %**, 2D/3D Q difference **0.85 %**, mass residual ≈10⁻¹⁶; Shanghai percentages above are legacy gamma_df results |
| **V&V** | ASME V&V 20 Standard Tier — MMS code verification (`p_obs ≥ 2.07`), GCI grid convergence, tolerance sweep |
| **GUI** | PySide6 + pyvistaqt 3D viewer · 3-workspace session persistence · glassmorphism dark theme |

All non-opening exterior faces are stationary no-slip walls. Momentum uses
half-cell tangential viscous fluxes, including both z walls in 3D, with no
extra volume penalty or post-solve velocity attenuation. Rectangular openings
intersect the actual primary and staggered grids directly; geometric support
is separate from the inlet taper. A single-layer 3D momentum solve retains
its z walls, while 2D has no finite-thickness z-wall term. Dated validation and
performance numbers above predate this wall change; affected production
acceptance is pending.

Water use is currently limited to research and design comparisons for existing
low-temperature, near-atmospheric-pressure cases, retaining the current property
formulas. R&D acceptance targets are **RMSRE ≤ 10% for both whole-exchanger Q and
water-side pressure drop**. Outlet temperature is assessed using absolute error
in K, alongside the actual temperature rise and measurement uncertainty.
Acceptance against matching fixed experimental cases is still pending; local
property comparisons establish neither general high-pressure applicability nor
whole-exchanger accuracy. The existing Shanghai validation reports **air-side**
pressure drop by default.

Water pressure-drop measurements serve as a **system-level water-pressure-drop
proxy**, including inlet/outlet piping losses that cannot be recovered separately.
Compare the current core prediction directly with measured system loss over fixed
case members, reporting RMSRE and signed bias against the 10% RMSRE R&D target.
Underprediction alone does not establish failure of the core resistance model,
and meeting this proxy target does not demonstrate 10% core pressure-drop accuracy.
Preserve the measurements without estimating or subtracting piping losses,
adding offsets, or refitting parameters to pass. For the new fixed Shanghai
16-case wall/experimental-D-F run specifically, the approved water proxy gate
is RMSRE ≤25% and whole-exchanger Q remains ≤10%; this scoped exception does
not replace the historical results or general R&D target. The new air-side
pressure-drop gate is pending a user decision (12% is only a candidate).

---

## 📐 Closure correlations

<div align="center">

<img src="assets/gammadf-error.png" width="92%" alt="gamma_df Forchheimer cF interpolation error — cF vs cell size L for Diamond and Gyroid, model curves at t=0.3/0.4/0.5mm with rough-experiment anchors at L6/L8 and leave-one-out blind predictions; LOO RMSRE 2.5% Diamond, 2.6% Gyroid.">

<sub>**Legacy/research `gamma_df` backend** is not either production UI mode. V3 experiment calibration is rebuilt on the current fixed-CFD K0/cF0 base and uses dataset/campaign applicability gates.</sub>

The experiment selector is a data-routing key, not a claim that K/cF differences
are intrinsic to air, water, or sCO2. The available campaigns use different rigs,
boundaries, pressure taps, manifolds, flow-area definitions, instruments, and
reduction paths; their individual contributions are not separated. Air's
core-specimen branch is limited to the L=6..8 mm, t=0.3..0.5 mm domain. sCO2 is HX-effective only
for uniform symmetric D/G-7-6; its original hot-side calibration/source-audit windows are:
0.5827..2.5396 m/s (Diamond) or 0.6120..2.4705 m/s (Gyroid). These ranges use
corrected absolute pressures for the same measured hot-side `ok_dp` members,
mass flows and experimental flow areas; sF remains frozen at 6.313005350332494
(Diamond) and 7.608907691857889 (Gyroid). The fitted D-F parameters
act as the porous-region closure and may be used with valid custom inlet/outlet
centres, widths, and any solver-supported flow direction; the calibration
measurements themselves used full faces with x-direction flow.
The water+air D/G-7-6 specimen has two complete, separate TPMS fluid networks
and delta=0; both sides therefore use the topology-derived single-side area (Diamond
5.94e-4 m², Gyroid 6.50e-4 m²), not `(28/34)*A_air`, the full 42×42 mm face,
or that face divided by two. In the reviewed operating window `u_water>=0.10
m/s`, the fixed-K0 water corrections are sF=4.8928 (Diamond, RMSRE 6.84%) and
4.1989 (Gyroid, 0.93%); they are bounded above by the measured 0.2541/0.2232
m/s limits. Matching HX-air uses separate sF=1.8024/2.0120 corrections over
the measured inlet-velocity windows 7.6566..22.7599 / 7.5231..24.5414 m/s.
These are the original calibration windows, retained unchanged for fitting
membership and source audits; lower-flow records remain intact. Raw records remain intact; water
`G_7_6/工况1` is excluded as negative dP, and `D_7_6/工况10` plus `工况11`
are both excluded as ambiguous duplicate rows. Custom-port runs use the same
calibrated porous D-F parameters; their boundary layout was not independently
validated by this full-face campaign. Each side selects its correction independently,
so all nine ordered air/water/sCO2 pairs are available when both sides satisfy their
own geometry, domain, and velocity applicability rules. Combining corrections from
different campaigns enables a model calculation; it is not joint experimental
validation of that fluid pair.

Production application windows approved on 2026-09-09 are distinct from those
calibration windows. With current inlet properties and voxel single-side area,
they are (Diamond / Gyroid, m/s): water **0.0139648–0.254055 / 0.0162341–0.225876**,
air **3.88324–22.7599 / 3.91282–24.5467**, sCO2 **0.434925–2.53961 /
0.381408–2.47046**. K0 and every frozen sF remain unchanged. Going outside the
original calibration window records the actual inlet speed, both windows,
side and approved purpose in run warnings and result metadata. Water's much
lower admitted speeds are approved extrapolation, not new fitted evidence.
This permission covers the reviewed 7/0.6 mm, 0.182×0.042×0.042 m measured
combinations and approved port checks; it does not establish an arbitrary
T/P/mass-flow domain or relax property-state guards.

<br><br>

<table><tr>
<td><img src="assets/nu-air-error.png" width="100%" alt="Air-side Nu vs Re — CFD scatter and solver correlation curves for Diamond (orange, RMSRE 10.1%) and Gyroid (blue, RMSRE 9.9%), Nu = c·Pr^(1/3)·Re^a·(Dh/L)^d, smooth-wall, Re 400-16k, dashed = x1.28 production roughness."></td>
<td><img src="assets/nu-water-error.png" width="100%" alt="Water-side Nu vs Re — CFD scatter and solver correlation curves for Diamond (orange, RMSRE 12.5%) and Gyroid (blue, RMSRE 12.0%), Nu = c·Re^a·Pr^(1/3), direct water-CFD fit, Re 100-50k, Pr 2.3-5.9."></td>
</tr></table>

<sub>Per-topology **Nusselt** power-laws (the solver's own coefficients, `solvers/nu_correlations.py`) — Nu vs Re over the full CFD fit set (**Diamond** orange · **Gyroid** blue). **Air** `Nu = c·Pr^⅓·Re^a·(Dh/L)^d` — smooth-wall fit RMSRE ≈ 10 %; production multiplies by **×1.28** experiment-derived SLM roughness (dashed). **Water** `Nu = c·Re^a·Pr^⅓` — direct fit to **water-CFD** (RMSRE ≈ 12 %).</sub>

</div>

---

## ⚙️ Install

The supported environments are macOS with Python 3.13 and Windows with
Python 3.12. Both use the exact shared versions in `requirements-lock.txt`.
For local development, keep one dependency-only venv per machine in a stable
path outside the repository. All worktrees on that machine can reuse it while
importing `sjtu_tpmshx` from their own repository root.

macOS:

```bash
git clone https://github.com/alexlu997/SJTU-TPMSHX.git
cd SJTU-TPMSHX

python3.13 -m venv "$HOME/.venvs/sjtu-tpmshx-py313"
PYTHON="$HOME/.venvs/sjtu-tpmshx-py313/bin/python"
"$PYTHON" -m pip install -r requirements-lock.txt
"$PYTHON" -m sjtu_tpmshx.runs.tools.check_locked_environment requirements-lock.txt
"$PYTHON" -m pip check
printf '%s\n' "$PYTHON" > .venv-path
```

Windows PowerShell:

```powershell
git clone https://github.com/alexlu997/SJTU-TPMSHX.git
cd SJTU-TPMSHX

$venv = Join-Path $env:USERPROFILE ".venvs\sjtu-tpmshx-py312"
py -3.12 -m venv $venv
$python = Join-Path $venv "Scripts\python.exe"
& $python -m pip install -r requirements-lock.txt
& $python -m sjtu_tpmshx.runs.tools.check_locked_environment requirements-lock.txt
& $python -m pip check
Set-Content -Path .venv-path -Value $python
```

If the Python Launcher is unavailable, replace `py -3.12` with the actual path
to a python.org CPython 3.12 interpreter. The Windows test scripts reject an
Anaconda-based venv because that combination has crashed PySide6 on the server.

`.venv-path` is local and ignored by Git. Codex-managed worktrees copy it via
`.worktreeinclude`; for a manually created Git worktree, copy the file once.
Existing worktrees are not updated automatically. Remote/Cloud worktrees and CI
use environments provisioned in those runtimes rather than this local pointer.
Do not rely on shell activation in unattended work: read the interpreter from
`.venv-path` and invoke it by absolute path. On macOS, for example:

```bash
PYTHON="$(<.venv-path)"
"$PYTHON" -m sjtu_tpmshx.cli --help
```

`requirements.txt` deliberately adds `-e .` on top of the shared lock. Keep it
for CI or a conventional editable package installation; do not install it into
the shared worktree venv. In a dependency-only venv the `tpmshx-run` console
script is absent, so use `python -m sjtu_tpmshx.cli` from the repository root.
`pip` itself is intentionally not pinned because it is the installer, not a
runtime dependency; the exact-lock check always ignores it.
When a lock file changes, intentionally rebuild the affected shared venv at its
fixed path, then rerun the exact-lock check, `pip check`, and both smoke commands
below. A mismatch stops unattended entry points instead of changing the
environment. Do not use ad-hoc incremental `pip install` commands. Stop every
project Python process using that venv before replacing it because all
worktrees observe the change.

After creating or intentionally rebuilding the shared venv, prewarm its native
libraries while someone is present. This is also the acceptance smoke for
Pillow, Matplotlib, PySide6, PyVista/VTK, Numba, NumPy/SciPy, and CoolProp:

```bash
mkdir -p .cache/matplotlib .cache/xdg
MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg" \
  "$PYTHON" -m sjtu_tpmshx.runs.smokes.smoke_dependencies
MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg" \
  "$PYTHON" -m sjtu_tpmshx.runs.smokes.smoke_ui_offscreen
```

PowerShell uses the same two modules after setting
`$env:MPLCONFIGDIR = Join-Path $PWD ".cache\matplotlib"` and
`$env:XDG_CACHE_HOME = Join-Path $PWD ".cache\xdg"`.
The remaining `python ...` examples are shorthand: unattended macOS commands
should use `"$PYTHON" ...`, and PowerShell commands should use `& $python ...`.

The Windows Server BO stack is optional: provision the fixed
`$PORT_WORKDIR\venv` from `requirements-lock-server.txt` while someone is
present, then run `scripts/port_retest_server.ps1`. The server launch scripts
require an exact lock match and never create it or install packages.

`asym_pyfluent_runner.py` is a separate orchestration skeleton for a licensed
ANSYS Fluent workstation. `ansys-fluent-core` is intentionally absent from the
shared and BO locks: installing PyFluent does not install Fluent or its license.
Provision it separately only when that workflow is used, matching the Fluent
machine's supported Python/API versions.

GPU PyTorch is **optional** and only needed for research-backend retraining.
The production runtime reads the packaged fixed-CFD CSV; `gamma_df` and `rbf`
remain explicit research backends.

---

## ▶️ Run

> [!TIP]
> New here? Launch the **GUI** to explore geometry + solvers interactively, then
> reproduce the paper numbers headless with the **validation** scripts below.

#### 🖥️ GUI

```bash
python -m sjtu_tpmshx.main
```

#### 🧪 Headless validation — Shanghai 16-case

```bash
# Lumped ε-NTU dual-Nu — current paper baseline
python -m sjtu_tpmshx.validation.cases.validate_shanghai_lumped_dual_nu

# 3D real solver (SIMPLE, Nz=10, mass-flux inlet)
python -m sjtu_tpmshx.validation.cases.validate_shanghai_3d_real

# Independent Diamond L7/t0.6 pressure-drop gate
python -m sjtu_tpmshx.validation.cases.validate_d76_3d
```

#### ✔️ Tests

Reproducibility gates set `PYTHONHASHSEED=0` before Python starts; CI and the
Windows test scripts already do this.

```bash
# full suite
python -m pytest sjtu_tpmshx/tests/ -q

# development subset
python -m pytest -q -m "not slow and not heavy"
```

---

## 🗂️ Repo layout

```text
SJTU-TPMSHX/                   # repo root
├── sjtu_tpmshx/               # Python package
│   ├── solvers/               # SIMPLE 2D/3D, LTNE, tpms_calc, roughness, envelope, asym_split/asym_geometry
│   ├── pipelines/             # stages_2d / stages_3d (+ stages_3d_helpers)
│   ├── df_surrogate/          # Darcy–Forchheimer surrogate (gamma_df / rbf)
│   ├── controllers/           # Qt: ComputeOrchestrator, ResultCache, pipelines
│   ├── core/ domain/ configs/ # Qt-free evaluators / validators / canonical case JSON
│   ├── optimization/          # qNEHVI multi-objective Pareto
│   ├── design/                # quick multi-case TPMS sizing tool
│   ├── ui/                    # PySide6 widgets, themes, ui_builders
│   ├── assets/logos/          # branding images (gitignored png)
│   ├── runs/                  # orchestration: production entry-points + helpers + golden gate
│   │   ├── demos/ diagnostics/ smokes/ tools/   # scripts grouped by role
│   │   └── cfd_asym/ _out/
│   ├── validation/            # V&V — result CSVs + status docs at this root
│   │   ├── harness/           # reusable test infra (_harness, _metrics, _case_sets, …)
│   │   └── cases/             # runners (Shanghai, MMS, GCI, conservation audits)
│   ├── tests/                 # pytest suite
│   └── main.py                # GUI entrypoint
├── projects/                  # collaboration deliverables (624-Retrodict / 703-sCO2-D76 / 704-Aircooler-10kW)
├── openspec/                  # spec-driven change proposals + capability specs
└── reports/ opt_runs/ poc/ benchmarks/   # computed outputs / PoC / perf benchmarks
```

Local experiment and CFD inputs live under `data/raw_data/` and are intentionally
ignored by Git. The current local layout includes the experiment spreadsheets,
`sCO2-CFD/{Diamond,Gyroid}/`, and `CO2-CFD/{Diamond,Gyroid}/`. Keep those names:
the loaders resolve them relative to the repository.
The sCO2 experiment loader expects `data/raw_data/sCO2-Experient.xlsx`
(the historical project spelling).

Run the fixed-CFD, conservation, pressure-drop, and 2D/3D parity gate with
`python -m sjtu_tpmshx.validation.cases.validate_sco2_v1`.
The module name is retained for compatibility although the production closure
is now shared by all three fluids.

Run the full-core experimental-Q smoke with
`python -m sjtu_tpmshx.validation.cases.validate_sco2_exp_q`. The validation
maps measured mass flow to the solver's interstitial inlet velocity with
`A_void = (epsilon / 2) * (0.042 m)^2` and
`u_in = mdot / (rho(T_in, P_in) * A_void)`. The loader's mean-state `u` remains
only an experimental Re/f reduction and is not passed to the field solver.
The 2D mass flow and duty are per metre of depth and are multiplied by the
physical 0.042 m core depth before comparison with the workbook. The runner
also checks the inlet-face integral of `epsilon/2 * rho * u * dA` against the
measured mass flow at `1e-6` relative tolerance. Experimental Q is the midpoint
of the hot- and cold-side `mdot * abs(h_in - h_out)` values; it is a validation
reference only and does not refit Nu or the fixed CFD D-F coefficients.
For this experiment, the loader converts measured gauge MPa to absolute Pa
once by adding 101325 Pa. Endpoint enthalpies and signed hot/cold duties use
the locked CoolProp CO2 path at each measured endpoint temperature and absolute
pressure. The solver inlet pressure and mass-to-velocity conversion use the
same absolute pressure. Raw gauge pressures, measured pressure drops, and
cached REFPROP enthalpies/Q/heat balance remain available alongside the new
`coolprop-heos-gauge-101325-v1` reference; the original REFPROP version is unknown.
This derived reference is not an independent validation of the equation of state.

The default smoke, `--case`, and dynamically selected `--all-valid` runs check
numerical diagnostics only. Experimental-Q acceptance requires the original
case list from a prior acceptance metadata JSON (`expected_cases`), preserving
the same Diamond 43 / Gyroid 40 members across pressure/reference changes:

```bash
python -m sjtu_tpmshx.validation.cases.validate_sco2_exp_q --case-manifest .cache/prior-acceptance.csv.meta.json --accept-q --dimension both --csv .cache/sco2-exp-q.csv
```

This applies only to the D/G-7-6 sCO2 whole-exchanger experiment in the
`实验数据处理-Diamond` and `实验数据处理-Gyroid` workbook sheets. Fixed members
are retained even if new reference quality checks fail; new qualifying cases
are not added. Acceptance requires both sides passing `ok_done`, recomputed
`ok_hb`, positive finite signed heat duty and mass flow, inlet/outlet temperature
280–700 K and absolute inlet/outlet pressure 7.9–16 MPa. Old and new heat-balance
flags are reported; there is no `ok_dp` or `ok_dT` exclusion.
Each selected dimension/topology must contain every planned
case exactly once, with finite positive Q values and all existing numerical
checks passing. Empty, missing, duplicate or failed results cannot pass.
Errors are recomputed as `e = Qsolver/Qref - 1`; `sqrt(mean(e**2))` must be
≤20% for Diamond and ≤6% for Gyroid in 2D, and ≤21% for Diamond and ≤6%
for Gyroid in 3D. These limits apply only to this experiment. Bias
`mean(e)`, median/P90 absolute error and the existing diagnostics remain reports,
with no new bias threshold. An acceptance failure returns exit code 1.

`--topology` and `--dimension` explicitly narrow the reported verdict; a pass for
one selected scope does not establish the complete experiment requirement,
G1/G2, or full-core energy acceptance. No Nu/D-F refit is performed, and this is
not a claim of blind validation independent of all historical data. The runner
prints the selected case numbers and operating ranges. `--csv` preserves the
plain CSV format and adds a `.csv.meta.json` sidecar with code revision/dirty
state, recorded data pin (actual data revision remains unverified), selection,
Q/metric definitions and actual resolved D-F modes. Keep private numerical
outputs under ignored `.cache/`; final model acceptance still requires runs on
the actual delivery version and separately verified data and energy evidence.

For reproducible runs, use the `SJTU-TPMSHX-data` commit recorded in
`data-revision.txt`. On Windows Server, `scripts/port_retest_server.ps1`
checks out that revision and copies its `raw_data/` directory automatically.

Current architecture and physical invariants are documented in
[`docs/architecture.md`](docs/architecture.md). Contributor and coding-agent
scope rules are in [`AGENTS.md`](AGENTS.md).

---

## ✅ V&V

ASME V&V 20 **Standard Tier** complete (single-day closure, 2026-05-04):

| Phase | Result |
|-------|--------|
| **A — MMS code verification** | A.1–A.4, 5-grid h-refinement, `p_obs ≥ 2.07` (gate ≥ 1.5) |
| **B — Grid convergence (GCI)** | T2 g20 **0.81 %** · T4 `H=8` g20 **6.38 %** (> 5 % gate — partial-B not yet grid-converged; g30 4.01 %, monotone) |
| **C — Tolerance / iteration sweep** | spread **0.02 %** |
| **D — Domain sweep** | **18 / 20** PASS, applicability `u ≤ 10 m/s` |
| **E — Validation vs experiment** | Shanghai lumped Q RMSRE **1.73 %** |

3D PPE Phase-A MMS `p_obs ≥ 2.07` (SOU 2nd-order verified).

---

## 📖 Cite

If you use this code, please cite the dissertation (in preparation). Provisional BibTeX:

```bibtex
@misc{lu_sjtu_tpmshx_2026,
  author = {Lu, Alex},
  title  = {SJTU-TPMSHX: a Validated Solver for TPMS Heat Exchangers},
  year   = {2026},
  url    = {https://github.com/alexlu997/SJTU-TPMSHX},
}
```

---

## 📜 License

**MIT** — see [LICENSE](LICENSE).

<div align="center">
<sub>Research / dissertation code · APIs evolve, expect rough edges · contributions & issues welcome</sub>
</div>

### sCO₂ Nu modes

The independent **sCO₂ Nu** selector offers **CFD 光滑壁面** (default) and
**实验标定**. CFD keeps the existing smooth-wall formula. Experimental mode
multiplies it by one positive `alpha_D` or `alpha_G` before the existing Nu
floor; both sides and both dimensions use the same topology parameter.
Values below one are allowed. D-F, frozen sF, air and water Nu are unchanged.
This is effective heat-transfer correction in the frozen model, not measured
local Nu or a separately identified roughness effect.

No fitted parameters are bundled. In the GUI, use **导入标定参数…** to load a
local JSON with `alpha_D`, `alpha_G`, `parameter_version`, `source`, and
`applicability` (nonempty source/scope descriptions), then select the mode.
Save/Load and run snapshots retain the resolved contents, so subsequent file
or UI edits do not change an accepted run. Missing or invalid experimental
parameters are errors, never an automatic CFD fallback. Old configurations
without Nu settings use CFD.

For the existing CLI, add the same fields under `sco2_nu` in a canonical
ComputeConfig JSON, plus `"mode": "experimental"`, and run
`python -m sjtu_tpmshx.cli CONFIG.json --json` with the configured interpreter.
Keep real calibration files and derived experiment data private. Synthetic
parameters in tests are only software checks, not usable fitted coefficients.

Results, CLI/CSV/NPZ exports and persistent run history record the selected
Nu and D-F models separately, including parameter version/source/scope.
The source's declared scope is not a validation verdict; geometry outside
the uniform 7 mm / 0.6 mm specimen is flagged and existing state/closure
checks remain active. Uniform sCO₂ local-hv diagnostics retain the last
coefficient evaluation's pre-floor extrema and floor counts, explicitly
labelled as using lagged temperature. They do not recompute Nu on the final
returned temperature or accumulate a full time series. Calibration,
holdout, numerical/energy and final experimental Q acceptance are separate
from these software functionality checks.
