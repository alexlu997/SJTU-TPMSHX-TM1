"""Quick stage observations match independent typed Python expressions."""
import ctypes as ct
from dataclasses import replace
import os
from pathlib import Path

import numpy as np
import pytest

from sjtu_tpmshx.development.tests.native.result_reference import api as reference
from sjtu_tpmshx.development.tests.native.test_result_metrics import (
    assert_observation, observe, quick_result,
)
from sjtu_tpmshx.development.tests.result_stage_fixture import thaw
from sjtu_tpmshx.postprocess import api as native
from sjtu_tpmshx.shared import _native_result as wire
from sjtu_tpmshx.shared.domain.metric_spec import MetricSpec
from sjtu_tpmshx.shared.io.result_io import load_result


def observed_evaluation(function, result, spec):
    value = function(result, spec)
    return dict(source_result_id=value.source_result_id,
        metrics={name: dict(value=row.value, status=row.status, reason=row.reason,
            spec=vars(row.spec)) for name, row in value.metrics.items()},
        qualification=thaw(value.qualification))


def compare(result, name, *, policy='warn'):
    unit = 'W' if name in ('Q', 'Q_cold') else 'Pa' if name.startswith('dP') else 'K' if name.startswith('T_out') else 'kg/s' if name.startswith('mass_flow') else '1'
    spec = MetricSpec(name, unit, 'three_module_v1', 'selected Quick evidence')
    expected = observe(observed_evaluation, reference.evaluate, result, spec, policy=policy)
    actual = observe(observed_evaluation, native.evaluate, result, spec, policy=policy)
    assert_observation(actual, expected)


@pytest.mark.parametrize('name,changes', [
    ('Q', dict(mass=2**53 + 1, cp=2**53 + 1)),
    ('Q', dict(mass=2**600, cp=2**600, inlet=300.)),
    ('Q', dict(mass=0, inlet=2**1100)),
    ('dP_A', dict(pin=2**1100 + 1, pout=2**1100)),
    ('dP_A', dict(pin=(1 << 63)-1, pout=-3)),
    ('Re_A', dict(rho=2**600, speed=2**600, mu=2**1200)),
    ('Re_A', dict(rho=2**53 + 1, speed=2**53 + 1)),
    ('Re_A', dict(rho=2**53 + 1, speed=1, mu=2**53 + 2)),
    ('Re_A', dict(rho=1., speed=-(1 << 63))),
    ('Re_A', dict(rho=np.ones(2), speed=-(1 << 63))),
    ('Re_A', dict(rho=np.array(1.1, dtype=np.float16), speed=np.array(.3, dtype=np.float16),
                  diameter=np.array(.1, dtype=np.float16), mu=np.array(.7, dtype=np.float16))),
    ('Re_A', dict(rho=np.int64(3), speed=np.int64(2), diameter=np.int64(4), mu=np.int64(3))),
    ('Re_A', dict(rho=np.float64(1.1), speed=np.float64(.3), mu=np.float64(.7))),
    ('mass_flow_A', dict(mass='3.125')),
    ('mass_flow_A', dict(mass=2**1100)),
])
def test_exact_integer_and_scalar_boundaries(name, changes):
    compare(quick_result(**changes), name)


@pytest.mark.parametrize('size', [0, 1, 2])
@pytest.mark.parametrize('dtype', [np.bool_, np.int8, np.uint64, np.float16, np.float32, '>f4'])
@pytest.mark.parametrize('role,name', [('mass', 'Q'), ('cp', 'Q'), ('inlet', 'Q'),
    ('rho', 'Re_A'), ('speed', 'Re_A'), ('diameter', 'Re_A'), ('mu', 'Re_A'),
    ('pressure', 'dP_A'), ('mass', 'energy_imbalance_rel')])
def test_typed_array_operands(size, dtype, role, name):
    values = np.linspace(1., 2., size).astype(dtype)
    changes = dict(pin=values, pout=values) if role == 'pressure' else {role: values}
    result = quick_result(**changes)
    if name == 'energy_imbalance_rel':
        result = replace(result, boundary_fluxes={**result.boundary_fluxes,
            'B': dict(mass_flow_kg_s=1., cp_J_kgK=1., inlet_temperature_K=301., velocity_m_s=1.)})
    compare(result, name)


