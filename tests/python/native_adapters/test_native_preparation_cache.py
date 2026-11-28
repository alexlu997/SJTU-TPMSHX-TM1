"""Exercise the inlet cache through the model and stage interfaces."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
import warnings

import pytest

from tm1.data_types.compute_config import Sco2NuConfig
from tm1.physical_models.tpms_calc import compute
from tm1.preprocess import api
from tm1.preprocess.preparation import PreparationObservers
from tm1.run_control.run_warnings import range_observations, warning_scope
from tests.python.native_preparation_abi import _configuration_mass_flow


def test_inlet_selection_keys_preserve_the_complete_source():
    compute.cache_clear()
    args = ('Gyroid', 7., .5, 6., 380., 200000., 16.)
    default = Sco2NuConfig()
    selections = (None, default, replace(default, alpha_D=1.), replace(default, alpha_G=1.),
                  replace(default, parameter_version='甲'), replace(default, source='甲'),
                  replace(default, source='甲\x00乙'), replace(default, applicability='甲'),
                  replace(default, mode='experimental', alpha_D=1., alpha_G=1.,
                          parameter_version='v1', source='CFD', applicability='test'))
    with warning_scope({}):
        for selection in selections:
            for flag in (False, True):
                first = compute(*args, sco2_nu=selection, co2_geometry=flag)
                again = compute(*args, sco2_nu=selection, co2_geometry=flag)
                assert first == again
    count = 2 * len(selections)
    assert compute.cache_info() == (count, count, 4096, count)


def test_overlapping_cold_inlets_bind_evidence_to_each_run():
    config = _configuration_mass_flow(pair=('air', 'air'))
    config.fluid_B = replace(config.fluid_A)
    config.fluid_A.u_mps = config.fluid_B.u_mps = .001
    barrier = Barrier(2)

    def prepare(k_s, concurrent=False):
        geometry = replace(config.geometry, k_s_W_mK=k_s)
        with warning_scope({}) as records:
            if concurrent:
                barrier.wait()
            case = api.prepare_case(replace(config, geometry=geometry), case_id='inlets')
            return case.parameters['static_properties'], range_observations(records)

    serial = {}
    for material in (13., 27.):
        compute.cache_clear()
        serial[material] = prepare(material)
    compute.cache_clear()
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [(k_s, pool.submit(prepare, k_s, True)) for k_s in serial]
        for k_s, job in jobs:
            values, observations = job.result()
            assert values == serial[k_s][0]
            assert observations == serial[k_s][1]
            sides = {item['side'] for item in observations if item['stage'] == 'inlet'}
            assert sides == {'A', 'B'}


def test_notice_observer_uses_the_current_scope():
    observers = PreparationObservers()
    message = 'Gyroid inlet notice'
    with pytest.warns(UserWarning, match=message):
        observers.observe_notice(0, 0, 99., message)
    with warning_scope({}) as records, warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter('always')
        observers.observe_notice(0, 0, 99., message)
        observers.observe_notice(1, 1, 0., 'preflight')
        observers.observe_notice(2, 0, 0., 'geometry')
        observers.observe_notice(2, 1, 0., 'geometry')
        assert not captured
        assert records[('nu_preflight', 'B')] == 'preflight'
        assert observers.extrap_reasons == ['geometry', 'geometry']
