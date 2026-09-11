"""Polygon-domain calculation pipeline.

Extracted from main.py (Task B.8). Entry: run_polygon_calculation.
All functions take `window` (Main_Menu) as first arg.

Lives in runs/ (UI-coupled pipeline, same tier as run_calculation.py) so
solvers/ stays importable without Qt/matplotlib.
"""
import warnings
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.tri as mtri
from matplotlib.gridspec import GridSpec

from PySide6.QtWidgets import QApplication, QMessageBox
from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry, air_cp
from sjtu_tpmshx.solvers.polygon_fvm import solve_polygon_domain
from sjtu_tpmshx.solvers.unstructured_mesh import BC_OUTLET_A, BC_OUTLET_B
from sjtu_tpmshx.ui.theme import get_theme


def run_polygon_calculation(window):
    """Top-level polygon run. Split into 4 phases."""
    import time as _time
    _t0 = _time.time()
    def _log(msg):
        print(f"  [{_time.time()-_t0:.1f}s] {msg}")
    try:
        cfg = _parse_inputs(window, _log)
        if cfg is None:
            return
        fields = _build_fields(window, cfg, _log)
        result = _run_solvers(window, cfg, fields, _log)
        _store_results(window, cfg, fields, result, _log)
    except Exception as e:
        import traceback
        traceback.print_exc()
        window.progress.setValue(0)
        window.progress.setFormat("")
        QMessageBox.critical(window, "Error", str(e))


def _parse_inputs(window, _log):
    """Phase 1: read UI widgets, validate, build mesh. Returns cfg or None."""
    from sjtu_tpmshx.solvers import unstructured_mesh as um
    from sjtu_tpmshx.solvers.unstructured_mesh import BC_INLET_A, BC_INLET_B

    if not window.compute_tpms():
        return None
    window.auto_fill_fluid_a()
    window.auto_fill_fluid_b()
    if window._K_ffA is None or window._K_ffB is None:
        QMessageBox.warning(window, "Missing Input", "Auto-fill failed.")
        return None

    L = float(window.le_L.text())
    H = float(window.le_H.text())
    u_A = float(window.le_uA.text())
    u_B = float(window.le_uB.text())
    # Honour UI K/°C toggle — compute path always receives Kelvin
    if hasattr(window, '_temp_to_K'):
        T_inA = window._temp_to_K(window.le_TinA)
        T_inB = window._temp_to_K(window.le_TinB)
    else:
        T_inA = float(window.le_TinA.text())
        T_inB = float(window.le_TinB.text())
    # Fluid cp evaluated at inlet T (matches SIMPLE path; previously read from
    # a read-only UI field that held a placeholder string and crashed).
    cp_f = float(air_cp(T_inA))

    shape = window.combo_shape.currentText()
    verts = um.hexagon(L, H) if shape == 'Hexagon' else um.octagon(L, H)

    edge_inA = window.combo_edge_inA.currentIndex()
    edge_outA = window.combo_edge_outA.currentIndex()
    edge_inB = window.combo_edge_inB.currentIndex()
    edge_outB = window.combo_edge_outB.currentIndex()
    edges = {edge_inA, edge_outA, edge_inB, edge_outB}
    if len(edges) < 4 or any(e < 0 for e in edges):
        QMessageBox.warning(window, "Edge Error",
                            "All four pipe edges must be different and valid.")
        return None

    window.progress.setValue(0)
    window.progress.setFormat("Building mesh...")
    QApplication.processEvents()

    tpms_type = window.combo_tpms.currentText()
    Lcell = float(window.le_Lcell.text())
    t_wall = float(window.le_t.text())
    k_s = float(window.le_ks.text())
    eps = window._eps_A
    g = tpms_geometry(tpms_type, Lcell, t_wall, k_s)

    x, y = verts[:, 0], verts[:, 1]
    poly_area = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))

    # Auto mesh density: ~15 cells along the shortest edge
    n_v = len(verts)
    min_edge = min(np.linalg.norm(verts[(i+1) % n_v] - verts[i])
                   for i in range(n_v))
    h_auto = min_edge / 15.0
    auto_target = max(int(poly_area / (h_auto**2 * np.sqrt(3) / 4)), 500)

    user_text = window.le_mesh_density.text().strip()
    if user_text == "" or user_text.lower() == "auto":
        target_cells = auto_target
        window.le_mesh_density.setText(str(target_cells))
    else:
        try:
            target_cells = int(user_text)
        except ValueError:
            target_cells = auto_target
            window.le_mesh_density.setText(str(target_cells))
    max_area = poly_area / max(target_cells, 100)
    mesh = um.TriMesh.from_polygon(verts, max_area=max_area)
    mesh.set_pipes([
        {'edge': edge_inA,  'frac_start': 0.0, 'frac_end': 1.0, 'bc': BC_INLET_A},
        {'edge': edge_outA, 'frac_start': 0.0, 'frac_end': 1.0, 'bc': BC_OUTLET_A},
        {'edge': edge_inB,  'frac_start': 0.0, 'frac_end': 1.0, 'bc': BC_INLET_B},
        {'edge': edge_outB, 'frac_start': 0.0, 'frac_end': 1.0, 'bc': BC_OUTLET_B},
    ])
    window._v_mesh_actual.setText(f"{mesh.n_cells}")
    _log(f"Mesh: {mesh.n_cells} cells")

    cfg = {
        'L': L, 'H': H, 'cp_f': cp_f,
        'u_A': u_A, 'u_B': u_B,
        'T_inA': T_inA, 'T_inB': T_inB,
        'shape': shape, 'verts': verts,
        'edge_inA': edge_inA, 'edge_outA': edge_outA,
        'edge_inB': edge_inB, 'edge_outB': edge_outB,
        'tpms_type': tpms_type, 'Lcell': Lcell,
        't_wall': t_wall, 'k_s': k_s, 'eps': eps, 'g': g,
        'mesh': mesh,
        'BC_OUTLET_A': BC_OUTLET_A,
        'BC_OUTLET_B': BC_OUTLET_B,
    }
    return cfg


