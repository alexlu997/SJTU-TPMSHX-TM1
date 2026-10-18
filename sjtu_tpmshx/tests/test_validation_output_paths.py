"""Validation output isolation; numerical work is stubbed, reference data retained."""
import importlib
import sys

import pandas as pd
import pytest

from sjtu_tpmshx.validation.harness import _provenance as provenance


DRIVERS = [
    ('phase_c_gci', [], ['phase_c_gci.csv', 'phase_c_gci_summary.csv',
                        'phase_c_f2_tol_sweep.csv']),
]


@pytest.mark.parametrize('name,args,filenames', DRIVERS)
def test_default_driver_runs_write_separately(monkeypatch, tmp_path, name, args, filenames):
    module = importlib.import_module(f'sjtu_tpmshx.validation.cases.{name}')
    monkeypatch.setattr(provenance, 'REPO_ROOT', tmp_path / 'package')
    references = {p: p.read_bytes() for p in provenance.REFERENCE_DIR.glob('*.csv')}
    monkeypatch.setattr(module, 'run_c1', lambda cid, **kw:
                        ([{'case': cid, 'Q_enth_A': 1.0}],
                         {'GCI_g20_pct': 6.0, 'all_grids_converged': True}))
    monkeypatch.setattr(module, 'run_c3_tol', lambda *a, **kw:
                        [{'Q_enth_A': 1.0, 'converged': True}] * 3)
    monkeypatch.setattr(sys, 'argv', [name, *args])
    for _ in range(2):
        result = module.main()
        assert result == 1  # The existing 5% GCI gate still applies.
    run_dirs = list((tmp_path / '.cache' / 'validation').iterdir())
    assert len(run_dirs) == 2
    for run_dir in run_dirs:
        assert all((run_dir / filename).is_file() for filename in filenames)
        for csv_path in run_dir.glob('*.csv'):
            assert not pd.read_csv(csv_path, comment='#').empty
    assert all(path.read_bytes() == content for path, content in references.items())


@pytest.mark.parametrize('name,option,reference', [('phase_c_gci', '--out-dir', '')])
def test_explicit_reference_destination_rejected_before_solve(
        monkeypatch, capsys, name, option, reference):
    module = importlib.import_module(f'sjtu_tpmshx.validation.cases.{name}')

    def forbidden(*args, **kwargs):
        pytest.fail('Solver called before rejecting reference output')

    monkeypatch.setattr(module, 'run_c1', forbidden)
    path = provenance.REFERENCE_DIR / reference
    monkeypatch.setattr(sys, 'argv', [name, option, str(path)])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    assert 'reference directory is read-only' in capsys.readouterr().err


def test_shared_writer_rejects_reference_symlink(tmp_path):
    reference = provenance.REFERENCE_DIR / 'phase_c_gci.csv'
    content = reference.read_bytes()
    link = tmp_path / 'new.csv'
    link.symlink_to(reference)
    with pytest.raises(ValueError, match='reference directory is read-only'):
        provenance.write_csv_with_provenance(pd.DataFrame({'x': [1]}), link, __file__)
    assert reference.read_bytes() == content








def test_gci_rejects_retired_case_before_starting_any_case(monkeypatch, capsys):
    from sjtu_tpmshx.validation.cases import phase_c_gci

    def forbidden(*args, **kwargs):
        pytest.fail('Started a case before rejecting the retired case list')

    monkeypatch.setattr(phase_c_gci, 'run_c1', forbidden)
    monkeypatch.setattr(sys, 'argv', ['phase_c_gci', '--cases', 'T2,T4_H8'])
    with pytest.raises(SystemExit) as exc:
        phase_c_gci.main()
    assert exc.value.code == 2
    assert 'T4_H8 used retired experimental corrections' in capsys.readouterr().err
