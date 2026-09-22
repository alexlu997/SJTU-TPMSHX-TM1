"""The standalone A-side demo must not request the GUI's absent B fields."""
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from sjtu_tpmshx.runs.demos import demo_vis_3d_interactive as demo


@pytest.mark.parametrize('off_screen', [False, True])
def test_demo_field_cycle_and_export_use_only_supplied_fields(monkeypatch, tmp_path, off_screen):
    values = np.arange(8, dtype=float).reshape(2, 2, 2)
    widths = np.full(2, 0.01)
    grid = demo.build_data_grid(2, 2, 2, widths, widths, widths,
                                300 + values, values, 101325 + values, 4 + values)
    plotter = Mock(plane_widgets=[])
    plotter.add_mesh_slice.side_effect = lambda mesh, **kw: mesh[kw['scalars']]
    events = {}
    plotter.add_key_event.side_effect = events.__setitem__
    expected = ['Ta', 'vmag', 'P_kPa', 'L_mm']

    def interact():
        for _ in expected:
            events['s']()
            events['c']()
            events['f']()
        events['1']()
        events['2']()
        events['3']()
        events['r']()

    plotter.show.side_effect = interact
    monkeypatch.setattr(demo.pv, 'Plotter', lambda **_: plotter)
    demo.launch_interactive(grid, off_screen=off_screen, out_dir=tmp_path)
    rendered = [call.kwargs['scalars'] for call in plotter.add_mesh_slice.call_args_list]
    assert set(rendered) == set(expected)
    exports = {Path(call.args[0]).name for call in plotter.screenshot.call_args_list}
    if off_screen:
        assert exports == {f'preview_{field}_{axis}_{mode}.png'
                           for field, axis, mode in product(expected, 'xyz', ['global', 'local'])}
        plotter.close.assert_called_once()
    else:
        assert exports == {f'slice_{field}_x_{mode}.png'
                           for field, mode in zip(expected, ['global', 'local'] * 2)}
        assert rendered[0] == rendered[8] == 'Ta'  # wraps through all four fields
    assert {'Tb', 'Ts', 'vmag_B', 'P_B_kPa'} <= set(demo.FIELD_ORDER)
    np.testing.assert_allclose(grid['P_kPa'], (101325 + grid['vmag']) / 1000)


def test_demo_main_adds_pressure_reference_before_display(monkeypatch):
    widths = np.full(2, 0.01)
    gauge = np.arange(8, dtype=float).reshape(2, 2, 2)
    flow = SimpleNamespace(P=gauge, P_ref_abs=180000,
                           u=np.zeros((3, 2, 2)), v=np.zeros((2, 3, 2)),
                           w=np.zeros((2, 2, 3)))
    temperature = np.full((2, 2, 2), 300.)
    monkeypatch.setattr(demo.sys, 'argv', ['demo', '--test'])
    monkeypatch.setattr(demo, 'run_case_8_fields', lambda **_: (
        flow, temperature, widths, widths, widths, 2, 2, 2, 10, 300))
    monkeypatch.setattr(demo, 'build_demo_zoning_field', lambda *_: np.full((2, 2, 2), 6.))
    launch = Mock()
    monkeypatch.setattr(demo, 'launch_interactive', launch)
    assert demo.main() == 0
    grid = launch.call_args.args[0]
    np.testing.assert_allclose(grid['P_kPa'].min(), 180.)
    np.testing.assert_allclose(grid['P_kPa'].max(), 180.007)