def _build_fields(window, cfg, _log):
    """Phase 2: no separate field arrays for polygon (mesh IS the field).
    Prepares the solver progress callback and returns fields dict."""
    def _on_progress(step, total):
        pct = min(100, int(step / total * 100))
        window.progress.setValue(pct)
        window.progress.setFormat(f"Computing...  {pct}%")
        QApplication.processEvents()

    window.progress.setFormat("Solving...")
    QApplication.processEvents()

    fields = {'on_progress': _on_progress}
    return fields


def _run_solvers(window, cfg, fields, _log):
    """Phase 3: call solve_polygon_domain and return raw result arrays."""
    mesh = cfg['mesh']
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        sol = solve_polygon_domain(
            mesh, cfg['tpms_type'], cfg['Lcell'], cfg['t_wall'],
            cfg['eps'], cfg['g']['D_h'],
            window._rho_A, window._mu_A, window._rho_B, window._mu_B,
            cfg['T_inA'], cfg['T_inB'], cfg['u_A'], cfg['u_B'],
            cfg['edge_inA'], cfg['edge_inB'],
            window._K_ffA, window._K_ffB, window._K_ss,
            window._h_vA, window._h_vB,
            cfg['cp_f'], A_0=cfg['g']['A_0'],
            progress_cb=fields['on_progress'], verbose=True)
    re_warns = [str(w.message) for w in caught if 'Re <' in str(w.message)]
    _log("Solve done")

    result = dict(sol)
    result['re_warns'] = re_warns
    return result


