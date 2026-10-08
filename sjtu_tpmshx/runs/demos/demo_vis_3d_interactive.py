"""demo_vis_3d_interactive.py — interactive 3D visualisation.

PyVista standalone window showing saved FieldResult 3D fields, with a draggable
slice-plane widget. The default display preserves the domain's real aspect.

Controls:
    [f]       cycle field (T_a → |v| → P → L_mm)
    [1/2/3]   set slice normal to x / y / z
    [s]       screenshot current view → slice_<field>_<normal>.png
    [r]       reset camera
    [q]       quit

With --cube, the domain is visually stretched to [0,1]³ (display-only scaling).
Its axis labels then show normalised position and an annotation provides the
real-world dimensions. The underlying physics data are unchanged.

Usage (from the repo root):
    python -m sjtu_tpmshx.runs.demos.demo_vis_3d_interactive results.h5
    python -m sjtu_tpmshx.runs.demos.demo_vis_3d_interactive results.h5 --test
    python -m sjtu_tpmshx.runs.demos.demo_vis_3d_interactive results.h5 --cube
"""

from __future__ import annotations
import argparse
import math
from pathlib import Path

import numpy as np
import pyvista as pv

from sjtu_tpmshx.ui.demo_vis_3d import load_visualization_result
from sjtu_tpmshx.ui.vis3d_constants import FIELD_ORDER, FIELD_META, tone_down_plane_widget


def build_data_grid(dx, dy, dz, Ta, vmag, P, L_field,
                    stretch_to_cube=False):
    """Build pv.RectilinearGrid with all 4 fields in real mm coords.

    stretch_to_cube=True distorts the grid to a unit cube (visual only).
    Default False = physically accurate aspect.
    Fields are cell-centred then promoted to point data for smooth slicing.
    P is absolute pressure in Pa, converted to kPa for display.
    """
    # Real-world coords in mm (easier on the eye than SI metres)
    x_edges = np.concatenate([[0.0], np.cumsum(dx)]) * 1000.0   # mm
    y_edges = np.concatenate([[0.0], np.cumsum(dy)]) * 1000.0
    z_edges = np.concatenate([[0.0], np.cumsum(dz)]) * 1000.0

    if stretch_to_cube:
        x_edges = x_edges / x_edges[-1]
        y_edges = y_edges / y_edges[-1]
        z_edges = z_edges / z_edges[-1]

    grid = pv.RectilinearGrid(x_edges, y_edges, z_edges)
    grid.cell_data['Ta']    = Ta.flatten(order='F')
    grid.cell_data['vmag']  = vmag.flatten(order='F')
    grid.cell_data['P_kPa'] = (P.flatten(order='F') / 1000.0)
    grid.cell_data['L_mm']  = L_field.flatten(order='F')
    return grid.cell_data_to_point_data()


