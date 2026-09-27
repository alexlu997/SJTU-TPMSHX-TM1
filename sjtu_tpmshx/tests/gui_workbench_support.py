"""Function-scoped workbench window and shared recorded-field sample."""
import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_result import ComputeResult

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture
def win(tmp_path, monkeypatch):
    from sjtu_tpmshx.controllers.session_manager import SessionManager
    from sjtu_tpmshx.main import Main_Menu

    original_init = SessionManager.__init__

    def local_session(self, base_dir=None, parent=None):
        original_init(self, base_dir=base_dir or tmp_path, parent=parent)

    monkeypatch.setattr(SessionManager, '__init__', local_session)
    window = Main_Menu()
    window.showNormal()
    window.resize(1300, 760)
    QApplication.processEvents()
    yield window
    window.close()
    QApplication.processEvents()


def _result(mode):
    shape = (4, 3, 3) if mode == '3d' else (4, 3)
    raw = np.arange(np.prod(shape), dtype=float).reshape(shape)
    fields = dict(Ta=raw + 350., Tb=raw + 300., Ts=raw + 320.,
                  P_fA=raw + 120000., P_fB=raw + 110000.,
                  ucA=raw + 1., vcA=raw + 2., ucB=raw + 3., vcB=raw + 4.,
                  N_x=4, N_y=3, L=.04, H=.03, dir_A=0, dir_B=3,
                  dx_arr=np.full(4, .01), dy_arr=np.full(3, .01))
    if mode == '3d':
        fields.update(wcA=raw + 5., wcB=raw + 6.,
                      vmag_A=np.sqrt(fields['ucA']**2 + fields['vcA']**2 + (raw + 5.)**2),
                      vmag_B=np.sqrt(fields['ucB']**2 + fields['vcB']**2 + (raw + 6.)**2),
                      dx=fields['dx_arr'], dy=fields['dy_arr'],
                      dz=np.array([.001, .002, .007]),
                      Lx=.04, Ly=.03, Lz=.01, L_mm=np.full(shape, 7.))
    return ComputeResult(Q_W=20., dP_A_Pa=10., dP_B_Pa=8.,
                         diagnostics={'mode': mode}, fields=fields)
