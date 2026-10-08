"""Render recorded 3D FieldResult fields as a 2×2 PyVista panel.

Run from the repository root::

    python -m sjtu_tpmshx.ui.demo_vis_3d results.h5 --output .cache/demos/fields.png

The viewer uses the archive's physical grid, native A-side fields and actual
L design field. It does not run a solver or synthesize missing physics data.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pyvista as pv

from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.ui.theme import FIELD_CMAP


def load_visualization_result(path):
    """Read a 3D archive containing the native fields used by both viewers."""
    result = load_result(path)
    if result.grid['dimension'] != 3:
        raise ValueError('3D visualization requires a 3D FieldResult archive')
    required = ('Ta', 'ucA', 'vcA', 'wcA', 'P_report_A')
    missing = [name for name in required if name not in result.fields]
    if missing:
        raise ValueError('3D visualization requires native fields: ' + ', '.join(missing))
    for name in required:
        if not np.all(np.isfinite(result.fields[name])):
            raise ValueError(f'3D visualization requires finite native field {name}')
    design = result.metadata.get('design_fields', {})
    if 'L_field_m' not in design:
        raise ValueError('3D visualization requires recorded design_fields.L_field_m')
    lengths = np.asarray(design['L_field_m'])
    if lengths.shape != result.fields['Ta'].shape or not np.all(np.isfinite(lengths) & (lengths > 0)):
        raise ValueError('recorded L_field_m must be a positive finite cell field on the 3D grid')
    return result


def build_pv_grid(dx, dy, dz):
    """Build a physical PyVista grid from SI cell-width arrays."""
    edges = [np.r_[0., np.cumsum(widths)] for widths in (dx, dy, dz)]
    return pv.RectilinearGrid(*edges)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('result', type=Path, help='Saved 3D FieldResult HDF5 file.')
    ap.add_argument('--output', type=Path, default=Path('.cache/demos/fields.png'))
    args = ap.parse_args()
    result = load_visualization_result(args.result)
    widths = [result.grid['d' + axis] for axis in 'xyz']
    dimensions = np.array([np.sum(values) for values in widths])
    Ta = result.fields['Ta']
    velocity = np.stack([result.fields[name] for name in ('ucA', 'vcA', 'wcA')], axis=-1)
    speed = np.linalg.norm(velocity, axis=-1)
    L_field = result.metadata['design_fields']['L_field_m'] * 1000.
    direction = result.boundary_fluxes.get('report', {}).get('A', {}).get('direction')
    if direction not in range(6):
        raise ValueError('Streamline visualization requires the recorded A-side port direction (0–5)')
    print(f"Loaded {args.result}: grid={Ta.shape}, status={dict(result.run_status)}")

    grid_T = build_pv_grid(*widths)
    grid_T.cell_data['Ta'] = Ta.ravel(order='F')
    grid_V = build_pv_grid(*widths)
    grid_V.cell_data['velocity'] = velocity.reshape(-1, 3, order='F')
    grid_V.cell_data['vmag'] = speed.ravel(order='F')
    grid_Vp = grid_V.cell_data_to_point_data()
    grid_L = build_pv_grid(*widths)
    grid_L.cell_data['L_mm'] = L_field.ravel(order='F')

    pv.set_plot_theme('document')
    p = pv.Plotter(shape=(2, 2), window_size=(1600, 1200), off_screen=True,
                   border=True, border_color='lightgray')
    p.subplot(0, 0)
    centre = grid_T.center
    slices = grid_T.slice_orthogonal(x=centre[0], y=centre[1], z=centre[2])
    p.add_mesh(slices, scalars='Ta', cmap=FIELD_CMAP,
               scalar_bar_args={'title': 'T_a [K]'})
    p.add_mesh(grid_T.outline(), color='black')
    p.add_text('(a) T_a orthogonal slices', font_size=10, position='upper_edge')
    p.view_isometric()

    p.subplot(0, 1)
    axis = direction // 2
    inward = 1. if direction % 2 == 0 else -1.
    seed_centre = dimensions * 0.5
    seed_centre[axis] = dimensions[axis] * (0.02 if inward > 0 else 0.98)
    transverse = [i for i in range(3) if i != axis]
    # Map an x-normal seed into the physical inlet plane, keeping its two
    # transverse extents aligned with the archived grid axes.
    seed = pv.Plane(direction=(1, 0, 0), i_size=1., j_size=1.,
                    i_resolution=6, j_resolution=4)
    points = np.empty_like(seed.points)
    points[:, axis] = seed_centre[axis]
    points[:, transverse[0]] = seed_centre[transverse[0]] + seed.points[:, 1] * dimensions[transverse[0]] * 0.9
    points[:, transverse[1]] = seed_centre[transverse[1]] + seed.points[:, 2] * dimensions[transverse[1]] * 0.9
    seed.points = points
    streams = grid_Vp.streamlines_from_source(
        seed, vectors='velocity', max_length=float(dimensions[axis] * 2.),
        integration_direction='forward', max_steps=200)
    if streams.n_points > 0:
        p.add_mesh(streams.tube(radius=float(np.min(dimensions) * 0.015)),
                   scalars='vmag', cmap=FIELD_CMAP,
                   scalar_bar_args={'title': '|v| [m/s]'})
    p.add_mesh(grid_T.outline(), color='black')
    p.add_text('(b) Recorded velocity streamlines', font_size=10, position='upper_edge')
    p.view_isometric()

    p.subplot(1, 0)
    T_iso = float(0.5 * (Ta.min() + Ta.max()))
    if Ta.max() > Ta.min():
        iso = grid_T.cell_data_to_point_data().contour(isosurfaces=[T_iso], scalars='Ta')
        if iso.n_points > 0:
            p.add_mesh(iso, color='orangered', opacity=0.6, show_edges=False)
    p.add_mesh(grid_T.outline(), color='black')
    p.add_text(f'(c) T_a isosurface @ {T_iso:.0f} K', font_size=10, position='upper_edge')
    p.view_isometric()

    p.subplot(1, 1)
    slices_L = grid_L.slice_orthogonal(x=centre[0], y=centre[1], z=centre[2])
    p.add_mesh(slices_L, scalars='L_mm', cmap=FIELD_CMAP,
               scalar_bar_args={'title': 'L [mm]'})
    p.add_mesh(grid_L.outline(), color='black')
    p.add_text('(d) Recorded L design field', font_size=10, position='upper_edge')
    p.view_isometric()
    p.link_views()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    p.screenshot(str(args.output))
    p.close()
    print(f'Saved: {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
