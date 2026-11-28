"""Mapping tests for installed names, native status codes, and typed records."""
import errno
import ctypes as ct
import json
import os
import subprocess
import sys

import numpy as np
import pytest

from tm1.cpp_interface._native_diagnostics import native_code, native_error
from tm1.cpp_interface.result_evaluation import _result_error
from tm1.physical_models import envelope, fluid_props
from tm1.run_control import diagnostics
from tm1.run_control.cancellation import CancelledError


def test_catalog_and_generated_sdk_header():
    subprocess.run([sys.executable, '-m', 'engineering.scripts.generate_diagnostic_codes', '--check'], check=True)
    catalog = diagnostics.diagnostic_catalog()
    assert catalog['version'] == 1
    for family in catalog['native_operations'].values():
        for cases in ('status', 'cause', 'kind', 'stop'):
            for code in family.get(cases, {}).values():
                if code is not None:
                    assert catalog['codes'][code]['class'] == 'error'


def test_public_class_identity():
    assert fluid_props.WaterStateError is diagnostics.WaterStateError
    assert fluid_props.QuickDesignWaterFieldError is diagnostics.QuickDesignWaterFieldError
    assert issubclass(diagnostics.QuickDesignWaterFieldError, diagnostics.WaterStateError)
    assert envelope.ChokedFlowError is diagnostics.ChokedFlowError


@pytest.mark.parametrize('image,operation,status,extra,code,cls', [
    ('geometry', 'tpmshx_geometry_counts_v1', 2, {}, 'numeric.zero_division', ZeroDivisionError),
    ('geometry', 'tpmshx_field_clip_v1', 2, {}, 'native.allocation', MemoryError),
    ('solver', 'tpmshx_run_saved_case_2d_v5', 4, {}, 'flow.choked', diagnostics.ChokedFlowError),
    ('solver', 'tpmshx_run_saved_case_2d_v5', 8, {}, 'df.velocity_outside_application', ValueError),
    ('solver', 'tpmshx_run_saved_case_3d_v3', 0, {'stop': 2}, 'run.cancelled', CancelledError),
    ('solver', 'tpmshx_run_quick_design_v2', 3, {}, 'quick.water_field', diagnostics.QuickDesignWaterFieldError),
    ('solver', 'tpmshx_run_quick_design_v2', 6, {}, 'run.cancelled', CancelledError),
    ('solver', 'tpmshx_solve_quick_design_v1', 6, {}, 'contract.unknown_status', RuntimeError),
    ('solver', 'tpmshx_solve_quick_design_v1', 0, {'stop': 2}, 'run.cancelled', CancelledError),
    ('preparation', 'tpmshx_prepare_quick_design_v3', 2, {}, 'native.allocation', MemoryError),
    ('preparation', 'tpmshx_prepare_quick_design_v3', 4, {}, 'contract.unknown_status', RuntimeError),
    ('preparation', 'tpmshx_prepare_quick_design_v3', 20, {}, 'contract.unknown_status', RuntimeError),
    ('preparation', 'tpmshx_preparation_2d_uniform_prepare_case_v1', 3, {'kind': 4},
     'capability.unsupported', NotImplementedError),
    ('result', 'tpmshx_result_stage_query_v3', 4, {'cause': 97}, 'contract.unknown_status', RuntimeError),
])
def test_native_identity_selects_type_independently_of_text(image, operation, status, extra, code, cls):
    failure = native_error(image, operation, status, '原始消息', **extra)
    assert type(failure) is cls
    assert failure.args == ('原始消息',)
    assert failure.diagnostic['code'] == code
    details = failure.diagnostic['details']
    assert (details['operation'], details['status']) == (operation, status)
    assert all(details[name] == value for name, value in extra.items())


