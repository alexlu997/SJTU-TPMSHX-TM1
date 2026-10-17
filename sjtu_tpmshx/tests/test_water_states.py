"""Actual water T/P boundaries; no solver or temporary-sweep acceptance."""

import numpy as np
import pytest
import CoolProp.CoolProp as CP

from sjtu_tpmshx.models.fluid_props import WaterStateError, check_water_state, get
from sjtu_tpmshx.models import tpms_calc, tpms_props
from sjtu_tpmshx.domain.run_warnings import warning_scope


def test_saturation_bracket_and_pressurized_liquid():
    t = 380.0
    psat = CP.PropsSI('P', 'T', t, 'Q', 0, 'Water')
    check_water_state('water', t, psat * 1.001)
    with pytest.raises(WaterStateError):
        check_water_state('water', t, psat * 0.999)
    with pytest.raises(WaterStateError):
        check_water_state('water', t, psat)
    check_water_state('water', [372.0, 374.0, 380.0], 200000.0)


@pytest.mark.parametrize('t,p', [(np.nan, 1e5), (300, 0), (300, np.inf),
                                 (700, 3e7), (300, 3e7), (260, 101325)])
def test_unsupported_or_unconfirmed_state_rejected(t, p):
    with pytest.raises(WaterStateError):
        check_water_state('water', t, p)


def test_high_pressure_liquid_is_not_mislabelled_supercritical_water():
    with pytest.raises(WaterStateError, match='high-pressure liquid.*unconfirmed'):
        check_water_state('water', 300, 3e7)


@pytest.mark.parametrize('pressure', [101325.0, 200000.0])
def test_melting_line_bracket(pressure):
    state = CP.AbstractState('HEOS', 'Water')
    assert state.has_melting_line()
    tm = state.melting_line(CP.iT, CP.iP, pressure)
    check_water_state('water', tm + .001, pressure)
    with pytest.raises(WaterStateError, match='freezing'):
        check_water_state('water', tm - .001, pressure)


def test_paired_arrays_and_model_values_unchanged():
    t = np.array([300.0, 380.0])
    p = np.array([101325.0, 200000.0])
    with warning_scope({}):
        before = [get('water').rho(t, p), get('water').mu(t, p),
                  get('water').cp(t, p), get('water').k(t, p)]
        check_water_state('water', t, p)
        after = [tpms_props.water_density(t), tpms_props.water_viscosity(t),
                 tpms_props.water_cp(t), tpms_props.water_conductivity(t)]
    for old, new in zip(before, after):
        np.testing.assert_array_equal(old, new)
    with pytest.raises(WaterStateError):
        check_water_state('water', t, p[::-1])
    with pytest.raises(WaterStateError):
        check_water_state('water', [300, 310], [1e5, 2e5, 3e5])


def test_compute_guard_before_cache_and_warning_collection(monkeypatch):
    from sjtu_tpmshx.models import fluid_props
    calls = []
    original = fluid_props.check_water_state

    def checked(*args, **kwargs):
        calls.append(args)
        original(*args, **kwargs)

    monkeypatch.setattr(fluid_props, 'check_water_state', checked)
    tpms_calc.compute.cache_clear()
    args = ('Gyroid', 7., .6, .2, 300., 101325., 16., 'water')
    with warning_scope({}):
        first = tpms_calc.compute(*args)
        assert tpms_calc.compute(*args) == first
    assert len(calls) == 2
    assert tpms_calc.compute.cache_info().hits == 1
    with warning_scope({}) as records:
        with pytest.raises(WaterStateError):
            tpms_calc.compute('Gyroid', 7., .6, .2, 400., 101325., 16., 'water')
    assert not records








@pytest.mark.parametrize('bad', [420., np.nan])
def test_water_error_reports_first_broadcast_cell(bad):
    with pytest.raises(WaterStateError) as error:
        check_water_state('water', [[300., bad], [bad, 300.]], 2e5,
                          where='thermal return B')
    assert str(error.value).startswith(
        f'thermal return B: water index=(0, 1), T={bad:g} K, P_abs=200000 Pa:')




@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('dimension', [2, 3])
def test_pipeline_inlet_checks_both_water_sides_before_domain_work(side, dimension):
    from sjtu_tpmshx.domain.compute_config import ComputeConfig, FluidConfig
    from sjtu_tpmshx.preprocess.two_d.preparation import _parse_inputs_cfg
    from sjtu_tpmshx.preprocess.three_d.preparation import _parse_inputs_3d_cfg
    cfg = ComputeConfig(fluid_A=FluidConfig(type='water'),
                        fluid_B=FluidConfig(type='water'))
    getattr(cfg, 'fluid_' + side).T_in_K = 400.
    cfg.geometry.Lz_m = .042
    with pytest.raises(WaterStateError, match='inlet ' + side):
        (_parse_inputs_cfg if dimension == 2 else _parse_inputs_3d_cfg)(cfg)
