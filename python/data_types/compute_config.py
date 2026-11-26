"""Qt-free production configuration and physical input validation.

The GUI converts widget values once through ``ui.window_config``.
Preprocessing consumes these dataclasses, while execution consumes prepared
CaseData. Shared physical checks are imported at their validation call sites.

- ``FluidConfig``     — per-side fluid (type + u + T_in + P_in)
- ``GeometryConfig``  — domain + TPMS unit-cell + solid k_s
- ``SolverConfig``    — grid + LTNE outer + SIMPLE inner convergence
- ``PartialBCConfig`` / ``ZoneInputConfig`` — per-side ports and spatial geometry
- ``ComputeConfig``   — composite, has the entrypoint adapters

Adapters
~~~~~~~~

- ``ui.window_config.config_from_window(window)`` — read ``window.le_*`` /
  ``window.combo_*`` once at the UI boundary; downstream callers no
  longer touch ``window``.
- ``ComputeConfig.from_json(path)`` / ``to_json(path)`` — JSON
  serialisation for production validation scripts and tests.

Port, zone and extrapolation settings are explicit inputs. Runtime callbacks
and cancellation belong to ``RunControl``; emitted warnings belong to results.

Runtime environment switches
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Runtime overrides and diagnostic switches. Production run overrides are
captured by ``domain.run_environment.capture_environment``; remaining flags
follow the read timing stated below.

- ``TPMSHX_ALLOW_EXTRAP`` (0) — permits warnings at the point applicability
  check. In production this allows inlet Nu/Re checks to proceed; it does not
  relax D-F geometry or fluid-property hard limits. Read by
  ``development/validation/surrogate_domain.py`` and continuous-field preparation.
- ``TPMSHX_CHI_S`` (unset) — constant χ_s research override.
  When unset, χ_s comes from the unit-cell homogenization fit
  ``chi_s_eff(type, ε)``;
  ``models/tpms_props.py`` (``chi_s_eff`` reads the override on each call).
- ``TPMSHX_DISABLE_3D_PANEL`` (0) — skip PyVista panel;
  ``ui/builders_canvas.py``.
- ``TPMSHX_PARALLEL_THRESHOLD`` (200000) — native parallel-sweep cell gate;
  ``cpp_interface/full_3d_stage.py`` reads it for each native call.
- ``TPMSHX_PHASE_A/C`` (1/0) — adaptive AMG / coarse bootstrap.
  Captured by ``preprocess/three_d/preparation.py`` (cfg keys win).
  Phase B / inner SIMPLE Anderson is retired; explicit enablement raises.
- ``TPMSHX_PREINIT_3D`` (0) — prewarm 3D panel at startup; ``applications/gui/ui/main_window.py``.
- ``TPMSHX_ROUGH_MODE`` (baseline; UI path defaults norris_1a) +
  ``TPMSHX_ROUGH_EPS_UM`` (100) — roughness model; single helper
  ``models.roughness.resolve_mode_from_env``.
- ``TPMSHX_VAR_RHOCP`` (unset) — overrides the 3D local-density thermal
  transport setting; defaults ON. The desktop fixes its config ON, while
  an explicit captured environment override still takes precedence.

- ``TPMSHX_DF_METHOD`` — explicit method for direct ``df_surrogate.predict``
  calls. Only ``cfd_full_core_3cell_fixed_v2`` is supported; retired method
  names fail. Production 2D/3D compute paths pin this fixed table.
- ``TPMSHX_ASYM_KAPPA`` (0) — research-only asym per-side κ correction
  after ``ingest_cfd_kappa``; production 2D/3D compute paths do not apply it.
  Read in ``development/runs/cfd_asym/kappa_asym.py``.
- ``TPMSHX_SCO2_COMPRESSIBLE`` (0, experimental) — A-side sCO2 local-pressure
  density/viscosity update and pressure-seed envelope check in native 3D
  execution. B is unchanged; this is not full compressible continuity. Its
  pressure anchor differs from true-h and is not covered by the ideal-gas
  inlet-pressure correction; an ON/OFF change is not accuracy evidence.
- ``TPMSHX_MAX_CELLS_3D`` (2000000) — hard 3D cell cap;
  ``preprocess/three_d/preparation.py``.
- ``TPMSHX_BUILD_S_MAX`` / ``TPMSHX_BUILD_LX_MAX`` — sizing-tool build
  envelope caps; ``design/sizing.py``.
- ``TPMSHX_LOG_LEVEL`` (INFO) / ``TPMSHX_LOG_TS`` (0) — central logging
  level / timestamp prefix; ``logutil.py``.
"""
from __future__ import annotations

import warnings
from dataclasses import asdict, dataclass, field
from math import isfinite
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple, Union

from sjtu_tpmshx.model_configs.model_parameters import load_model_parameters


FluidType = Literal['air', 'water', 'sco2', 'co2']
DFMode = Literal['cfd_smooth', 'experimental']
TPMSType = Literal['Diamond', 'Gyroid']
ZoneAxis = Literal['x', 'y', 'grid', 'continuous']

_MODEL = load_model_parameters()
SCO2_P_RANGE_PA = tuple(_MODEL['sco2']['pressure_range_Pa'])
SCO2_T_RANGE_K = tuple(_MODEL['sco2']['temperature_range_K'])
_GEOMETRY_RESTRICTIONS = _MODEL['geometry_restrictions']


def validate_enthalpy_algorithm(algorithm, temperature_tolerance):
    """Validate the persisted conservative energy recipe and its K update gate."""
    if algorithm not in ('legacy_h_fou', 'temperature_fou', 'temperature_sou'):
        raise ValueError(f'unsupported enthalpy_algorithm: {algorithm}')
    if (isinstance(temperature_tolerance, bool)
            or not isinstance(temperature_tolerance, (int, float))
            or not isfinite(temperature_tolerance) or temperature_tolerance <= 0.):
        raise ValueError('enthalpy_temperature_tol_K must be finite and positive')


