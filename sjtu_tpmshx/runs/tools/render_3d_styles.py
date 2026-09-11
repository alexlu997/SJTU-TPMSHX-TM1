"""render_3d_styles.py — 3D output style showcase.

Per-field outputs (5 styles):
  1. publication_4panel.png — 3D triple-slice + 3 ortho 2D in 4-panel grid
  2. presentation_large.png — single large triple-slice (1600×1400)
  3. volume_tuned.png       — ray-cast volume with sharper opacity ramp
  4. iso_3level.png         — 3 cleaner isosurfaces
  5. rotate.mp4             — 120-frame rotation video (Ts only, ~3 MB)
  6. interactive.html       — PyVista HTML export (Ts only)

Field selection:
  - Ts is the LTNE-coupling showcase → all 6 outputs
  - Ta, Tb, vmag, P_kPa → outputs 1 + 2 only (lighter)
"""
import os
import numpy as np

os.environ['PYVISTA_OFF_SCREEN'] = 'true'

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.image import imread

import pyvista as pv
pv.OFF_SCREEN = True
pv.global_theme.background = 'white'
pv.global_theme.font.color = 'black'

from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry
from sjtu_tpmshx.pipelines.stages_3d import _run_3d_stack


def build_cube_cfg():
    L = H = Lz = 0.050
    Nx = Ny = Nz = 20
    Lcell, t_wall, k_s = 7.0, 0.5, 16.0
    tpms_type = 'Gyroid'
    g = tpms_geometry(tpms_type, Lcell, t_wall, k_s)
    return dict(
        L=L, H=H, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
        u_A=20.0, u_B=10.0,
        T_inA=422.0, T_inB=293.15,
        P_inA=192362.0, P_inB=101325.0,
        T_s_init=None,
        Lcell=Lcell, t_wall=t_wall, k_s=k_s,
        tpms_type=tpms_type,
        eps=g['epsilon'], D_h=g['D_h'],
        fluid_A_cfg=dict(dir=0, in_ctr=H/2, in_w=H, out_ctr=H/2, out_w=H),
        fluid_B_cfg=dict(dir=3, in_ctr=L/2, in_w=L, out_ctr=L/2, out_w=L),
        wall_refine_3d=False,
        zone_grid_cells=None,
        fluid_type_A='air', fluid_type_B='air',
    )


def make_grid(res):
    Nx, Ny, Nz = res['Ta'].shape
    dx, dy, dz = res['dx'], res['dy'], res['dz']
    xe = np.concatenate([[0.0], np.cumsum(dx)]) * 1000.0
    ye = np.concatenate([[0.0], np.cumsum(dy)]) * 1000.0
    ze = np.concatenate([[0.0], np.cumsum(dz)]) * 1000.0
    grid = pv.RectilinearGrid(xe, ye, ze)
    for k, arr in [('Ta', res['Ta']), ('Tb', res['Tb']), ('Ts', res['Ts']),
                   ('vmag', res['vmag']), ('P_kPa', res['P_kPa'])]:
        grid.cell_data[k] = arr.flatten(order='F')
    return grid.cell_data_to_point_data()


