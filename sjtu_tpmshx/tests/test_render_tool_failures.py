"""Render/smoke process status, using spies instead of a native GL context."""
from types import SimpleNamespace

import numpy as np
import pytest


def test_smoke_solver_failure_restores_environment_and_fails(monkeypatch):
    from sjtu_tpmshx.runs.smokes import smoke_ui_3d_modes as smoke
    monkeypatch.setenv('TPMSHX_ROUGH_MODE', 'original')
    monkeypatch.delenv('TPMSHX_ROUGH_EPS_UM', raising=False)
    monkeypatch.setattr(smoke, '_run_3d_stack', lambda cfg: (_ for _ in ()).throw(RuntimeError('solve failed')))
    assert smoke.main() == 1
    assert smoke.os.environ['TPMSHX_ROUGH_MODE'] == 'original'
    assert 'TPMSHX_ROUGH_EPS_UM' not in smoke.os.environ


def test_smoke_nonfinite_result_is_failure(monkeypatch):
    from sjtu_tpmshx.runs.smokes import smoke_ui_3d_modes as smoke
    monkeypatch.setattr(smoke, '_run_3d_stack', lambda cfg: dict(Q_total=np.nan, dP_A=1., dP_B=1.))
    assert smoke.run_with_mode('test', 'baseline') is None


def test_demo_render_failure_controls_exit(monkeypatch):
    from sjtu_tpmshx.runs.demos import demo_3d_cube_volume as demo
    monkeypatch.setattr(demo, '_run_3d_stack', lambda cfg: {})
    monkeypatch.setattr(demo, 'make_grid', lambda res: object())
    monkeypatch.setattr(demo.os, 'makedirs', lambda *a, **kw: None)
    monkeypatch.setattr(demo, 'render_volume', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('render failed')))
    monkeypatch.setattr(demo, 'render_triple_slice', lambda *a, **kw: None)
    monkeypatch.setattr(demo, 'render_iso', lambda *a, **kw: None)
    assert demo.main() == 1


@pytest.mark.parametrize('fails', [False, True])
def test_html_plotter_is_closed_after_success_and_failure(monkeypatch, fails):
    from sjtu_tpmshx.runs.tools import render_3d_styles as styles
    closed = []

    def export(*args):
        if fails:
            raise RuntimeError('HTML unavailable')

    plotter = SimpleNamespace(add_mesh=lambda *a, **kw: None,
                              add_text=lambda *a, **kw: None,
                              view_isometric=lambda: None, export_html=export,
                              close=lambda: closed.append(True))
    monkeypatch.setattr(styles.pv, 'Plotter', lambda **kw: plotter)

    class Grid:
        center = (0., 0., 0.)

        def __getitem__(self, key):
            return np.array([1., 2.])

        def slice(self, **kwargs):
            return self

        def outline(self):
            return self

    assert styles.render_html(Grid(), 'Ta', 'Title', 'unused') is (not fails)
    assert closed == [True]
