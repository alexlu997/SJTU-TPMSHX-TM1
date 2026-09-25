"""Quick-design scalar water states; geometry and thermal solves are stubbed."""
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
        # Existing mean model evaluates (320 + 500)/2 K at the inlet 0.2 MPa.
        with pytest.raises(fluid_props.WaterStateError, match='T=410 K, P_abs=200000 Pa'):
            run_case(prepared)
        assert len(calls) == 1
    else:
        result = run_case(prepared)
        assert len(calls) == len(result.run_status['passes']) == 2
        assert result.run_status['converged'] is True
