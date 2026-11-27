"""The reference comparator reports one decoded difference for each affected case."""
import warnings

import numpy as np

from engineering.scripts.restructure_reference import compare, exact, record_case, save


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
        save(folder, {'native': {}, 'cases': exact(cases)})
    assert not compare(old, old)
    capsys.readouterr()
    assert compare(old, new)
    report = capsys.readouterr().out
    assert 'stage.prepared.T(0, 1): 0x0.0p+0 != -0x0.0p+0' in report
    assert 'stage.field' not in report
    assert "python_warnings[0]: 'RuntimeWarning: first' != 'RuntimeWarning: second'" in report
    assert 'control: equal' in report
