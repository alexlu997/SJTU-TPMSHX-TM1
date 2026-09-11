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


def test_real_eos_return_and_end_of_iteration_reject(monkeypatch):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    h_vapor = CP.PropsSI('H', 'T', 420., 'P', 200000., 'Water')
    with pytest.raises(WaterStateError):
        ent._T_of_h_field(np.array([h_vapor]), 200000., 'water')

    def vapor_after_sweep(hA, *args):
        hA[:] = h_vapor

    monkeypatch.setattr(ent, '_gs_enthalpy_sweeps_3d', vapor_after_sweep)
    with pytest.raises(WaterStateError, match='EOS return'):
        ent.solve_ltne_enthalpy_3d(
            1, 1, 1, .01, .01, .01, .7, 16., .01, .01, 100., 100.,
            300., 320., 200000., fluid_A='water', fluid_B='water', n_outer=1)


def test_enthalpy_warm_start_uses_local_pressure():
    from sjtu_tpmshx.solvers.ltne_enthalpy_3d import solve_ltne_enthalpy_3d_pipeline
    cell = np.ones((1, 1, 1))
    with pytest.raises(WaterStateError, match='warm start A'):
        solve_ltne_enthalpy_3d_pipeline(
            1, 1, 1, [1.], [1.], [1.], cell * .7, cell * 5.,
            cell * 100., cell * 100., .01, .01, 300., 320., 2e5, 2e5, 0, 1,
            fluid_A='water', fluid_B='water', Ta_init=cell * 380.,
            pressure_A_field=cell * 1e5, n_outer=1)


def test_2d_enthalpy_wrapper_propagates_water_state_error():
    from sjtu_tpmshx.solvers.ltne_enthalpy_2d import solve_enthalpy_2d
    flux = (np.zeros((2, 1)), np.zeros((1, 2)))
    with pytest.raises(WaterStateError, match='inlet B'):
        solve_enthalpy_2d(
            300., 400., 2e5, 1e5, flux, flux, 100., 100., 5., .35, .35,
            [1.], [1.], P_inA=2e5, P_inB=1e5,
            fluid_A='water', fluid_B='water', max_iter=1)


@pytest.mark.parametrize('bad', [420., np.nan])
def test_water_error_reports_first_broadcast_cell(bad):
    with pytest.raises(WaterStateError) as error:
        check_water_state('water', [[300., bad], [bad, 300.]], 2e5,
                          where='thermal return B')
    assert str(error.value).startswith(
        f'thermal return B: water index=(0, 1), T={bad:g} K, P_abs=200000 Pa:')


@pytest.mark.parametrize('adapter', [False, True])
@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('eos_failure', [False, True])
def test_shared_driver_final_water_eos_rejection(monkeypatch, adapter, side, eos_failure):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    from sjtu_tpmshx.solvers.ltne_enthalpy_2d import solve_enthalpy_2d

    h_vapor = (-1e9 if eos_failure else
               CP.PropsSI('H', 'T', 420., 'P', 200000., 'Water'))
    sweeps = []

    def invalidate_last_sweep(hA, hB, *args):
        sweeps.append(1)
        (hA if side == 'A' else hB)[:] = h_vapor

    monkeypatch.setattr(ent, '_gs_enthalpy_sweeps_3d', invalidate_last_sweep)
    cell = np.ones((1, 1, 1))
    with pytest.raises(WaterStateError, match=f'enthalpy final EOS return {side}') as error:
        if adapter:
            flux = (np.zeros((2, 1)), np.zeros((1, 2)))
            solve_enthalpy_2d(
                300., 320., 2e5, 2e5, flux, flux, 100., 100., 5., .35, .35,
                [1.], [1.], P_inA=2e5, P_inB=2e5,
                fluid_A='water', fluid_B='water', max_iter=1)
        else:
            ent.solve_ltne_enthalpy_3d_pipeline(
                1, 1, 1, [1.], [1.], [1.], cell * .7, cell * 5.,
                cell * 100., cell * 100., 0., 0., 300., 320., 2e5, 2e5, 0, 1,
                fluid_A='water', fluid_B='water', n_outer=1)
    assert sweeps == [1]
    assert 'index=(0, 0, 0)' in str(error.value)
    if eos_failure:
        assert isinstance(error.value.__cause__, ValueError)
        assert 'state unconfirmed' in str(error.value)
        assert 'input h=[[[-1.e+09]]] J/kg, P_abs=[[[200000.]]] Pa' in str(error.value)
    else:
        assert 'P_abs=200000 Pa' in str(error.value)


def test_water_vector_eos_exception_does_not_invent_failed_index(monkeypatch):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    calls = []
    original = ent._PropsSI

    def eos(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(ent, '_PropsSI', eos)
    with pytest.raises(WaterStateError, match='iteration EOS return B') as error:
        ent._T_of_h_field(np.array([-1e9, -2e9]), np.array([2e5, 3e5]),
                          'water', where='enthalpy iteration EOS return B')
    assert len(calls) == 1
    assert isinstance(error.value.__cause__, ValueError)
    assert 'failed index undetermined, input shape=(2,)' in str(error.value)
    assert 'input h=[-1.e+09 -2.e+09] J/kg, P_abs=[200000. 300000.] Pa' in str(error.value)


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('dimension', [2, 3])
def test_pipeline_inlet_checks_both_water_sides_before_domain_work(side, dimension):
    from sjtu_tpmshx.domain.compute_config import ComputeConfig, FluidConfig
    from sjtu_tpmshx.pipelines.stages_2d import _parse_inputs_cfg
    from sjtu_tpmshx.pipelines.stages_3d import _parse_inputs_3d_cfg
    cfg = ComputeConfig(fluid_A=FluidConfig(type='water'),
                        fluid_B=FluidConfig(type='water'))
    getattr(cfg, 'fluid_' + side).T_in_K = 400.
    cfg.geometry.Lz_m = .042
    with pytest.raises(WaterStateError, match='inlet ' + side):
        (_parse_inputs_cfg if dimension == 2 else _parse_inputs_3d_cfg)(cfg)
