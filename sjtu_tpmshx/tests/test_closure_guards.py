"""Closure-model robustness guards (Stage 2, 2026-06-25).

Audit (Agent 4) found several closures that silently return physically
meaningless values outside their calibration window. These guards make the
out-of-window behaviour explicit (clear error for impossible inputs, a loud
one-shot warning for extrapolation) without erroring on valid inputs.
"""
import warnings as W

import numpy as np
import pytest

import sjtu_tpmshx.models.tpms_calc as tpms_calc
import sjtu_tpmshx.models.tpms_props as tpms_props   # warn-state lives here (arch-b-c-e B)
from sjtu_tpmshx.models.tpms_calc import geometry, compute, water_density
import sjtu_tpmshx.models.nu_correlations as nu_correlations
from sjtu_tpmshx.models.nu_correlations import nu_water_topo
from sjtu_tpmshx.df_surrogate.predict import predict_dP_compressible
from sjtu_tpmshx.domain.compute_config import (ComputeConfig, FluidConfig,
                                         ZoneInputConfig)
from sjtu_tpmshx.preprocess.two_d.preparation import _check_zoned_fluid_support


# ── geometry degeneracy floor ──────────────────────────────────────────────
def test_geometry_near_degenerate_raises_instead_of_zero_eps():
    # 2t just below L passes the 2t>=L guard but yields eps=0 / D_h=0 silently.
    with pytest.raises(ValueError):
        geometry('Gyroid', 4.0, 1.99, 16.0)


def test_geometry_valid_still_works():
    g = geometry('Gyroid', 7.0, 0.5, 16.0)
    assert g['epsilon'] > 0.0 and g['D_h'] > 0.0


# ── zoned 2D + non-air side -> fail loud (would silently use air props) ─────
def test_zoned_water_side_raises_not_implemented():
    cc = ComputeConfig(fluid_B=FluidConfig(type='water'),
                       zones=ZoneInputConfig(enabled=True))
    with pytest.raises(NotImplementedError):
        _check_zoned_fluid_support(cc)


def test_zoned_air_air_ok_and_disabled_zones_ok():
    # air-air zoned: fine. zones disabled with water: fine (uniform path).
    _check_zoned_fluid_support(ComputeConfig(zones=ZoneInputConfig(enabled=True)))
    _check_zoned_fluid_support(ComputeConfig(fluid_B=FluidConfig(type='water'),
                                             zones=ZoneInputConfig(enabled=False)))


# A T-only correlation warns about its fit, never infers phase without P.
def test_water_density_warns_fit_extrapolation_only():
    tpms_props._range_warnings_emitted.clear()
    with W.catch_warnings(record=True) as rec:
        W.simplefilter('always')
        water_density(400.0)
    msgs = [str(w.message).lower() for w in rec]
    assert any('outside fitted range' in m for m in msgs), msgs
    assert not any('two-phase' in m or 'saturation' in m for m in msgs), msgs


def test_water_viscosity_finite_below_140K():
    # Audit fix: 10**(247.8/(T-140)) overflowed to +inf near T=141 K.
    assert np.isfinite(tpms_calc.water_viscosity(141.0))
    assert np.all(np.isfinite(
        tpms_calc.water_viscosity(np.array([130.0, 141.0, 200.0]))))


def test_water_viscosity_unchanged_for_physical_water():
    T = 313.15   # 40 C, denom = 173 >> 10 floor -> bit-identical
    expected = 2.414e-5 * 10.0 ** (247.8 / (T - 140.0))
    assert tpms_calc.water_viscosity(T) == expected


def test_water_density_no_two_phase_warn_in_range():
    with W.catch_warnings(record=True) as rec:
        W.simplefilter('always')
        water_density(330.0)               # 57 C, liquid
    msgs = [str(w.message).lower() for w in rec]
    assert not any('two-phase' in m or 'boil' in m for m in msgs), msgs


# ── nu_water_topo extrapolation warning ────────────────────────────────────
def test_nu_water_topo_warns_outside_range():
    nu_correlations._WATER_NU_WARNED.clear()
    with W.catch_warnings(record=True) as rec:
        W.simplefilter('always')
        nu_water_topo('Gyroid', 80000.0, 4.0)   # Re > 50000
    assert any('water' in str(w.message).lower() for w in rec)


# ── Nu air window unified to [400, 16000] (was [600, 30000] in compute) ─────
def test_compute_nu_window_unified_no_warn_at_re_581():
    compute.cache_clear()
    nu_correlations._EXTRAP_WARNED.clear()
    with W.catch_warnings(record=True) as rec:
        W.simplefilter('always')
        compute('Diamond', 6.0, 0.4, 5.0, 350.0, 101325.0, 16.0)  # Re ~ 581
    msgs = [str(w.message) for w in rec]
    # 581 is inside the single-source window [400, 16000]; the old duplicate
    # [600, 30000] check would have warned.
    assert not any('validated range' in m for m in msgs), msgs


# ── compressible dP infeasibility honesty ──────────────────────────────────
def test_predict_dP_choked_warns_when_rescuing_to_pin():
    import sjtu_tpmshx.df_surrogate.predict as predmod
    predmod._CHOKE_WARNED.clear()
    with W.catch_warnings(record=True) as rec:
        W.simplefilter('always')
        # Huge G over a long channel -> P_out^2 < 0 -> non-strict P_in rescue.
        dP = predict_dP_compressible(
            'Gyroid', 7.0, 0.5, 0.78, G=200.0, T=800.0, P_in=101325.0,
            mu=3.6e-5, L=0.7, strict=False)
    assert dP == pytest.approx(101325.0)
    assert any('chok' in str(w.message).lower()
               or 'infeasible' in str(w.message).lower() for w in rec)


def test_predict_dP_choke_warns_per_geometry_not_once_per_process():
    # Audit fix (choke-warn-key-too-coarse): the warning was keyed on the
    # constant string 'choke', so only the FIRST choked candidate in a design
    # sweep warned. Now keyed on (tpms, L, t) -> a second, different choked
    # geometry warns too.
    import sjtu_tpmshx.df_surrogate.predict as predmod
    predmod._CHOKE_WARNED.clear()
    geoms = [('Gyroid', 7.0, 0.5), ('Diamond', 4.0, 0.3)]
    warned = 0
    for tpms, L, t in geoms:
        with W.catch_warnings(record=True) as rec:
            W.simplefilter('always')
            predict_dP_compressible(tpms, L, t, 0.78, G=200.0, T=800.0,
                                    P_in=101325.0, mu=3.6e-5, L=0.7,
                                    strict=False)
        if any('chok' in str(w.message).lower() for w in rec):
            warned += 1
    assert warned == 2, "each distinct choked geometry must warn"