@pytest.mark.parametrize('policy', ['warn', 'raise', 'ignore'])
@pytest.mark.parametrize('name', ['Q', 'Re_A'])
def test_earlier_fp_event_precedes_later_shape_error(policy, name):
    changes = (dict(inlet=np.full(3, -65504., dtype=np.float16),
                    mass=np.ones(2, dtype=np.float16), cp=np.ones(2, dtype=np.float16))
               if name == 'Q' else dict(rho=np.full(2, 1e308), speed=np.full(2, 1e308),
                                        diameter=np.ones(3)))
    compare(quick_result(**changes), name, policy=policy)


@pytest.mark.parametrize('policy', ['warn', 'raise', 'ignore'])
@pytest.mark.parametrize('size', [0, 1, 2])
def test_weak_cast_precedes_empty_array_iteration(policy, size):
    compare(quick_result(rho=1e308, speed=np.ones(size, dtype=np.float16)), 'Re_A', policy=policy)


@pytest.mark.parametrize('policy', ['warn', 'raise', 'ignore'])
def test_earlier_reynolds_operation_precedes_missing_diameter(policy):
    result = quick_result(rho=np.full(2, 1e308), speed=np.full(2, 1e308))
    result = replace(result, metadata={**result.metadata, 'parameters': {'arrangement': 'counter'}})
    compare(result, 'Re_A', policy=policy)


@pytest.mark.parametrize('shape', [(), (2,), (2, 2), (0, 2, 1), (1, 0, 1), (1, 1, 0), (1, 2, 1, 2)])
@pytest.mark.parametrize('name', ['T_out_A', 'T_out_B'])
def test_original_outlet_index_and_empty_mean_protocol(shape, name):
    result = quick_result()
    result = replace(result, fields={**result.fields, 'Ta' if name.endswith('A') else 'Tb': np.ones(shape)})
    compare(result, name)


@pytest.mark.parametrize('role,name', [('mass', 'Q'), ('cp', 'Q'), ('inlet', 'Q'),
    ('rho', 'Re_A'), ('speed', 'Re_A'), ('diameter', 'Re_A'), ('mu', 'Re_A'), ('pin', 'dP_A')])
@pytest.mark.parametrize('value', [None, '3', (), (1, 2)])
def test_portable_object_protocols_stay_at_the_original_operation(role, name, value):
    compare(quick_result(**{role: value}), name)


@pytest.mark.parametrize('key,value,name', [
    ('model', None, 'Q'), ('model', 3, 'Re_A'), ('model', np.array([1, 2]), 'Q'),
    ('parameters', None, 'T_out_B'), ('parameters', (), 'Re_A'),
    ('properties', None, 'Re_A'), ('properties', (), 'Re_A'),
])
def test_malformed_records_keep_the_first_consumed_error(key, value, name):
    result = quick_result()
    compare(replace(result, metadata={**result.metadata, key: value}), name)


def test_selected_spec_identity_and_missing_qualification_are_retained():
    result = quick_result()
    spec = MetricSpec('dP_A', 'Pa', 'three_module_v1', 'caller-owned definition')
    value = native.evaluate(result, spec)
    assert value.metrics['dP_A'].spec is spec
    assert value.source_result_id == result.result_id
    assert value.qualification['physical']['status'] == 'unverified'
    assert value.qualification['optimization']['status'] != 'passed'


@pytest.mark.parametrize('shape', [(), (1,)])
@pytest.mark.parametrize('policy', ['warn', 'raise', 'ignore'])
def test_half_precision_maximum_keeps_its_comparison_cast_policy(shape, policy):
    result = quick_result(mass=np.ones(shape, dtype=np.float16))
    result = replace(result, boundary_fluxes={**result.boundary_fluxes,
        'B': dict(mass_flow_kg_s=1., cp_J_kgK=1., inlet_temperature_K=301., velocity_m_s=1.)})
    compare(result, 'energy_imbalance_rel', policy=policy)


