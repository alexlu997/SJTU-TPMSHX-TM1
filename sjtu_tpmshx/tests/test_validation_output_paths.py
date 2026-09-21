"""Validation output isolation; numerical work is stubbed, reference data retained."""
import importlib
import sys

import numpy as np
import pandas as pd
import pytest

from sjtu_tpmshx.validation.harness import _provenance as provenance


DRIVERS = [
    ('mms_phase_a3_h_refine', ['--cases', '1d', '--grids', '4,8,30'],
     ['mms_phase_a3_h_refine.csv', 'mms_phase_a3_orders.csv', 'mms_phase_a3_report.md']),
    ('mms_phase_a4_boundary', ['--grids', '4,8,30'],
     ['mms_phase_a4_boundary.csv', 'mms_phase_a4_orders.csv']),
    ('mms_phase_b4_order', [], ['mms_phase_b4_orders.csv']),
    ('phase_c_gci', [], ['phase_c_gci.csv', 'phase_c_gci_summary.csv',
                        'phase_c_f2_tol_sweep.csv']),
]


def _fake_mms(case, *, Nx, Ny, Nz, **kwargs):
    error = 1 / Nx**2
    exact = np.ones((Nx, Ny, Nz))
    result = dict(outer_iters=1, last_chg=error, converged=True)
    for phase, field in [('A', 'Ta'), ('B', 'Tb'), ('s', 'Ts')]:
        result.update({f'L2_{phase}': error, f'Linf_{phase}': error,
                       f'{field}_num': exact + error, f'{field}_exact': exact})
    return result


@pytest.mark.parametrize('name,args,filenames', DRIVERS)
def test_default_driver_runs_write_separately(monkeypatch, tmp_path, name, args, filenames):
    module = importlib.import_module(f'sjtu_tpmshx.validation.cases.{name}')
    monkeypatch.setattr(provenance, 'REPO_ROOT', tmp_path / 'package')
    references = {p: p.read_bytes() for p in provenance.REFERENCE_DIR.glob('*.csv')}
    if name == 'phase_c_gci':
        monkeypatch.setattr(module, 'run_c1', lambda cid, **kw:
                            ([{'case': cid, 'Q_enth_A': 1.0}], {'GCI_g20_pct': 6.0}))
        monkeypatch.setattr(module, 'run_c3_tol', lambda *a, **kw:
                            [{'Q_enth_A': 1.0}, {'Q_enth_A': 1.0}])
    else:
        monkeypatch.setattr(module, 'run_mms', _fake_mms)
    monkeypatch.setattr(sys, 'argv', [name, *args])
    for _ in range(2):
        result = module.main()
        if name == 'phase_c_gci':
            assert result == 1  # output changes must not hide the existing 5% gate
    run_dirs = list((tmp_path / '.cache' / 'validation').iterdir())
    assert len(run_dirs) == 2
    for run_dir in run_dirs:
        assert all((run_dir / filename).is_file() for filename in filenames)
        for csv_path in run_dir.glob('*.csv'):
            assert not pd.read_csv(csv_path, comment='#').empty
    assert all(path.read_bytes() == content for path, content in references.items())


@pytest.mark.parametrize('name,option,reference', [
    ('mms_phase_a3_h_refine', '--out_csv', 'mms_phase_a3_h_refine.csv'),
    ('mms_phase_a3_h_refine', '--orders_csv', 'mms_phase_a3_orders.csv'),
    ('mms_phase_a3_h_refine', '--report', 'mms_phase_a3_orders.csv'),
    ('mms_phase_a4_boundary', '--out_csv', 'mms_phase_a4_boundary.csv'),
    ('mms_phase_a4_boundary', '--orders_csv', 'mms_phase_a4_orders.csv'),
    ('mms_phase_b4_order', '--out_csv', 'mms_phase_b4_orders.csv'),
    ('phase_c_gci', '--out-dir', ''),
])
def test_explicit_reference_destination_rejected_before_solve(
        monkeypatch, capsys, name, option, reference):
    module = importlib.import_module(f'sjtu_tpmshx.validation.cases.{name}')

    def forbidden(*args, **kwargs):
        pytest.fail('Solver called before rejecting reference output')

    monkeypatch.setattr(module, 'run_c1' if name == 'phase_c_gci' else 'run_mms', forbidden)
    path = provenance.REFERENCE_DIR / reference
    monkeypatch.setattr(sys, 'argv', [name, option, str(path)])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    assert 'reference directory is read-only' in capsys.readouterr().err


def test_shared_writer_rejects_reference_symlink(tmp_path):
    reference = provenance.REFERENCE_DIR / 'mms_phase_a3_orders.csv'
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
