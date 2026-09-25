"""Current validation outputs and gates retain their physical/data contracts."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from sjtu_tpmshx.validation.cases import audit_3d_conservation as audit


def test_production_conservation_import_keeps_warning_policy_and_avoids_audit():
    import subprocess
    import sys
    from sjtu_tpmshx.postprocess.conservation import compute_phase2a

    assert audit.compute_phase2a is compute_phase2a
    subprocess.run([sys.executable, '-c', '''
import sys, warnings
import numpy
import sjtu_tpmshx.postprocess
before = warnings.filters[:]
from sjtu_tpmshx.postprocess.conservation import compute_phase2a
assert warnings.filters == before
assert not any(name.startswith(('sjtu_tpmshx.solvers', 'sjtu_tpmshx.validation'))
               for name in sys.modules)
'''], check=True)


def _certificate_result(active_b=True):
    boundary = dict(physical_external_inward_W=-40., inlet_diffusion_inward_W=40.)
    return dict(
        Ta=np.ones((2, 2, 2)), _audit_fB={} if active_b else None,
        eps_A_strict=.001, eps_A_strict_cellmax=.002,
        eps_B_strict=.001 if active_b else None,
        eps_B_strict_cellmax=.002 if active_b else None,
        Q_sA=-100. if active_b else 0., Q_sB=100. if active_b else 0.,
        h_vB_field=np.ones((2, 2, 2)) if active_b else np.zeros((2, 2, 2)),
        model_h_balance=dict(physical_boundary_complete=True,
                             sides={'A': boundary, 'B': boundary}),
    )


@pytest.mark.parametrize('key', ['eps_A_strict', 'eps_A_strict_cellmax',
                                'eps_B_strict', 'eps_B_strict_cellmax'])
@pytest.mark.parametrize('value', [None, np.nan, np.inf, .01, .05, -.001])
def test_current_conservation_gate_rejects_missing_nonfinite_and_failed_certificates(key, value):
    result = _certificate_result()
    result[key] = value
    certificate = audit.compute_phase2a(result)
    assert not all(ok for _, ok in certificate['gates'])


@pytest.mark.parametrize('active_b', [False, True])
def test_current_conservation_report_uses_full_cv_certificate(active_b):
    result = _certificate_result(active_b)
    if not active_b:
        result['model_h_balance'] = None  # T5 capacity-temperature path.
    # Retired interior-source diagnostics have no current gate semantics.
    result.update(Q_sA_interior=1e9, Q_sB_interior=-1e9)
    certificate = audit.compute_phase2a(result)
    cell = dict(net_out_total=0., net_out_abs=0., spurious_enthalpy_W=0.,
                net_out_max_cell=0., net_out_p99=0.)
    report, passed = audit.render_case('T1', result, certificate, dict(A=cell, B=None))
    assert passed
    assert 'strict global < 1 %' in report and 'strict cellmax < 1 %' in report
    assert 'half-cell inlet diffusion' in report
    if not active_b:
        assert certificate['sides']['B'] is None and 'N/A (disabled)' in report
        assert 'capacity-temperature path' in report
        result['h_vB_field'][0, 0, 0] = 1.
        assert not all(ok for _, ok in audit.compute_phase2a(result)['gates'])


@pytest.mark.parametrize('damage', ['boundary', 'source', 'missing_ledger'])
def test_current_conservation_requires_complete_boundary_and_source_balance(damage):
    result = _certificate_result()
    if damage == 'boundary':
        result['model_h_balance']['physical_boundary_complete'] = False
    elif damage == 'source':
        result['Q_sB'] *= .9
    else:
        del result['model_h_balance']
        with pytest.raises(KeyError):
            audit.compute_phase2a(result)
        return
    assert not all(ok for _, ok in audit.compute_phase2a(result)['gates'])


@pytest.mark.parametrize('damage', ['global', 'cellmax', 'missing'])
def test_failed_current_certificate_controls_cli_exit(monkeypatch, tmp_path, damage):
    result = _certificate_result()
    result['solver_converged'] = True
    if damage == 'missing':
        result.pop('eps_A_strict')
    else:
        result['eps_A_strict' + ('_cellmax' if damage == 'cellmax' else '')] = .02
    cell = dict(net_out_total=0., net_out_abs=0., spurious_enthalpy_W=0.,
                net_out_max_cell=0., net_out_p99=0.)
    monkeypatch.setattr(audit, '_run_3d_stack', lambda cfg: result)
    monkeypatch.setattr(audit, 'compute_phase2c_h3', lambda res: dict(A=cell, B=None))
    for name in ('compute_phase3', 'compute_phase4', 'compute_phase5'):
        monkeypatch.setattr(audit, name, lambda res: None)
    report = tmp_path / 'audit.md'
    monkeypatch.setattr('sys.argv', ['audit', '--cases', 'T1', '--out', str(report)])
    assert audit.main() == 1
    assert '**FAIL**' in report.read_text()


def test_grid_sweep_keeps_every_failed_certificate_member(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, '_run_3d_stack', lambda cfg: dict(solver_converged=True))
    report = tmp_path / 'audit.md'
    monkeypatch.setattr('sys.argv', ['audit', '--cases', 'T1', '--phase6_grid_convergence',
                                   '--out', str(report)])
    assert audit.main() == 1
    output = report.read_text()
    for grid in (12, 20, 30):
        assert f'error_g{grid}' in output and f"'certificate_pass_g{grid}': False" in output


def test_lumped_outputs_are_separate_attributable_and_do_not_touch_data(monkeypatch, tmp_path):
    from sjtu_tpmshx.validation.cases import validate_shanghai_lumped_dual_nu as lumped
    from sjtu_tpmshx.validation.harness import _harness, _provenance

    source = pd.DataFrame(np.zeros((16, 32)))
    for col, value in {5: .05, 7: .03, 24: 25., 25: 50., 28: 150.,
                       29: 100., 30: 1e5}.items():
        source.iloc[:, col] = value
    monkeypatch.setattr(_harness, 'load_cases_df', lambda *a: source)
    monkeypatch.setattr(_provenance, 'REPO_ROOT', tmp_path / 'package')
    for _ in range(2):
        lumped.main([])
    files = sorted((tmp_path / '.cache/validation').glob('*/shanghai_lumped_dual_nu.csv'))
    assert len(files) == 2
    for path in files:
        frame, metadata = _provenance.read_csv_with_provenance(path)
        assert len(frame) == 16 and frame['case'].tolist() == list(range(1, 17))
        assert (frame['Q_pred_xf'] > 0).all() and (frame['Q_pred_cf'] > 0).all()
        assert metadata['script'].endswith('validate_shanghai_lumped_dual_nu.py')
        assert metadata['rows'] == 16 and metadata['date']
    assert not (tmp_path / 'data').exists()
    with pytest.raises(SystemExit) as stopped:
        lumped.main(['--out-dir', str(_provenance.REFERENCE_DIR)])
    assert stopped.value.code == 2


def test_sou_benchmark_reports_physical_face_pressure(monkeypatch):
    from sjtu_tpmshx.runs import benchmark_sou_3d as benchmark
    from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D

    widths = np.array([.1, .2, .4, .3])
    centres = np.cumsum(widths) - .5 * widths
    state = SimpleNamespace(P=(1234. - 700. * centres)[None, :, None],
                            inlet_frac=np.ones((1, 1)), outlet_frac=np.ones((1, 1)),
                            dx=np.ones(1), dy=widths, dz=np.ones(1),
                            solve=lambda **kw: (True, 3))
    class Solver:
        extract_dP_face_extrap = staticmethod(SIMPLESolver3D.extract_dP_face_extrap)

        def __new__(cls, **kwargs):
            return state

    monkeypatch.setattr(benchmark, 'SIMPLESolver3D', Solver)
    conv, iterations, _, pressure = benchmark.run(1, 4, 1, True)
    assert conv and iterations == 3
    assert pressure == pytest.approx(700.)
