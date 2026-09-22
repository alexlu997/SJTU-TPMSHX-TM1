"""demo_3d_cube_volume.py — true 3D volume rendering of cube case.

Uses PyVista offscreen ray-cast volume rendering. Renders the 50³ cube
result from `demo_3d_cube_air_air.py` as actual 3D scenes (not 2D slices).

Output PNGs (per field):
  1. Volume — full ray-cast volume with semi-transparent opacity ramp
  2. Triple-slice — three orthogonal cutting planes through the cube
  3. Iso — isosurface of the median value
"""
import os
from pathlib import Path
import numpy as np

# Force offscreen before any pyvista import
os.environ['PYVISTA_OFF_SCREEN'] = 'true'

import pyvista as pv
pv.OFF_SCREEN = True
pv.global_theme.background = 'white'
pv.global_theme.font.color = 'black'

from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack


def build_cube_cfg():
    # B2 2.6: canonical template; cube deltas = 50 mm cube, 20^3 grid.
    from sjtu_tpmshx.runs._case_template import build_cfg as _template_cfg
    return _template_cfg(L=0.050, H=0.050, Lz=0.050, Nx=20, Ny=20, Nz=20)


def make_grid(res):
    """Build pv.RectilinearGrid from solver result + attach all scalar fields."""
    Nx, Ny, Nz = res['Ta'].shape
    dx = res['dx']; dy = res['dy']; dz = res['dz']
    # Edges in mm so the camera frames a sensible scale
    x_edges = np.concatenate([[0.0], np.cumsum(dx)]) * 1000.0
    y_edges = np.concatenate([[0.0], np.cumsum(dy)]) * 1000.0
    z_edges = np.concatenate([[0.0], np.cumsum(dz)]) * 1000.0
    grid = pv.RectilinearGrid(x_edges, y_edges, z_edges)
    fields_to_attach = {
        'Ta': res['Ta'],
        'Tb': res['Tb'],
        'Ts': res['Ts'],
        'vmag': res['vmag'],
        'P_kPa': res['P_kPa'],
    }
    for key, arr in fields_to_attach.items():
        grid.cell_data[key] = arr.flatten(order='F')
    grid = grid.cell_data_to_point_data()
    return grid


def render_volume(grid, scalar, title, outpath):
    """True 3D ray-cast volume render."""
    p = pv.Plotter(off_screen=True, window_size=(900, 800))
    p.background_color = 'white'
    arr = grid[scalar]
    lo, hi = float(arr.min()), float(arr.max())
    if hi - lo < 1e-12:
        hi = lo + 1.0
    # Opacity ramp: transparent at low end, opaque at high end → see interior
    opacity = [0.0, 0.05, 0.15, 0.35, 0.65]
    sb_args = {'title': scalar, 'fmt': '%.2f', 'color': 'black',
               'title_font_size': 14, 'label_font_size': 12,
               'vertical': True, 'position_x': 0.86, 'position_y': 0.2,
               'width': 0.06, 'height': 0.6, 'n_labels': 6}
    p.add_volume(grid, scalars=scalar, cmap='turbo', clim=(lo, hi),
                 opacity=opacity, shade=True,
                 ambient=0.4, diffuse=0.7, specular=0.3,
                 show_scalar_bar=True, scalar_bar_args=sb_args)
    p.add_mesh(grid.outline(), color='black', line_width=2)
    try:
        p.add_axes(line_width=3, x_color='red', y_color='green', z_color='blue',
                   xlabel='X (A flow)', ylabel='Y (B flow)', zlabel='Z',
                   color='black')
    except Exception:
        p.add_axes()
    p.show_bounds(grid='back', location='outer',
                  xtitle='x [mm]  (A: hot at x=0)',
                  ytitle='y [mm]  (B: cold at y=Ly)',
                  ztitle='z [mm]',
                  n_xlabels=3, n_ylabels=3, n_zlabels=3,
                  font_size=11, color='black')
    p.add_text(title, font_size=12, color='black', position='upper_edge')
    p.view_isometric()
    p.camera.zoom(1.3)
    p.screenshot(outpath, transparent_background=False)
    p.close()


