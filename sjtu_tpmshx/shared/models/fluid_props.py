"""Single source of truth for per-fluid transport properties + Nu dispatch.

Adding a fluid starts with a FLUIDS entry and the applicable model tests.
Consumers retain their packing and laminar-Nu floor policy. C++ owns the
property, Nu and derived arithmetic. This module selects the per-fluid
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

from . import co2_correlations, co2_props, nu_correlations, sco2_props, tpms_props, _native_properties


class WaterStateError(ValueError):
    """An actual water state is unsupported or cannot be confirmed."""


class QuickDesignWaterFieldError(WaterStateError):
    """A quick-design field cannot satisfy the existing liquid-water contract."""


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
    try:
        _native_properties.paired_state('water_pt', temperatures, pressures)
    except _native_properties.StateError as error:
        if not temperatures.size:
            raise WaterStateError(f'{where}: water requires finite positive K and Pa(abs)') from None
        index = tuple(map(int, np.unravel_index(error.failure.index, temperatures.shape)))
        failure = WaterStateError(
            f'{where}: water index={index}, T={temperatures[index]:g} K, '
            f'P_abs={pressures[index]:g} Pa: {error}')
        if error.failure.reason == 1:
            raise failure from None
        cause = WaterStateError(str(error)) if error.failure.reason == 6 else ValueError(str(error))
        raise failure from cause


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
    return nu_correlations.nu_from_Re(tpms_type, Re, eps_f, L_mm, D_h_mm)


def _nu_water(tpms_type, Re, eps_f, L_mm, D_h_mm, Pr):
    # Direct per-topology water Nu fit (nu_correlations.WATER_NU_COEFFS;
    # smooth-wall water CFD, no air x1.28). eps_f / L_mm / D_h_mm unused —
    # kept for the FluidModel.nu signature contract.
    del eps_f, L_mm, D_h_mm
    return nu_correlations.nu_water_topo(tpms_type, Re, Pr)


def _nu_sco2(tpms_type, Re, eps_f, L_mm, D_h_mm, Pr, *, settings=None):
    # Default: smooth-wall CFD fit. Explicit experimental settings select the
    # total effective coefficient in nu_sco2_selected, applied once.
    del eps_f
    if settings is not None:
        return nu_correlations.nu_sco2_selected(
            tpms_type, Re, Pr, L_mm, D_h_mm, settings=settings)
    return nu_correlations.nu_sco2_topo(tpms_type, Re, Pr, L_mm, D_h_mm)


def _sco2_prop(key):
    """Adapt the native sCO2 query and require absolute pressure.

    Scalar calls use the existing cache. Field calls broadcast T and P.
    The native backend reads inlet or local pressure from those inputs.
    """
    def _wrapped(T, P=None):
        if P is None:
            raise ValueError(
                "sCO2 properties require pressure P [Pa]; caller passed P=None. "
                "Fix the call site to forward the inlet/local pressure.")
        return sco2_props.sco2_prop(key, T, P)
    return _wrapped


def _nu_co2(tpms_type, Re, eps_f, L_mm, D_h_mm, Pr):
    return co2_correlations.nusselt(tpms_type, Re, Pr, L_mm, D_h_mm)


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
    # True excludes the air-calibrated roughness.py multipliers. Despite the
    # flag's name, this does not assert that a CFD fit contains roughness.
    # Water/sCO2 use the fixed CFD D-F base; any selected experimental D-F
    # correction has its own calibration scope. Water Nu is smooth-wall CFD.
    embeds_roughness: bool = False
    # Specific enthalpy h(T[, P]) [J/kg], for the true-enthalpy duty Q = ṁ·Δh.
    # Set for sCO2. None for air/water: their callers retain the selected
    # temperature/cp or integrated model-enthalpy formulation.
    enthalpy: Callable | None = None
    nu_floor_multiplier: float = 1.


FLUIDS = {
    'co2': FluidModel(
        name='co2', compressible=False,
        rho=partial(co2_props.co2_prop, 'D'),
        cp=partial(co2_props.co2_prop, 'C'),
        mu=partial(co2_props.co2_prop, 'V'),
        k=partial(co2_props.co2_prop, 'L'),
        nu=_nu_co2, embeds_roughness=True,
        enthalpy=partial(co2_props.co2_prop, 'H'),
        nu_floor_multiplier=co2_correlations.NU_MULTIPLIER,
    ),
    'air': FluidModel(
        name='air', compressible=True,
        rho=tpms_props.air_density,        # (T, P=101325) -> rho
        cp=lambda T, P=None: tpms_props.air_cp(T),           # T-only; P ignored
        mu=lambda T, P=None: tpms_props.air_viscosity(T),
        k=lambda T, P=None: tpms_props.air_conductivity(T),
        nu=_nu_air,
        embeds_roughness=False,
    ),
    'water': FluidModel(
        name='water', compressible=False,
        rho=lambda T, P=None: tpms_props.water_density(T),   # incompressible: P ignored
        cp=lambda T, P=None: tpms_props.water_cp(T),
        mu=lambda T, P=None: tpms_props.water_viscosity(T),
        k=lambda T, P=None: tpms_props.water_conductivity(T),
        nu=_nu_water,
        embeds_roughness=True,
    ),
    'sco2': FluidModel(
        # Incompressible momentum adapter; density can still vary with T.
        # Property calls accept inlet or local absolute P from their caller;
        # this flag does not freeze the energy solver's pressure-dependent EOS.
        name='sco2', compressible=False,
        rho=_sco2_prop("D"),
        cp=_sco2_prop("C"),
        mu=_sco2_prop("V"),
        k=_sco2_prop("L"),
        nu=_nu_sco2,
        # Exclude air-specific multipliers for both sCO2 Nu selections.
        embeds_roughness=True,
        enthalpy=_sco2_prop("H"),  # true-enthalpy duty ṁ·Δh (cp·ΔT wrong for sCO2)
    ),
}


def get(fluid: str, *, sco2_nu=None) -> FluidModel:
    """Return the model for 'air', 'water', 'sco2' or 'co2', case-insensitive."""
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
