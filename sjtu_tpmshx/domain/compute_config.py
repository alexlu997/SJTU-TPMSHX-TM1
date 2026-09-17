"""Strict-typed compute configuration dataclasses.

Audit followup C3 (L-a-1, 2026-05-28): replace the implicit "window
object holds all settings" contract with explicit dataclasses. The
solver / runs / optimization / validation layers all accept
``ComputeConfig`` instead of the Qt window. The UI layer is the *only*
place that reads ``QLineEdit`` / ``QComboBox`` values — everything
below this module is Qt-free.

The module is deliberately pure: no imports from ``sjtu_tpmshx``
internals (only stdlib + ``typing``). This avoids any circular import
risk and keeps the schema readable from a single file.

Schema (per
``vault/reports/engineering/2026-05-28-sjtu-tpmshx-4-perspective-audit-CN.html``
§视角2 §2.2 with minor extensions noted inline):

- ``FluidConfig``     — per-side fluid (type + u + T_in + P_in)
- ``GeometryConfig``  — domain + TPMS unit-cell + solid k_s
- ``SolverConfig``    — grid + LTNE outer + SIMPLE inner + roughness
- ``ComputeConfig``   — composite, has the entrypoint adapters

Adapters
~~~~~~~~

- ``ui.window_config.config_from_window(window)`` — read ``window.le_*`` /
  ``window.combo_*`` once at the UI boundary; downstream callers no
  longer touch ``window``. (Moved out of this module in the contracts-layer
  split, 2026-07-02 — this module is now import-clean of any UI concern.)
- ``ComputeConfig.from_json(path)`` / ``to_json(path)`` — JSON
  serialisation for production validation scripts and tests.

Roadmap
~~~~~~~

C3 is the foundation for C4 (Pipeline ABC).  This module purposefully
does *not* describe partial-pipe BC, zone configs, or session state
(extrap reasons, cancel tokens) — those continue through their
existing window attributes for now; the grep gate (Task 4.3) limits
the scope to ``window.le_*`` reads, which this dataclass replaces.

Runtime env-flag registry (Batch-4, 2026-06-10)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Central inventory of every ``TPMSHX_*`` knob. Flags are read at call
time (never cached) so tests can monkeypatch them; each has one reading
site or one shared helper, listed here. Adding a flag = add a row.

- ``TPMSHX_ALLOW_EXTRAP`` (0) — surrogate out-of-window → warn, not abort.
  Read in ``df_surrogate/surrogate_domain.py``, ``solvers/sigmoid_field.py``,
  ``solvers/sigmoid_field_3d.py`` (3 identical 1-line parsers — kept local
  to avoid a solvers→df_surrogate dependency; keep in sync).
- ``TPMSHX_CHI_S`` (unset) — CONSTANT χ_s override (legacy escape hatch,
  pre-B2 default was 1.0). When unset, χ_s comes from the B2 unit-cell
  homogenization fit ``chi_s_eff(type, ε)`` (2026-07-06);
  ``solvers/tpms_props.py`` (read at import).
- ``TPMSHX_DEBUG`` (unset) — debug prints; ``solvers/simple_solver_3d.py``.
- ``TPMSHX_DISABLE_3D_PANEL`` (0) — skip PyVista panel;
  ``ui/builders_canvas.py``.
- ``TPMSHX_EAGER_3D_SLICES`` (0) — precompute 3D slices;
  ``ui/plot_3d_results.py``.
- ``TPMSHX_PARALLEL_THRESHOLD`` (200000) — red-black prange cell gate;
  ``solvers/simple_solver_3d.py`` (module-level, fixed at import).
- ``TPMSHX_PHASE_A/C`` (1/0) — adaptive AMG / coarse bootstrap.
  Captured by ``preprocess/three_d/preparation.py`` (cfg keys win).
  Phase B / inner SIMPLE Anderson is retired; explicit enablement raises.
- ``TPMSHX_PREINIT_3D`` (0) — prewarm 3D panel at startup; ``main.py``.
- ``TPMSHX_PROFILE_3D`` (0) — per-outer wall-clock profiler;
  ``pipelines/run_stack_3d.py`` (``_prof_3d_enabled``; ``.profile_3d``
  flag file works too).
- ``TPMSHX_ROUGH_MODE`` (baseline; UI path defaults norris_1a) +
  ``TPMSHX_ROUGH_EPS_UM`` (100) — roughness model; single helper
  ``solvers.roughness.resolve_mode_from_env``.
- ``TPMSHX_RUN_SHANGHAI_REGRESSION`` (0) — opt-in long validation gate;
  ``tests/test_shanghai_regression.py``.
- ``TPMSHX_SIMPLE_TOL`` (1e-5) — SIMPLE pp tol for diagnostic sweeps;
  single helper ``pipelines.run_stack_3d._simple_tol_default``.
- ``TPMSHX_VAR_RHOCP`` (unset) — local-P gas density override (UI checkbox
  is primary); ``pipelines/run_stack_3d.py``.

Registry sync 2026-07-03 (maintainability-closeout) — flags that existed
but were missing above:

- ``TPMSHX_DF_METHOD`` — explicit method for direct ``df_surrogate.predict``
  calls. Only ``cfd_full_core_3cell_fixed_v2`` is supported; retired method
  names fail. Production 2D/3D compute paths pin this fixed table.
- ``TPMSHX_ASYM_KAPPA`` (0) — research-only asym per-side κ correction
  after ``ingest_cfd_kappa``; production 2D/3D compute paths do not apply it.
  Read in ``df_surrogate/kappa_asym.py``.
- ``TPMSHX_NUM_THREADS`` (unset → numba default) — headless/script numba
  thread count; ``solvers/threads.py`` (GUI spinbox is primary). Unset on a
  many-core box + grid ≥ TPMSHX_PARALLEL_THRESHOLD → one-shot advisory log
  recommends ``recommend_solver_threads()`` (≈ min(64, physical cores);
  bandwidth-bound kernels; P3.2 — advisory only, pool never auto-changed).
- ``TPMSHX_BO_CORE_BUDGET`` (unset → whole machine) — this BO process's
  core share for the joblib workers×inner split; multi-arm launchers set
  it per arm (``optimization/optimizer_qnehvi.py::_resolve_core_budget``,
  engage-time INFO logs the resolved split).
- ``TPMSHX_SCO2_COMPRESSIBLE`` (0, experimental) — opt-in sCO2
  compressible path; ``pipelines/run_stack_3d.py``.
- ``TPMSHX_MAX_CELLS_3D`` (2000000) — hard 3D cell cap;
  ``pipelines/run_stack_3d.py`` (robustness-hardening).
- ``TPMSHX_BUILD_S_MAX`` / ``TPMSHX_BUILD_LX_MAX`` — sizing-tool build
  envelope caps; ``design/sizing.py``.
- ``TPMSHX_2D_MASSFLUX`` (1) — validation-only toggle;
  ``validation/cases/validate_shanghai_aligned.py``.
- ``TPMSHX_LOG_LEVEL`` (INFO) / ``TPMSHX_LOG_TS`` (0) — central logging
  level / timestamp prefix; ``logutil.py``.
"""
from __future__ import annotations