def launch_interactive(grid, *, off_screen=False, out_dir=None,
                        stretched=False, real_dims=None):
    """Spin up the PyVista window with widgets + keybindings.

    stretched : whether the grid has been visually stretched to a cube.
                Only affects the info-text annotation.
    """
    if out_dir is None:
        out_dir = Path(__file__).resolve().parents[3] / '.cache' / 'demos' / 'interactive'
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if real_dims is None:
        if stretched:
            raise ValueError('Cube-stretched display requires the physical real_dims')
        real_dims = tuple((grid.bounds[2*i+1] - grid.bounds[2*i]) / 1000. for i in range(3))

    # This A-side demo supplies a subset of the embedded panel's fields.
    field_order = [field for field in FIELD_ORDER if field in grid.point_data]
    if not field_order:
        raise ValueError('The grid has no supported point fields to display')
    pv.set_plot_theme('document')
    pl = pv.Plotter(window_size=(1280, 900), off_screen=off_screen,
                    title='SJTU-TPMSHX 3D Interactive Slice')

    # Pre-compute global clim for each available field (for 'global' mode).
    global_clim = {f: (float(grid[f].min()), float(grid[f].max()))
                   for f in field_order}

    # Mutable state
    state = {'field_idx': 0, 'normal': 'x', 'scale_mode': 'global'}
    slice_holder = {'actor': None, 'widget_on': False, 'slice_mesh': None}

    def current_field():
        return field_order[state['field_idx']]

    def header_text():
        f = current_field()
        return f"{FIELD_META[f]['title']}   |   slice ⊥ {state['normal']}   |   colorbar: {state['scale_mode']}"

    def footer_text():
        Lx_mm, Ly_mm, Lz_mm = (d * 1000 for d in real_dims)
        aspect_note = ('cube-stretched display' if stretched
                       else 'true aspect')
        return (f"Real domain: {Lx_mm:.0f} x {Ly_mm:.0f} x {Lz_mm:.0f} mm   ({aspect_note})\n"
                f"[f] cycle field   [1/2/3] normal x/y/z   [c] clim global/local   "
                f"[s] screenshot   [r] reset camera   [q] quit")

    # Bounding box outline (minimal, no dense grid)
    pl.add_mesh(grid.outline(), color='#3c4758', line_width=2)
    axes = pl.show_bounds(
        bounds=grid.bounds,
        grid='back', location='outer',
        xtitle='x/Lx' if stretched else 'x (mm)',
        ytitle='y/Ly' if stretched else 'y (mm)',
        ztitle='z/Lz' if stretched else 'z (mm)',
        n_xlabels=3, n_ylabels=3, n_zlabels=3,
        all_edges=False, minor_ticks=False, use_2d=False,
        font_size=11,
        color='#1a1f24',
    )
    pl.add_axes(interactive=False, line_width=2)

    def rebuild_slice():
        f = current_field()
        meta = FIELD_META[f]

        # Tear down previous slice + widget + all scalar bars
        if slice_holder['widget_on']:
            try:
                pl.clear_plane_widgets()
            except Exception:
                pass
            slice_holder['widget_on'] = False
        if slice_holder['actor'] is not None:
            try:
                pl.remove_actor(slice_holder['actor'])
            except Exception:
                pass
            slice_holder['actor'] = None
        for fkey in field_order:
            try:
                pl.remove_scalar_bar(FIELD_META[fkey]['title'])
            except Exception:
                pass

        # Decide clim + scalar-bar format
        sbar_fmt = meta['fmt']
        if state['scale_mode'] == 'global':
            clim = global_clim[f]
        else:  # 'local' — compute slice data range at current plane centre
            origin = grid.center
            slc = grid.slice(normal=state['normal'], origin=origin)
            if slc.n_points > 0 and f in slc.array_names:
                vals = slc[f]
                if vals.size > 0:
                    lo, hi = float(vals.min()), float(vals.max())
                    if hi - lo < 1e-12:   # degenerate (constant slice)
                        hi = lo + 1.0
                    clim = (lo, hi)
                    # Adaptive scalar-bar fmt if range too narrow for default precision
                    span = hi - lo
                    ref = max(abs(lo), abs(hi), 1e-30)
                    # Adaptive precision: ensure span >> label-rounding granularity
                    if span > 0:
                        n_digits = max(2, int(math.ceil(math.log10(ref / span))) + 2)
                        n_digits = min(n_digits, 7)
                        sbar_fmt = f'%.{n_digits}g'
                else:
                    clim = global_clim[f]
            else:
                clim = global_clim[f]

        actor = pl.add_mesh_slice(
            grid, scalars=f, cmap=meta['cmap'],
            normal=state['normal'],
            clim=clim,
            lighting=False,     # avoid mid-value "greyed-out" artefacts
            widget_color='#606870',       # Gemini: tone down widget
            outline_translation=False,     # remove the heavy corner handles
            tubing=False,
            scalar_bar_args={
                'title': meta['title'],
                'n_labels': 5,
                'vertical': True,
                'position_x': 0.88,
                'position_y': 0.12,
                'width': 0.06,
                'height': 0.60,
                'fmt': sbar_fmt,
                'title_font_size': 13,
                'label_font_size': 11,
                'color': '#1a1f24',
            },
            show_edges=False,
            name='live_slice',
        )
        slice_holder['actor'] = actor
        slice_holder['widget_on'] = True
        tone_down_plane_widget(pl)

        # Header (bold, big) + footer (dim, small)
        pl.add_text(header_text(), font_size=14, position='upper_edge',
                    color='#1a1f24', name='info_header', shadow=False)
        pl.add_text(footer_text(), font_size=9, position='lower_edge',
                    color='#606870', name='info_footer')
        # Widget actors expand scene bounds while they are rebuilt.
        axes.update_bounds(grid.bounds)

    def cycle_field():
        state['field_idx'] = (state['field_idx'] + 1) % len(field_order)
        rebuild_slice()
        pl.render()

    def set_normal(n):
        state['normal'] = n
        rebuild_slice()
        pl.render()

    def toggle_clim():
        state['scale_mode'] = 'local' if state['scale_mode'] == 'global' else 'global'
        rebuild_slice()
        pl.render()

    def screenshot():
        f = current_field()
        fname = out_dir / f"slice_{f}_{state['normal']}_{state['scale_mode']}.png"
        pl.screenshot(str(fname))
        print(f"[screenshot] saved: {fname}")

    def reset_cam():
        pl.reset_camera()
        pl.render()

    pl.add_key_event('f', cycle_field)
    pl.add_key_event('1', lambda: set_normal('x'))
    pl.add_key_event('2', lambda: set_normal('y'))
    pl.add_key_event('3', lambda: set_normal('z'))
    pl.add_key_event('c', toggle_clim)
    pl.add_key_event('s', screenshot)
    pl.add_key_event('r', reset_cam)

    rebuild_slice()
    pl.view_isometric()
    pl.camera.zoom(1.1)

    if off_screen:
        # Emit preview sweep: field × normal × (global|local)
        from itertools import product
        for f_idx, normal, mode in product(range(len(field_order)),
                                            ['x', 'y', 'z'],
                                            ['global', 'local']):
            state['field_idx'] = f_idx
            state['normal'] = normal
            state['scale_mode'] = mode
            rebuild_slice()
            pl.view_isometric()
            pl.camera.zoom(1.1)
            fn = field_order[f_idx]
            fname = out_dir / f"preview_{fn}_{normal}_{mode}.png"
            pl.screenshot(str(fname))
            print(f"[preview] {fname.name}")
        pl.close()
        return

    print("\n=== Interactive window opened ===")
    print("Drag the red arrow on the plane widget to move the slice.")
    print("Keybindings:")
    print("  [f]     cycle field")
    print("  [1/2/3] set slice normal to x / y / z")
    print("  [s]     screenshot current view")
    print("  [r]     reset camera")
    print("  [q]     quit\n")
    pl.show()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('result', type=Path, help='Saved 3D FieldResult HDF5 file.')
    ap.add_argument('--test', action='store_true',
                    help='Off-screen render for CI smoke (no window).')
    ap.add_argument('--cube', action='store_true',
                    help='Stretch display to cube (visual only, distorts aspect). '
                         'Default is true physical aspect.')
    ap.add_argument('--out-dir', type=Path, help='Screenshot directory (default: .cache/demos/interactive).')
    args = ap.parse_args()

    result = load_visualization_result(args.result)
    widths = [result.grid['d' + axis] for axis in 'xyz']
    fields = result.fields
    vmag = np.sqrt(sum(fields[name]**2 for name in ('ucA', 'vcA', 'wcA')))
    L_field = result.metadata['design_fields']['L_field_m'] * 1000.
    print(f"Loaded {args.result}: grid={fields['Ta'].shape}, status={dict(result.run_status)}")
    grid = build_data_grid(*widths, fields['Ta'], vmag, fields['P_report_A'], L_field,
                           stretch_to_cube=args.cube)
    launch_interactive(grid, off_screen=args.test, out_dir=args.out_dir,
                        stretched=args.cube, real_dims=tuple(np.sum(d) for d in widths))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
