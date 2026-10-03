"""Quick-design scalar and full-field water states with controlled thermal solves."""
from dataclasses import replace
import importlib

import numpy as np
import pytest

from sjtu_tpmshx.models import design_fluids, fluid_props
from sjtu_tpmshx.preprocess.api import prepare_quick_design
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.tests.design.test_forward import _case


@pytest.mark.parametrize('fluid,temperature,pressure', [
    ('air', 645.6, 1088700.), ('water', 350., 200000.), ('sco2', 480., 9e6),
])
def test_valid_scalar_properties_keep_registry_values(fluid, temperature, pressure):
    actual = design_fluids.fluid_props(fluid, temperature, pressure)
    model = fluid_props.get(fluid)
    for name in ('rho', 'mu', 'k', 'cp'):
        assert getattr(actual, name) == getattr(model, name)(temperature, pressure)
    assert actual.Pr == actual.mu * actual.cp / actual.k


def test_scalar_water_state_uses_pressure_before_liquid_properties():
    # 350 K is within the T-only fit, but liquid water is unsupported at 10 kPa.
    with pytest.raises(fluid_props.WaterStateError, match='quick-design properties'):
        design_fluids.fluid_props('water', 350., 10000.)


@pytest.mark.parametrize('side', ['hot', 'cold'])
def test_public_preparation_rejects_nonliquid_water_before_drag(monkeypatch, side):
    preparation = importlib.import_module('sjtu_tpmshx.preprocess.app_modes.quick_design')
    model = importlib.import_module('sjtu_tpmshx.models.quick_design')
    monkeypatch.setattr(preparation, 'tpms_geometry', lambda *a, **kw: {
        'epsilon': .6, 'epsilon_A': .3, 'A_0': 1000., 'D_h': .002})
    def forbidden(*args, **kwargs):
        pytest.fail('invalid water state reached the drag calculation')
    monkeypatch.setattr(model, '_dp_one', forbidden)
    suffix = 'h' if side == 'hot' else 'c'
    case = replace(_case(), **{side + '_fluid': 'water',
                              'T_in_' + suffix: 350., 'P_in_' + suffix: 10000.})
    with pytest.raises(fluid_props.WaterStateError, match='quick-design properties'):
        prepare_quick_design(case, 'Diamond', 7., .5, .084, .05, case_id='invalid-water')


@pytest.mark.parametrize('cold_outlet', [350., 500.])
def test_mean_pass_checks_representative_water_state(monkeypatch, cold_outlet):
    preparation = importlib.import_module('sjtu_tpmshx.preprocess.app_modes.quick_design')
    model = importlib.import_module('sjtu_tpmshx.models.quick_design')
    execution = importlib.import_module('sjtu_tpmshx.solvers.backends.python.quick_design.execution')
    monkeypatch.setattr(preparation, 'tpms_geometry', lambda *a, **kw: {
        'epsilon': .6, 'epsilon_A': .3, 'A_0': 1000., 'D_h': .002})
    monkeypatch.setattr(model, '_dp_one', lambda *a, **kw: 100.)
    calls = []
    def thermal(*args, **kwargs):
        if calls and cold_outlet == 500.:
            pytest.fail('unsupported representative water state reached the second solve')
        calls.append(args)
        shape = tuple(args[3:6])
        return (*(np.full(shape, value) for value in (550., cold_outlet, 450.)),
                {'converged': True})
    monkeypatch.setattr(execution, 'solve_full_domain_3d', thermal)
    prepared = prepare_quick_design(_case(), 'Diamond', 7., .5, .084, .05,
                                    case_id='mean-water', prop_model='mean')
    if cold_outlet == 500.:
        # The full first-pass field fails before mean-property evaluation.
        with pytest.raises(fluid_props.QuickDesignWaterFieldError,
                           match='T=500 K, P_abs=200000 Pa'):
            run_case(prepared)
        assert len(calls) == 1
    else:
        result = run_case(prepared)
        assert len(calls) == len(result.run_status['passes']) == 2
        assert result.run_status['converged'] is True


@pytest.mark.parametrize('side', ['hot', 'cold'])
@pytest.mark.parametrize('prop_model,bad_pass', [('const', 1), ('mean', 1), ('mean', 2)])
def test_local_water_hotspot_fails_before_reuse_or_return(monkeypatch, side, prop_model, bad_pass):
    preparation = importlib.import_module('sjtu_tpmshx.preprocess.app_modes.quick_design')
    model = importlib.import_module('sjtu_tpmshx.models.quick_design')
    execution = importlib.import_module('sjtu_tpmshx.solvers.backends.python.quick_design.execution')
    monkeypatch.setattr(preparation, 'tpms_geometry', lambda *a, **kw: {
        'epsilon': .6, 'epsilon_A': .3, 'A_0': 1000., 'D_h': .002})
    monkeypatch.setattr(model, '_dp_one', lambda *a, **kw: 100.)
    case = (_case() if side == 'cold' else
            replace(_case(), hot_fluid='water', T_in_h=360., P_in_h=200000.,
                    cold_fluid='air', T_in_c=300.))
    calls = []
    def thermal(*args, **kwargs):
        calls.append(args)
        shape = tuple(args[3:6])
        fields = tuple(np.full(shape, value) for value in (340., 330., 335.))
        if len(calls) == bad_pass:
            fields[0 if side == 'hot' else 1][0, 0, 0] = 500.
        return (*fields, {'converged': True})
    monkeypatch.setattr(execution, 'solve_full_domain_3d', thermal)
    prepared = prepare_quick_design(case, 'Diamond', 7., .5, .084, .05,
                                    case_id='local-hotspot', prop_model=prop_model)
    with pytest.raises(fluid_props.QuickDesignWaterFieldError,
                       match=r'thermal return .*index=\(0, 0, 0\), T=500 K'):
        run_case(prepared)
    assert len(calls) == bad_pass


