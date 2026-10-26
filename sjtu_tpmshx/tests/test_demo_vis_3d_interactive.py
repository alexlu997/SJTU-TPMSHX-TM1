"""The standalone viewer reads archived native fields without solving again."""
from dataclasses import replace
from itertools import product
from pathlib import Path
from unittest.mock import Mock
import sys

import numpy as np
import pytest

from sjtu_tpmshx.runs.demos import demo_vis_3d_interactive as demo
from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.io.result_io import save_result


@pytest.mark.parametrize('off_screen', [False, True])
def test_demo_field_cycle_and_export_use_only_supplied_fields(monkeypatch, tmp_path, off_screen):
    values = np.arange(8, dtype=float).reshape(2, 2, 2)
    widths = np.full(2, 0.01)
    grid = demo.build_data_grid(widths, widths, widths,
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
    assert plotter.show_bounds.call_args.kwargs['bounds'] == grid.bounds
    plotter.show_bounds.return_value.update_bounds.assert_called_with(grid.bounds)
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


def _sample_result(*, spatial=False, dimension=3):
    axes = tuple('xyz'[:dimension])
    grid = dict(dimension=dimension, length_unit='m', axis_order=axes)
    for axis, widths in zip(axes, ([0.01, 0.02], [0.015, 0.005], [0.008, 0.004])):
        grid['d' + axis] = np.array(widths)
        grid[axis + '_edges'] = np.r_[0., np.cumsum(widths)]
    shape = (2,) * dimension
    values = np.arange(2**dimension, dtype=float).reshape(shape)
    fields = dict(Ta=300. + values, P_report_A=180000. + values,
                  ucA=np.full(shape, 2.), vcA=np.full(shape, 3.), wcA=np.full(shape, 6.))
    metadata = {key: dict(unit='K' if key == 'Ta' else 'Pa' if key == 'P_report_A' else 'm/s',
                         axes=axes, location='cell', state='native') for key in fields}
    return FieldResult('view-result', 'view-case', 'fixture', grid=grid,
        fields=fields, field_metadata=metadata,
        boundary_fluxes={'report': {'A': {'direction': 0}}},
        run_status={'execution': 'completed', 'converged': False},
        metadata={'design_fields': {'L_field_m': .004 + (.0005 * values if spatial else np.zeros(shape))}})


@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('cube', [False, True])
def test_demo_main_reads_real_archive_fields_and_grid(monkeypatch, tmp_path, capsys, spatial, cube):
    result = _sample_result(spatial=spatial)
    path = tmp_path / 'result.h5'
    save_result(result, path)
    monkeypatch.setattr(sys, 'argv', ['demo', str(path), '--test'] + (['--cube'] if cube else []))
    launch = Mock()
    monkeypatch.setattr(demo, 'launch_interactive', launch)
    assert demo.main() == 0
    grid = launch.call_args.args[0]
    np.testing.assert_allclose(grid['P_kPa'].min(), 180.)
    np.testing.assert_allclose(grid['P_kPa'].max(), 180.007)
    np.testing.assert_allclose(grid['vmag'], 7.)  # all three archived velocity components
    np.testing.assert_allclose(grid['Ta'][[0, -1]], [300., 307.])
    np.testing.assert_allclose(grid['L_mm'][[0, -1]], [4., 7.5 if spatial else 4.])
    np.testing.assert_allclose(grid.x, np.array([0., 5., 20., 30.]) / (30. if cube else 1.))
    np.testing.assert_allclose(grid.y, np.array([0., 7.5, 17.5, 20.]) / (20. if cube else 1.))
    np.testing.assert_allclose(grid.z, np.array([0., 4., 10., 12.]) / (12. if cube else 1.))
    np.testing.assert_allclose(launch.call_args.kwargs['real_dims'], [.03, .02, .012])
    assert launch.call_args.kwargs['stretched'] is cube
    assert "'converged': False" in capsys.readouterr().out


@pytest.mark.parametrize('viewer', ['interactive', 'cube', 'four_panel'])
def test_viewer_grid_preserves_physical_linear_fields(viewer):
    import pyvista as pv
    from sjtu_tpmshx.ui.demo_vis_3d import build_pv_grid
    from sjtu_tpmshx.runs.demos.demo_3d_cube_volume import make_grid

    widths = [np.array(w) for w in ([.001, .009], [.002, .005, .001], [.004])]
    centres = [np.cumsum(w) - w / 2 for w in widths]
    x, y, z = np.meshgrid(*centres, indexing='ij')
    temperature = 300. + 200.*x - 300.*y + 400.*z
    if viewer == 'interactive':
        grid = demo.build_data_grid(*widths, temperature, temperature, temperature * 1000., temperature)
    elif viewer == 'cube':
        result = FieldResult('grid', 'case', 'fixture', grid=dict(zip(('dx', 'dy', 'dz'), widths)),
            fields={key: temperature * (1000. if key.startswith('P_') else 1.) for key in
                    ('Ta_display', 'Tb_display', 'Ts_display', 'vmag_A', 'P_fA_display')})
        grid = make_grid(result)
    else:
        grid = build_pv_grid(*widths)
        grid.point_data['Ta'] = np.pad(temperature, 1, mode='edge').ravel(order='F')
    unit = 1. if viewer == 'four_panel' else 1000.
    positions = np.array([[.0013, .0031, .002], [.004, .005, .002]])
    sample = pv.PolyData(positions * unit).sample(grid)
    assert sample['vtkValidPointMask'].all()
    np.testing.assert_allclose(sample['Ta'], 300. + 200.*positions[:, 0] - 300.*positions[:, 1]
                               + 400.*positions[:, 2], rtol=0., atol=1e-12)
    restored = grid['Ta'].reshape(grid.dimensions, order='F')[1:-1, 1:-1, 1:-1]
    np.testing.assert_array_equal(restored, temperature)


@pytest.mark.parametrize('invalid, message', [
    ('2d', '3D FieldResult'), ('missing_velocity', 'wcA'), ('missing_pressure', 'P_report_A'),
    ('missing_L', 'L_field_m'), ('scalar_L', 'cell field'), ('nonfinite', 'finite native field Ta')])
def test_viewer_rejects_archive_without_required_native_3d_fields(tmp_path, invalid, message):
    result = _sample_result(dimension=2 if invalid == '2d' else 3)
    if invalid.startswith('missing_') and invalid != 'missing_L':
        missing = 'wcA' if invalid == 'missing_velocity' else 'P_report_A'
        result = replace(result, fields={k: v for k, v in result.fields.items() if k != missing},
                         field_metadata={k: v for k, v in result.field_metadata.items() if k != missing})
    elif invalid in ('missing_L', 'scalar_L'):
        result = replace(result, metadata={'design_fields': {} if invalid == 'missing_L' else {'L_field_m': .004}})
    elif invalid == 'nonfinite':
        bad = np.array(result.fields['Ta'])
        bad[0, 0, 0] = np.nan
        result = replace(result, fields={**result.fields, 'Ta': bad})
    path = tmp_path / 'result.h5'
    save_result(result, path)
    with pytest.raises(ValueError, match=message):
        demo.load_visualization_result(path)
