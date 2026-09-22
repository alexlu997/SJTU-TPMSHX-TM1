"""Run a real 3D GUI compute offscreen with isolated user state.

Checks the published ComputeResult and lazily rendered temperature, pressure
and velocity slices. The native PyVista volume panel is unavailable offscreen;
its absence must not discard fields used for plotting or export. This is a
wiring smoke, not native 3D or physical-accuracy qualification.
"""
import time

import numpy as np

from sjtu_tpmshx.runs import _smoke_boot
from sjtu_tpmshx.runs.smokes.smoke_ui_offscreen import _smoke_window


def main():
    _smoke_boot.patch_modals()
    with _smoke_window() as (app, win):
        win.combo_dim.setCurrentIndex(1)
        win.combo_grid.setCurrentIndex(win.combo_grid.findData(False))
        win.le_Nx.setText('12'); win.le_Ny.setText('10'); win.le_Nz.setText('4')
        win.auto_fill_fluid_a(); win.auto_fill_fluid_b()
        app.processEvents()
        print('[1/3] autofill OK', flush=True)

        win.run_calculation()
        assert win.compute.is_running(), 'orchestrator did not start'
        print('[2/3] compute started (Pipeline3D worker)', flush=True)
        t0 = time.monotonic()
        while win.compute.is_running() and time.monotonic() - t0 < 900:
            app.processEvents(); time.sleep(0.05)
        app.processEvents()
        assert not win.compute.is_running(), '3D smoke timed out'
        assert win._compute_error is None, f'worker error: {win._compute_error}'
        res = win.cache.get_result('3d')
        assert res is not None, 'ComputeResult was not retained after publication'
        assert res.diagnostics.get('mode') == '3d'
        fields = res.fields
        needed = {'Ta', 'Tb', 'Ts', 'vmag_A', 'vmag_B', 'P_fA', 'P_fB',
                  'L_mm', 'dx', 'dy', 'dz', 'Lx', 'Ly', 'Lz',
                  'dir_A', 'dir_B', 'ucA', 'vcA', 'wcA'}
        missing = needed - set(fields)
        assert not missing, f'ComputeResult.fields missing: {sorted(missing)}'
        for name in ('Ta', 'Tb', 'Ts'):
            assert fields[name].ndim == 3 and np.isfinite(fields[name]).all(), name
        assert 'u_A_in_mps' in res.props and 'T_in_A_K' in res.props
        from sjtu_tpmshx.ui.plot_2d_results import ensure_result_plot
        for name in ('temp', 'pres', 'vel'):
            assert ensure_result_plot(win, name), f'{name} slice failed'
            assert name in win.cache.get_drawn_tabs()
            assert getattr(win, 'canvas_' + name)._hover_data
        assert win.cache.get_result('3d') is res, 'slice rendering replaced the export source'
        summary = (f"[3/3] PASS in {time.monotonic()-t0:.0f}s — "
                   f"Q={res.Q_W:.1f} W  dP_A={res.dP_A_Pa:.0f} Pa  "
                   f"Ta{fields['Ta'].shape}  extrap={bool(res.extrap_reasons)}")
    print(summary, flush=True)


if __name__ == '__main__':
    main()
