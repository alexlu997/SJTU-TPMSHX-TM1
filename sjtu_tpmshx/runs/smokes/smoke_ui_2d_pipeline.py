"""Run a real 2D GUI compute offscreen with isolated user state.

Verifies current result fields and temperature plotting after worker publication.
Run from the repository root with ``python -m
sjtu_tpmshx.runs.smokes.smoke_ui_2d_pipeline``. This is a wiring smoke, not a
mesh-independence or experimental-accuracy check.
"""
import time

import numpy as np

from sjtu_tpmshx.runs import _smoke_boot
from sjtu_tpmshx.runs.smokes.smoke_ui_offscreen import _smoke_window


def main():
    _smoke_boot.patch_modals()
    with _smoke_window() as (app, win):
        win.combo_dim.setCurrentIndex(0)
        win.combo_grid.setCurrentIndex(win.combo_grid.findData(False))
        win.le_Nx.setText('16'); win.le_Ny.setText('24')
        win.auto_fill_fluid_a(); win.auto_fill_fluid_b()
        app.processEvents()
        print('[1/3] autofill OK', flush=True)

        win.run_calculation()
        assert win.compute.is_running(), 'orchestrator did not start'
        print('[2/3] compute started (Pipeline2D worker)', flush=True)
        t0 = time.monotonic()
        while win.compute.is_running() and time.monotonic() - t0 < 600:
            app.processEvents(); time.sleep(0.05)
        app.processEvents()
        assert not win.compute.is_running(), '2D smoke timed out'
        assert win._compute_error is None, f'worker error: {win._compute_error}'

        result = win.cache.get_result('2d')
        assert result and result.get('Ta') is not None, 'no results written'
        shape = (result['N_x'], result['N_y'])
        for name in ('Ta', 'Tb', 'Ts'):
            values = result[name]
            assert values.shape == shape and np.isfinite(values).all(), name
        assert result['Q_total'] > 0, f"non-physical Q_total {result['Q_total']!r}"
        assert 'temp' in win.cache.get_drawn_tabs() and win.canvas_temp._hover_data
        summary = (f"[3/3] PASS in {time.monotonic()-t0:.0f}s — "
                   f"Q={result['Q_total']:.1f} W/m  dP_A={result['dP_A']:.0f} Pa  "
                   f"dP_B={result['dP_B']:.0f} Pa  Ta{shape}")
    print(summary, flush=True)


if __name__ == '__main__':
    main()
