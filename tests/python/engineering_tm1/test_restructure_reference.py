"""The reference comparator reports one decoded difference for each affected case."""
import warnings
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest

from engineering.scripts.restructure_reference import (
    CASES, check_extensions, compare, configuration, difference, exact, legacy_difference, read, record_case, save,
)


def test_first_difference_per_case(tmp_path, capsys):
    old = tmp_path / 'old'
    new = tmp_path / 'new'
    for folder, zero, messages in ((old, 0., ['first', 'second']), (new, -0., ['second', 'first'])):
        folder.mkdir()
        cases = {'stage': {'prepared': {'T': np.array([[1., zero]])}, 'field': zero},
                 'control': [4, True, b'\x00\xff']}
        with record_case(cases, {}, 'emitted') as output:
            output['status'] = 'completed'
            for message in messages:
                warnings.warn(message, RuntimeWarning, stacklevel=2)
        save(folder, {'native': {}, 'botorch_kernel': {'path': folder.name}, 'cases': exact(cases)})
    assert not compare(old, old)
    capsys.readouterr()
    assert compare(old, new)
    report = capsys.readouterr().out
    assert "BoTorch kernel: {'path': 'old'} -> {'path': 'new'}" in report
    assert 'stage.prepared.T(0, 1): 0x0.0p+0 != -0x0.0p+0' in report
    assert 'stage.field' not in report
    assert "python_warnings[0]: 'RuntimeWarning: first' != 'RuntimeWarning: second'" in report
    assert 'control: equal' in report


@pytest.mark.parametrize('name', ['air-2d', 'handoff-2d', 'handoff-3d'])
def test_legacy_projection_keeps_original_field_and_performance(name):
    old = dict(field=dict(metadata={'original': -0.}), performance={'Q': 5.})
    new = deepcopy(old)
    new['field']['metadata'].update(diagnostic_records=[], effective_settings={'version': 'effective_settings_v1'})
    def compare_case():
        return legacy_difference(name, old, deepcopy(new), {'air-2d'}, ('field', 'settings'))
    assert compare_case() is None
    new['performance']['other'] = []
    assert 'performance.other: added' in compare_case()
    new['performance'].pop('other')
    new['field']['metadata']['original'] = 0.
    assert '.field.metadata.original:' in compare_case()
    new['field']['metadata']['original'] = -0.
    new['field']['metadata'].pop('diagnostic_records')
    assert 'diagnostic_records: required addition missing' in compare_case()
    if name.startswith('handoff'):
        new['field']['metadata']['diagnostic_records'] = []
        new['prepared'] = {'metadata': {'diagnostic_records': []}}
        assert '.prepared: added' in compare_case()


def test_design_projection_only_accepts_original_rows_and_conditions():
    row = dict(reason='pre-existing reason', percase=[{'warnings': []}])
    old = dict(best=deepcopy(row), rows=[row])
    candidate = deepcopy(old)
    for item in [candidate['best'], *candidate['rows']]:
        item.update(code=None, details=[])
        item['percase'][0].update(acceptance_records=[], warning_records=[])
    def check():
        return legacy_difference('quick-design', old, deepcopy(candidate), (), ('design',))
    assert check() is None
    candidate['rows'][0]['percase'].append({'warning_records': []})
    assert 'percase: length' in check()
    candidate['rows'][0]['percase'].pop()
    candidate['best']['reason'] = 'changed'
    assert '.best.reason:' in check()


def test_owner_rejection_keeps_measured_pressure_and_original_text():
    from tm1.preprocess.api import prepare_case
    spec = read(CASES)
    cfg = configuration(spec, spec['stages'][spec['rejected']['case']])
    cfg.fluid_A.P_in_Pa = spec['rejected']['P_in_Pa']
    with pytest.raises(ValueError) as caught:
        prepare_case(cfg, case_id='rejected')
    record = caught.value.diagnostic
    assert type(caught.value) is ValueError
    assert str(caught.value) == 'sCO2 fluid A pressure must be 7.9..16 MPa'
    assert record == dict(code='input.invalid', message=str(caught.value),
                          details=dict(field='fluid_A.P_in_Pa', side='A', P_abs_Pa=7e6, bounds_Pa=(7.9e6, 16e6)))


@pytest.mark.parametrize('stage', ['case', 'result'])
def test_extension_tree_survives_hdf5_and_strict_json(tmp_path, stage):
    from tm1.file_io.case_io import load_case, save_case
    from tm1.file_io.result_io import load_result, save_result
    from tests.python.io_tm1.io_support import sample_case
    from tests.python.postprocess_tm1.test_conservative_energy_results import result_fixture
    source, write, restore = ((sample_case(), save_case, load_case) if stage == 'case'
                              else (result_fixture(2), save_result, load_result))
    array = np.array([0., -0., np.nan, -np.inf], dtype=np.float64).reshape(2, 2)
    metadata = dict(source.metadata, diagnostic_records=({'code': 'input.invalid', 'message': '测量',
                    'details': {'field': 'T_K', 'samples_K': array, 'reason': 'measured'}},))
    source = replace(source, metadata=metadata)
    path = tmp_path / ('case.yaml' if stage == 'case' else 'field.h5')
    write(source, path)
    received = restore(path)
    check_extensions(source.metadata, received.metadata, ('diagnostic_records',))
    assert isinstance(received.metadata['diagnostic_records'], tuple)
    assert difference((array,), [array], 'type')
    assert difference(array, array.astype('f4'), 'dtype')
    assert difference(array, array.ravel(), 'shape')
    assert difference(array, np.abs(array), 'bytes')