def validate_simple_velocity_relaxation(value):
    """Validate the optional native SIMPLE velocity relaxation."""
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                              or not isfinite(value) or not 0. < value <= 1.):
        raise ValueError('simple_velocity_relaxation must be in (0, 1]')


def reject_retired_research_options(config):
    """Reject retired research controls before physical preparation."""
    outer = sorted(key for key in config if key in (
        'outer_anderson', 'outer_anderson_m', 'outer_anderson_trust',
        'outer_anderson_patience'))
    if outer:
        raise ValueError(
            f'Outer property Anderson is retired: {outer}. Remove these research options.')
    retired = sorted(key for key in config
                     if key in ('partial_B_closure', 'audit_zero_K_ffB_at_outlet')
                     or isinstance(key, str) and key.startswith(('m4_', 'chi_B_', 'audit_h2_')))
    if retired:
        raise ValueError(
            f'B-side participation experiments are retired: {retired}. '
            'Remove these research options; physical port boundaries remain supported.')


# ── dataclasses ──────────────────────────────────────────────────────


def _quantity(symbol, unit, range_ref='ComputeConfig.validate_static_inputs', *,
              dimensions=(2, 3)):
    """Describe a stored quantity. A range reference names its validator or model resource."""
    return dict(symbol=symbol, unit=unit, dimensions=dimensions,
                range_ref=range_ref)


@dataclass
class FluidConfig:
    """Single-side fluid inlet state."""
    type: FluidType = 'air'
    u_mps: float = field(default=5.0, metadata=_quantity('u', 'm/s', 'ComputeConfig.validate'))
    T_in_K: float = field(default=300.0, metadata=_quantity('T_in', 'K'))
    P_in_Pa: float = field(default=101325.0, metadata=_quantity('P_in', 'Pa'))
    # None prescribes velocity; otherwise total inlet flow is authoritative.
    mass_flow_kg_s: Optional[float] = field(default=None, metadata=_quantity('ṁ', 'kg/s'))


@dataclass
class GeometryConfig:
    """TPMS unit cell + macroscopic domain + solid conductivity.

    ``solver.Nz >= 2`` selects 3D and requires an explicit positive ``Lz_m``.
    ``Nz=1`` selects the 2D XY plane. Total inlet mass flow requires an
    explicit positive physical depth ``Lz_m``. Integral results keep per-unit-depth units.
    """
    tpms: TPMSType = 'Gyroid'
    L_cell_mm: float = field(default=7.0, metadata=_quantity('L', 'mm', 'model_configs.df_domain.TRAIN_L'))
    t_wall_mm: float = field(default=0.6, metadata=_quantity('t', 'mm', 'model_configs.df_domain.TRAIN_T'))
    k_s_W_mK: float = field(default=16.0, metadata=_quantity('k_s', 'W/(m·K)'))
    L_dom_m: float = field(default=0.182, metadata=_quantity('L_x', 'm'))
    H_dom_m: float = field(default=0.042, metadata=_quantity('H', 'm'))
    Lz_m: Optional[float] = field(default=None, metadata=_quantity('L_z', 'm'))
    # Asymmetric porosity: offset-isosurface centre δ (φ-units). 0.0 →
    # symmetric 50/50 (bit-identical). |δ|>0 → ε_A (φ<δ−C) ≠ ε_B (φ>δ+C);
    # consumed by native 3D geometry preparation. Human targets
    # (A%/B%) convert to δ in run scripts via runs/diagnostics/asym_target_scan.
    delta_levelset: float = field(default=0.0, metadata=_quantity('δ', '1'))


@dataclass
class SolverConfig:
    """Grid and solver controls for full compute and multi-condition optimization.

    For the production controls below, ``None``
    means "use the dimension-specific built-in":

    - ``max_outer_ltne``: SIMPLE↔LTNE outer iterations.
      Auto = 10 (2D coupling) / 12 (3D; fast_sweep profile: 3).
    - ``outer_tol_K``: outer temperature-delta tolerance [K].
      Auto = 1.0 (2D) / 0.5 (3D).
    - ``max_iter_simple``: SIMPLE inner iteration cap.
      Auto = 10000 (2D) / per-stage 600–2000 (3D).

    ``alpha_T`` (numerics-internal relaxation) and ``rough_mode`` (the
    bhatti_shah_1b option is the ledger-ROUGH-X double-count trap) were
    REMOVED from the user surface; ``from_dict`` drops them from legacy
    JSONs with a notice. Roughness sweeps remain possible via the
    ``TPMSHX_ROUGH_MODE`` env (research escape hatch).

    ``T_s_init_K=None`` uses the default seed
    ``0.5 * (T_inA + T_inB)`` in the native full 2D and 3D solvers.

    F2 CONVERGENCE GATES (both dimensions)
    ------------------------------------------------------------------------
    - ``convergence_mode``: ``None`` or ``'f2'`` in every compute mode and
      raw solver. Captured ``TPMSHX_CONV_MODE`` overrides config. The old
      mass/velocity exit and ``'legacy'`` selector are retired.
    - ``mom_tol`` / ``mass_local_tol`` / ``mass_global_tol``: independent
      momentum / solved-cell continuity / boundary mass gates, confirmed
      consecutively, with a separate outlet-backflow gate.

    The pressure-subproblem residual history drives adaptive AMG,
    independently of these exit gates.
    """
    max_outer_ltne: Optional[int] = None
    outer_tol_K: Optional[float] = field(default=None, metadata=_quantity('ΔT', 'K'))
    max_iter_simple: Optional[int] = None
    simple_velocity_relaxation: Optional[float] = None
    Nx: int = field(default=30, metadata=_quantity('N_x', '1'))
    Ny: int = field(default=60, metadata=_quantity('N_y', '1'))
    Nz: int = field(default=1, metadata=_quantity('N_z', '1'))
    T_s_init_K: Optional[float] = field(
        default=None, metadata=_quantity('T_s,0', 'K', 'solver/full_2d.cpp:validate (2D)'))
    convergence_mode: Optional[str] = None      # None -> pipelines resolve 'f2' (env wins)
    mom_tol: Optional[float] = None
    mass_local_tol: Optional[float] = None
    mass_global_tol: Optional[float] = None
    # Historical IDs remain readable; the selected native library validates execution.
    enthalpy_algorithm: Literal['legacy_h_fou', 'temperature_fou', 'temperature_sou'] = _MODEL['native_controls']['enthalpy_algorithm']
    enthalpy_temperature_tol_K: float = field(
        default=_MODEL['native_controls']['enthalpy_temperature_tol_K'],
        metadata=_quantity('ΔT', 'K', 'validate_enthalpy_algorithm'))
    # Optional integral h(T) controls; None keeps the actual route defaults.
    model_h_max_iterations: Optional[int] = None
    model_h_temperature_tol_K: Optional[float] = field(default=None, metadata=_quantity('ΔT', 'K'))
    model_h_q_relative_tol: Optional[float] = None
    # Optional full EOS thermal controls. None keeps the route's existing
    # defaults; explicit values survive config -> prepared case -> replay.
    ltne_enthalpy_outer: Optional[int] = None
    ltne_enthalpy_nsweep: Optional[int] = None
    ltne_enthalpy_omega: Optional[float] = None
    ltne_enthalpy_tol: Optional[float] = None  # normalized enthalpy update, not K
    ltne_enthalpy_coupled_energy_tol: Optional[float] = None
    ltne_enthalpy_equation_energy_tol: Optional[float] = None
    require_enthalpy_update_on_temperature: bool = False


