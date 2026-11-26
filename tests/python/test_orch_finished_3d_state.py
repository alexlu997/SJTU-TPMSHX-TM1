"""Keep the accepted 3D result when the field or volume display is unavailable."""
import pytest

from sjtu_tpmshx.data_types.compute_result import ComputeResult
from tests.python.gui_worker_support import win as win


@pytest.mark.parametrize('render_result', [True, False, RuntimeError("PyVista context lost")],
                         ids=['slices-ready', 'no-slices', 'renderer-error'])
def test_3d_field_delivery_keeps_the_result_and_defers_the_volume(win, monkeypatch, render_result):
    def draw(window, field):
        if isinstance(render_result, RuntimeError):
            raise render_result
        return render_result

    monkeypatch.setattr('sjtu_tpmshx.applications.gui.ui.plot_2d_results.ensure_result_plot', draw)
    result = ComputeResult(Q_W=100., dP_A_Pa=50., diagnostics={'mode': '3d'})
    success = win.results.present(result, mode='3d', provenance=None, elapsed=1.)
    assert success is (render_result is True)
    assert win.workbench.rendered_slices is success
    assert not win.workbench.volume_ready
    assert win.cache.get_result('3d').Q_W == 100.
    assert win.btn_export.isEnabled()
