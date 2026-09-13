"""Result-presentation slice of ``Main_Menu`` (P2.5a, 2026-07-20).

Moved verbatim from ``ui/mixins/run_controller.py`` — the ComputeResult →
window adapter (write_result), the plot finalizer (_finalize_plots), and
the summary/diagnostics surface (_update_result_summary /
_diag_summary_text / _show_diag_dialog). 5 methods.

Presentation only: consumes a finished
:class:`domain.compute_result.ComputeResult`; never launches or cancels
compute (that stays in RunControllerMixin, which calls into this slice
via ``self`` through the ``Main_Menu`` MRO). Deps are function-local
imports plus the TOAST constant — no main.py module state.
"""

from __future__ import annotations

from sjtu_tpmshx.ui.ui_constants import TOAST_MS_SHORT


class RunResultsMixin:
    """ComputeResult→window adapter + plot finalizer + diagnostics surface."""

    def _finalize_plots(self):
        """Thin wrapper — delegates to run_calculation module (Task B.9).
        Freezes repaints around the multi-canvas population so the user
        sees one clean frame flip instead of five intermediate paints."""
        from sjtu_tpmshx.ui.plot_2d_results import finalize_plots
        self.setUpdatesEnabled(False)
        try:
            out = finalize_plots(self)
        finally:
            self.setUpdatesEnabled(True)
        # 2026-05-22 (UI report point 1): finalize_plots renders the
        # temp/pres/vel canvases but never recorded them in _drawn_tabs, so
        # Export Figure's picker only listed "Geometry" after a 2D compute.
        # Mark them here (mirrors the 3D path's drawn.add at main.py ~4207).
        # layout/pareto are marked by their own draw routines.
        drawn = getattr(self, '_drawn_tabs', set())
        drawn.update({'temp', 'pres', 'vel'})
        self._drawn_tabs = drawn
        return out

    def write_result(self, result):
        """Copy a :class:`domain.compute_result.ComputeResult`
        onto the legacy window attributes (``_compute_results`` dict,
        ``_compute_warnings``, ``_extrap_reasons``, ``_K_ff*``,
        ``_rho_*``, ``_mu_*``, ``_h_v*``, ``_zone_*``) so the existing
        finalize_plots / redraw_temperature_panel renderers keep
        working when the compute path runs via
        :class:`controllers.compute_pipeline.Pipeline2D` instead of
        the legacy ``pipelines.stages_2d.run_calculation_inner``.

        Audit C4 (L-a-2, 2026-05-28). This is the *UI adapter*
        counterpart to ``controllers.module_adapter.to_compute_result`` — together they replace the
        pre-C4 ``pipelines.stages_2d._store_results(window, cfg, raw)``
        which conflated UI writes with result assembly. Since B2 2.1b/c
        (2026-06-13) this is the ONLY ComputeResult→window copy: the GUI
        worker returns Pipeline2D/3D's result, the GUI finished slot calls
        this adapter, and the legacy
        ``run_calculation_inner`` / ``run_calculation_3d_inner`` paths
        are deleted.
        """
        # ui-plan3-workbench T2: one diagnostics snapshot per run, consumed
        # by the result sidebar + the 诊断详情 dialog. Built BEFORE the 3D
        # early-return so both modes fill it.
        # robustness-hardening (2026-07-03): surface the first-class
        # convergence verdict — a diverged solve used to display Q/dP
        # indistinguishably from a good one.
        if not getattr(result, 'converged', True):
            _nc_msg = ("求解未收敛 — Q/ΔP 来自未收敛场，仅供参考"
                       "（提高 max_iter、放宽 tol 或加密网格后重算）。")
            if _nc_msg not in result.warnings:
                result.warnings.insert(0, _nc_msg)
        from copy import deepcopy
        self._tout_K_cache = (result.T_out_A_K, result.T_out_B_K)
        self._result_Q_unit = result.metadata.get('units', {}).get(
            'Q', 'W' if result.diagnostics.get('mode') == '3d' else 'W/m')
        label = getattr(self, '_lbl_Q_unit', None)
        if label is not None:
            label.setText(f'<i>Q</i><sub>total</sub> [{self._result_Q_unit}]')
        self._result_model_metadata = {key: deepcopy(result.metadata[key])
                                       for key in ('darcy_forchheimer', 'sco2_nu')
                                       if key in result.metadata}
        is_3d = result.diagnostics.get('mode') == '3d'
        self._diag_summary = {
            'mode': result.diagnostics.get('mode', '2d'),
            'converged': bool(getattr(result, 'converged', True)),
            'Q_W': result.Q_W,
            'Q_unit': self._result_Q_unit,
            'dP_A': result.dP_A_Pa, 'dP_B': result.dP_B_Pa,
            'Q_A': result.residuals.get('Q_enthalpy_A' if is_3d else 'Q_A'),
            'Q_B': result.residuals.get('Q_enthalpy_B' if is_3d else 'Q_B'),
            'Q_net': result.residuals.get('Q_net'),
            'closure_rel': result.residuals.get('energy_imbalance_rel'),
            'closure_basis': '全域固体交换' if is_3d else '两侧焓流',
            'envelope_valid': result.diagnostics.get('envelope_valid'),
            'envelope_warnings': list(
                result.diagnostics.get('envelope_warnings', []) or []),
            'extrap': list(result.extrap_reasons),
            'warnings': list(result.warnings),
            'iters': {k: result.diagnostics.get(k) for k in
                      ('iter_outer', 'iter_simple_A', 'iter_simple_B')},
            'wall_s': result.diagnostics.get('wall_time_s'),
            'coeffs': {k: result.coeffs.get(k) for k in
                       ('K_ffA', 'K_ffB', 'K_ss', 'h_vA', 'h_vB')},
        }

        # ── 3D branch: the renderer (ui/plot_3d_results) now consumes the
        # ComputeResult directly (B3 C5 — raw_3d dict carrier retired).
        # Publish the dataclass as window._result_3d and stop.
        if result.diagnostics.get('mode') == '3d':
            self._result_3d = result
            self._extrap_reasons = list(result.extrap_reasons)
            self._has_extrap = bool(result.extrap_reasons)
            return

        # Export must select this newly published 2D run, not a prior 3D run.
        if getattr(self, '_result_3d', None) is not None:
            self._result_3d = None
        f = result.fields
        self._compute_results = {
            'metadata': deepcopy(result.metadata),
            'converged': result.converged,
            'warnings': list(result.warnings),
            'extrap_reasons': list(result.extrap_reasons),
            'envelope_valid': result.diagnostics.get('envelope_valid'),
            'outer_converged': (result.diagnostics.get('convergence_detail') or {}
                                ).get('outer_converged'),
            'Ta': f.get('Ta'), 'Tb': f.get('Tb'), 'Ts': f.get('Ts'),
            'ucA': f.get('ucA'), 'vcA': f.get('vcA'),
            'ucB': f.get('ucB'), 'vcB': f.get('vcB'),
            **{name + '_disp': f.get(name + '_disp') for name in ('ucA', 'vcA', 'ucB', 'vcB')},
            'P_fA': f.get('P_fA'), 'P_fB': f.get('P_fB'),
            'dP_A': result.dP_A_Pa, 'dP_B': result.dP_B_Pa,
            'Q_total': result.Q_W,
            'N_x': f.get('N_x'), 'N_y': f.get('N_y'),
            'L': f.get('L'), 'H': f.get('H'),
            'dir_A': f.get('dir_A'), 'dir_B': f.get('dir_B'),
            'zone_config': f.get('zone_config'),
            'za': f.get('za'),
            'dx_arr': f.get('dx_arr'), 'dy_arr': f.get('dy_arr'),
            # (residuals_A/B snapshots dropped — they only fed the removed 2D
            # convergence plot; the solver still tracks residuals internally.)
            'Q_A': result.residuals.get('Q_A', float('nan')),
            'Q_B': result.residuals.get('Q_B', float('nan')),
            'Q_net': result.residuals.get('Q_net', float('nan')),
            'energy_imbalance_rel': result.residuals.get(
                'energy_imbalance_rel', float('nan')),
        }
        # Slider/export caches — the legacy _run_solvers wrote these
        # directly onto the window (run_calculation.py Step-2 tail); on
        # the Pipeline path those writes land on the shim and vanish, so
        # mirror them here ([np.newaxis] wrap = legacy 3D-compat shape).
        import numpy as _np
        self.T_fA = (f['Ta'][_np.newaxis] if f.get('Ta') is not None
                     else None)
        self.T_fB = (f['Tb'][_np.newaxis] if f.get('Tb') is not None
                     else None)
        self.T_s = (f['Ts'][_np.newaxis] if f.get('Ts') is not None
                    else None)
        self._compute_warnings = list(result.warnings)
        self._extrap_reasons = list(result.extrap_reasons)
        self._has_extrap = bool(result.extrap_reasons)

        # Fluid + porous coefficients — UI Fluids panel reads these
        # after Auto-Fill; Pipeline path recomputes them from cfg, so
        # forward to keep the read-out panel consistent.
        for _key in ('K_ffA', 'K_ffB', 'K_ss', 'h_vA', 'h_vB'):
            _val = result.coeffs.get(_key)
            if _val is not None:
                setattr(self, f'_{_key}', _val)
        for _key in ('rho_A', 'rho_B', 'mu_A', 'mu_B'):
            _val = result.props.get(_key)
            if _val is not None:
                setattr(self, f'_{_key}', _val)

        # Zone stats (None when zones disabled).
        if result.zones is not None:
            self._zone_axis_dir = result.zones.get('axis_dir')
            self._zone_stats = result.zones.get('stats')
            self._zone_boundaries = result.zones.get('boundaries')
            self._zone_boundaries_x = result.zones.get('boundaries_x')
            self._zone_boundaries_y = result.zones.get('boundaries_y')
        else:
            self._zone_stats = None
            self._zone_axis_dir = None
            self._zone_boundaries = None
            self._zone_boundaries_x = None
            self._zone_boundaries_y = None

    def _update_result_summary(self):
        """Mirror the headline numbers from the detail result labels into the
        prominent canvas-top summary bar. No-op if the bar was not built.

        Pro-Max upgrade: each chip compares against the previous successful
        run (stored in `_recent_runs[1]` — index 0 is the run just pushed
        by `_end_compute_ui`). Positive deltas green for Q (more heat is
        better), negative deltas green for ΔP (lower drop is better).
        Neutral gray when no prior run exists or values are identical.
        """
        if not hasattr(self, '_res_chips') or not hasattr(self, '_result_summary_bar'):
            return
        chips = self._res_chips
        def _get(attr):
            w = getattr(self, attr, None)
            if w is None:
                return None
            t = w.text().strip()
            return t if t and t != '—' else None

        # Direction: which way is "good"?  "up" → green when increased.
        pairs = [
            ('Q',     '_r_Q',     'up',      'Q'),
            ('dPA',   '_r_dP_A',  'down',    'dP_A'),
            ('dPB',   '_r_dP_B',  'down',    'dP_B'),
            ('ToutA', '_r_ToutA', 'neutral', 'ToutA'),
            ('ToutB', '_r_ToutB', 'neutral', 'ToutB'),
        ]

        prev = None
        recents = getattr(self, '_recent_runs', None)
        if recents is not None and len(recents) >= 2:
            prev = recents[1]  # index 0 is the run we just finalised

        from sjtu_tpmshx.ui.theme import get_theme as _gt
        _t = _gt()
        _up_good = _t.get('accent_green', '#22C55E')
        _bad = _gt().get('err_soft', '#F87171')
        _neutral = _t.get('sub_fg', '#94A3B8')

        for key, attr, direction, rec_key in pairs:
            chip = chips.get(key)
            if chip is None:
                continue
            v = _get(attr)
            if not v:
                chip.setText('—')
                # Clear any previously rendered delta label.
                _dl = getattr(chip, '_delta_label', None)
                if _dl is not None:
                    _dl.setText('')
                continue
            chip.setText(v)
            _dl = getattr(chip, '_delta_label', None)
            if key == 'Q' and prev is not None and prev.get('Q_unit') != getattr(self, '_result_Q_unit', None):
                if _dl is not None:
                    _dl.setText('')
                continue
            if _dl is None or prev is None or direction == 'neutral':
                if _dl is not None:
                    _dl.setText('')
                continue
            try:
                cur_f = float(v)
                prev_txt = (prev.get(rec_key) or '').strip()
                prev_f = float(prev_txt)
                if abs(prev_f) < 1e-12:
                    _dl.setText('')
                    continue
                pct = (cur_f - prev_f) / abs(prev_f) * 100.0
                arrow = '↑' if pct > 0 else ('↓' if pct < 0 else '·')
                good = (direction == 'up' and pct > 0) or \
                       (direction == 'down' and pct < 0)
                col = _up_good if good else (_bad if abs(pct) > 1e-3 else _neutral)
                _dl.setText(f"{arrow}{abs(pct):.1f}%")
                _dl.setStyleSheet(
                    f"color:{col}; font-size:8pt; font-weight:bold;"
                    "background:transparent; border:none; padding-left:4px;")
            except Exception:
                _dl.setText('')
        # UI report 2026-05-07 issue #5: the headline summary chips (Q /
        # ΔP A / ΔP B / T_out A / T_out B) are redundant with the detail
        # result frame on the Geometry page (build_page_domain). Suppress
        # the chip strip when the user is on the Geometry tab — it adds
        # value as a persistent reminder on Temperature/Pressure/Velocity/
        # 3D tabs where the inputs aren't visible.
        # ui-plan3-workbench T2: the horizontal chip strip is RETIRED — the
        # sidebar's 本次结果 card shows the same data next to the field.
        # Chips stay alive as the data carriers this method writes.
        self._result_summary_bar.setVisible(False)
        try:
            from sjtu_tpmshx.ui.builders_canvas import (refresh_result_sidebar,
                                            update_result_sidebar_visibility)
            refresh_result_sidebar(self)
            update_result_sidebar_visibility(self)
        except Exception:
            pass

    def _diag_summary_text(self):
        """Plain-text diagnostics block (ui-plan3-workbench T3) — pasteable
        into 组会/周报. Returns '' when no run has landed."""
        d = getattr(self, '_diag_summary', None)
        if not d:
            return ''
        def _f(v, fmt="{:.4g}"):
            return fmt.format(v) if isinstance(v, (int, float)) and v == v else '—'
        rel = d.get('closure_rel')
        env = d.get('envelope_valid')
        it = d.get('iters') or {}
        co = d.get('coeffs') or {}
        lines = [
            f"SJTU-TPMSHX 诊断摘要 ({d.get('mode', '2d').upper()})",
            f"Q = {_f(d.get('Q_W'))} {d.get('Q_unit', '?')} · ΔP_A = {_f(d.get('dP_A'))} Pa"
            f" · ΔP_B = {_f(d.get('dP_B'))} Pa",
            f"两侧焓流: Q_A = {_f(d.get('Q_A'))} {d.get('Q_unit', '?')} · Q_B = {_f(d.get('Q_B'))} {d.get('Q_unit', '?')}",
            f"能量闭合（{d.get('closure_basis', '两侧焓流')}） = {_f(abs(rel) * 100 if isinstance(rel, (int, float)) and rel == rel else None, '{:.2f}')} %",
            f"收敛: {'是' if d.get('converged', True) else '否（结果仅供参考）'}"
            f" · 包络: {'有效' if env else ('失效' if env is not None else '—')}"
            f" · 外推 {len(d.get('extrap') or [])} 项",
            f"迭代: 外循环 {it.get('iter_outer', '—')} · SIMPLE A/B"
            f" {it.get('iter_simple_A', '—')}/{it.get('iter_simple_B', '—')}"
            f" · 耗时 {_f(d.get('wall_s'), '{:.1f}')} s",
            f"闭合系数: K_ffA={_f(co.get('K_ffA'))} K_ffB={_f(co.get('K_ffB'))}"
            f" h_vA={_f(co.get('h_vA'))} h_vB={_f(co.get('h_vB'))}",
        ]
        for w in (d.get('warnings') or []) + (d.get('envelope_warnings') or []):
            lines.append(f"⚠ {w}")
        for e in d.get('extrap') or []:
            lines.append(f"⚠ 外推: {e}")
        return "\n".join(lines)

    def _show_diag_dialog(self):
        """诊断详情 dialog: energy ledger, coefficients, iterations,
        warnings, one-click copy (ui-plan3-workbench T3)."""
        txt = self._diag_summary_text()
        if not txt:
            self.statusBar().showMessage("暂无诊断数据 — 请先计算。",
                                         TOAST_MS_SHORT)
            return
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QPlainTextEdit,
                                       QPushButton, QHBoxLayout)
        from sjtu_tpmshx.ui.theme import get_theme as _gt
        _t = _gt()
        dlg = QDialog(self)
        dlg.setWindowTitle("诊断详情")
        dlg.resize(560, 420)
        lay = QVBoxLayout(dlg)
        view = QPlainTextEdit(txt)
        view.setReadOnly(True)
        view.setStyleSheet(
            f"QPlainTextEdit{{background:{_t['card_bg']}; color:{_t['fg']};"
            f" border:1px solid {_t['card_border']}; border-radius:6px;"
            f" font-family:{_t['mono_family']}; font-size:9pt;}}")
        lay.addWidget(view)
        row = QHBoxLayout()
        btn_copy = QPushButton("复制诊断摘要")
        def _copy():
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(self._diag_summary_text())
            self.statusBar().showMessage("诊断摘要已复制。", TOAST_MS_SHORT)
        btn_copy.clicked.connect(_copy)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dlg.accept)
        row.addStretch(1); row.addWidget(btn_copy); row.addWidget(btn_close)
        lay.addLayout(row)
        dlg.exec()