import json
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple, Union


FluidType = Literal['air', 'water', 'sco2']
DFMode = Literal['cfd_smooth', 'experimental']
TPMSType = Literal['Diamond', 'Gyroid']
RoughMode = Literal['baseline', 'norris_1a', 'bhatti_shah_1b']
ZoneAxis = Literal['x', 'y', 'grid']

SCO2_P_RANGE_PA = (7.9e6, 16.0e6)


# ── dataclasses ──────────────────────────────────────────────────────


@dataclass
class FluidConfig:
    """Single-side fluid inlet state."""
    type: FluidType = 'air'
    u_mps: float = 5.0
    T_in_K: float = 300.0
    P_in_Pa: float = 101325.0


@dataclass
class GeometryConfig:
    """TPMS unit cell + macroscopic domain + solid conductivity.

    ``Lz_m=None`` flags a 2D run; the legacy 2D path keeps using the
    XY plane and ignores Lz, while the 3D path *requires* ``Lz_m``
    (and ``solver.Nz >= 2``).
    """
    tpms: TPMSType = 'Gyroid'
    L_cell_mm: float = 7.0
    t_wall_mm: float = 0.6
    k_s_W_mK: float = 16.0
    L_dom_m: float = 0.182
    H_dom_m: float = 0.042
    Lz_m: Optional[float] = None
    # Asymmetric porosity: offset-isosurface centre δ (φ-units). 0.0 →
    # symmetric 50/50 (bit-identical). |δ|>0 → ε_A (φ<δ−C) ≠ ε_B (φ>δ+C);
    # consumed by models.asym_split._eps_sides_for_run. Human targets
    # (A%/B%) convert to δ in run scripts via runs/diagnostics/asym_target_scan.
    delta_levelset: float = 0.0


