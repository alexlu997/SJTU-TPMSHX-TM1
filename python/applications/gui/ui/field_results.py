"""Publish the accepted single-run result and display its fields and diagnostics."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import math
from time import perf_counter

from sjtu_tpmshx.applications.gui.ui.fmt import qualification_reasons
from sjtu_tpmshx.applications.gui.ui.ui_constants import TOAST_MS_MED, TOAST_MS_SHORT


def recorded_elapsed_s(result) -> float | None:
    """Return the single recorded solve duration in seconds, or None if unrecorded."""
    if result is None:
        return None
    diag = getattr(result, "diagnostics", None)
    if isinstance(diag, dict):
        ws = diag.get("wall_time_s")
        if isinstance(ws, (int, float)) and not isinstance(ws, bool) and math.isfinite(ws):
            return float(ws)
    meta = getattr(result, "metadata", None)
    if isinstance(meta, dict):
        timings = meta.get("timings_s")
        if isinstance(timings, dict):
            total = timings.get("total")
            if (
                isinstance(total, (int, float))
                and not isinstance(total, bool)
                and math.isfinite(total)
            ):
                return float(total)
    return None


class FieldResults:
    def __init__(self, window):
        self.window = window

    def finalize_plots(self):
        """Show the initial temperature plot; other fields render on demand."""
        window = self.window
        from sjtu_tpmshx.applications.gui.ui.plot_2d_results import finalize_plots, ensure_result_plot
        window.setUpdatesEnabled(False)
        try:
            out = finalize_plots(window)
            for field, dialog in window.workbench.detached_canvases.items():
                if field in ('temp', 'pres', 'vel') and dialog.isVisible():
                    ensure_result_plot(window, field)
        finally:
            window.setUpdatesEnabled(True)
        return out

    def publish(self, result):
        """Publish one ComputeResult for rendering, diagnostics and export."""
        window = self.window
        if not getattr(result, 'converged', True):
            _nc_msg = ("求解未收敛 — Q/ΔP 来自未收敛场，仅供参考"
                       "（请查看诊断，核对工况、网格与迭代预算后重算）。")
            if _nc_msg not in result.warnings:
                result.warnings.insert(0, _nc_msg)

        # Only the latest published run owns the summary, plots and exports.
        # A new accepted result also invalidates readiness of the old 3D views.
        window.workbench.volume_ready = False
        window.workbench.volume_error = False
        window.workbench.requested_3d_result = None
        window.workbench.requested_3d_action = None
        panel = getattr(window, 'canvas_3d', None)
        if panel is not None and hasattr(panel, 'hide'):
            panel.hide()
        window.workbench.rendered_slices = False
        mode = result.diagnostics.get('mode', '2d')
        # Isolate published containers while sharing the field arrays.
        window.cache.set_result(mode, replace(
            result, fields=dict(result.fields), coeffs=dict(result.coeffs),
            residuals=dict(result.residuals), zones=deepcopy(result.zones),
            metadata=deepcopy(result.metadata), warnings=list(result.warnings),
            extrap_reasons=list(result.extrap_reasons),
            diagnostics={**result.diagnostics,
                'envelope_warnings': list(result.diagnostics.get('envelope_warnings') or ()),
                'convergence_detail': dict(
                result.diagnostics.get('convergence_detail') or {})},
        ))
        from sjtu_tpmshx.applications.gui.ui.builders_sidebar import clear_sample_points
        clear_sample_points(window)

    def summary(self):
        """Read diagnostics and scalar values from the published result."""
        window = self.window
        result = window.cache.get_result()
        if result is None:
            return {}
        return {
            'mode': result.diagnostics.get('mode', '2d'),
            'converged': bool(getattr(result, 'converged', True)),
            'qualification': result.metadata.get('qualification', {}),
            'applicability_evidence': result.metadata.get('applicability_evidence', {}),
            'Q_W': result.Q_W,
            'Q_unit': result.metadata.get('units', {}).get(
                'Q', 'W' if result.diagnostics.get('mode') == '3d' else 'W/m'),
            'T_out_A_K': result.T_out_A_K, 'T_out_B_K': result.T_out_B_K,
            'timings_s': result.metadata.get('timings_s', {}),
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
            'iters': {
                'iter_outer': (result.diagnostics.get('convergence_detail') or {}).get('outer_iters'),
                **{k: result.diagnostics.get(k) for k in ('iter_simple_A', 'iter_simple_B')},
            },
            'wall_s': result.diagnostics.get('wall_time_s'),
            'coeffs': {k: result.coeffs.get(k) for k in
                       ('K_ffA', 'K_ffB', 'K_ss', 'h_vA', 'h_vB')},
        }

    def refresh_summary(self):
        """Refresh the visible footer from the published result."""
        window = self.window
        from sjtu_tpmshx.applications.gui.ui.builders_sidebar import (
            refresh_result_sidebar, update_result_sidebar_visibility,
        )
        refresh_result_sidebar(window)
        update_result_sidebar_visibility(window)

    def diagnostic_text(self):
        """Plain-text diagnostics block (ui-plan3-workbench T3) — pasteable
        into 组会/周报. Returns '' when no run has landed."""
        window = self.window
        d = self.summary()
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
            f"迭代: 外循环 {_f(it.get('iter_outer'), '{:.0f}')} · SIMPLE A/B"
            f" {_f(it.get('iter_simple_A'), '{:.0f}')}/{_f(it.get('iter_simple_B'), '{:.0f}')}"
            f" · 耗时 {_f(d.get('wall_s'), '{:.1f}')} s",
            f"闭合系数: K_ffA={_f(co.get('K_ffA'))} K_ffB={_f(co.get('K_ffB'))}"
            f" h_vA={_f(co.get('h_vA'))} h_vB={_f(co.get('h_vB'))}",
        ]
        qualification = d.get('qualification', {})
        design = qualification.get('design', {})
        state = {'eligible': '合格', 'rejected': '不合格', 'unverified': '未核实'}.get(
            design.get('status'), '未核实')
        lines.append('设计资格：' + state + '；实验与桌面验收另行记录。')
        lines.extend('原因：' + reason for reason in qualification_reasons(
            qualification, d.get('applicability_evidence')))
        for name, label in (('physical', '物理台账'), ('applicability', '适用范围'), ('model_scope', '模型适用性')):
            passed = qualification.get(name, {}).get('passed')
            lines.append(label + '：' + ('通过' if passed is True else '未通过' if passed is False else '未核实'))
        co2_model = window.cache.get_result().metadata.get('co2')
        if co2_model:
            lines.append('CO₂ 侧 ' + '/'.join(co2_model['sides'])
                         + f"：单相 HEOS；固定阻力 ×{co2_model['pressure_multiplier']:g}"
                         + f"、Nu ×{co2_model['nu_multiplier']:g}（含下限）；两侧共用 CO₂ CFD 几何。")
        timings = d.get('timings_s')
        if timings:
            lines.append("阶段耗时：" + " · ".join(
                f"{label} {_f(timings.get(key), '{:.3f}')} s"
                for key, label in (('prepare', '准备'), ('solve', '求解'),
                                   ('postprocess', '后处理'), ('display', '显示'),
                                   ('volume_display', '三维加载')) if key in timings))
        for w in (d.get('warnings') or []) + (d.get('envelope_warnings') or []):
            lines.append(f"⚠ {w}")
        for e in d.get('extrap') or []:
            lines.append(f"⚠ 外推: {e}")
        return "\n".join(lines)

    def show_diag_dialog(self):
        """诊断详情 dialog: energy ledger, coefficients, iterations,
        warnings, one-click copy (ui-plan3-workbench T3)."""
        window = self.window
        txt = self.diagnostic_text()
        if not txt:
            window.statusBar().showMessage("暂无诊断数据 — 请先计算。",
                                         TOAST_MS_SHORT)
            return
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QPlainTextEdit,
                                       QPushButton, QHBoxLayout)
        from sjtu_tpmshx.applications.gui.ui.theme import get_theme as _gt
        _t = _gt()
        dlg = QDialog(window)
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
            QGuiApplication.clipboard().setText(self.diagnostic_text())
            window.statusBar().showMessage("诊断摘要已复制。", TOAST_MS_SHORT)
        btn_copy.clicked.connect(_copy)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dlg.accept)
        row.addStretch(1); row.addWidget(btn_copy); row.addWidget(btn_close)
        lay.addLayout(row)
        dlg.exec()

    def render(self, mode):
        """Render the published result and report presentation success."""
        window = self.window
        if mode == '3d':
            from sjtu_tpmshx.applications.gui.ui.plot_2d_results import ensure_result_plot
            field = window.workbench.resolve_2d_view_card()
            success = ensure_result_plot(window, field)
            window.workbench.rendered_slices = success
            window.workbench.update_tab_visibility()
            if success:
                window.workbench.switch_tab(field, foreground=False)
                window.statusBar().showMessage('场图已显示；首次选择三维时加载体视图。', 8000)
            for key, dialog in window.workbench.detached_canvases.items():
                if key in ('temp', 'pres', 'vel') and dialog.isVisible():
                    ensure_result_plot(window, key)
            detached = window.workbench.detached_volume
            if detached is not None and detached.isVisible():
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, window, lambda: window.workbench.request_3d_view(
                    lambda: None, background=True))
            return success

        # 2D mode (default).
        # 2026-05-09 — wrap finalize_plots so a panel crash (e.g. NaN
        # contourf, water-side LTNE divergence) does NOT block 2D results
        # from unlocking. The user still benefits from valid velocity /
        # pressure canvases even when one panel fails to render.
        _finalize_ok = True
        try:
            self.finalize_plots()
        except Exception as _fe:
            _finalize_ok = False
            import traceback
            traceback.print_exc()
            window.statusBar().showMessage(
                f"Plot finalize failed: {_fe!r} — partial 2D results available.",
                8000)
        window.workbench.update_tab_visibility()
        window.workbench.switch_tab('temp', foreground=False)
        if _finalize_ok:
            from sjtu_tpmshx.applications.gui.ui.layout_drawer import refresh_last_2d_thumbnail
            refresh_last_2d_thumbnail(window)
            window.statusBar().showMessage("Done.", TOAST_MS_MED)
        return _finalize_ok

    def present(self, result, *, mode, provenance, elapsed):
        """Publish the accepted run before drawing. Keep it when drawing fails."""
        window = self.window
        started = perf_counter()
        published = False
        success = False
        try:
            if provenance is not None:
                axes = ('dx', 'dy', 'dz') if mode == '3d' else ('dx_arr', 'dy_arr')
                recorded = deepcopy(provenance)
                if 'actual_grid' not in recorded or not recorded['actual_grid']:
                    recorded['actual_grid'] = [
                        len(result.fields[key]) if result.fields.get(key) is not None else '?'
                        for key in axes
                    ]
                result.metadata['run_provenance'] = recorded
            self.publish(result)
            published = True
            if provenance is None or not provenance.get('resumed_from'):
                for side, inlet in result.metadata.get('inlet_inputs', {}).items():
                    if inlet['mass_flow_kg_s'] is not None:
                        getattr(window, 'le_u' + side).setText(format(inlet['u_mps'], '.17g'))
            success = self.render(mode)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            stage = 'display' if published else 'publication'
            window.statusBar().showMessage(f"Result {stage} failed: {exc}", 12000)
        if published:
            display_s = perf_counter() - started
            published_result = window.cache.get_result()
            published_result.metadata.setdefault('timings_s', {})['display'] = display_s
            if not success:
                for field in ('temp', 'pres', 'vel'):
                    canvas = getattr(window, f'canvas_{field}', None)
                    if canvas is not None and not window.cache.is_drawn(field):
                        canvas.fig.clear()
                        canvas._hover_data = None
                        canvas.draw_idle()
            solve_elapsed = recorded_elapsed_s(published_result)
            if solve_elapsed is None and isinstance(elapsed, (int, float)) and math.isfinite(elapsed):
                solve_elapsed = float(elapsed) + display_s
            window._last_elapsed_s = solve_elapsed
            self.refresh_summary()
            if window.single_run.is_idle() and hasattr(window, '_run_status_card'):
                card = window._run_status_card
                status_kind = (
                    'unconverged' if getattr(published_result, 'converged', True) is False
                    else ('warning' if (published_result.warnings or published_result.extrap_reasons)
                          else 'success')
                )
                card.finish(
                    status_kind,
                    solve_elapsed if isinstance(solve_elapsed, (int, float)) else 0.0,
                    message='',
                    log_available=bool((window.single_run.compute.last_log() or '').strip()),
                )
            window.workbench.update_tab_visibility()
            window.btn_export.setEnabled(True)
            window._refresh_status_bar()
            window.history.stamp_result_provenance(solve_elapsed)
            if success:
                window.history.push_recent_run()
        return success