@dataclass
class OptimizerConfig:
    """Retired screening settings retained for existing configuration files.

    Current full solves and multi-condition optimization use SolverConfig.
    These archived values are preserved on load/save and are not executed.
    """
    max_outer_ltne: int = 4
    outer_tol_K: float = 0.5
    max_iter_simple: int = 800
    alpha_T: float = 0.7


@dataclass
class PartialBCConfig:
    """Per-side partial-pipe inlet/outlet placement (cross-stream).

    ``dir`` encodes ``0=+x``, ``1=-x``, ``2=+y``, ``3=-y``;
    3D also supports ``4=+z`` and ``5=-z``. ``in_ctr``/``in_w`` and
    ``out_ctr``/``out_w`` are inlet / outlet centre + width in the
    first cross-stream coordinate (m). ``in_z_*``/``out_z_*`` describe the
    second cross-stream coordinate (z for x/y flow, y for z flow);
    ``None`` means full extent along that coordinate.

    Audit C4 (L-a-2): added so the pipeline does not have to call back
    into ``window._fluid_config(which)``.
    """
    dir: int = 0
    in_ctr: float = field(default=0.0, metadata=_quantity('s_1,in', 'm'))
    in_w: float = field(default=0.0, metadata=_quantity('w_1,in', 'm'))
    out_ctr: float = field(default=0.0, metadata=_quantity('s_1,out', 'm'))
    out_w: float = field(default=0.0, metadata=_quantity('w_1,out', 'm'))
    in_z_ctr: Optional[float] = field(default=None, metadata=_quantity('s_2,in', 'm', dimensions=(3,)))
    in_z_w: Optional[float] = field(default=None, metadata=_quantity('w_2,in', 'm', dimensions=(3,)))
    out_z_ctr: Optional[float] = field(default=None, metadata=_quantity('s_2,out', 'm', dimensions=(3,)))
    out_z_w: Optional[float] = field(default=None, metadata=_quantity('w_2,out', 'm', dimensions=(3,)))
    # 2D only: False preserves the historical four-cell edge profile.
    # 3D already imposes uniform flow over the geometric opening.
    uniform_inlet_2d: bool = False


def bc_to_dict(bc: 'PartialBCConfig', L_dom: float, H_dom: float,
               *, side: str = 'A', with_z: bool = False):
    """Convert a :class:`PartialBCConfig` into the legacy solver BC dict.

    Offline validation and GUI preflight use this preview. Prepared cases
    store the ports returned by the native preparation library.

    * ``side='A'`` expands a nonpositive width to a full face.
      This applies to both active fluids in a typed configuration.
    * ``side='B'`` preserves the historical single-fluid sentinel. Two
      nonpositive widths return ``None``. Mixed widths remain available
      to the GUI for validation.
    * ``with_z=True`` — append the ``in_z_*``/``out_z_*`` overlay when the cfg
      captured 3D z-partial fields (``None`` = full face along z).
    """
    for width in (bc.in_w, bc.out_w):
        try:
            finite = isfinite(width)
        except (TypeError, ValueError, OverflowError):
            finite = False
        if not finite:
            raise ValueError('port width must be finite before full-face normalization')
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
    if with_z:
        for end in ('in', 'out'):
            center, width = getattr(bc, f'{end}_z_ctr'), getattr(bc, f'{end}_z_w')
            if center is not None or width is not None:
                d[f'{end}_z_ctr'] = center
                d[f'{end}_z_w'] = width
    if not with_z and bc.uniform_inlet_2d:
        d['uniform_inlet_2d'] = True
    return d