@pytest.mark.parametrize('side', ['hot', 'cold'])
def test_invalid_external_water_field_never_reaches_thermal(monkeypatch, side):
    preparation = importlib.import_module('sjtu_tpmshx.preprocess.app_modes.quick_design')
    model = importlib.import_module('sjtu_tpmshx.models.quick_design')
    execution = importlib.import_module('sjtu_tpmshx.solvers.backends.python.quick_design.execution')
    monkeypatch.setattr(preparation, 'tpms_geometry', lambda *a, **kw: {
        'epsilon': .6, 'epsilon_A': .3, 'A_0': 1000., 'D_h': .002})
    monkeypatch.setattr(model, '_dp_one', lambda *a, **kw: 100.)
    monkeypatch.setattr(execution, 'solve_full_domain_3d',
                        lambda *a, **kw: pytest.fail('invalid water warm start reached thermal solve'))
    case = (_case() if side == 'cold' else
            replace(_case(), hot_fluid='water', T_in_h=360., P_in_h=200000.,
                    cold_fluid='air', T_in_c=300.))
    prepared = prepare_quick_design(case, 'Diamond', 7., .5, .084, .05, case_id='warm-water')
    shape = tuple(len(prepared.grid['d' + axis]) for axis in 'xyz')
    seed = tuple(np.full(shape, value) for value in (340., 330., 335.))
    seed[0 if side == 'hot' else 1][0, 0, 0] = 500.
    prepared = replace(prepared, parameters={**prepared.parameters, 'initial_fields': seed})
    with pytest.raises(fluid_props.QuickDesignWaterFieldError, match='design external warm start'):
        run_case(prepared)


def test_persisted_input_water_failure_is_not_a_candidate_field_failure(monkeypatch):
    preparation = importlib.import_module('sjtu_tpmshx.preprocess.app_modes.quick_design')
    model = importlib.import_module('sjtu_tpmshx.models.quick_design')
    execution = importlib.import_module('sjtu_tpmshx.solvers.backends.python.quick_design.execution')
    monkeypatch.setattr(preparation, 'tpms_geometry', lambda *a, **kw: {
        'epsilon': .6, 'epsilon_A': .3, 'A_0': 1000., 'D_h': .002})
    monkeypatch.setattr(model, '_dp_one', lambda *a, **kw: 100.)
    monkeypatch.setattr(execution, 'solve_full_domain_3d',
                        lambda *a, **kw: pytest.fail('invalid inlet reached thermal solve'))
    prepared = prepare_quick_design(_case(), 'Diamond', 7., .5, .084, .05, case_id='persisted-water')
    op = {**prepared.parameters['operating_point'], 'P_in_c': 10000., 'T_in_c': 350.}
    prepared = replace(prepared, parameters={**prepared.parameters, 'operating_point': op})
    with pytest.raises(fluid_props.WaterStateError, match='design inlet B') as caught:
        run_case(prepared)
    assert type(caught.value) is fluid_props.WaterStateError


@pytest.mark.parametrize('mdot,prop_model', [(.5, 'const'), (.2, 'const'), (.2, 'mean')])
def test_real_water_hotspot_is_rejected_even_before_mean_property_pass(mdot, prop_model):
    from sjtu_tpmshx.design.forward import forward
    # Observed regression: at mdot=.5 the outlet mean was only 360.73 K,
    # while one local water cell reached 393.95 K at the inlet 0.2 MPa.
    case = replace(_case(), mdot_c=mdot)
    with pytest.raises(fluid_props.QuickDesignWaterFieldError,
                       match=r'design-inlet-pass thermal return B: water index=.*P_abs=200000 Pa'):
        forward(case, 'Diamond', 7., .5, .084, .05, 'cross', prop_model=prop_model)


def test_previously_feasible_real_sizing_dimensions_leave_liquid_water():
    from sjtu_tpmshx.design.forward import forward
    case = replace(_case(), mdot_c=.2, Q=70000., dPlim_h=.05)
    # This exact design previously passed convergence, duty, dP and Re checks.
    with pytest.raises(fluid_props.QuickDesignWaterFieldError,
                       match='design-inlet-pass thermal return B'):
        forward(case, 'Diamond', 7., .5, .06929800158, .04815439363, 'cross')
