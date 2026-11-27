"""The reference comparator reports one decoded difference for each affected case."""
import numpy as np

from engineering.scripts.restructure_reference import compare, exact, save


def test_first_difference_per_case(tmp_path, capsys):
    old = tmp_path / 'old'
    new = tmp_path / 'new'
    for folder, zero, warnings in ((old, 0., ['first', 'second']), (new, -0., ['second', 'first'])):
        folder.mkdir()
        cases = {'field': {'T': np.array([[1., zero]]), 'later': zero},
                 'warnings': warnings, 'control': [4, True]}
        save(folder, {'native': {}, 'cases': exact(cases)})
    assert not compare(old, old)
    capsys.readouterr()
    assert compare(old, new)
    report = capsys.readouterr().out
    assert 'field.T(0, 1): 0x0.0p+0 != -0x0.0p+0' in report
    assert 'field.later' not in report
    assert "warnings[0]: 'first' != 'second'" in report
    assert 'control: equal' in report