@dataclass
class ZoneInputConfig:
    """Zone / continuous-field control state.

    ``config`` is the pre-resolved ``models.zone_config.ZoneConfig``
    instance (1D zone mode), or its JSON-shaped dictionary for canonical
    input, restored at the 1D pipeline boundary. It is ``None`` when zones are disabled or
    running in grid mode (``grid`` carries the cell list instead).
    The UI adapter snapshots ``config`` via
    ``ui.zone_table.build_zone_config`` at the boundary so the pipeline
    layer never has to touch the Qt zone-table widget.
    Discrete zones vary L/t only. Their optional ``tpms_type`` and ``k_s``
    copies must agree with the main GeometryConfig; they do not select an
    independent topology or material.

    For ``axis='continuous'``, ``config`` is a JSON dictionary with
    ``x_decision`` (L controls then t controls, both in mm), ``n_ctrl_x``,
    ``n_ctrl_y``, ``symmetric_y``, ``spline_order``, ``L_bounds`` and
    ``t_bounds``, plus optional ``n_ctrl_z`` for a true XYZ field. Omitting
    ``n_ctrl_z`` retains the XY layout for older inputs. Topology, conductivity
    and domain come only from the main GeometryConfig. These are parameter fields, not manufactured
    TPMS geometry or evidence of gradient-model applicability.

    """
    enabled: bool = False
    axis: ZoneAxis = 'y'
    grid: Optional[Dict[str, Any]] = None  # cells / tpms_type / k_s
    config: Optional[Any] = None  # 1D ZoneConfig or canonical 1D/continuous dictionary
    pareto_x_decision: Optional[Any] = field(
        default=None, metadata=_quantity('L, t', 'mm', 'preprocess/preparation_case.cpp:sigmoid_geometry',
                                         dimensions=(2,)))
    pareto_y_trans_inlet: float = field(
        default=0.2, metadata=_quantity('y_in/H', '1', None, dimensions=(2,)))
    pareto_y_trans_outlet: float = field(
        default=0.2, metadata=_quantity('y_out/H', '1', None, dimensions=(2,)))

    def validate(self) -> 'ZoneInputConfig':
        """Validate active spatial input without altering the supplied design."""
        import math

        if not self.enabled:
            return self
        if self.axis not in ('x', 'y', 'grid', 'continuous'):
            raise ValueError(f'Zone axis must be x, y, grid or continuous, got {self.axis!r}')
        if self.axis == 'continuous':
            from sjtu_tpmshx.model_configs.df_domain import TRAIN_L, TRAIN_T
            required = {'x_decision', 'n_ctrl_x', 'n_ctrl_y', 'symmetric_y',
                        'spline_order', 'L_bounds', 't_bounds'}
            spec = self.config
            if (not isinstance(spec, dict) or not required <= set(spec)
                    or set(spec) - required - {'n_ctrl_z'}):
                raise ValueError(f'Continuous field config requires {sorted(required)} and optional n_ctrl_z')
            if self.grid is not None or self.pareto_x_decision is not None:
                raise ValueError('Continuous field cannot also supply grid or sigmoid decisions')
            control_keys = ('n_ctrl_x', 'n_ctrl_y') + (('n_ctrl_z',) if 'n_ctrl_z' in spec else ())
            for name in (*control_keys, 'spline_order'):
                if type(spec[name]) is not int:
                    raise ValueError(f'Continuous field {name} must be an integer')
            order = spec['spline_order']
            if not 1 <= order <= 3:
                raise ValueError('Continuous field spline_order must be 1..3')
            if any(spec[name] < 1 for name in control_keys):
                raise ValueError('Continuous field needs >=1 controls per axis')
            if type(spec['symmetric_y']) is not bool:
                raise ValueError('Continuous field symmetric_y must be boolean')
            for name in ('x_decision', 'L_bounds', 't_bounds'):
                values = spec[name]
                if not isinstance(values, list) or any(
                        type(value) not in (int, float) or not math.isfinite(value) for value in values):
                    raise ValueError(f'Continuous field {name} must be a list of finite numbers')
            for name, resource in (('L_bounds', TRAIN_L), ('t_bounds', TRAIN_T)):
                bounds = spec[name]
                if len(bounds) != 2 or not resource[0] <= bounds[0] <= bounds[1] <= resource[1]:
                    raise ValueError(f'Continuous field {name} must be ordered within {resource} mm')
            ny = (spec['n_ctrl_y'] + 1) // 2 if spec['symmetric_y'] else spec['n_ctrl_y']
            count = spec['n_ctrl_x'] * ny * spec.get('n_ctrl_z', 1)
            if len(spec['x_decision']) != 2 * count:
                raise ValueError(f'Continuous field x_decision must contain {2 * count} values')
            for values, bounds in ((spec['x_decision'][:count], spec['L_bounds']),
                                   (spec['x_decision'][count:], spec['t_bounds'])):
                if any(not bounds[0] <= value <= bounds[1] for value in values):
                    raise ValueError('Continuous field control values must lie within their L/t bounds')
            return self
        if self.axis != 'grid':
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
    """Permit inlet Nu/Re applicability warnings in production preparation.

    ``allow`` is the saved input setting; the point check also accepts the
    ``TPMSHX_ALLOW_EXTRAP`` environment override. Neither changes D-F geometry
    or fluid-property hard limits, nor certifies the local field's Nu range.
    Reasons are recorded separately in run warnings; this dataclass is input only.

    Audit C4 (L-a-2).
    """
    allow: bool = False


@dataclass(slots=True)
class FeatureFlags:
    """Solver mesh and transport settings.

    The desktop selects port refinement through its mesh scheme.
    ``variable_rho_cp`` uses SIMPLE's local density
    in 3D thermal transport and gates eligible air/water mass-flux transport.
    It is fixed ON in the desktop and defaults ON for other callers; never
    default this off. ``temp_unit`` mirrors
    ``window._temp_unit`` purely for round-tripping; ComputeConfig fields are
    always Kelvin so the solver itself never needs this flag.

    Audit C4 (L-a-2).
    """
    port_wall_refine: bool = False  # 2D/3D port-aligned graded grid; Nx/Ny/Nz are totals
    variable_rho_cp: bool = True   # default ON (local-P gas density; 2026-06-09)
    temp_unit: Literal['K', 'C'] = 'K'


