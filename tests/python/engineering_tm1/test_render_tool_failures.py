"""Render/smoke process status, using spies instead of a native GL context."""
from types import SimpleNamespace

import numpy as np


def test_smoke_solver_failure_restores_environment_and_fails(monkeypatch):
    from tm1.development.runs.smokes import smoke_ui_3d_modes as smoke
    monkeypatch.setenv('TPMSHX_ROUGH_MODE', 'original')
    monkeypatch.delenv('TPMSHX_ROUGH_EPS_UM', raising=False)
    monkeypatch.setattr(smoke, 'run_case', lambda cfg: (_ for _ in ()).throw(RuntimeError('solve failed')))
    assert smoke.main() == 1
    assert smoke.os.environ['TPMSHX_ROUGH_MODE'] == 'original'
    assert 'TPMSHX_ROUGH_EPS_UM' not in smoke.os.environ


def test_smoke_nonfinite_result_is_failure(monkeypatch):
    from tm1.development.runs.smokes import smoke_ui_3d_modes as smoke
    monkeypatch.setattr(smoke, 'run_case', lambda case: SimpleNamespace(metadata={'diagnostics': dict(Q_total=np.nan, dP_A=1., dP_B=1.)}))
    assert smoke.run_with_mode('test', 'baseline') is None