@pytest.mark.parametrize('dtype', [np.bool_, np.int8, np.uint64, np.float16, np.float32, '>f4'])
@pytest.mark.parametrize('name', ['Q', 'Re_A'])
@pytest.mark.parametrize('shape', [(), (1,), (2,)])
def test_typed_chains_keep_intermediate_rounding(dtype, name, shape):
    values = np.full(shape, 2, dtype=dtype)
    changes = (dict(mass=values, cp=values) if name == 'Q'
               else dict(rho=values, speed=values, diameter=values, mu=values))
    compare(quick_result(**changes), name)


@pytest.mark.parametrize('case', ['cross-const', 'cross-mean', 'counter-const'])
def test_frozen_quick_public_reports(case):
    root = os.environ.get('TPMSHX_RESULT_STAGE_FROZEN_DIR')
    if not root:
        pytest.skip('set TPMSHX_RESULT_STAGE_FROZEN_DIR to use the frozen Quick solves')
    result = load_result(Path(root) / f'quick-design-{case}/results.h5')
    expected = observe(observed_evaluation, reference.evaluate, result, None)
    actual = observe(observed_evaluation, native.evaluate, result, None)
    assert_observation(actual, expected)
    metrics = reference.evaluate(result).metrics
    for name, args in [('evaluate_applicability', (result,)),
                       ('evaluate_physical_balance', (result,)),
                       ('evaluate_qualification', (result, metrics))]:
        expected = observe(lambda: thaw(getattr(reference, name)(*args)))
        actual = observe(lambda: thaw(getattr(native, name)(*args)))
        assert_observation(actual, expected)


@pytest.mark.parametrize('execution', [None, (), {'version': 'historical', 'sides': None},
    {'version': 9, 'sides': ()}, {'version': 'full_execution_v1', 'sides': None},
    {'version': 'full_execution_v1', 'sides': ()}])
@pytest.mark.parametrize('early_overflow', [False, True])
def test_execution_metadata_keeps_its_original_consumption_point(execution, early_overflow):
    result = quick_result(**({'inlet': 2**1100} if early_overflow else {}))
    result = replace(result, metadata={**result.metadata, 'execution_record': execution})
    compare(result, 'Q')


@pytest.mark.parametrize('dtype,values', [(np.float16, (1.1, .3, .1, .7)),
    (np.int8, (100, 2, 2, 3))])
def test_one_element_chain_exposes_rounding_and_integer_wrap(dtype, values):
    rho, speed, diameter, mu = (np.asarray([value], dtype=dtype) for value in values)
    compare(quick_result(rho=rho, speed=speed, diameter=diameter, mu=mu), 'Re_A')


@pytest.mark.parametrize('dtype,values', [(np.float16, (1.1, .3, .1, .7)),
    (np.int8, (100, 2, 2, 3)), (np.float32, (1.1, .3, .1, .7))])
@pytest.mark.parametrize('size', [1, 2])
def test_published_quick_field_abi_keeps_each_typed_intermediate(dtype, values, size):
    rho, speed, diameter, mu = (np.full(size, value, dtype=dtype) for value in values)

    def reference_chain():
        flow = rho * abs(speed)
        numerator = flow * diameter
        return flow, numerator, numerator / mu

    expected = observe(reference_chain)
    assert expected[0][0] == 'value'
    templates = expected[0][1]

    def native_chain():
        outputs = []
        first = rho
        pointer = ct.POINTER(wire._Array)
        for name, second, template in zip(('quick_reynolds_flow_field', 'quick_reynolds_length_field',
                                           'quick_reynolds_quotient_field'), (speed, diameter, mu), templates):
            output = np.empty_like(template)
            a, b, target = wire.array(first), wire.array(second), wire.array(output)
            wire.call('tpmshx_result_' + name + '_v1', [pointer, pointer, pointer],
                ct.byref(a.raw), ct.byref(b.raw), ct.byref(target.raw))
            outputs.append(output)
            first = output
        return tuple(outputs)

    assert_observation(observe(native_chain), expected)