@dataclass(frozen=True)
class Sco2NuConfig:
    """Run-owned total C_eff values; smooth CFD remains the default selection.

    ``alpha_D/G`` store the complete amplitude, not an additional multiplier.
    The current calibration is selected explicitly through the model factory
    or its packaged parameter file; saved inputs retain their own values.
    """
    mode: str = 'cfd_smooth'
    alpha_D: float | None = field(default=None, metadata=_quantity('C_eff,D', '1', 'Sco2NuConfig.validate'))
    alpha_G: float | None = field(default=None, metadata=_quantity('C_eff,G', '1', 'Sco2NuConfig.validate'))
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
    """Input settings for preparation and application adapters.

    Construct at the UI boundary with ``ui.window_config.config_from_window``
    or from script input with :meth:`from_json`.
    Preparation creates frozen ``CaseData`` from these inputs.
    The public solver API consumes that prepared ``CaseData``.
    """
    fluid_A: FluidConfig = field(default_factory=FluidConfig)
    fluid_B: FluidConfig = field(default_factory=FluidConfig)
    geometry: GeometryConfig = field(default_factory=GeometryConfig)
    solver: SolverConfig = field(default_factory=SolverConfig)
    # Preserve the retired screening block in existing configuration archives.
    optimizer: Optional[OptimizerConfig] = None
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
        from sjtu_tpmshx.file_io.text_file import read_json
        return cls.from_dict(read_json(path))

    def to_dict(self) -> dict[str, Any]:
        """Return a detached archive, omitting unused retired settings."""
        data = asdict(self)
        if self.optimizer is None:
            data.pop('optimizer')
        return data

    def to_json(self, path: Union[str, Path]) -> None:
        """Write the configuration archive as JSON."""
        from sjtu_tpmshx.file_io.text_file import write_json
        write_json(path, self.to_dict())

    def validate_static_inputs(self, *, _native_preparation: bool = False) -> 'ComputeConfig':
        """Validate before prescribed mass flow has resolved inlet velocities.

        This preparation stage checks geometry, thermodynamic inputs, ports
        and numerical settings. It does not qualify an executable case:
        ``validate()`` must still check the resolved speeds and calibration.
        """
        _validate_static_settings(vars(self), lambda: self.is_3d,
                                  _native_preparation=_native_preparation)
        return self

    def validate(self, *, resolved_inlet_speeds: bool = False, _native_preparation: bool = False) -> 'ComputeConfig':
        """Reject non-physical inputs at the script and preparation boundary.

        ``from_dict``/``from_json`` call this; direct dataclass construction
        stays permissive for callers assembling a configuration in stages.
        """
        try:
            return self._validate_inputs(resolved_inlet_speeds, _native_preparation)
        except (TypeError, ValueError, ArithmeticError):
            if _native_preparation:
                self._validate_inputs(resolved_inlet_speeds, False)
            raise

    def _validate_inputs(self, resolved_inlet_speeds, native_preparation):
        import math

        self.validate_static_inputs(_native_preparation=native_preparation)
        _validate_inlet_speeds(self.fluid_A, self.fluid_B, resolved_inlet_speeds)
        ge = self.geometry
        if self.df_mode == 'experimental' and not native_preparation:
            from sjtu_tpmshx.cpp_interface import _native_df
            from sjtu_tpmshx.model_configs.model_parameters import load_preparation_df_parameters

            domain = (ge.L_dom_m, ge.H_dom_m, ge.Lz_m) if self.is_3d else (ge.L_dom_m, ge.H_dom_m)
            native_domain = all(type(value) in (int, float) for value in (*domain, ge.delta_levelset))
            geometry_mode = (1 if self.zones.axis == 'continuous' else 2) if self.zones.enabled else 0
            fluids = self.fluid_A.type, self.fluid_B.type
            hx = None
            scope = _native_df.experiment_scope(
                ge.tpms, fluids, geometry_mode, ge.L_cell_mm, ge.t_wall_mm,
                native_domain and ge.delta_levelset == 0., domain if native_domain else ())
            if scope is None:
                # Without a preparation library, the resource data gives the same scope.
                hx = load_preparation_df_parameters()['hx']
                cell, wall = hx['geometry_mm']
                tolerance = hx['geometry_absolute_tolerance_mm']
                transfer = (geometry_mode == 1 and ge.tpms == 'Gyroid' and fluids == ('air', 'water')
                            and math.isclose(ge.L_cell_mm, cell, rel_tol=0., abs_tol=tolerance)
                            and math.isclose(ge.t_wall_mm, wall, rel_tol=0., abs_tol=tolerance))
                layout = not geometry_mode or transfer or fluids == ('co2', 'co2')
            else:
                transfer, layout, hx_domain = scope
            if scope is None or not native_domain:
                hx_domain = None
            if not layout:
                raise ValueError(
                    "experimental calibration currently requires uniform L/t; "
                    "continuous Shanghai Gyroid air/water fields may use "
                    "the 7/0.6 calibration as an exploratory extrapolation")
            for side, fl in (('A', self.fluid_A),
                             ('B', self.fluid_B)):
                if fl.type == 'co2':
                    continue  # Fixed CO2 factors are independent of the global D-F selection.
                if fl.mass_flow_kg_s is not None and not resolved_inlet_speeds:
                    continue  # Preparation checks calibration after resolving the prescribed flow.
                try:
                    selection = _native_df.selection(ge.tpms, fl.type, ge.L_cell_mm, ge.t_wall_mm,
                                                     fl.u_mps, transfer=transfer)
                    if not selection.branch:
                        _native_df.scales(ge.tpms, selection, ge.L_cell_mm, ge.t_wall_mm)
                except ValueError as exc:
                    raise ValueError(
                        f"experimental calibration unavailable for active side "
                        f"{side}: {exc}") from exc
                if not selection.scope:
                    continue
                if hx_domain is None:
                    # The saved Python value can require conversion at this boundary.
                    if hx is None:
                        hx = load_preparation_df_parameters()['hx']
                    hx_domain = not (ge.delta_levelset != 0.) and all(
                        math.isclose(value, target) for value, target in zip(domain, hx['domain_m']))
                if not hx_domain:
                    raise ValueError(
                        f"experimental calibration side {side} is HX-effective "
                        "and requires delta=0 with the matching 0.182 x 0.042"
                        " x 0.042 m campaign domain")
        return self

    @classmethod
    def from_dict(cls, data: Dict[str, Any], *, prepared_grid: bool = False, _native_preparation: bool = False) -> 'ComputeConfig':
        """Build a ComputeConfig from a JSON-shaped dict.

        Supports two layouts:

        1. **Canonical** — keys ``fluid_A``, ``fluid_B``,
           ``geometry``, ``solver``, each mapping to the corresponding
           dataclass shape (``asdict`` round-trip).
        2. **Legacy Shanghai baseline** — ``geometry`` + ``domain``
           dicts; ``domain.L_dom_m`` / ``H_dom_m`` / ``Lz_m`` fold
           into :class:`GeometryConfig`. Fluids fall back to defaults
           because the Shanghai loop overwrites them per case.

        ``prepared_grid`` reads controls for a saved grid or geometry export.
        Callers must not construct a solver grid from these decoded inputs.
        """
        if not isinstance(data, dict):
            raise ValueError('ComputeConfig must be a JSON object')
        reject_retired_research_options(data)
        # The legacy layout is identified by its domain section. Optional
        # canonical sections must never decide how the remaining fields parse.
        if 'domain' not in data:
            values = _decode_canonical_settings(cls, data, prepared_grid=prepared_grid)
            return cls(**values).validate(_native_preparation=_native_preparation)

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
        # The checked-in Shanghai input also records the experiment's flow
        # area; its validation harness consumes these two legacy fields.
        unknown = set(domain_raw) - {'L_dom_m', 'H_dom_m', 'Lz_m',
                                     'n_units', 'a_flow_per_unit_m2'}
        if unknown:
            raise ValueError(f'legacy domain has unknown fields: {sorted(unknown)}')
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


