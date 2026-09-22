"""Validation must retain failed cases and return failure, without large solves."""
import sys

import numpy as np
import pandas as pd
import pytest

from sjtu_tpmshx.validation.cases import phase_c_gci as gci
from sjtu_tpmshx.validation.cases import audit_3d_conservation as audit
from sjtu_tpmshx.validation.cases import validate_shanghai_3d_real as shanghai
from sjtu_tpmshx.validation.harness._provenance import REFERENCE_DIR


def test_richardson_nonuniform_triplet_recovers_known_second_order():
    grids = np.array([12, 20, 30])
    table = gci._gci_table(grids, 1. + 1. / grids**2)
    assert table['order_obs'] == pytest.approx(2., abs=1e-9)
    assert table['Q_inf'] == pytest.approx(1., abs=1e-12)
    assert table['Q_finest'] != table['Q_inf']


@pytest.mark.parametrize('values', [[1., 2., 1.], [1., 1., 1.], [1., np.nan, 2.]])
def test_undetermined_order_does_not_assume_second_order(values):
    table = gci._gci_table([12, 20, 30], values)
    assert np.isnan(table['order_obs']) and np.isnan(table['Q_inf'])
    assert np.isnan(table['GCI_g20_pct'])


@pytest.mark.parametrize('values,converged', [([1., 1., 2.], True),
                                           ([1., 1., np.nan], True),
                                           ([1., 1., 1.], False)])
def test_gci_tolerance_failures_control_exit(tmp_path, monkeypatch, values, converged):
    monkeypatch.setattr(gci, 'run_c1', lambda case, **kw:
                        ([{'case': case}], dict(GCI_g20_pct=1., all_grids_converged=True)))
    monkeypatch.setattr(gci, 'run_c3_tol', lambda *a, **kw:
                        [dict(Q_enth_A=value, converged=converged) for value in values])
    monkeypatch.setattr(sys, 'argv', ['gci', '--cases', 'T2', '--out-dir', str(tmp_path)])
    assert gci.main() == 1


def _shanghai_row(index):
    return dict(case=index + 1, pressure_state_valid=1, pressure_clip_hits=0,
                converged=True, grid_nx=8, grid_ny=4, grid_nz=3,
                outer_converged=True, outer_iters=1, Q_net_rel=0., mass_rel_A=0.,
                dP_exp=100., dP_sim=101., Q_exp=100., Q_sim=101.,
                **{'err_dP%': 1., 'err_Q%': 1.})


@pytest.mark.parametrize('damage', ['nonfinite', 'invalid', 'unconverged', 'exception', 'none'])
def test_shanghai_failed_members_remain_in_separate_output(tmp_path, monkeypatch, damage):
    monkeypatch.setattr(shanghai, 'load_cases_df', lambda *a: pd.DataFrame([{}, {}]))

    def run(index, *args, **kw):
        row = _shanghai_row(index)
        if index == 1:
            if damage == 'nonfinite': row['err_Q%'] = np.nan
            if damage == 'invalid': row['pressure_state_valid'] = 0
            if damage == 'unconverged': row['converged'] = False
            if damage == 'exception': raise RuntimeError('injected solve failure')
        return row

    monkeypatch.setattr(shanghai, '_run_one_case_pipeline', run)
    code = shanghai.main(['--cases', '2', '--out-dir', str(tmp_path)])
    assert code == (0 if damage == 'none' else 1)
    rows = pd.read_csv(tmp_path / 'shanghai_3d_baseline.csv', comment='#')
    assert rows['case'].tolist() == [1, 2]
    if damage == 'exception': assert 'injected solve failure' in rows.loc[1, 'error']


@pytest.mark.parametrize('module,args', [(shanghai, ['--out-dir']), (audit, ['--out'])])
def test_tools_reject_reference_outputs_before_solve(monkeypatch, module, args):
    monkeypatch.setattr(sys, 'argv', ['tool', *args, str(REFERENCE_DIR / 'no-write')])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2


def test_t1_really_is_parallel_full_face():
    cfg = audit.make_T1(4)
    assert cfg['fluid_A_cfg']['dir'] == cfg['fluid_B_cfg']['dir'] == 0
    assert cfg['fluid_B_cfg']['in_w'] == cfg['H']


@pytest.mark.parametrize('reverse', [False, True])
def test_temperature_change_does_not_excuse_steady_mass_imbalance(reverse):
    v = np.full((2, 3, 2), -2. if reverse else 2.)
    v[:, 0 if reverse else -1, :] *= .9
    face = dict(u=np.zeros((3, 2, 2)), v=v, w=np.zeros((2, 2, 3)),
                rho=np.ones((2, 2, 2)), dx=np.ones(2), dy=np.ones(2), dz=np.ones(2),
                dir_real=1 if reverse else 0)
    result = audit.compute_phase4(dict(_audit_sA_face=face, _audit_T_inA=300., T_A_out=600.))
    assert result['A']['imbal_rel'] == pytest.approx(.1)
    assert result['A']['temperature_change_rel'] == 1.
    assert result['A']['m_in'] == 8.
    assert 'drift_expected' not in result['A']


def test_conservation_diagnostic_exception_controls_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, '_run_3d_stack', lambda cfg: dict(solver_converged=True))
    monkeypatch.setattr(audit, 'compute_phase2a_interior', lambda res: (_ for _ in ()).throw(RuntimeError('bad audit')))
    monkeypatch.setattr(audit, 'compute_phase2c_h3', lambda res: {})
    monkeypatch.setattr(audit, 'compute_phase3', lambda res: None)
    monkeypatch.setattr(audit, 'compute_phase4', lambda res: None)
    monkeypatch.setattr(audit, 'compute_phase5', lambda res: None)
    monkeypatch.setattr(audit, 'render_case', lambda *a: ('injected diagnostic failure', True))
    path = tmp_path / 'report.md'
    monkeypatch.setattr(sys, 'argv', ['audit', '--cases', 'T1', '--out', str(path)])
    assert audit.main() == 1
    assert 'injected diagnostic failure' in path.read_text()
