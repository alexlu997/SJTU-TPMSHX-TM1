"""Publish finished compute data, render fields and expose result diagnostics.

RunControllerMixin owns worker dispatch and cancellation; this mixin only
consumes ComputeResult and writes the GUI's result cache and scalar snapshot.
"""

from __future__ import annotations

from dataclasses import replace

from sjtu_tpmshx.ui.ui_constants import TOAST_MS_SHORT


class RunResultsMixin:
    """ComputeResult→window adapter + plot finalizer + diagnostics surface."""

    def _finalize_plots(self):
        """Show the initial temperature plot; other fields render on demand."""
        from sjtu_tpmshx.ui.plot_2d_results import finalize_plots, ensure_result_plot
        self.setUpdatesEnabled(False)
        try:
            out = finalize_plots(self)
            for field, dialog in getattr(self, '_detached_canvases', {}).items():
                if field in ('temp', 'pres', 'vel') and dialog.isVisible():
                    ensure_result_plot(self, field)
        finally:
            self.setUpdatesEnabled(True)
        return out

    def write_result(self, result):
        """Publish one ComputeResult for rendering, diagnostics and export."""
        # ui-plan3-workbench T2: one diagnostics snapshot per run, consumed
        # by the result sidebar + the 诊断详情 dialog. Built BEFORE the 3D
        # early-return so both modes fill it.
        # robustness-hardening (2026-07-03): surface the first-class
        # convergence verdict — a diverged solve used to display Q/dP
        # indistinguishably from a good one.
        if not getattr(result, 'converged', True):
            _nc_msg = ("求解未收敛 — Q/ΔP 来自未收敛场，仅供参考"
                       "（请查看诊断，核对工况、网格与迭代预算后重算）。")
            if _nc_msg not in result.warnings:
                result.warnings.insert(0, _nc_msg)
        from copy import deepcopy
        self._tout_K_cache = (result.T_out_A_K, result.T_out_B_K)
        self._result_Q_unit = result.metadata.get('units', {}).get(
            'Q', 'W' if result.diagnostics.get('mode') == '3d' else 'W/m')
        self._result_model_metadata = {key: deepcopy(result.metadata[key])
                                       for key in ('darcy_forchheimer', 'sco2_nu', 'sco2_enthalpy_eos')
                                       if key in result.metadata}
        self._diag_summary = {
            'mode': result.diagnostics.get('mode', '2d'),
            'converged': bool(getattr(result, 'converged', True)),
            'Q_W': result.Q_W,
            'Q_unit': self._result_Q_unit,
            'dP_A': result.dP_A_Pa, 'dP_B': result.dP_B_Pa,
            'Q_A': result.residuals.get('Q_A'),
            'Q_B': result.residuals.get('Q_B'),
            'Q_net': result.residuals.get('Q_net'),
            'closure_rel': result.residuals.get('energy_imbalance_rel'),
            'closure_basis': '主网格两侧有符号焓流',
            'Q_definition': result.metadata.get('metric_definitions', {}).get('Q', {}),
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

        # Only the latest published run owns the summary, plots and exports.
        # A new accepted result also invalidates readiness of the old 3D views.
        self._3d_view_ready = False
        self._rendered_3d_slices = False
        # 3D renderers consume ComputeResult directly.
        if result.diagnostics.get('mode') == '3d':
            self.cache.clear('2d')
            self.cache.set_result('3d', result)
            self._extrap_reasons = list(result.extrap_reasons)
            self._has_extrap = bool(result.extrap_reasons)
            return

        self.cache.clear('3d')
        # Keep the 2D publication snapshot isolated from later edits to the
        # source containers, while retaining the existing field-array sharing.
        self.cache.set_result('2d', replace(
            result, fields=dict(result.fields), residuals=dict(result.residuals),
            metadata=deepcopy(result.metadata), warnings=list(result.warnings),
            extrap_reasons=list(result.extrap_reasons),
            diagnostics={**result.diagnostics, 'convergence_detail': dict(
                result.diagnostics.get('convergence_detail') or {})},
        ))
        self._compute_warnings = list(result.warnings)
        self._extrap_reasons = list(result.extrap_reasons)
        self._has_extrap = bool(result.extrap_reasons)

        # Boundaries used by the zone overlays.
        if result.zones is not None:
            self._zone_axis_dir = result.zones.get('axis_dir')
            self._zone_boundaries = result.zones.get('boundaries')
            self._zone_boundaries_x = result.zones.get('boundaries_x')
            self._zone_boundaries_y = result.zones.get('boundaries_y')
        else:
            self._zone_axis_dir = None
            self._zone_boundaries = None
            self._zone_boundaries_x = None
            self._zone_boundaries_y = None

    def _update_result_summary(self):
        """Refresh the visible footer from the published scalar snapshot."""
        from sjtu_tpmshx.ui.builders_sidebar import (
            refresh_result_sidebar, update_result_sidebar_visibility,
        )
        refresh_result_sidebar(self)
        update_result_sidebar_visibility(self)

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
            "换热量口径：主网格 A 侧边界焓流绝对值；两侧焓流以放热为正。",
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
        timings = d.get('timings_s')
        if timings:
            lines.append("阶段耗时：" + " · ".join(
                f"{label} {_f(timings.get(key), '{:.3f}')} s"
                for key, label in (('prepare', '准备'), ('solve', '求解'),
                                   ('postprocess', '后处理'), ('display', '显示'))))
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