def _store_results(window, cfg, fields, result, _log):
    """Phase 4: build plots, update result labels and status bar."""
    mesh = cfg['mesh']
    shape = cfg['shape']
    tpms_type = cfg['tpms_type']
    re_warns = result['re_warns']

    # ── Prepare plot data ──
    window.progress.setFormat("Plotting...")
    QApplication.processEvents()

    def _cell_to_node(field):
        nv = np.zeros(mesh.n_nodes); wt = np.zeros(mesh.n_nodes)
        np.add.at(nv, mesh.cells.ravel(), np.repeat(field, 3))
        np.add.at(wt, mesh.cells.ravel(), 1)
        return nv / np.maximum(wt, 1)

    _t = get_theme()

    def _pub_axes(ax):
        ax.set_facecolor(_t['ax_bg'])
        ax.set_aspect('equal')
        ax.tick_params(labelsize=10, colors=_t['ax_text'], direction='in')
        ax.set_xlabel('$x$ [mm]', fontsize=11, color=_t['ax_text'])
        ax.set_ylabel('$y$ [mm]', fontsize=11, color=_t['ax_text'])
        for sp in ax.spines.values():
            sp.set_edgecolor(_t['ax_spine'])

    def _clip_pct(arr, lo=1, hi=99):
        vmin, vmax = np.percentile(arr, [lo, hi])
        return np.clip(arr, vmin, vmax), vmin, vmax

    def _safe(field):
        """Replace NaN/Inf with field median so plots don't crash."""
        f = np.array(field, dtype=np.float64)
        bad = ~np.isfinite(f)
        if bad.any():
            med = np.nanmedian(f[~bad]) if (~bad).any() else 0.0
            f[bad] = med
            _log(f"  Cleaned {bad.sum()} NaN/Inf values")
        return f

    nTa = _cell_to_node(_safe(result['Ta']))
    nTb = _cell_to_node(_safe(result['Tb']))
    nTs = _cell_to_node(_safe(result['Ts']))
    nPA = _cell_to_node(_safe(result['P_A']))
    nPB = _cell_to_node(_safe(result['P_B']))
    # Velocity: Laplacian smoothing kills degenerate-cell outliers
    # Vectorized gather/scatter form (audit M-e / P5, 2026-05-28); the
    # original Python triple-loop ran 8 * n_cells * 3 iterations and was
    # the dominant cost of build_2d_field_results for large meshes.
    def _smooth(field, n_passes=8):
        f = np.asarray(field, dtype=np.float64).copy()
        nbr = mesh.nbr  # shape (n_cells, 3); -1 marks boundary
        # Sentinel: route -1 -> len(f) and zero its contribution via mask.
        idx = np.where(nbr >= 0, nbr, f.size).astype(np.int64)
        mask = (nbr >= 0).astype(np.float64)
        cnt = mask.sum(axis=1)
        for _ in range(n_passes):
            f_pad = np.concatenate([f, [0.0]])
            nbr_sum = (f_pad[idx] * mask).sum(axis=1)
            f = (f + nbr_sum) / (1.0 + cnt)
        return f

    nUmagA = _cell_to_node(_smooth(_safe(
        np.sqrt(result['u_A']**2 + result['v_A']**2))))
    nUmagB = _cell_to_node(_smooth(_safe(
        np.sqrt(result['u_B']**2 + result['v_B']**2))))

    T_min = min(nTa.min(), nTb.min(), nTs.min())
    T_max = max(nTa.max(), nTb.max(), nTs.max())
    _log("Node values done")

    # ── Triangulation + interpolation grid ──
    triang = mtri.Triangulation(mesh.nodes[:, 0] * 1000,
                                 mesh.nodes[:, 1] * 1000,
                                 mesh.cells)
    # Remove zero-area triangles to avoid invalid triangulation
    areas = mesh.cell_areas
    if np.any(areas < 1e-30):
        mask = areas < 1e-30
        triang.set_mask(mask)
        _log(f"Masked {mask.sum()} degenerate triangles")

    # Try building interpolation grid; fall back to tricontourf
    _use_interp = False
    try:
        _nfine = 200
        _xi = np.linspace(mesh.nodes[:, 0].min() * 1000,
                          mesh.nodes[:, 0].max() * 1000, _nfine)
        _yi = np.linspace(mesh.nodes[:, 1].min() * 1000,
                          mesh.nodes[:, 1].max() * 1000, _nfine)
        _Xi, _Yi = np.meshgrid(_xi, _yi)
        # Test with a simple field to verify interpolator works
        _test = mtri.LinearTriInterpolator(triang, nTa)
        _test(_Xi[:1, :1], _Yi[:1, :1])
        _use_interp = True
        _log("Using interpolated contourf (smooth)")
    except Exception as exc:
        _log(f"Interpolation unavailable ({exc}), "
             f"using tricontourf")

    def _safe_levels(vmin, vmax, n=512):
        """Ensure levels span a non-zero range."""
        if not np.isfinite(vmin): vmin = 0.0
        if not np.isfinite(vmax): vmax = 1.0
        if vmax - vmin < 1e-10:
            vmin -= 0.5; vmax += 0.5
        return np.linspace(vmin, vmax, n)

    def _contour(ax, field, levels, cmap):
        """Plot contour — interpolated if possible, else tri."""
        if _use_interp:
            Zi = mtri.LinearTriInterpolator(
                triang, field)(_Xi, _Yi)
            Zi = np.ma.array(np.asarray(Zi),
                             mask=np.isnan(np.asarray(Zi)))
            return ax.contourf(_Xi, _Yi, Zi, levels=levels,
                               cmap=cmap, extend='both')
        return ax.tricontourf(triang, field, levels=levels,
                              cmap=cmap, extend='both')

    def _plot_row(fig, plot_fields, titles, cmaps, vmins, vmaxs,
                  cb_labels, suptitle):
        fig.clear()
        fig.patch.set_facecolor(_t['fig_bg'])
        gs = GridSpec(2, 3, figure=fig,
                      height_ratios=[1, 0.04], hspace=0.22,
                      wspace=0.15)
        for i in range(3):
            ax  = fig.add_subplot(gs[0, i])
            cax = fig.add_subplot(gs[1, i])
            levels = _safe_levels(vmins[i], vmaxs[i])
            cf = _contour(ax, plot_fields[i], levels, cmaps[i])
            ax.set_title(titles[i], fontsize=12,
                         fontweight='bold', color=_t['ax_text'], pad=4)
            _pub_axes(ax)
            if i > 0:
                ax.set_ylabel('')
                ax.tick_params(labelleft=False)
            cb = fig.colorbar(cf, cax=cax,
                              orientation='horizontal')
            cb.set_label(cb_labels[i], fontsize=10,
                         color=_t['ax_text'], labelpad=2)
            cb.ax.tick_params(labelsize=9, colors=_t['ax_text'],
                              length=2, pad=1)
            cb.locator = plt.MaxNLocator(nbins=6, integer=True)
            cb.update_ticks()
        fig.suptitle(suptitle, fontsize=13, fontweight='bold',
                     color=_t['ax_text'], y=0.97)
        fig.subplots_adjust(top=0.90, bottom=0.08,
                            left=0.05, right=0.97)

    # ── Temperature ──
    _plot_row(
        window.canvas_temp.fig,
        [nTa, nTb, nTs],
        [r'Fluid A, $T_{f,A}$', r'Fluid B, $T_{f,B}$',
         r'Solid, $T_s$'],
        ['jet'] * 3,
        [T_min] * 3, [T_max] * 3,
        ['Temperature [K]'] * 3,
        f'{shape} Domain  |  {tpms_type} TPMS  |  '
        f'{mesh.n_cells} cells')
    window.canvas_temp.draw()
    _log("Temp plot done")
    QApplication.processEvents()

    # ── Pressure (each fluid gets its own range) ──
    dP_node = nPA - nPB
    dP_abs = max(abs(dP_node.min()), abs(dP_node.max()), 1e-6)
    _plot_row(
        window.canvas_pres.fig,
        [nPA, nPB, dP_node],
        [r'Fluid A, $P_A$', r'Fluid B, $P_B$',
         r'$\Delta P = P_A - P_B$'],
        ['viridis', 'viridis', 'coolwarm'],
        [0, 0, -dP_abs],
        [nPA.max(), nPB.max(), dP_abs],
        ['Pressure [Pa]', 'Pressure [Pa]',
         'Pressure difference [Pa]'],
        f'{shape} Domain  |  Pressure Fields')
    window.canvas_pres.draw()
    _log("Pressure plot done")
    QApplication.processEvents()

    # ── Velocity (1×2, tricontourf — robust for any mesh) ──
    fig_v = window.canvas_vel.fig
    fig_v.clear(); fig_v.patch.set_facecolor(_t['fig_bg'])
    gs_v = GridSpec(2, 2, figure=fig_v,
                    height_ratios=[1, 0.04], hspace=0.22, wspace=0.15)
    for i, (nf_raw, title) in enumerate([
        (nUmagA, r'Fluid A, $|\mathbf{U}_A|$'),
        (nUmagB, r'Fluid B, $|\mathbf{U}_B|$'),
    ]):
        nf, vlo, vhi = _clip_pct(nf_raw, lo=0.5, hi=99.5)
        ax  = fig_v.add_subplot(gs_v[0, i])
        cax = fig_v.add_subplot(gs_v[1, i])
        levels = _safe_levels(vlo, vhi)
        cf = ax.tricontourf(triang, nf, levels=levels,
                            cmap='turbo', extend='both')
        ax.set_title(title, fontsize=12, fontweight='bold',
                     color=_t['ax_text'], pad=4)
        _pub_axes(ax)
        if i > 0:
            ax.set_ylabel(''); ax.tick_params(labelleft=False)
        cb = fig_v.colorbar(cf, cax=cax, orientation='horizontal')
        cb.set_label('Velocity [m/s]', fontsize=10,
                     color=_t['ax_text'], labelpad=2)
        cb.ax.tick_params(labelsize=9, colors=_t['ax_text'],
                          length=2, pad=1)
    fig_v.suptitle(f'{shape} Domain  |  Velocity Fields',
                   fontsize=13, fontweight='bold',
                   color=_t['ax_text'], y=0.97)
    fig_v.subplots_adjust(top=0.90, bottom=0.08,
                          left=0.06, right=0.97)
    window.canvas_vel.draw()
    _log("Velocity plot done")

    # ── Update results ──
    BC_OUTLET_A = cfg['BC_OUTLET_A']
    BC_OUTLET_B = cfg['BC_OUTLET_B']
    window._r_dP_A.setText(
        f"{abs(result['P_A'].max() - result['P_A'].min()):.1f}")
    window._r_dP_B.setText(
        f"{abs(result['P_B'].max() - result['P_B'].min()):.1f}")
    outA = {ci for ci in range(mesh.n_cells)
            for fi in range(3)
            if mesh.bc_type[ci, fi] == BC_OUTLET_A}
    outB = {ci for ci in range(mesh.n_cells)
            for fi in range(3)
            if mesh.bc_type[ci, fi] == BC_OUTLET_B}
    if outA:
        window._r_ToutA.setText(
            f"{result['Ta'][list(outA)].mean():.1f}")
    if outB:
        window._r_ToutB.setText(
            f"{result['Tb'][list(outB)].mean():.1f}")

    if re_warns:
        window.statusBar().showMessage(
            f"Warning: {re_warns[0]}", 10000)
    else:
        window.statusBar().showMessage(
            f"Done: {mesh.n_cells} cells, {shape} domain", 5000)

    window.slider.hide()
    window.progress.setValue(100)
    window.progress.setFormat("Done")
    _log("All done")