@dataclass
class SolverConfig:
    """Grid + PRODUCTION solver accuracy knobs (R3 rewire, 2026-07-07).

    History: these fields used to carry the OPTIMIZER's cheap-eval budget
    (tol 1e-2 / 800 iters) and were consumed by nothing else — the
    pipelines hardcoded their own values, so a saved JSON did not
    describe what actually ran. The optimizer budget now lives in
    :class:`OptimizerConfig`. For the production controls below, ``None``
    means "use the dimension-specific built-in":

    - ``max_outer_ltne``: SIMPLE↔LTNE outer iterations.
      Auto = 10 (2D coupling) / sweep-profile value (3D: 5, fast 3).
    - ``outer_tol_K``: outer temperature-delta tolerance [K].
      Auto = 1.0 (2D) / 0.5 (3D).
    - ``max_iter_simple``: SIMPLE inner iteration cap.
      Auto = 10000 (2D) / per-stage 600–2000 (3D).
    - ``tol_simple``: retained for configuration/call compatibility;
      it does not control the F2 gates described below.

    ``alpha_T`` (numerics-internal relaxation) and ``rough_mode`` (the
    bhatti_shah_1b option is the ledger-ROUGH-X double-count trap) were
    REMOVED from the user surface; ``from_dict`` drops them from legacy
    JSONs with a notice. Roughness sweeps remain possible via the
    ``TPMSHX_ROUGH_MODE`` env (research escape hatch).

    ``T_s_init_K=None`` falls back to the legacy seed
    ``0.5 * (T_inA + T_inB)`` inside ``solve_full_domain[_3d]``.

    F2 CONVERGENCE GATES (BOTH dims since C9, ledger C6/C7/C9 — 2026-07-12)
    ------------------------------------------------------------------------
    - ``convergence_mode``: ``None`` or ``'f2'`` in every compute mode and
      raw solver. Captured ``TPMSHX_CONV_MODE`` overrides config. The old
      mass/velocity exit and ``'legacy'`` selector are retired.
    - ``mom_tol`` / ``mass_local_tol`` / ``mass_global_tol``: independent
      momentum / solved-cell continuity / boundary mass gates, confirmed
      consecutively, with a separate outlet-backflow gate.

    ``tol_simple`` remains a serialized setting and ``solve(tol=...)`` remains
    callable; neither sets F2 tolerances. The pressure-subproblem residual
    history still drives adaptive AMG, independently of these exit gates.
    """
    max_outer_ltne: Optional[int] = None
    outer_tol_K: Optional[float] = None
    max_iter_simple: Optional[int] = None
    tol_simple: Optional[float] = None
    Nx: int = 30
    Ny: int = 60
    Nz: int = 1
    T_s_init_K: Optional[float] = None
    convergence_mode: Optional[str] = None      # None -> pipelines resolve 'f2' (env wins)
    mom_tol: Optional[float] = None
    mass_local_tol: Optional[float] = None
    mass_global_tol: Optional[float] = None


@dataclass
class OptimizerConfig:
    """Cheap-eval BUDGET for the design optimizer (R3 split, 2026-07-07).

    These values control the evaluators' fast screening solves only —
    they produce design RANKINGS, not quotable numbers. Final Pareto
    picks must be re-solved through the production pipeline (which obeys
    :class:`SolverConfig`). Defaults are byte-identical to the values the
    optimizer consumed from the old SolverConfig fields.
    ``tol_simple`` remains serialized but does not control F2 convergence.
    """
    max_outer_ltne: int = 4
    outer_tol_K: float = 0.5
    max_iter_simple: int = 800
    tol_simple: float = 1e-2
    alpha_T: float = 0.7


@dataclass
class PartialBCConfig:
    """Per-side partial-pipe inlet/outlet placement (cross-stream).

    ``dir`` is the flow direction encoded by ``window._DIR_MAP``:
    ``0=+x``, ``1=-x``, ``2=+y``, ``3=-y``. ``in_ctr``/``in_w`` and
    ``out_ctr``/``out_w`` are inlet / outlet centre + width in the
    cross-stream coordinate (m). ``in_z_*``/``out_z_*`` extend to the
    3D z-axis partial mask; ``None`` means "full face along z".

    Audit C4 (L-a-2): added so the pipeline does not have to call back
    into ``window._fluid_config(which)``.
    """
    dir: int = 0
    in_ctr: float = 0.0
    in_w: float = 0.0
    out_ctr: float = 0.0
    out_w: float = 0.0
    in_z_ctr: Optional[float] = None
    in_z_w: Optional[float] = None
    out_z_ctr: Optional[float] = None
    out_z_w: Optional[float] = None
    # 2D only: False preserves the historical four-cell edge profile.
    # 3D already imposes uniform flow over the geometric opening.
    uniform_inlet_2d: bool = False


