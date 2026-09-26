"""Sensitivity sweep — N×N surrogate evaluation of two parameters.

Uses the air-only 0-D `tpms_calc.compute` correlation for Fluid A to rank
cell size, wall thickness and velocity. Pressure loss uses the fixed CFD
baseline; Q/volume uses an assumed 40 K difference. Click a valid heatmap
cell to load that configuration into the main input fields.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QLineEdit,
)

from .theme import FIELD_CMAP, get_theme
from .matplotlib_canvas import MatplotlibCanvas


# Available sweep parameters: (key, label, unit, default_min, default_max)
_SWEEP_PARAMS = [
    ('L_cell', 'TPMS cell L', 'mm', 4.0, 8.0),
    ('t',     'Wall thickness t', 'mm', 0.3, 0.6),
    ('u_A',   'Fluid A velocity', 'm/s', 1.0, 30.0),
]

# Metrics the heatmap can display
_METRICS = [
    ('Q_per_vol',   'Q / volume',       'W / m³'),
    ('dP_per_L',    'ΔP / length',      'Pa / m'),
    ('h_v',         'Volumetric h_v',   'W/m³·K'),
    ('ratio',       'h_v / (ΔP/L)',     'W/(m²·K·Pa)'),
]

_SCOPE_NOTE = (
    "Fluid A only: air correlations. Pressure loss uses the CFD baseline "
    "without experimental correction. Q/volume = h_v × 40 K is a ranking "
    "estimate. Click a valid cell to load parameters into the main inputs.")


def _eval_surrogate(tpms, L_cell_mm, t_mm, u, T_in_K, P_in_Pa, k_s):
    """One air-only surrogate evaluation; not a two-stream heat-duty solve."""
    from sjtu_tpmshx.models.tpms_calc import compute as _tpms_compute
    r = _tpms_compute(tpms, L_cell_mm, t_mm, u, T_in_K, P_in_Pa, k_s)
    h_v = r.get('h_v') or (
        r['H_sf'] * r.get('A_0', 0.0))
    dT = 40.0  # heuristic fluid→solid ΔT for ranking (cancels out for ratio)
    Q_vol = h_v * dT
    return {
        'Q_per_vol': Q_vol,
        'dP_per_L': r['dP_per_L'],
        'h_v': h_v,
        'ratio': h_v / max(r['dP_per_L'], 1e-9),
        'Re': r['Re'],
        'Nu': r['Nu'],
    }


class SensitivityDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self.setWindowTitle("Sensitivity sweep")
        self.resize(980, 720)

        t = get_theme()
        _surface = t.get('surface_raised', t['card_bg'])
        _border = t.get('border_subtle', t['card_border'])
        _sub = t.get('sub_fg', t['fg'])

        self.setStyleSheet(
            f"QDialog{{background:{_surface}; color:{t['fg']};}}")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14); root.setSpacing(12)

        # Control strip
        ctrl = QHBoxLayout(); ctrl.setSpacing(10)
        self._combo_x = QComboBox(); self._combo_y = QComboBox()
        self._combo_m = QComboBox()
        for key, lbl, unit, *_ in _SWEEP_PARAMS:
            self._combo_x.addItem(f"{lbl} [{unit}]", key)
            self._combo_y.addItem(f"{lbl} [{unit}]", key)
        self._combo_x.setCurrentIndex(0)
        self._combo_y.setCurrentIndex(1)
        for key, lbl, unit in _METRICS:
            self._combo_m.addItem(f"{lbl} [{unit}]", key)
        self._combo_m.setCurrentIndex(3)  # default h_v/(dP/L) ratio

        from .field_factory import default_factory
        _tm = default_factory().theme
        for cb in (self._combo_x, self._combo_y, self._combo_m):
            cb.setStyleSheet(_tm.style('COMBO'))
            cb.setFixedHeight(30)
            # 2026-05-20 UI sweep (Tier 21): invalidate the cached sweep
            # grid whenever an axis/metric selection changes. Without
            # this, the heatmap kept showing the PREVIOUS sweep's data
            # while the combos advertised new axes — clicking a cell
            # then loaded parameters decoded against the stale axis
            # mapping (wrong L_cell / t pushed into the main inputs).
            cb.currentIndexChanged.connect(self._invalidate_grid)

        self._le_steps = QLineEdit("9")
        self._le_steps.setFixedWidth(56)
        self._le_steps.setStyleSheet(_tm.style('INP'))
        self._le_steps.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_x = QLabel("X axis:"); lbl_y = QLabel("Y axis:")
        lbl_m = QLabel("Metric:"); lbl_n = QLabel("Steps:")
        for l in (lbl_x, lbl_y, lbl_m, lbl_n):
            l.setStyleSheet(_tm.style('LBL'))

        ctrl.addWidget(lbl_x); ctrl.addWidget(self._combo_x, 1)
        ctrl.addWidget(lbl_y); ctrl.addWidget(self._combo_y, 1)
        ctrl.addWidget(lbl_m); ctrl.addWidget(self._combo_m, 1)
        ctrl.addWidget(lbl_n); ctrl.addWidget(self._le_steps)

        btn_run = QPushButton("Run sweep")
        btn_run.setFixedHeight(32)
        btn_run.setMinimumWidth(120)
        btn_run.setStyleSheet(_tm.style('BTN_PRIMARY'))
        btn_run.clicked.connect(self._run_sweep)
        ctrl.addWidget(btn_run)
        # Tier 24: keep a handle so _run_sweep can disable it during the
        # synchronous N×N sweep (prevents re-entrant launches + signals
        # "busy").
        self._btn_run = btn_run
        root.addLayout(ctrl)

        # Heatmap canvas
        self._canvas = MatplotlibCanvas(1, 1, figsize=(9, 6))
        self._canvas.setStyleSheet(
            f"background:{t['card_bg']}; border:1px solid {_border};"
            "border-radius:6px;")
        root.addWidget(self._canvas, 1)

        # Hint footer
        hint = self._hint = QLabel(_SCOPE_NOTE)
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color:{_sub}; font-size:9pt; font-style:italic;"
            "background:transparent; border:none;")
        root.addWidget(hint)

        self._grid_params = None  # (X, Y, key_x, key_y, key_m)
        self._canvas.mpl_connect('button_press_event', self._on_click)

    def _invalidate_grid(self, *_, message="Selection changed — click ‘Run sweep’."):
        """Drop the cached sweep grid + clear the heatmap. Called when an
        axis/metric combo changes so a stale grid cannot be clicked.
        Added 2026-05-20 UI sweep (Tier 21)."""
        if getattr(self, '_grid_params', None) is None:
            return
        self._grid_params = None
        try:
            fig = self._canvas.fig
            fig.clear()
            ax = fig.add_subplot(111)
            t = get_theme()
            ax.set_facecolor(t.get('ax_bg', '#fff'))
            ax.text(0.5, 0.5, message,
                    ha='center', va='center', color=t.get('sub_fg', '#888'),
                    fontsize=10, transform=ax.transAxes)
            ax.set_xticks([]); ax.set_yticks([])
            self._canvas.draw_idle()
        except Exception:
            pass

    def _collect_fixed_params(self):
        w = self._window
        try:
            tpms_idx = w.combo_tpms.currentIndex()
            tpms = "Gyroid" if tpms_idx == 1 else "Diamond"
        except Exception:
            tpms = "Gyroid"
        def _read(attr, default):
            wid = getattr(w, attr, None)
            if wid is None:
                return default
            try:
                return float(wid.text())
            except Exception:
                return default
        # 2026-05-20 UI sweep (Tier 24): T_in MUST go through the main
        # window's `_temp_to_K` so the K/°C header toggle is honoured.
        # Previously it was read as a raw float — when the UI was in °C
        # mode, a value like 148.85 °C was passed to the surrogate as
        # 148.85 K, producing badly wrong thermophysical properties and
        # dP across the whole sweep.
        _le_tin = getattr(w, 'le_TinA', None)
        if _le_tin is not None and hasattr(w, '_temp_to_K'):
            try:
                T_in = float(w._temp_to_K(_le_tin))
            except Exception:
                T_in = 422.0
        else:
            T_in = _read('le_TinA', 422.0)
        return {
            'tpms': tpms,
            'L_cell': _read('le_Lcell', 7.0),
            't':     _read('le_t', 0.5),
            'u_A':   _read('le_uA', 20.0),
            'T_in':  T_in,
            'P_in':  _read('le_PinA', 192362.0),
            'k_s':   _read('le_ks', 16.0),
        }

    def _range_for(self, key):
        for k, lbl, unit, lo, hi in _SWEEP_PARAMS:
            if k == key:
                return lo, hi
        return 1.0, 10.0

    def _run_sweep(self):
        from .window_config import _parse_fluid_label
        fluid = _parse_fluid_label(getattr(self._window, 'combo_fluidA', None))
        if fluid != 'air':
            self._invalidate_grid(message=f"Fluid A must be Air (selected: {fluid}).")
            self._hint.setText(
                f"Cannot run: Fluid A must be Air (selected: {fluid}). " + _SCOPE_NOTE)
            return
        self._hint.setText(_SCOPE_NOTE)
        key_x = self._combo_x.currentData()
        key_y = self._combo_y.currentData()
        key_m = self._combo_m.currentData()
        if key_x == key_y:
            self._window.statusBar().showMessage(
                "Sweep axes must differ.", 5000)
            return
        try:
            n = max(3, min(25, int(self._le_steps.text())))
        except Exception:
            n = 9
        lo_x, hi_x = self._range_for(key_x)
        lo_y, hi_y = self._range_for(key_y)
        xs = np.linspace(lo_x, hi_x, n)
        ys = np.linspace(lo_y, hi_y, n)
        fixed = self._collect_fixed_params()
        grid = np.zeros((n, n))
        # 2026-05-20 UI sweep (Tier 24):
        #  (#5) disable the Run button + show a busy status while the
        #       synchronous sweep runs, and pump the event loop once per
        #       row so the window does not look frozen during the up-to
        #       625 surrogate calls. (A full worker-thread port is the
        #       longer-term fix; this keeps the UI responsive cheaply.)
        #  (#4) collect failures so a swept grid full of NaN is not
        #       presented as if it were valid — surface the count + the
        #       first error message instead of silently plotting blanks.
        from PySide6.QtWidgets import QApplication as _QApp
        _btn = getattr(self, '_btn_run', None)
        if _btn is not None:
            try:
                _btn.setEnabled(False)
            except Exception:
                pass
        _fail_n = 0
        _fail_msg = ""
        try:
            for i, vx in enumerate(xs):
                for j, vy in enumerate(ys):
                    args = dict(fixed)
                    args[key_x] = float(vx)
                    args[key_y] = float(vy)
                    try:
                        out = _eval_surrogate(
                            args['tpms'], args['L_cell'], args['t'],
                            args['u_A'], args['T_in'], args['P_in'],
                            args['k_s'])
                        grid[j, i] = out.get(key_m, 0.0)
                    except Exception as _e:
                        grid[j, i] = np.nan
                        _fail_n += 1
                        if not _fail_msg:
                            _fail_msg = str(_e)
                # Pump the event loop after each row so the dialog repaints
                # and stays responsive on large N.
                try:
                    self._window.statusBar().showMessage(
                        f"Sensitivity sweep … row {i + 1}/{n}", 2000)
                    _QApp.processEvents()
                except Exception:
                    pass
        finally:
            if _btn is not None:
                try:
                    _btn.setEnabled(True)
                except Exception:
                    pass

        self._grid_params = {
            'xs': xs, 'ys': ys, 'grid': grid,
            'key_x': key_x, 'key_y': key_y, 'key_m': key_m,
            'fixed': fixed,
        }
        self._plot()
        # Surface sweep failures explicitly (#4).
        if _fail_n:
            try:
                self._window.statusBar().showMessage(
                    f"Sensitivity sweep: {_fail_n}/{n * n} points failed "
                    f"(shown as blank cells). First error: {_fail_msg}", 10000)
            except Exception:
                pass

    def _plot(self):
        if self._grid_params is None:
            return
        gp = self._grid_params
        xs = gp['xs']; ys = gp['ys']; grid = gp['grid']
        key_x = gp['key_x']; key_y = gp['key_y']; key_m = gp['key_m']

        t = get_theme()
        fig = self._canvas.fig
        fig.clear()
        fig.patch.set_facecolor(t['fig_bg'])
        ax = fig.add_subplot(111)
        self._grid_axes = ax
        ax.set_facecolor(t['ax_bg'])

        im = ax.pcolormesh(xs, ys, grid, shading='nearest', cmap=FIELD_CMAP)
        try:
            levels = np.linspace(np.nanmin(grid), np.nanmax(grid), 8)
            ax.contour(xs, ys, grid, levels=levels, colors='white',
                       alpha=0.35, linewidths=0.6)
        except Exception:
            pass

        label_map = {k: (lbl, unit) for k, lbl, unit, *_ in _SWEEP_PARAMS}
        m_map = {k: (lbl, unit) for k, lbl, unit in _METRICS}
        x_lbl, x_unit = label_map.get(key_x, (key_x, ''))
        y_lbl, y_unit = label_map.get(key_y, (key_y, ''))
        m_lbl, m_unit = m_map.get(key_m, (key_m, ''))
        ax.set_xlabel(f"{x_lbl}  [{x_unit}]", fontsize=10,
                      color=t['ax_text'])
        ax.set_ylabel(f"{y_lbl}  [{y_unit}]", fontsize=10,
                      color=t['ax_text'])
        ax.set_title(f"Air sensitivity — {m_lbl}\nPressure loss: CFD baseline", fontsize=12,
                     color=t['ax_text'], loc='left', pad=6)
        ax.tick_params(colors=t['ax_text'], labelsize=9)
        for sp in ax.spines.values():
            sp.set_edgecolor(t['ax_spine'])
        cb = fig.colorbar(im, ax=ax)
        cb.set_label(f"{m_lbl}  [{m_unit}]", fontsize=9,
                      color=t['ax_text'])
        cb.ax.tick_params(colors=t['ax_text'], labelsize=8)
        cb.outline.set_edgecolor(t['ax_spine'])
        fig.subplots_adjust(left=0.10, right=0.92, top=0.92, bottom=0.10)
        self._canvas.draw()

    def _on_click(self, event):
        if (self._grid_params is None or event.inaxes is None
                or event.inaxes is not getattr(self, '_grid_axes', None)):
            return
        gp = self._grid_params
        xs = gp['xs']; ys = gp['ys']
        x_click = event.xdata; y_click = event.ydata
        if x_click is None or y_click is None:
            return
        i = int(np.argmin(np.abs(xs - x_click)))
        j = int(np.argmin(np.abs(ys - y_click)))
        if not np.isfinite(gp['grid'][j, i]):
            return
        vx = float(xs[i]); vy = float(ys[j])
        # 2026-05-20 UI sweep (Tier 24): a picked design changes the input
        # fields, so the previous compute result is now stale. Invalidate
        # it up front (same helper the preset / recent-run paths use), so
        # the result tabs disable and the user is not left looking at the
        # old plots beside the new inputs.
        if hasattr(self._window, '_invalidate_results_for_preset_load'):
            try:
                self._window._invalidate_results_for_preset_load()
            except Exception:
                pass
        # Write the picked params into the matching left-panel fields.
        attr_map = {'L_cell': 'le_Lcell', 't': 'le_t', 'u_A': 'le_uA'}
        for key, val in ((gp['key_x'], vx), (gp['key_y'], vy)):
            attr = attr_map.get(key)
            if attr is None:
                continue
            le = getattr(self._window, attr, None)
            if le is not None:
                le.setText(f"{val:.4g}")
                # Emit editingFinished so the programmatic change is
                # captured by the global Undo stack (which hooks that
                # signal) — Ctrl+Z can then revert a Pareto/heatmap pick.
                try:
                    le.editingFinished.emit()
                except Exception:
                    pass
        self._window.statusBar().showMessage(
            f"Loaded {gp['key_x']}={vx:.3g}, {gp['key_y']}={vy:.3g}. "
            "Close this dialog and click Compute.", 6000)


def open_sensitivity(window):
    dlg = SensitivityDialog(window)
    dlg.exec()