def render_triple_slice(grid, scalar, title, outpath):
    """3 orthogonal cutting planes through center of cube — 3D scene.

    Use show_scalar_bar=True on the first add_mesh so the bar picks up the
    actual scalar range (otherwise a separate add_scalar_bar() call defaults
    to a 0-1 normalised range).
    """
    p = pv.Plotter(off_screen=True, window_size=(900, 800))
    p.background_color = 'white'
    arr = grid[scalar]
    lo, hi = float(arr.min()), float(arr.max())
    if hi - lo < 1e-12:
        hi = lo + 1.0
    cx, cy, cz = grid.center
    slc_x = grid.slice(normal='x', origin=(cx, cy, cz))
    slc_y = grid.slice(normal='y', origin=(cx, cy, cz))
    slc_z = grid.slice(normal='z', origin=(cx, cy, cz))
    sb_args = {'title': scalar, 'fmt': '%.2f', 'color': 'black',
               'title_font_size': 14, 'label_font_size': 12,
               'vertical': True, 'position_x': 0.86, 'position_y': 0.2,
               'width': 0.06, 'height': 0.6, 'n_labels': 6}
    p.add_mesh(slc_x, scalars=scalar, cmap='turbo', clim=(lo, hi),
               show_scalar_bar=True, scalar_bar_args=sb_args,
               lighting=False, name='sx')
    p.add_mesh(slc_y, scalars=scalar, cmap='turbo', clim=(lo, hi),
               show_scalar_bar=False, lighting=False, name='sy')
    p.add_mesh(slc_z, scalars=scalar, cmap='turbo', clim=(lo, hi),
               show_scalar_bar=False, lighting=False, name='sz')
    p.add_mesh(grid.outline(), color='black', line_width=2)
    # XYZ triad in corner — gives unambiguous orientation cue
    try:
        p.add_axes(line_width=3, x_color='red', y_color='green', z_color='blue',
                   xlabel='X (A flow)', ylabel='Y (B flow)', zlabel='Z',
                   color='black')
    except Exception:
        p.add_axes()
    p.show_bounds(grid='back', location='outer',
                  xtitle='x [mm]  (A: hot at x=0)',
                  ytitle='y [mm]  (B: cold at y=Ly)',
                  ztitle='z [mm]',
                  n_xlabels=3, n_ylabels=3, n_zlabels=3,
                  font_size=11, color='black')
    p.add_text(title, font_size=12, color='black', position='upper_edge')
    p.view_isometric()
    p.camera.zoom(1.3)
    p.screenshot(outpath, transparent_background=False)
    p.close()


def render_iso(grid, scalar, title, outpath, n_iso=5):
    """Isosurface render — multiple iso-levels through the cube."""
    p = pv.Plotter(off_screen=True, window_size=(900, 800))
    p.background_color = 'white'
    arr = grid[scalar]
    lo, hi = float(arr.min()), float(arr.max())
    if hi - lo < 1e-12:
        hi = lo + 1.0
    iso_values = np.linspace(lo + 0.1*(hi-lo), hi - 0.1*(hi-lo), n_iso)
    contours = grid.contour(isosurfaces=iso_values, scalars=scalar)
    sb_args = {'title': scalar, 'fmt': '%.2f', 'color': 'black',
               'title_font_size': 14, 'label_font_size': 12,
               'vertical': True, 'position_x': 0.86, 'position_y': 0.2,
               'width': 0.06, 'height': 0.6, 'n_labels': 6}
    p.add_mesh(contours, scalars=scalar, cmap='turbo', clim=(lo, hi),
               opacity=0.65, show_scalar_bar=True, scalar_bar_args=sb_args)
    p.add_mesh(grid.outline(), color='black', line_width=2)
    try:
        p.add_axes(line_width=3, x_color='red', y_color='green', z_color='blue',
                   xlabel='X (A flow)', ylabel='Y (B flow)', zlabel='Z',
                   color='black')
    except Exception:
        p.add_axes()
    p.show_bounds(grid='back', location='outer',
                  xtitle='x [mm]  (A: hot at x=0)',
                  ytitle='y [mm]  (B: cold at y=Ly)',
                  ztitle='z [mm]',
                  n_xlabels=3, n_ylabels=3, n_zlabels=3,
                  font_size=11, color='black')
    p.add_text(title + f'  ({n_iso} iso-levels)',
               font_size=12, color='black', position='upper_edge')
    p.view_isometric()
    p.camera.zoom(1.4)
    p.screenshot(outpath, transparent_background=False)
    p.close()


def main():
    cfg = build_cube_cfg()
    print("Running 50x50x50 mm cube case...")
    import time
    t0 = time.time()
    res = _run_3d_stack(cfg)
    print(f"Solver: {time.time()-t0:.1f}s")
    grid = make_grid(res)

    outdir = str(Path(__file__).resolve().parents[3] / '.cache' / 'demos' / 'cube_3d')
    os.makedirs(outdir, exist_ok=True)

    fields = [
        ('Ts',    'Ts (Solid) [K]'),
        ('Ta',    'Ta (Fluid A, hot, +x) [K]'),
        ('Tb',    'Tb (Fluid B, cold, -y) [K]'),
        ('vmag',  '|v|_A [m/s]'),
        ('P_kPa', 'P_A abs [kPa]'),
    ]
    print("\nRendering 3D scenes...")
    failures = 0
    for fkey, fname in fields:
        # 3 render styles per field
        p_vol = os.path.join(outdir, f'cube_{fkey}_volume.png')
        p_slc = os.path.join(outdir, f'cube_{fkey}_triple_slice.png')
        p_iso = os.path.join(outdir, f'cube_{fkey}_iso.png')
        try:
            render_volume(grid, fkey, fname + ' — volume rendering', p_vol)
            print(f"  vol  {p_vol}")
        except Exception as e:
            failures += 1
            print(f"  vol  FAILED ({fkey}): {e}")
        try:
            render_triple_slice(grid, fkey, fname + ' — 3 orthogonal slices', p_slc)
            print(f"  slc  {p_slc}")
        except Exception as e:
            failures += 1
            print(f"  slc  FAILED ({fkey}): {e}")
        try:
            render_iso(grid, fkey, fname + ' — isosurfaces', p_iso, n_iso=5)
            print(f"  iso  {p_iso}")
        except Exception as e:
            failures += 1
            print(f"  iso  FAILED ({fkey}): {e}")
    print(f"\nRendering finished: {failures} failures.")
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