def bc_to_dict(bc: 'PartialBCConfig', L_dom: float, H_dom: float,
               *, side: str = 'A', with_z: bool = False):
    """Convert a :class:`PartialBCConfig` into the legacy solver BC dict.

    Single source for the 2D + 3D conversions (was three near-duplicate
    ``_bc_cfg_to_dict_*`` functions). The side-B asymmetry is INTENTIONAL —
    it reproduces the legacy ValueError fallback in ``_parse_inputs``:

    * ``side='A'`` — a degenerate BC (``in_w<=0`` or ``out_w<=0``) falls back
      to a full-face inlet/outlet spanning the cross-stream axis. Used by the
      2D path (both sides) and 3D side A.
    * ``side='B'`` — a *fully* degenerate BC (``in_w<=0`` AND ``out_w<=0``)
      returns ``None``, which ``_run_3d_stack`` reads as "no B fluid —
      single-fluid A-alone run" (it skips the B SIMPLE build). A
      partially-degenerate BC returns the raw partial dict (no full-face
      fallback). 3D side B only.

      NOTE: the ComputeConfig→3D boundary (``preprocess.three_d.preparation._parse_inputs_3d_cfg``)
      rebuilds a full-face B from a None here, because via ComputeConfig
      fluid_B is always a configured 2nd fluid (a None there is just the
      ``PartialBCConfig`` default widths, meaning full-face cross-flow). The
      genuine single-fluid path reaches ``_run_3d_stack`` with an explicit
      ``fluid_B_cfg=None`` and bypasses that boundary.
    * ``with_z=True`` — append the ``in_z_*``/``out_z_*`` overlay when the cfg
      captured 3D z-partial fields (``None`` = full face along z).
    """
    is_x_flow = bc.dir in (0, 1)
    cross_dim = H_dom if is_x_flow else L_dom
    if side == 'B' and bc.in_w <= 0 and bc.out_w <= 0:
        return None
    # Raw-cfg dicts are heterogeneous by design (int dir, float extents,
    # Optional z-window) — say so instead of letting mypy infer float-only.
    d: Dict[str, Any]
    if (bc.in_w > 0 and bc.out_w > 0) or side == 'B':
        d = dict(dir=bc.dir, in_ctr=bc.in_ctr, in_w=bc.in_w,
                 out_ctr=bc.out_ctr, out_w=bc.out_w)
    else:
        d = dict(dir=bc.dir, in_ctr=cross_dim / 2, in_w=cross_dim,
                 out_ctr=cross_dim / 2, out_w=cross_dim)
    if with_z and bc.in_z_ctr is not None:
        d['in_z_ctr'] = bc.in_z_ctr
        d['in_z_w'] = bc.in_z_w
        d['out_z_ctr'] = bc.out_z_ctr
        d['out_z_w'] = bc.out_z_w
    if not with_z and bc.uniform_inlet_2d:
        d['uniform_inlet_2d'] = True
    return d


@dataclass
class ZoneInputConfig:
    """Zone / sigmoid-field control state.

    Captures the inputs that the legacy ``window._build_zone_config()``
    + ``window._zone_axis()`` pair plus the ``_pareto_*`` attributes
    fed into the 2D/3D solver.

    ``config`` is the pre-resolved ``solvers.zone_config.ZoneConfig``
    instance (1D zone mode), or its JSON-shaped dictionary for canonical
    input, restored at the 1D pipeline boundary. It is ``None`` when zones are disabled or
    running in grid mode (``grid`` carries the cell list instead).
    The UI adapter snapshots ``config`` via
    ``ui.zone_table.build_zone_config(window)`` at the boundary so the Pipeline
    layer never has to touch the Qt zone-table widget.

    Audit C4 (L-a-2).
    """
    enabled: bool = False
    axis: ZoneAxis = 'y'
    grid: Optional[Dict[str, Any]] = None  # cells / tpms_type / k_s
    config: Optional[Any] = None  # 1D ZoneConfig or its canonical JSON dictionary
    pareto_x_decision: Optional[Any] = None
    pareto_y_trans_inlet: float = 0.2
    pareto_y_trans_outlet: float = 0.2

    def validate(self) -> 'ZoneInputConfig':
        """Reject invalid rectangles; partial coverage keeps its existing meaning."""
        import math

        if not self.enabled or self.axis != 'grid':
            return self
        if not isinstance(self.grid, dict) or not self.grid.get('cells'):
            raise ValueError('Enabled grid zones require non-empty grid cells')
        for index, cell in enumerate(self.grid['cells'], 1):
            for axis in ('x', 'y'):
                try:
                    start, end = cell[f'{axis}0'], cell[f'{axis}1']
                    valid = (math.isfinite(start) and math.isfinite(end)
                             and 0 <= start < end <= 1)
                except (KeyError, TypeError):
                    valid = False
                if not valid:
                    raise ValueError(
                        f'Zone grid cell {index}: {axis} coordinates must be '
                        'finite and satisfy 0 <= start < end <= 1')
        return self


@dataclass
class ExtrapPolicy:
    """Surrogate-domain extrapolation policy.

    ``allow`` mirrors the ``chk_allow_extrap`` checkbox (or the
    ``TPMSHX_ALLOW_EXTRAP=1`` env var read by the optimizer entrypoints).
    The pipeline appends string reasons to a separate ``warnings`` list
    on :class:`ComputeResult`; this dataclass is *input only*.

    Audit C4 (L-a-2).
    """
    allow: bool = False


@dataclass
class FeatureFlags:
    """UI toggles that survive into the solver layer.

    ``wall_refine_3d`` mirrors ``window.chk_wall_refine_3d`` (3D wall
    boundary-layer refinement). ``variable_rho_cp`` mirrors
    ``window.chk_var_rhocp`` (3D LTNE energy-kernel gas density from SIMPLE's
    local pressure ρ(P_local,T) instead of inlet pressure — conserves
    compressible reverse flow; default ON since 2026-06-09, see the field
    default below — hard invariant #1, never default this off). ``temp_unit`` mirrors
    ``window._temp_unit`` purely for round-tripping; ComputeConfig fields are
    always Kelvin so the solver itself never needs this flag.

    Audit C4 (L-a-2).
    """
    wall_refine_3d: bool = False
    port_wall_refine: bool = False  # 2D/3D port-aligned graded grid; Nx/Ny/Nz are totals
    variable_rho_cp: bool = True   # default ON (local-P gas density; 2026-06-09)
    temp_unit: Literal['K', 'C'] = 'K'