def _add_axes_show_bounds(p):
    try:
        p.add_axes(line_width=3,
                   x_color='red', y_color='green', z_color='blue',
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


def render_triple_slice(grid, scalar, title, outpath, window=(900, 800), zoom=1.3):
    """Triple orthogonal slice through center."""
    p = pv.Plotter(off_screen=True, window_size=window)
    p.background_color = 'white'
    arr = grid[scalar]
    lo, hi = float(arr.min()), float(arr.max())
    if hi - lo < 1e-12: hi = lo + 1.0
    cx, cy, cz = grid.center
    sb_args = {'title': scalar, 'fmt': '%.2f', 'color': 'black',
               'title_font_size': 14, 'label_font_size': 12,
               'vertical': True, 'position_x': 0.86, 'position_y': 0.2,
               'width': 0.06, 'height': 0.6, 'n_labels': 6}
    for i, n in enumerate(['x', 'y', 'z']):
        slc = grid.slice(normal=n, origin=(cx, cy, cz))
        p.add_mesh(slc, scalars=scalar, cmap='turbo', clim=(lo, hi),
                   show_scalar_bar=(i == 0), scalar_bar_args=sb_args if i == 0 else None,
                   lighting=False, name=f's{n}', opacity=0.92)
    p.add_mesh(grid.outline(), color='black', line_width=2)
    _add_axes_show_bounds(p)
    p.add_text(title, font_size=12, color='black', position='upper_edge')
    # Slight off-axis (azimuth 30°, elevation 25°) reads better than pure iso
    p.view_isometric()
    p.camera.azimuth = 30
    p.camera.elevation = 25
    p.camera.zoom(zoom)
    p.screenshot(outpath, transparent_background=False)
    p.close()


def render_volume_tuned(grid, scalar, title, outpath):
    """Volume ray-cast with sharper opacity (low values fully transparent)."""
    p = pv.Plotter(off_screen=True, window_size=(900, 800))
    p.background_color = 'white'
    arr = grid[scalar]
    lo, hi = float(arr.min()), float(arr.max())
    if hi - lo < 1e-12: hi = lo + 1.0
    sb_args = {'title': scalar, 'fmt': '%.2f', 'color': 'black',
               'title_font_size': 14, 'label_font_size': 12,
               'vertical': True, 'position_x': 0.86, 'position_y': 0.2,
               'width': 0.06, 'height': 0.6, 'n_labels': 6}
    # Tuned ramp: low end fully transparent, high end nearly solid
    p.add_volume(grid, scalars=scalar, cmap='turbo', clim=(lo, hi),
                 opacity=[0.0, 0.0, 0.08, 0.4, 0.95],
                 shade=True, ambient=0.4, diffuse=0.7, specular=0.3,
                 show_scalar_bar=True, scalar_bar_args=sb_args)
    p.add_mesh(grid.outline(), color='black', line_width=2)
    _add_axes_show_bounds(p)
    p.add_text(title + ' — volume (tuned opacity)', font_size=12,
               color='black', position='upper_edge')
    p.view_isometric()
    p.camera.azimuth = 30; p.camera.elevation = 25
    p.camera.zoom(1.3)
    p.screenshot(outpath, transparent_background=False)
    p.close()


def render_iso_3level(grid, scalar, title, outpath):
    """3 isosurfaces (cleaner than 5)."""
    p = pv.Plotter(off_screen=True, window_size=(900, 800))
    p.background_color = 'white'
    arr = grid[scalar]
    lo, hi = float(arr.min()), float(arr.max())
    if hi - lo < 1e-12: hi = lo + 1.0
    iso_values = np.linspace(lo + 0.2*(hi-lo), hi - 0.2*(hi-lo), 3)
    contours = grid.contour(isosurfaces=iso_values, scalars=scalar)
    sb_args = {'title': scalar, 'fmt': '%.2f', 'color': 'black',
               'title_font_size': 14, 'label_font_size': 12,
               'vertical': True, 'position_x': 0.86, 'position_y': 0.2,
               'width': 0.06, 'height': 0.6, 'n_labels': 6}
    p.add_mesh(contours, scalars=scalar, cmap='turbo', clim=(lo, hi),
               opacity=0.55, show_scalar_bar=True, scalar_bar_args=sb_args)
    p.add_mesh(grid.outline(), color='black', line_width=2)
    _add_axes_show_bounds(p)
    p.add_text(title + ' — 3 isosurfaces', font_size=12,
               color='black', position='upper_edge')
    p.view_isometric()
    p.camera.azimuth = 30; p.camera.elevation = 25
    p.camera.zoom(1.3)
    p.screenshot(outpath, transparent_background=False)
    p.close()


def render_rotation_mp4(grid, scalar, title, outpath, n_frames=120):
    """120-frame azimuth rotation movie (mp4)."""
    p = pv.Plotter(off_screen=True, window_size=(800, 700))
    p.background_color = 'white'
    arr = grid[scalar]
    lo, hi = float(arr.min()), float(arr.max())
    if hi - lo < 1e-12: hi = lo + 1.0
    cx, cy, cz = grid.center
    sb_args = {'title': scalar, 'fmt': '%.2f', 'color': 'black',
               'title_font_size': 14, 'label_font_size': 12,
               'vertical': True, 'position_x': 0.86, 'position_y': 0.2,
               'width': 0.06, 'height': 0.6, 'n_labels': 6}
    for i, n in enumerate(['x', 'y', 'z']):
        slc = grid.slice(normal=n, origin=(cx, cy, cz))
        p.add_mesh(slc, scalars=scalar, cmap='turbo', clim=(lo, hi),
                   show_scalar_bar=(i == 0), scalar_bar_args=sb_args if i == 0 else None,
                   lighting=False, name=f's{n}')
    p.add_mesh(grid.outline(), color='black', line_width=2)
    _add_axes_show_bounds(p)
    p.add_text(title + ' — rotating', font_size=12,
               color='black', position='upper_edge')
    # Try mp4 first; if no ffmpeg backend, fall back to gif.
    use_gif = False
    try:
        p.open_movie(outpath, framerate=30, quality=8)
    except Exception as e:
        print(f"  (mp4 backend failed: {e}; trying gif fallback)")
        gif_path = outpath.replace('.mp4', '.gif')
        try:
            p.open_gif(gif_path, fps=20)
            use_gif = True
            outpath = gif_path
        except Exception as e2:
            print(f"  (gif also failed: {e2}; skipping)")
            p.close()
            return False
    p.camera.elevation = 25
    p.camera.zoom(1.3)
    try:
        for angle in np.linspace(0, 360, n_frames, endpoint=False):
            p.camera.azimuth = angle
            p.write_frame()
    except Exception as e:
        print(f"  (write_frame failed: {e}; possibly missing imageio-ffmpeg)")
        p.close()
        # Try gif fallback if we were on mp4
        if not use_gif:
            return render_rotation_gif(grid, scalar, title,
                                         outpath.replace('.mp4', '.gif'),
                                         n_frames=n_frames)
        return False
    p.close()
    return True


def render_rotation_gif(grid, scalar, title, outpath, n_frames=60):
    """Pure-gif fallback if mp4 unavailable."""
    p = pv.Plotter(off_screen=True, window_size=(700, 600))
    p.background_color = 'white'
    arr = grid[scalar]
    lo, hi = float(arr.min()), float(arr.max())
    if hi - lo < 1e-12: hi = lo + 1.0
    cx, cy, cz = grid.center
    sb_args = {'title': scalar, 'fmt': '%.2f', 'color': 'black',
               'title_font_size': 14, 'label_font_size': 12,
               'vertical': True, 'position_x': 0.86, 'position_y': 0.2,
               'width': 0.06, 'height': 0.6, 'n_labels': 6}
    for i, n in enumerate(['x', 'y', 'z']):
        slc = grid.slice(normal=n, origin=(cx, cy, cz))
        p.add_mesh(slc, scalars=scalar, cmap='turbo', clim=(lo, hi),
                   show_scalar_bar=(i == 0),
                   scalar_bar_args=sb_args if i == 0 else None,
                   lighting=False, name=f's{n}')
    p.add_mesh(grid.outline(), color='black', line_width=2)
    _add_axes_show_bounds(p)
    p.add_text(title + ' — rotating', font_size=12,
               color='black', position='upper_edge')
    try:
        p.open_gif(outpath, fps=20)
    except Exception as e:
        print(f"  (gif open failed: {e})")
        p.close()
        return False
    p.camera.elevation = 25
    p.camera.zoom(1.3)
    for angle in np.linspace(0, 360, n_frames, endpoint=False):
        p.camera.azimuth = angle
        p.write_frame()
    p.close()
    return True


def render_html(grid, scalar, title, outpath):
    """Interactive HTML — for sharing / review."""
    p = pv.Plotter(off_screen=False, window_size=(900, 800))
    arr = grid[scalar]
    lo, hi = float(arr.min()), float(arr.max())
    if hi - lo < 1e-12: hi = lo + 1.0
    cx, cy, cz = grid.center
    for n in ('x', 'y', 'z'):
        slc = grid.slice(normal=n, origin=(cx, cy, cz))
        p.add_mesh(slc, scalars=scalar, cmap='turbo', clim=(lo, hi),
                   lighting=False, name=f's{n}')
    p.add_mesh(grid.outline(), color='black', line_width=2)
    p.add_text(title, font_size=12, color='black', position='upper_edge')
    p.view_isometric()
    try:
        p.export_html(outpath)
        return True
    except Exception as e:
        print(f"  (html export failed: {e})")
        return False


def render_publication_4panel(grid, scalar, title, outpath, unit,
                                cell_arr, dx_mm, dy_mm, dz_mm):
    """4-panel composite — 3D iso + 3 ortho 2D, shared colorbar.

    Strategy: render 3D triple-slice to temp PNG, load it into matplotlib
    gridspec layout hosting 3 ortho 2D contourf in the other 3 quadrants.
    Shared colorbar on the right.

    `cell_arr` (Nx, Ny, Nz) is the original solver output for 2D contourf
    — passed in directly because grid's cell_data is stripped after
    `cell_data_to_point_data()`. dx/dy/dz_mm are 1-D spacing arrays.
    """
    Nx, Ny, Nz = cell_arr.shape

    # Render 3D scene to temp PNG
    tmp_3d = outpath.replace('.png', '_tmp3d.png')
    render_triple_slice(grid, scalar, title + ' — 3D view',
                          tmp_3d, window=(800, 700), zoom=1.4)
    img_3d = imread(tmp_3d)

    xc = np.cumsum(dx_mm) - dx_mm / 2
    yc = np.cumsum(dy_mm) - dy_mm / 2
    zc = np.cumsum(dz_mm) - dz_mm / 2
    i_mid, j_mid, k_mid = Nx // 2, Ny // 2, Nz // 2

    vmin = float(cell_arr.min()); vmax = float(cell_arr.max())
    if vmax - vmin < 1e-12: vmax = vmin + 1.0
    levels = np.linspace(vmin, vmax, 80)

    fig = plt.figure(figsize=(13, 10))
    gs = GridSpec(2, 3, figure=fig, width_ratios=[1, 1, 0.05],
                   wspace=0.32, hspace=0.32, left=0.06, right=0.95,
                   top=0.92, bottom=0.07)
    fig.suptitle(title, fontsize=15, fontweight='bold', y=0.97)

    # Top-left: 3D image
    ax3d = fig.add_subplot(gs[0, 0])
    ax3d.imshow(img_3d)
    ax3d.set_title('3D view (triple slice)', fontweight='bold', fontsize=11)
    ax3d.axis('off')

    # Top-right: TOP (XY at mid-z)
    axTop = fig.add_subplot(gs[0, 1])
    Y2, X2 = np.meshgrid(yc, xc)
    cf = axTop.contourf(X2, Y2, cell_arr[:, :, k_mid], levels=levels,
                         cmap='turbo', vmin=vmin, vmax=vmax, extend='both')
    axTop.set_title(f'TOP — XY @ z={zc[k_mid]:.1f} mm',
                    fontweight='bold', fontsize=11)
    axTop.set_xlabel('x [mm]'); axTop.set_ylabel('y [mm]')
    axTop.set_aspect('equal')

    # Bottom-left: FRONT (XZ at mid-y)
    axFr = fig.add_subplot(gs[1, 0])
    Z2, X2 = np.meshgrid(zc, xc)
    cf = axFr.contourf(X2, Z2, cell_arr[:, j_mid, :], levels=levels,
                       cmap='turbo', vmin=vmin, vmax=vmax, extend='both')
    axFr.set_title(f'FRONT — XZ @ y={yc[j_mid]:.1f} mm',
                   fontweight='bold', fontsize=11)
    axFr.set_xlabel('x [mm]'); axFr.set_ylabel('z [mm]')
    axFr.set_aspect('equal')

    # Bottom-right: SIDE (YZ at mid-x)
    axSi = fig.add_subplot(gs[1, 1])
    Z2, Y2 = np.meshgrid(zc, yc)
    cf = axSi.contourf(Y2, Z2, cell_arr[i_mid, :, :], levels=levels,
                       cmap='turbo', vmin=vmin, vmax=vmax, extend='both')
    axSi.set_title(f'SIDE — YZ @ x={xc[i_mid]:.1f} mm',
                   fontweight='bold', fontsize=11)
    axSi.set_xlabel('y [mm]'); axSi.set_ylabel('z [mm]')
    axSi.set_aspect('equal')

    # Right column: shared colorbar
    cax = fig.add_subplot(gs[:, 2])
    cb = fig.colorbar(cf, cax=cax, format='%.2f')
    cb.set_label(unit, fontsize=12)
    cb.ax.tick_params(labelsize=10)
    cb.mappable.set_clim(vmin, vmax)

    fig.savefig(outpath, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close(fig)

    # Clean up temp
    try: os.remove(tmp_3d)
    except Exception: pass


def render_presentation_large(grid, scalar, title, outpath):
    """Single large triple-slice for slides."""
    render_triple_slice(grid, scalar, title, outpath,
                          window=(1600, 1400), zoom=1.3)


if __name__ == '__main__':
    cfg = build_cube_cfg()
    print("Solving 50x50x50 mm cube case...")
    import time
    t0 = time.time()
    res = _run_3d_stack(cfg)
    print(f"Solver: {time.time()-t0:.1f}s")
    grid = make_grid(res)

    # Preserve raw arrays + spacings for 2D contourf (grid.cell_data is gone
    # after cell_data_to_point_data()).
    raw_arrays = {'Ta': res['Ta'], 'Tb': res['Tb'], 'Ts': res['Ts'],
                  'vmag': res['vmag'], 'P_kPa': res['P_kPa']}
    dx_mm = res['dx'] * 1000.0
    dy_mm = res['dy'] * 1000.0
    dz_mm = res['dz'] * 1000.0

    outdir = os.path.join(os.path.dirname(__file__), 'demo_output', 'cube_3d_styles')
    os.makedirs(outdir, exist_ok=True)

    fields = [
        ('Ts',    'Ts (Solid) [K]', '[K]', True),
        ('Ta',    'Ta (Fluid A, hot, +x) [K]', '[K]', False),
        ('Tb',    'Tb (Fluid B, cold, -y) [K]', '[K]', False),
        ('vmag',  '|v|_A [m/s]', '[m/s]', False),
        ('P_kPa', 'P_A abs [kPa]', '[kPa]', False),
    ]
    print("\nGenerating publication-quality outputs:")
    for fkey, fname, unit, full_set in fields:
        print(f"\n--- {fkey} ---")
        # 1. publication 4-panel
        p_pub = os.path.join(outdir, f'{fkey}_publication_4panel.png')
        render_publication_4panel(grid, fkey, fname, p_pub, unit,
                                    raw_arrays[fkey], dx_mm, dy_mm, dz_mm)
        print(f"  [1] publication 4-panel : {p_pub}")
        # 2. presentation large
        p_pres = os.path.join(outdir, f'{fkey}_presentation_large.png')
        render_presentation_large(grid, fkey, fname, p_pres)
        print(f"  [2] presentation large  : {p_pres}")

        if full_set:
            # 3. volume tuned
            p_vol = os.path.join(outdir, f'{fkey}_volume_tuned.png')
            render_volume_tuned(grid, fkey, fname, p_vol)
            print(f"  [3] volume (tuned)      : {p_vol}")
            # 4. iso 3-level
            p_iso = os.path.join(outdir, f'{fkey}_iso_3level.png')
            render_iso_3level(grid, fkey, fname, p_iso)
            print(f"  [4] iso (3-level)       : {p_iso}")
            # 5. rotation mp4
            p_mp4 = os.path.join(outdir, f'{fkey}_rotate.mp4')
            ok = render_rotation_mp4(grid, fkey, fname, p_mp4, n_frames=90)
            if ok:
                print(f"  [5] rotation mp4        : {p_mp4}")
            # 6. interactive HTML
            p_html = os.path.join(outdir, f'{fkey}_interactive.html')
            ok = render_html(grid, fkey, fname, p_html)
            if ok:
                print(f"  [6] interactive HTML    : {p_html}")
    print("\nDone.")