def _validate_static_settings(values, is_3d, *, _native_preparation=False, port_windows_fit=None):
    import math

    solver = values['solver']
    zones = values['zones']
    extrap = values['extrap']
    flags = values['flags']
    nu = values['sco2_nu']
    df_mode = values['df_mode']
    ge = values['geometry']
    fluid_a = values['fluid_A']
    fluid_b = values['fluid_B']
    bc_a = values['bc_A']
    bc_b = values['bc_B']

    validate_enthalpy_algorithm(solver.enthalpy_algorithm,
                               solver.enthalpy_temperature_tol_K)

    validate_simple_velocity_relaxation(solver.simple_velocity_relaxation)
    for name in ('ltne_enthalpy_outer', 'ltne_enthalpy_nsweep', 'model_h_max_iterations'):
        value = getattr(solver, name)
        if value is None:
            continue
        minimum = 0 if name == 'ltne_enthalpy_nsweep' else 1
        if type(value) is not int or value < minimum:
            raise ValueError(f'ComputeConfig.solver.{name} must be an integer >= {minimum}')
    for name in ('ltne_enthalpy_omega', 'ltne_enthalpy_tol',
                 'ltne_enthalpy_coupled_energy_tol', 'ltne_enthalpy_equation_energy_tol',
                 'model_h_temperature_tol_K', 'model_h_q_relative_tol'):
        value = getattr(solver, name)
        if value is None:
            continue
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not isfinite(value) or value <= 0.
                or name == 'ltne_enthalpy_omega' and value > 1.):
            raise ValueError(f'ComputeConfig.solver.{name} is invalid')
    require_h = solver.require_enthalpy_update_on_temperature
    if type(require_h) is not bool:
        raise ValueError('ComputeConfig.solver.require_enthalpy_update_on_temperature must be boolean')

    for name, value in (
            ('zones.enabled', zones.enabled),
            ('extrap.allow', extrap.allow),
            ('flags.port_wall_refine', flags.port_wall_refine),
            ('flags.variable_rho_cp', flags.variable_rho_cp)):
        if type(value) is not bool:
            raise ValueError(f'ComputeConfig.{name} must be boolean')
    for name in ('Nx', 'Ny', 'Nz', 'max_iter_simple', 'max_outer_ltne'):
        value = getattr(solver, name)
        if value is None and name in ('max_iter_simple', 'max_outer_ltne'):
            continue
        if type(value) is not int:
            raise ValueError(f'ComputeConfig.solver.{name}={value!r} must be an integer')

    zones.validate()
    if zones.enabled and zones.axis in ('x', 'y', 'grid'):
        zone_source = zones.grid if zones.axis == 'grid' else zones.config
        for key, expected in (('tpms_type', ge.tpms),
                              ('k_s', ge.k_s_W_mK)):
            actual = (zone_source.get(key, expected) if isinstance(zone_source, dict)
                      else getattr(zone_source, key, expected))
            if actual != expected:
                raise ValueError(f'ComputeConfig.zones.{key}={actual!r} conflicts '
                                 f'with main geometry value {expected!r}')
    nu.validate()
    if zones.enabled and zones.axis == 'continuous':
        assert zones.config is not None  # Required by zones.validate().
        if ge.delta_levelset != 0.0:
            raise ValueError('Continuous spatial fields require delta_levelset=0')
        if not is_3d() and 'n_ctrl_z' in zones.config:
            raise ValueError('2D continuous fields cannot supply n_ctrl_z')
    if df_mode not in ('cfd_smooth', 'experimental'):
        raise ValueError(
            f"ComputeConfig.df_mode={df_mode!r} — must be "
            "'cfd_smooth' or 'experimental'")

    def _bad(name, v):
        raise ValueError(
            f"ComputeConfig.{name}={v!r} — must be finite and > 0")

    checks = [
        ('geometry.L_dom_m', ge.L_dom_m),
        ('geometry.H_dom_m', ge.H_dom_m),
        ('geometry.L_cell_mm', ge.L_cell_mm),
        ('geometry.t_wall_mm', ge.t_wall_mm),
        ('geometry.k_s_W_mK', ge.k_s_W_mK),
    ]
    if ge.Lz_m is not None:
        checks.append(('geometry.Lz_m', ge.Lz_m))
    for side, fl in (('A', fluid_a), ('B', fluid_b)):
        if fl.mass_flow_kg_s is not None:
            if (type(fl.mass_flow_kg_s) not in (int, float)
                    or not math.isfinite(fl.mass_flow_kg_s) or fl.mass_flow_kg_s <= 0):
                _bad(f'fluid_{side}.mass_flow_kg_s', fl.mass_flow_kg_s)
            if ge.Lz_m is None:
                raise ValueError('Total mass flow requires an explicit positive geometry.Lz_m')
        checks += [
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
    for name, n in (('solver.Nx', solver.Nx),
                    ('solver.Ny', solver.Ny),
                    ('solver.Nz', solver.Nz)):
        if n < 1:
            raise ValueError(
                f"ComputeConfig.{name}={n} — must be >= 1")

    # ── Lz contract (2026-07-12) ─────────────────────────────────────────
    # This class's own GeometryConfig docstring says the 3D path *requires*
    # Lz_m, but stages_3d silently substituted 0.042 m (the Shanghai depth)
    # when it was None — a 3D result computed against a magic constant the
    # user never chose, with every extensive scalar (Q, mass, dP_B) scaled
    # by it. Nz >= 2 is exactly `is_3d`, so this is a config error.
    if is_3d() and ge.Lz_m is None:
        raise ValueError(
            f"ComputeConfig.geometry.Lz_m is None but solver.Nz="
            f"{solver.Nz} >= 2 selects the 3D path, which requires an "
            "explicit domain depth (it used to silently fall back to "
            "0.042 m). Set geometry.Lz_m, or set Nz=1 for a 2D run.")

    # ── Numerical solver settings (2026-07-12) ───────────────────────────
    # Both widths must select the same mode: positive for partial ports,
    # nonpositive for full faces.
    for side, bc in (('A', bc_a), ('B', bc_b)):
        if not isinstance(bc.uniform_inlet_2d, bool):
            raise ValueError(f'ComputeConfig.bc_{side}.uniform_inlet_2d must be boolean')
        if (bc.in_w <= 0.0) != (bc.out_w <= 0.0):
            raise ValueError(
                f"ComputeConfig.bc_{side}.in_w and out_w must both be "
                "positive, or both be <= 0 for a full-face port")
        if _native_preparation and type(bc.dir) is int and 0 <= bc.dir < (6 if is_3d() else 4):
            # The native stage validates plain numbers and resolves full faces.
            fields: tuple = (bc.in_ctr, bc.in_w, bc.out_ctr, bc.out_w) if bc.in_w > 0 else (
                ge.H_dom_m if bc.dir < 2 else ge.L_dom_m,)
            if is_3d():
                for pair in ((bc.in_z_ctr, bc.in_z_w), (bc.out_z_ctr, bc.out_z_w)):
                    if any(v is not None for v in pair):
                        fields += pair
            if (all(type(v) in (int, float, bool) for v in fields)
                    and isfinite(bc.in_w) and isfinite(bc.out_w)):
                continue
        # For preview and other Python validation, bc_to_dict expands full faces.
        pipe = bc_to_dict(bc, ge.L_dom_m, ge.H_dom_m, side='A', with_z=is_3d())
        if port_windows_fit is not None and type(bc.dir) is int and 0 <= bc.dir < 4 and not is_3d():
            cross = ge.H_dom_m if bc.dir < 2 else ge.L_dom_m
            window = (cross, pipe['in_ctr'], pipe['in_w'], pipe['out_ctr'], pipe['out_w'])
            if all(type(value) is float for value in window) and port_windows_fit(*window):
                continue
        from sjtu_tpmshx.data_types.validator import validate_pipe_config
        problems = validate_pipe_config(
            pipe, ge.L_dom_m, ge.H_dom_m,
            Lz_dom=ge.Lz_m, is_3d=is_3d())
        errors = [str(problem) for problem in problems
                  if problem.severity == 'error']
        if errors:
            raise ValueError(
                f"ComputeConfig.bc_{side} is invalid: " + "; ".join(errors))

    # None selects the dimension-specific default; explicit gates must
    # be finite and positive.
    _gate_checks: Tuple[Tuple[str, Optional[float]], ...] = (
        ('solver.outer_tol_K', solver.outer_tol_K),
        # F2 gates (ledger C7). Same rule: positive and finite.
        # A zero or negative gate is strictly unreachable (all
        # three residuals are >= 0), so the solve could only ever
        # burn max_iter and report converged=False.
        ('solver.mom_tol', solver.mom_tol),
        ('solver.mass_local_tol', solver.mass_local_tol),
        ('solver.mass_global_tol', solver.mass_global_tol))
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
    from sjtu_tpmshx.run_control.run_environment import require_f2_mode
    require_f2_mode(solver.convergence_mode)

    if solver.max_iter_simple is not None:
        mi = solver.max_iter_simple
        if mi < 1:
            raise ValueError(
                f"ComputeConfig.solver.max_iter_simple={mi} — must be >= 1")
    if solver.max_outer_ltne is not None:
        mo = solver.max_outer_ltne
        # Outer convergence requires two temperature states.
        if mo < 2:
            raise ValueError(
                f"ComputeConfig.solver.max_outer_ltne={mo} — must be >= 2. "
                "A single outer pass can never satisfy the coupling "
                "criterion (it needs a previous iterate to compare "
                "against), so the run could only ever report "
                "converged=False.")

    # V2 production D-F closure is a water+sCO2 CFD table with bilinear
    # interpolation in geometry only. Extrapolation is not supported.
    from sjtu_tpmshx.model_configs.df_domain import CASE_GEOMETRY_LIMITS, TRAIN_L, TRAIN_T
    if not TRAIN_L[0] <= ge.L_cell_mm <= TRAIN_L[1] or not TRAIN_T[0] <= ge.t_wall_mm <= TRAIN_T[1]:
        raise ValueError(f'V2 geometry must lie inside the CFD grid: {CASE_GEOMETRY_LIMITS}')

    fluids = (fluid_a.type, fluid_b.type)
    for side, fl in (('A', fluid_a), ('B', fluid_b)):
        if fl.type != 'sco2':
            continue
        if not SCO2_T_RANGE_K[0] <= fl.T_in_K <= SCO2_T_RANGE_K[1]:
            raise ValueError(f'sCO2 fluid {side} temperature must be {SCO2_T_RANGE_K[0]:g}..{SCO2_T_RANGE_K[1]:g} K')
        if not SCO2_P_RANGE_PA[0] <= fl.P_in_Pa <= SCO2_P_RANGE_PA[1]:
            raise ValueError(f'sCO2 fluid {side} pressure must be {SCO2_P_RANGE_PA[0]/1e6:g}..{SCO2_P_RANGE_PA[1]/1e6:g} MPa')
    for fluid, label in (('sco2', 'sCO2 V2'), ('co2', 'CO2')):
        if fluid not in fluids:
            continue
        if zones.enabled and zones.axis != 'continuous' and fluid in _GEOMETRY_RESTRICTIONS['discrete_zones']:
            raise ValueError(f'{label} does not support discrete zones')
        if ge.delta_levelset != 0. and fluid in _GEOMETRY_RESTRICTIONS['levelset_offset']:
            message = 'CO2 requires symmetric delta_levelset=0 geometry' if fluid == 'co2' else 'sCO2 V2 requires delta_levelset=0'
            raise ValueError(message)


def _validate_inlet_speeds(fluid_a, fluid_b, resolved_inlet_speeds):
    import math

    for side, fluid in (('A', fluid_a), ('B', fluid_b)):
        if fluid.mass_flow_kg_s is not None and not resolved_inlet_speeds:
            continue
        try:
            speed = float(fluid.u_mps)
        except (TypeError, ValueError):
            speed = math.nan
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError(
                f'ComputeConfig.fluid_{side}.u_mps={fluid.u_mps!r} — must be finite and > 0')


def _decode_canonical_settings(cls, data, *, prepared_grid):
    unknown = set(data) - set(cls.__dataclass_fields__)
    if unknown:
        raise ValueError(f'unknown ComputeConfig fields: {sorted(unknown)}')
    fA_d = data.get('fluid_A', {}) or {}
    fB_d = data.get('fluid_B', {}) or {}
    ge_d = data.get('geometry', {}) or {}
    so_d = dict(data.get('solver', {}) or {})
    if prepared_grid:
        # Saved grids that predate these fields keep their original recipe.
        so_d.setdefault('enthalpy_algorithm', 'temperature_sou')
        so_d.setdefault('enthalpy_temperature_tol_K', 1e-8)
    reject_retired_research_options(so_d)
    # Old case files may contain retired controls. Report their
    # removal once at this import boundary, never in runtime APIs.
    _dropped = [k for k in ('alpha_T', 'rough_mode', 'tol_simple') if k in so_d]
    for key in _dropped:
        del so_d[key]
    if _dropped:
        warnings.warn(
            f"solver config keys {_dropped} are retired and were ignored; "
            "F2 uses mom_tol, mass_local_tol and mass_global_tol. "
            "Full-compute and multi-condition solve budgets use 'solver'; "
            "'optimizer' is archive-only.", stacklevel=3)
    op_d = dict(data.get('optimizer', {}) or {})
    if 'tol_simple' in op_d:
        del op_d['tol_simple']
        warnings.warn(
            "optimizer.tol_simple is retired and was ignored; "
            "it did not control F2 convergence.", stacklevel=3)
    # audit C4 additions — all optional, default-constructed
    # when absent so old JSON files keep round-tripping.
    bcA_d = data.get('bc_A', {}) or {}
    bcB_d = data.get('bc_B', {}) or {}
    zn_d = data.get('zones', {}) or {}
    fl_d = dict(data.get('flags', {}) or {})
    reject_retired_research_options(fl_d)
    if 'wall_refine_3d' in fl_d:
        retired = fl_d.pop('wall_refine_3d')
        if type(retired) is not bool:
            raise ValueError('flags.wall_refine_3d must be boolean')
        if retired and not prepared_grid:
            raise ValueError('wall_refine_3d is retired. Select port_wall_refine '
                             'with total grid counts, or use the archived source version.')
    ex_d = data.get('extrap', {}) or {}
    return dict(
        fluid_A=FluidConfig(**fA_d) if fA_d else FluidConfig(),
        fluid_B=FluidConfig(**fB_d) if fB_d else FluidConfig(),
        geometry=GeometryConfig(**ge_d) if ge_d else GeometryConfig(),
        solver=SolverConfig(**so_d) if so_d else SolverConfig(),
        optimizer=(OptimizerConfig(**op_d)
                   if data.get('optimizer') is not None else None),
        bc_A=PartialBCConfig(**bcA_d) if bcA_d else PartialBCConfig(),
        bc_B=PartialBCConfig(**bcB_d) if bcB_d else PartialBCConfig(),
        zones=ZoneInputConfig(**zn_d) if zn_d else ZoneInputConfig(),
        flags=FeatureFlags(**fl_d) if fl_d else FeatureFlags(),
        extrap=ExtrapPolicy(**ex_d) if ex_d else ExtrapPolicy(),
        envelope_mode=data.get('envelope_mode', 'raise'),
        df_mode=data.get('df_mode', 'cfd_smooth'),
        sco2_nu=Sco2NuConfig(**data.get('sco2_nu', {})),
    )


def _checked_saved_2d_settings(data, *, port_windows_fit=None):
    """Validate canonical saved host settings before the native scope check."""
    reject_retired_research_options(data)
    values = _decode_canonical_settings(ComputeConfig, data, prepared_grid=True)
    _validate_static_settings(values, lambda: int(values['solver'].Nz) >= 2, port_windows_fit=port_windows_fit)
    _validate_inlet_speeds(values['fluid_A'], values['fluid_B'], resolved_inlet_speeds=False)
    return values


__all__ = [
    'FluidType', 'DFMode', 'TPMSType', 'ZoneAxis',
    'FluidConfig', 'GeometryConfig', 'SolverConfig', 'OptimizerConfig',
    'PartialBCConfig', 'ZoneInputConfig',
    'ExtrapPolicy', 'FeatureFlags',
    'ComputeConfig', 'Sco2NuConfig',
]