@dataclass(frozen=True)
class Sco2NuConfig:
    """Run-owned effective Nu parameters; no measured coefficients ship by default."""
    mode: str = 'cfd_smooth'
    alpha_D: float | None = None
    alpha_G: float | None = None
    parameter_version: str = ''
    source: str = ''
    applicability: str = ''

    def validate(self):
        import math
        if self.mode not in ('cfd_smooth', 'experimental'):
            raise ValueError(f'Unsupported sCO2 Nu mode: {self.mode!r}')
        for name in ('alpha_D', 'alpha_G'):
            value = getattr(self, name)
            if value is None and self.mode == 'cfd_smooth':
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'sCO2 Nu {name} must be finite and positive')
        for name in ('parameter_version', 'source', 'applicability'):
            value = getattr(self, name)
            if not isinstance(value, str) or (self.mode == 'experimental' and not value.strip()):
                raise ValueError(f'sCO2 Nu requires {name}')
        return self


@dataclass
class ComputeConfig:
    """Composite settings handed to solver-side entrypoints.

    Constructed at the UI boundary via ``ui.window_config.config_from_window``
    or at a
    script/test boundary via :meth:`from_json`. Downstream consumers
    *only* see this object.
    """
    fluid_A: FluidConfig = field(default_factory=FluidConfig)
    fluid_B: FluidConfig = field(default_factory=FluidConfig)
    geometry: GeometryConfig = field(default_factory=GeometryConfig)
    solver: SolverConfig = field(default_factory=SolverConfig)
    # R3 (2026-07-07): optimizer budget split out of SolverConfig — the two
    # consumers (production pipelines vs optimizer screening) need
    # different values for the same-named knobs; sharing fields is what
    # made them decorative for years.
    optimizer: OptimizerConfig = field(default_factory=OptimizerConfig)
    # ── audit C4 additions: cover the non-le_* window state that the
    # ── pipeline needs but C3 deliberately punted on.
    bc_A: PartialBCConfig = field(default_factory=PartialBCConfig)
    bc_B: PartialBCConfig = field(default_factory=PartialBCConfig)
    zones: ZoneInputConfig = field(default_factory=ZoneInputConfig)
    extrap: ExtrapPolicy = field(default_factory=ExtrapPolicy)
    flags: FeatureFlags = field(default_factory=FeatureFlags)
    # Compressible validity-envelope behaviour (robustness, 2026-06-25):
    # 'raise' (default) -> ChokedFlowError on a choked/supersonic solve;
    # 'warn' -> run but flag envelope_valid=False (useful for batch sweeps that
    # must not abort on one choked operating point); 'off' -> legacy silent.
    envelope_mode: str = 'raise'
    # Darcy-Forchheimer method exposed to users. The default is the unchanged
    # V2 water+sCO2 CFD table; experiment mode applies a reviewed effective
    # correction selected by matching dataset/campaign boundaries.
    df_mode: DFMode = 'cfd_smooth'
    sco2_nu: Sco2NuConfig = field(default_factory=Sco2NuConfig)

    # ── derived ──────────────────────────────────────────────────────

    @property
    def is_3d(self) -> bool:
        """True when the solver should run on the full 3D grid."""
        return int(self.solver.Nz) >= 2

    # ── adapters ─────────────────────────────────────────────────────


    # ── JSON ─────────────────────────────────────────────────────────

    @classmethod
    def from_json(cls, path: Union[str, Path]) -> 'ComputeConfig':
        """Load a ComputeConfig from a JSON file.

        Accepts both the canonical schema (mirroring the dataclass
        tree) and the legacy ``configs/shanghai_baseline.json`` shape
        (geometry + domain, fluids missing → defaults). The legacy
        path is the same one that ``configs.load_shanghai_baseline``
        already consumes, so production validate scripts can switch
        with a one-line change.
        """
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return cls.from_dict(data)

    def to_json(self, path: Union[str, Path]) -> None:
        """Write the config as JSON. Unknown / Path-typed fields
        round-trip through ``asdict`` (all-stdlib types)."""
        Path(path).write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding='utf-8',
        )

    def validate(self) -> 'ComputeConfig':
        """Reject non-finite / non-physical scalars at the SCRIPT boundary
        (robustness-hardening, 2026-07-03).

        `json.loads` happily produces NaN/Infinity and negative values, and
        the script/optimizer path bypasses every UI widget gate — so
        ``from_dict``/``from_json`` call this. Direct dataclass construction
        stays permissive on purpose (tests build deliberately-odd configs).
        Returns self so call sites can chain.
        """
        import math

        self.zones.validate()
        self.sco2_nu.validate()
        if self.flags.port_wall_refine and self.flags.wall_refine_3d:
            raise ValueError('Select either port/wall refinement or six-wall 3D refinement')
        if self.df_mode not in ('cfd_smooth', 'experimental'):
            raise ValueError(
                f"ComputeConfig.df_mode={self.df_mode!r} — must be "
                "'cfd_smooth' or 'experimental'")

        def _bad(name, v):
            raise ValueError(
                f"ComputeConfig.{name}={v!r} — must be finite and > 0")

        ge = self.geometry
        checks = [
            ('geometry.L_dom_m', ge.L_dom_m),
            ('geometry.H_dom_m', ge.H_dom_m),
            ('geometry.L_cell_mm', ge.L_cell_mm),
            ('geometry.t_wall_mm', ge.t_wall_mm),
            ('geometry.k_s_W_mK', ge.k_s_W_mK),
        ]
        if ge.Lz_m is not None:
            checks.append(('geometry.Lz_m', ge.Lz_m))
        for side, fl in (('A', self.fluid_A), ('B', self.fluid_B)):
            checks += [
                (f'fluid_{side}.u_mps', fl.u_mps),
                (f'fluid_{side}.T_in_K', fl.T_in_K),
                (f'fluid_{side}.P_in_Pa', fl.P_in_Pa),
            ]
        for name, v in checks:
            try:
                fv = float(v)
            except (TypeError, ValueError):
                _bad(name, v)
            if not math.isfinite(fv) or fv <= 0.0:
                _bad(name, v)
        for name, n in (('solver.Nx', self.solver.Nx),
                        ('solver.Ny', self.solver.Ny),
                        ('solver.Nz', self.solver.Nz)):
            try:
                iv = int(n)
            except (TypeError, ValueError):
                raise ValueError(
                    f"ComputeConfig.{name}={n!r} — must be an int >= 1")
            if iv < 1:
                raise ValueError(
                    f"ComputeConfig.{name}={n} — must be >= 1")

        # ── Lz contract (2026-07-12) ─────────────────────────────────────────
        # This class's own GeometryConfig docstring says the 3D path *requires*
        # Lz_m, but stages_3d silently substituted 0.042 m (the Shanghai depth)
        # when it was None — a 3D result computed against a magic constant the
        # user never chose, with every extensive scalar (Q, mass, dP_B) scaled
        # by it. Nz >= 2 is exactly `is_3d`, so this is a config error.
        if self.is_3d and self.geometry.Lz_m is None:
            raise ValueError(
                f"ComputeConfig.geometry.Lz_m is None but solver.Nz="
                f"{self.solver.Nz} >= 2 selects the 3D path, which requires an "
                "explicit domain depth (it used to silently fall back to "
                "0.042 m). Set geometry.Lz_m, or set Nz=1 for a 2D run.")

        # ── Numerical solver settings (2026-07-12) ───────────────────────────
        # All production callers pass here through ComputePipeline.run().
        # Normalise the typed-config full-face sentinel before applying the
        # shared port validator. ComputeConfig always has two fluids, so side
        # B uses the same full-face rule as A; its legacy None means
        # single-fluid only below this boundary.
        from .validator import validate_pipe_config
        for side, bc in (('A', self.bc_A), ('B', self.bc_B)):
            if not isinstance(bc.uniform_inlet_2d, bool):
                raise ValueError(f'ComputeConfig.bc_{side}.uniform_inlet_2d must be boolean')
            if (bc.in_w <= 0.0) != (bc.out_w <= 0.0):
                raise ValueError(
                    f"ComputeConfig.bc_{side}.in_w and out_w must both be "
                    "positive, or both be <= 0 for a full-face port")
            pipe = bc_to_dict(
                bc, ge.L_dom_m, ge.H_dom_m, side='A', with_z=self.is_3d)
            problems = validate_pipe_config(
                pipe, ge.L_dom_m, ge.H_dom_m,
                Lz_dom=ge.Lz_m, is_3d=self.is_3d)
            errors = [str(problem) for problem in problems
                      if problem.severity == 'error']
            if errors:
                raise ValueError(
                    f"ComputeConfig.bc_{side} is invalid: " + "; ".join(errors))

        # These were previously UNVALIDATED: a JSON with max_outer_ltne=0,
        # outer_tol_K=-1 or tol_simple=1e9 loaded clean and produced a result
        # that looked like a solve. None = "use the dimension built-in" and
        # stays legal.
        _gate_checks: Tuple[Tuple[str, Optional[float]], ...] = (
            ('solver.outer_tol_K', self.solver.outer_tol_K),
            ('solver.tol_simple', self.solver.tol_simple),
            # F2 gates (ledger C7). Same rule: positive and finite.
            # A zero or negative gate is strictly unreachable (all
            # three residuals are >= 0), so the solve could only ever
            # burn max_iter and report converged=False.
            ('solver.mom_tol', self.solver.mom_tol),
            ('solver.mass_local_tol', self.solver.mass_local_tol),
            ('solver.mass_global_tol', self.solver.mass_global_tol))
        # Loop names deliberately distinct from the earlier all-float checks
        # (mypy unifies a reused loop variable's type across the function).
        for _gname, _gval in _gate_checks:
            if _gval is None:
                continue
            try:
                fv = float(_gval)
            except (TypeError, ValueError):
                _bad(_gname, _gval)
            if not math.isfinite(fv) or fv <= 0.0:
                _bad(_gname, _gval)
        from sjtu_tpmshx.domain.run_environment import require_f2_mode
        require_f2_mode(self.solver.convergence_mode)

        if self.solver.max_iter_simple is not None:
            try:
                mi = int(self.solver.max_iter_simple)
            except (TypeError, ValueError):
                raise ValueError(
                    f"ComputeConfig.solver.max_iter_simple="
                    f"{self.solver.max_iter_simple!r} — must be an int >= 1")
            if mi < 1:
                raise ValueError(
                    f"ComputeConfig.solver.max_iter_simple={mi} — must be >= 1")
        if self.solver.max_outer_ltne is not None:
            try:
                mo = int(self.solver.max_outer_ltne)
            except (TypeError, ValueError):
                raise ValueError(
                    f"ComputeConfig.solver.max_outer_ltne="
                    f"{self.solver.max_outer_ltne!r} — must be an int >= 2")
            # < 2 CANNOT converge: OuterConvergence needs a previous field to
            # diff against, so the first outer iteration is never 'converged'
            # by construction — the loop always exits on the cap and the run
            # can only ever report converged=False. Fail loud here (the typed
            # production boundary) rather than silently ship a result that
            # claims nothing. The raw-cfg path (_run_3d_stack) still accepts 1
            # as an explicit single-pass SCREENING mode — it now honestly
            # reports solver_converged=False (see run_stack_3d.py).
            if mo < 2:
                raise ValueError(
                    f"ComputeConfig.solver.max_outer_ltne={mo} — must be >= 2. "
                    "A single outer pass can never satisfy the coupling "
                    "criterion (it needs a previous iterate to compare "
                    "against), so the run could only ever report "
                    "converged=False. For a deliberate single-pass screening "
                    "sweep, drive pipelines.run_stack_3d._run_3d_stack directly "
                    "with a raw cfg dict and read convergence_detail — do not "
                    "route it through the typed production config.")

        # V2 production D-F closure is a water+sCO2 CFD table with bilinear
        # interpolation in geometry only. Extrapolation is not supported.
        if not 4.0 <= self.geometry.L_cell_mm <= 8.0 \
                or not 0.3 <= self.geometry.t_wall_mm <= 0.6:
            raise ValueError(
                "V2 geometry must lie inside the CFD grid: "
                "4 <= L <= 8 mm, 0.3 <= t <= 0.6 mm")

        sco2_A = self.fluid_A.type == 'sco2'
        sco2_B = self.fluid_B.type == 'sco2'
        if sco2_A or sco2_B:
            for side, fl in (('A', self.fluid_A), ('B', self.fluid_B)):
                if fl.type != 'sco2':
                    continue
                if not 280.0 <= fl.T_in_K <= 700.0:
                    raise ValueError(
                        f"sCO2 fluid {side} temperature must be 280..700 K")
                if not SCO2_P_RANGE_PA[0] <= fl.P_in_Pa <= SCO2_P_RANGE_PA[1]:
                    raise ValueError(
                        f"sCO2 fluid {side} pressure must be 7.9..16 MPa")
            if self.zones.enabled:
                raise ValueError("sCO2 V2 does not support zones")
            if self.geometry.delta_levelset != 0.0:
                raise ValueError("sCO2 V2 requires delta_levelset=0")
        if self.df_mode == 'experimental':
            from sjtu_tpmshx.df_surrogate.experimental_correction import (
                correction_scale)
            if self.zones.enabled:
                raise ValueError(
                    "experimental calibration currently requires uniform L/t; "
                    "zoned geometry remains available in CFD smooth-wall mode")
            for side, fl in (('A', self.fluid_A),
                             ('B', self.fluid_B)):
                try:
                    _, _, _, scope = correction_scale(
                        self.geometry.tpms, fl.type,
                        self.geometry.L_cell_mm, self.geometry.t_wall_mm,
                        fl.u_mps)
                except ValueError as exc:
                    raise ValueError(
                        f"experimental calibration unavailable for active side "
                        f"{side}: {exc}") from exc
                if scope != 'HX-effective':
                    continue
                if (self.geometry.delta_levelset != 0.0
                        or not math.isclose(ge.L_dom_m, 0.182)
                        or not math.isclose(ge.H_dom_m, 0.042)
                        or (self.is_3d and (ge.Lz_m is None
                                            or not math.isclose(
                                                ge.Lz_m, 0.042)))):
                    raise ValueError(
                        f"experimental calibration side {side} is HX-effective "
                        "and requires delta=0 with the matching 0.182 x 0.042"
                        " x 0.042 m campaign domain")
        return self

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ComputeConfig':
        """Build a ComputeConfig from a JSON-shaped dict.

        Supports two layouts:

        1. **Canonical** — keys ``fluid_A``, ``fluid_B``,
           ``geometry``, ``solver``, each mapping to the corresponding
           dataclass shape (``asdict`` round-trip).
        2. **Legacy Shanghai baseline** — ``geometry`` + ``domain``
           dicts; ``domain.L_dom_m`` / ``H_dom_m`` / ``Lz_m`` fold
           into :class:`GeometryConfig`. Fluids fall back to defaults
           because the Shanghai loop overwrites them per case.
        """
        if not isinstance(data, dict):
            raise ValueError('ComputeConfig must be a JSON object')
        # The legacy layout is identified by its domain section. Optional
        # canonical sections must never decide how the remaining fields parse.
        if 'domain' not in data:
            unknown = set(data) - set(cls.__dataclass_fields__)
            if unknown:
                raise ValueError(f'unknown ComputeConfig fields: {sorted(unknown)}')
            fA_d = data.get('fluid_A', {}) or {}
            fB_d = data.get('fluid_B', {}) or {}
            ge_d = data.get('geometry', {}) or {}
            so_d = dict(data.get('solver', {}) or {})
            # R3 legacy tolerance: alpha_T / rough_mode left SolverConfig
            # (2026-07-07) — old JSONs still carry them; drop with a notice
            # instead of TypeError-ing every archived config.
            _dropped = [k for k in ('alpha_T', 'rough_mode') if so_d.pop(k, None) is not None]
            if _dropped:
                warnings.warn(
                    f"solver config keys {_dropped} are retired (R3 split, "
                    f"2026-07-07) and were ignored; optimizer budget lives "
                    f"under the 'optimizer' section now.", stacklevel=2)
            op_d = data.get('optimizer', {}) or {}
            # audit C4 additions — all optional, default-constructed
            # when absent so old JSON files keep round-tripping.
            bcA_d = data.get('bc_A', {}) or {}
            bcB_d = data.get('bc_B', {}) or {}
            zn_d = data.get('zones', {}) or {}
            fl_d = data.get('flags', {}) or {}
            ex_d = data.get('extrap', {}) or {}
            return cls(
                fluid_A=FluidConfig(**fA_d) if fA_d else FluidConfig(),
                fluid_B=FluidConfig(**fB_d) if fB_d else FluidConfig(),
                geometry=GeometryConfig(**ge_d) if ge_d else GeometryConfig(),
                solver=SolverConfig(**so_d) if so_d else SolverConfig(),
                optimizer=(OptimizerConfig(**op_d) if op_d
                           else OptimizerConfig()),
                bc_A=PartialBCConfig(**bcA_d) if bcA_d else PartialBCConfig(),
                bc_B=PartialBCConfig(**bcB_d) if bcB_d else PartialBCConfig(),
                zones=ZoneInputConfig(**zn_d) if zn_d else ZoneInputConfig(),
                flags=FeatureFlags(**fl_d) if fl_d else FeatureFlags(),
                extrap=ExtrapPolicy(**ex_d) if ex_d else ExtrapPolicy(),
                envelope_mode=data.get('envelope_mode', 'raise'),
                df_mode=data.get('df_mode', 'cfd_smooth'),
                sco2_nu=Sco2NuConfig(**data.get('sco2_nu', {})),
            ).validate()

        # ── legacy shanghai_baseline.json layout ────────────────
        # Keys: _meta / geometry / domain / _excluded
        unknown = set(data) - {'_meta', 'geometry', 'domain', '_excluded', 'sco2_nu'}
        if unknown:
            raise ValueError(f'mixed or unknown legacy config fields: {sorted(unknown)}')
        geom_raw = data.get('geometry', {}) or {}
        domain_raw = data.get('domain', {}) or {}
        unknown = set(geom_raw) - {'tpms', 'L_cell_mm', 't_wall_mm', 'k_s_W_mK'}
        if unknown:
            raise ValueError(f'legacy geometry has canonical or unknown fields: {sorted(unknown)}')
        geom = GeometryConfig(
            tpms=geom_raw.get('tpms', 'Gyroid'),
            L_cell_mm=float(geom_raw.get('L_cell_mm', 7.0)),
            t_wall_mm=float(geom_raw.get('t_wall_mm', 0.6)),
            k_s_W_mK=float(geom_raw.get('k_s_W_mK', 16.0)),
            L_dom_m=float(domain_raw.get('L_dom_m', 0.182)),
            H_dom_m=float(domain_raw.get('H_dom_m', 0.042)),
            Lz_m=(float(domain_raw['Lz_m'])
                  if 'Lz_m' in domain_raw else None),
        )
        return cls(geometry=geom,
                   sco2_nu=Sco2NuConfig(**data.get('sco2_nu', {}))).validate()


__all__ = [
    'FluidType', 'DFMode', 'TPMSType', 'RoughMode', 'ZoneAxis',
    'FluidConfig', 'GeometryConfig', 'SolverConfig', 'OptimizerConfig',
    'PartialBCConfig', 'ZoneInputConfig',
    'ExtrapPolicy', 'FeatureFlags',
    'ComputeConfig', 'Sco2NuConfig',
]