def test_budget_stop_and_operation_specific_overflow():
    assert native_code('solver', 'tpmshx_solve_quick_design_v1', 0, stop=1) is None
    assert native_code('solver', 'tpmshx_run_saved_case_3d_v3', 0, stop=1) is None
    result = _result_error(4, 2, b'overflow message')
    property_error = native_error('preparation', 'tpmshx_preparation_water_pt_v1', 3, 'different text', cause=2)
    assert type(result) is type(property_error) is OverflowError
    assert result.args == ('overflow message',)
    assert property_error.args == (errno.ERANGE, os.strerror(errno.ERANGE))


@pytest.mark.parametrize('status,outer_kind,outer_type,code,second_kind,second_type,second_code', [
    (3, 2, diagnostics.WaterStateError, 'fluid.water_state', 4, NotImplementedError, 'capability.unsupported'),
    (2, 2, MemoryError, 'native.allocation', 2, diagnostics.WaterStateError, 'fluid.water_state'),
    (2, 5, MemoryError, 'native.allocation', 2, diagnostics.WaterStateError, 'fluid.water_state'),
])
def test_preparation_failure_copies_ordered_causes(
        status, outer_kind, outer_type, code, second_kind, second_type, second_code):
    from tm1.cpp_interface import _native_preparation_case as wire, preparation_host
    failure = wire._Failure(kind=outer_kind, side=1, cause_count=2)
    for item, kind, message in zip(failure.causes, (1, second_kind), (b'first', b'second'), strict=True):
        item.kind, item.message = kind, message
    with pytest.raises(outer_type) as caught:
        preparation_host._check_status('tpmshx_preparation_2d_uniform_prepare_case_v1', status,
                                       ct.create_string_buffer(b'outer'), failure, diagnostics.WaterStateError,
                                       chi_error=ValueError('invalid chi'))
    failure.causes[0].message = b'released'
    outer = caught.value
    assert type(outer) is outer_type and outer.diagnostic['code'] == code
    assert outer.diagnostic['details']['side'] == 'B'
    assert type(outer.__cause__) is ValueError
    assert outer.__cause__.args == ('first',)
    assert type(outer.__cause__.__cause__) is second_type
    assert [(row['code'], row['message'], row['details']['status']) for row in outer.diagnostic['details']['causes']] == [
        ('stage.invalid_input', 'first', status), (second_code, 'second', status)]


@pytest.mark.parametrize('status,kind', [(99, 2), (1, 0)])
def test_unknown_preparation_identity_keeps_raw_status_and_kind(status, kind):
    from tm1.cpp_interface import _native_preparation_case as wire, preparation_host
    with pytest.raises(RuntimeError) as caught:
        preparation_host._check_status('tpmshx_preparation_2d_uniform_prepare_case_v1', status,
                                       ct.create_string_buffer(b'error'), wire._Failure(kind=kind),
                                       diagnostics.WaterStateError)
    record = caught.value.diagnostic
    assert type(caught.value) is RuntimeError and caught.value.args == ('error',)
    assert record['code'] == 'contract.unknown_status'
    assert (record['details']['status'], record['details']['kind']) == (status, kind)


def test_result_unknown_numerical_cause_keeps_public_message():
    problem = _result_error(4, 8, b'buffer text')
    assert type(problem) is RuntimeError
    assert problem.args == ('native result stage returned an invalid numerical cause',)
    assert problem.diagnostic['code'] == 'contract.unknown_status'
    assert problem.diagnostic['details']['cause'] == 8


def test_record_copies_ordered_samples_and_uses_strict_json():
    samples = np.array([-0., np.nan, np.inf, -np.inf])
    row = diagnostics.diagnostic_record('input.invalid', 'bad input', {'field': 'T', 'samples_K': samples})
    samples[:] = 42.
    values = row['details']['samples_K']
    assert isinstance(values, tuple)
    assert np.signbit(values[0])
    assert json.loads(json.dumps(row, allow_nan=False))['details']['samples_K'] == [-0., 'NaN', 'Infinity', '-Infinity']
    with pytest.raises(ValueError, match='requires field'):
        diagnostics.diagnostic_record('input.invalid', '', {})
    with pytest.raises(TypeError, match='requires string'):
        diagnostics.diagnostic_record('input.invalid', '', {'field': 17})
