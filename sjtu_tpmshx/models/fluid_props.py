"""Single source of truth for per-fluid transport properties + Nu dispatch.

Adding a fluid = add one FLUIDS entry. Shim consumers in
``pipelines/stages_2d.py`` / ``stages_3d.py`` (formerly
``runs/run_calculation{,_3d}.py``) keep their own dict/tuple packing, Prandtl
formula and laminar-Nu floor — this module only selects the per-fluid
*primitives* (which rho/cp/mu/k/nu function to use), collapsing the scattered
``if fluid == 'water': ... else: ...`` branches into one place.

Behavior contract (must stay byte-identical to the old inline dispatch):
  * air.rho == tpms_calc.air_density (P defaults to 101325 like the old lambda)
  * water.rho ignores P (incompressible), like ``lambda T, P=None: water_density(T)``
  * air.nu ignores Pr → tpms_calc.nu_from_Re uses its built-in Pr_AIR default
  * water.nu uses the per-topology nu_water_topo fit (forwards caller Pr)
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import partial
from typing import Callable

import numpy as np
import CoolProp.CoolProp as CP

from . import tpms_calc
from . import sco2_props


class WaterStateError(ValueError):
    """An actual water state is unsupported or cannot be confirmed."""


def check_water_state(fluid, T, P, *, where="water state") -> None:
    """Check paired actual K/Pa(abs) states, never a temperature-only primitive.

    This is a stable-liquid exclusion check, not a general pressure/accuracy
    certificate for the T-only correlations. Their empirical warnings remain.
    Each call owns its HEOS state, including concurrent A/B calls.
    """
    if fluid.strip().lower() != 'water':
        return
    try:
        temperatures, pressures = np.broadcast_arrays(
            np.asarray(T, dtype=float), np.asarray(P, dtype=float))
    except (TypeError, ValueError) as exc:
        raise WaterStateError(f"{where}: water requires paired T/P states") from exc
    if not temperatures.size:
        raise WaterStateError(f"{where}: water requires finite positive K and Pa(abs)")
    if not (
            np.isfinite(temperatures).all() and np.isfinite(pressures).all()
            and (temperatures > 0).all() and (pressures > 0).all()):
        index = tuple(map(int, np.unravel_index(np.flatnonzero(
            ~np.isfinite(temperatures) | ~np.isfinite(pressures)
            | (temperatures <= 0) | (pressures <= 0))[0], temperatures.shape)))
        raise WaterStateError(
            f"{where}: water index={index}, T={temperatures[index]:g} K, "
            f"P_abs={pressures[index]:g} Pa: requires finite positive K and Pa(abs)")
    state = CP.AbstractState('HEOS', 'Water')
    for flat_index, (t, p) in enumerate(zip(temperatures.flat, pressures.flat)):
        try:
            state.update(CP.PT_INPUTS, float(p), float(t))
            phase = state.phase()
            if phase == CP.iphase_supercritical_liquid:
                raise WaterStateError(
                    "high-pressure liquid: T-only model applicability unconfirmed")
            if phase != CP.iphase_liquid:
                raise WaterStateError("only stable single-phase liquid water is supported")
            if not state.has_melting_line():
                raise WaterStateError("solid/liquid stability unconfirmed")
            t_melt = state.melting_line(CP.iT, CP.iP, float(p))
            if not np.isfinite(t_melt) or t <= t_melt:
                raise WaterStateError("freezing boundary or solid/metastable water unsupported")
        except (ValueError, RuntimeError) as exc:
            index = tuple(map(int, np.unravel_index(flat_index, temperatures.shape)))
            raise WaterStateError(
                f"{where}: water index={index}, T={t:g} K, P_abs={p:g} Pa: {exc}") from exc


def check_finite_temperatures(Ta, Tb, Ts, *, where):
    """Reject non-finite actual fields; callers retain water-state precedence."""
    for side, field in (('A', Ta), ('B', Tb), ('solid', Ts)):
        if field is None:  # No supplied warm start; the solver initializes it.
            continue
        values = np.asarray(field)
        finite = np.isfinite(values)
        if not finite.all():
            index = tuple(map(int, np.unravel_index(
                np.flatnonzero(~finite)[0], values.shape)))
            raise ValueError(
                f'{where}: {side} temperature index={index}, '
                f'T={values[index]:g} K is non-finite')


def _nu_air(tpms_type, Re, eps_f, L_mm, D_h_mm, Pr=None):
    # Air uses nu_from_Re's built-in Pr default (Pr_AIR); any Pr passed in is
    # ignored, matching the air branch in run_calculation{,_3d}.
    return tpms_calc.nu_from_Re(tpms_type, Re, eps_f, L_mm, D_h_mm)


def _nu_water(tpms_type, Re, eps_f, L_mm, D_h_mm, Pr):
    # Direct per-topology water Nu fit (nu_correlations.WATER_NU_COEFFS;
    # smooth-wall water CFD, no air x1.28). eps_f / L_mm / D_h_mm unused —
    # kept for the FluidModel.nu signature contract.
    del eps_f, L_mm, D_h_mm
    return tpms_calc.nu_water_topo(tpms_type, Re, Pr)


def _nu_sco2(tpms_type, Re, eps_f, L_mm, D_h_mm, Pr, *, settings=None):
    # V1 uses the smooth-wall CFD fit directly; experiment roughness/pressure
    # losses are deliberately outside this validation round.
    del eps_f
    if settings is not None:
        from .nu_correlations import nu_sco2_selected
        return nu_sco2_selected(tpms_type, Re, Pr, L_mm, D_h_mm, settings=settings)
    return tpms_calc.nu_sco2_topo(tpms_type, Re, Pr, L_mm, D_h_mm)


def _sco2_prop(key):
    """Wrap an sCO2 property (by CoolProp key) so a missing P raises a clear
    error rather than a cryptic CoolProp failure (sCO2 props are P-dependent),
    and so a SCALAR or a whole FIELD of T/P both work. The 2D/3D variable-
    property loop calls these primitives with arrays (T field + local-P field);
    air/water are numpy-elementwise, sCO2 must vectorise its CoolProp call.
    sco2_props.sco2_prop dispatches scalar->cached / array->vectorised."""
    def _wrapped(T, P=None):
        if P is None:
            raise ValueError(
                "sCO2 properties require pressure P [Pa]; caller passed P=None. "
                "Fix the call site to forward the inlet/local pressure.")
        return sco2_props.sco2_prop(key, T, P)
    return _wrapped


@dataclass(frozen=True)
class FluidModel:
    name: str
    compressible: bool
    rho: Callable    # (T[, P]) -> density [kg/m^3]
    cp: Callable     # (T[, P]) -> specific heat [J/kg/K]
    mu: Callable     # (T[, P]) -> dynamic viscosity [Pa.s]
    k: Callable      # (T[, P]) -> thermal conductivity [W/m/K]
    # Signature widened to (T, P) for sCO2 (2026-06-26): air/water ignore P
    # (lambda T, P=None: f(T)) so existing m.cp(T) calls stay value-identical;
    # sCO2 cp/mu/k REQUIRE P (real-gas) and callers must forward it.
    nu: Callable     # (tpms, Re, eps_f, L_mm, D_h_mm, Pr) -> Nu (pre-floor)
    # Guard for the (air-calibrated) roughness.py multipliers: when True they
    # must NOT be applied to this fluid. Water's D-F closure is experiment-
    # trained (already contains SLM roughness) and its Nu is the smooth-wall
    # per-topology fit (nu_water_topo) — the air roughness modes don't apply
    # either way. Air takes the env-gated roughness modes.
    embeds_roughness: bool = False
    # Specific enthalpy h(T[, P]) [J/kg], for the true-enthalpy duty Q = ṁ·Δh.
    # Only set for strongly-variable-cp fluids (sCO2) where cp·ΔT ≠ Δh across a
    # HX temperature span; None for air/water (near-constant cp ⇒ the duty
    # extraction keeps the value-identical cp·ΔT form, golden-safe).
    enthalpy: Callable | None = None


FLUIDS = {
    'air': FluidModel(
        name='air', compressible=True,
        rho=tpms_calc.air_density,        # (T, P=101325) -> rho
        cp=lambda T, P=None: tpms_calc.air_cp(T),           # T-only; P ignored
        mu=lambda T, P=None: tpms_calc.air_viscosity(T),
        k=lambda T, P=None: tpms_calc.air_conductivity(T),
        nu=_nu_air,
        embeds_roughness=False,
    ),
    'water': FluidModel(
        name='water', compressible=False,
        rho=lambda T, P=None: tpms_calc.water_density(T),   # incompressible: P ignored
        cp=lambda T, P=None: tpms_calc.water_cp(T),
        mu=lambda T, P=None: tpms_calc.water_viscosity(T),
        k=lambda T, P=None: tpms_calc.water_conductivity(T),
        nu=_nu_water,
        embeds_roughness=True,
    ),
    'sco2': FluidModel(
        name='sco2', compressible=False,   # Phase A: incompressible (D-7-6 ΔP/P<2%);
                                           # ρ=ρ(T,P_in) varies with T. Compressible
                                           # ρ(P_local) is Phase B (high-ΔP cases).
        rho=_sco2_prop("D"),
        cp=_sco2_prop("C"),
        mu=_sco2_prop("V"),
        k=_sco2_prop("L"),
        nu=_nu_sco2,
        # True here means "do NOT apply the air-calibrated roughness.py
        # multipliers" — correct for sCO2 whose closures are now smooth-wall
        # CFD (2026-07-15): roughness is deliberately UNMODELLED (not baked
        # in), and the air modes are the wrong anchor for it. Rename trap:
        # the flag gates air-mode application, it does not assert the fit
        # contains roughness.
        embeds_roughness=True,
        enthalpy=_sco2_prop("H"),  # true-enthalpy duty ṁ·Δh (cp·ΔT wrong for sCO2)
    ),
}


def get(fluid: str, *, sco2_nu=None) -> FluidModel:
    """Return the FluidModel for ``fluid`` ('air' | 'water'), case-insensitive."""
    try:
        model = FLUIDS[fluid.strip().lower()]
    except (KeyError, AttributeError):
        raise ValueError(f"unknown fluid {fluid!r}; known: {sorted(FLUIDS)}")

    if model.name == 'sco2' and sco2_nu is not None:
        sco2_nu.validate()
        if sco2_nu.mode == 'experimental':
            return replace(model, nu=partial(_nu_sco2, settings=sco2_nu))
    return model


def flow_model(fluid: str) -> str:
    """SIMPLE-solver fluid_type string for ``fluid``:
    'ideal_gas' (compressible) or 'incompressible'."""
    return 'ideal_gas' if get(fluid).compressible else 'incompressible'
