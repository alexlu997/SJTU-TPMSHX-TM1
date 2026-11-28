"""Export recorded numerical results and displayed figures."""
from __future__ import annotations

import json
from datetime import datetime
import re

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from tm1._version import __version__
from tm1.run_control.provenance import SOURCE_ROOT, repository_revision
from tm1.applications.gui.ui.ui_constants import TOAST_MS_SHORT, TOAST_MS_MED


class ResultExport:
    def __init__(self, window):
        self.window = window

    def export_results(self):
        """Export last compute results to CSV + optional NPZ."""
        window = self.window
        import csv
        from pathlib import Path
        from tm1.file_io.file_set import staged_files
        res_3d = window.cache.get_result('3d')
        res_2d = window.cache.get_result('2d')
        # Export accepted numerical data independently of renderer readiness.
        has_3d = res_3d is not None
        if res_2d is None and not has_3d:
            QMessageBox.information(window, "暂无结果",
                "请先运行计算以生成可导出的结果。")
            return
        # File dialogs process worker completion signals. Keep the accepted
        # object selected at click time even if another result is published.
        result = res_3d if res_3d is not None else res_2d
        path, _ = QFileDialog.getSaveFileName(
            window, "导出计算结果", "results.csv",
            "CSV 文件 (*.csv);;所有文件 (*)")
        if not path:
            return
        try:
            rows = []
            _rf = result.fields
            diag = result.diagnostics or {}
            status = {
                'converged': result.converged,
                'envelope_valid': diag.get('envelope_valid'),
                'outer_converged': (diag.get('convergence_detail') or {}
                                    ).get('outer_converged'),
                'metadata': result.metadata,
                'warnings': result.warnings,
                'extrap_reasons': result.extrap_reasons,
            }
            q_unit = 'W' if res_3d is not None else 'W/m'
            rows.append([f"Q [{q_unit}]", f"{result.Q_W:.4f}"])
            rows.append(["dP_A [Pa]", f"{result.dP_A_Pa:.2f}"])
            rows.append(["dP_B [Pa]", f"{result.dP_B_Pa:.2f}"])
            if res_3d is not None:
                rows.append(["T_inA [K]",
                             f"{res_3d.props.get('T_in_A_K', 0) or 0:.2f}"])
                rows.append(["u_A [m/s]",
                             f"{res_3d.props.get('u_A_in_mps', 0) or 0:.4f}"])
            Ta = _rf.get('Ta')
            if Ta is not None:
                rows.append(["Ta_min [K]", f"{float(Ta.min()):.2f}"])
                rows.append(["Ta_max [K]", f"{float(Ta.max()):.2f}"])
                rows.append(["Grid Nx", str(Ta.shape[0])])
                rows.append(["Grid Ny", str(Ta.shape[1])])
                if res_3d is not None:
                    rows.append(["Grid Nz", str(Ta.shape[2])])
            if res_3d is not None:
                rows.append(["Lx [m]", f"{_rf.get('Lx', 0) or 0:.6f}"])
                rows.append(["Ly [m]", f"{_rf.get('Ly', 0) or 0:.6f}"])
                rows.append(["Lz [m]", f"{_rf.get('Lz', 0) or 0:.6f}"])
            else:
                rows.append(["Lx [m]", f"{_rf.get('L', 0) or 0:.6f}"])
                rows.append(["Ly [m]", f"{_rf.get('H', 0) or 0:.6f}"])
            # Same UTF-8 JSON values in CSV and Unicode NPZ scalars. Missing
            # legacy state is explicitly unknown, never assumed converged.
            status = {key: ('unknown' if value is None else
                            json.dumps(value, ensure_ascii=False))
                      for key, value in status.items()}
            rows.extend(status.items())
            # Optional: save 3D fields as NPZ alongside. Keep the legacy
            # NPZ schema (vmag, P_kPa) stable: map from ComputeResult.fields
            # (vmag_A → vmag; P_fA/1000 → P_kPa).
            # All arrays retain physical XYZ order. Velocities are m/s,
            # P_fA/B are the existing display pressures in Pa, L/t are mm,
            # and dx/dy/dz are the actual cell widths in m.
            path = Path(path)
            npz_path = path.with_name(path.stem + '_fields.npz')
            if res_3d is not None:
                _rf = res_3d.fields
                save_dict = dict(status)
                for npz_key, src in (('Ta', 'Ta'), ('Tb', 'Tb'),
                                     ('Ts', 'Ts'), ('vmag', 'vmag_A'),
                                     ('ucA', 'ucA'), ('vcA', 'vcA'), ('wcA', 'wcA'),
                                     ('ucB', 'ucB'), ('vcB', 'vcB'), ('wcB', 'wcB'),
                                     ('vmag_A', 'vmag_A'), ('vmag_B', 'vmag_B'),
                                     ('P_fA', 'P_fA'), ('P_fB', 'P_fB'),
                                     ('L_mm', 'L_mm'), ('t_mm', 't_mm'), ('dx', 'dx'),
                                     ('dy', 'dy'), ('dz', 'dz')):
                    v = _rf.get(src)
                    if v is not None:
                        save_dict[npz_key] = v
                _p_fa = _rf.get('P_fA')
                if _p_fa is not None:
                    save_dict['P_kPa'] = _p_fa / 1000.0
            paths = [path, npz_path] if res_3d is not None else [path]
            # A 2D replacement also retires the old 3D companion, after the
            # new CSV is complete; a failed export leaves the old pair intact.
            with staged_files(paths, remove=(() if res_3d is not None else (npz_path,))) as stage:
                with (stage / path.name).open('w', newline='', encoding='utf-8') as f:
                    w = csv.writer(f)
                    w.writerow(["Parameter", "Value"])
                    w.writerows(rows)
                if res_3d is not None:
                    import numpy as _np_exp
                    _np_exp.savez_compressed(stage / npz_path.name, **save_dict)
            window.dialogs.notify(f"已导出：{path}", kind="success", duration_ms=TOAST_MS_MED)
        except Exception as e:
            window.dialogs.notify(f"导出失败：{path}", kind="error", duration_ms=TOAST_MS_MED)
            QMessageBox.critical(window, "导出失败", str(e))

    def single_3d_ready(self) -> bool:
        """Return True when the single-run 3D volume panel is rendered and capturable."""
        window = self.window
        panel = getattr(window, 'canvas_3d', None)
        return bool(
            window.workbench.volume_ready
            and panel is not None
            and getattr(panel, 'plotter', None) is not None
            and getattr(panel, '_volume_actor', None) is not None
        )

    def available_figure_entries(self) -> list[tuple[str, str]]:
        """Return ``(label, key)`` pairs for every currently exportable figure."""
        window = self.window
        all_items = [
            ("温度", 'temp'),
            ("压力", 'pres'),
            ("速度", 'vel'),
            ("三维视图", '3d'),
            ("几何布局", 'layout'),
            ("Pareto / 优化", 'pareto'),
            ("优化尺寸/壁厚场", 'opt_field'),
            ("优化三维场", 'opt_3d'),
        ]
        available = set(window.cache.get_drawn_tabs())
        if self.single_3d_ready():
            available.add('3d')
        else:
            available.discard('3d')
        if window.optimization.pareto_ready():
            available.add('pareto')
        if window.optimization.field_ready():
            available.add('opt_field')
        if window.optimization.volume_ready():
            available.add('opt_3d')
        if (window.cache.get_result('2d') is not None
                or window.cache.get_result('3d') is not None):
            available.update(('temp', 'pres', 'vel'))
        return [(name, key) for name, key in all_items if key in available]

    def _active_copy_target(self) -> tuple[str, object, bool]:
        """Resolve ``(tab_key, canvas_or_panel, is_ready)`` for the active workbench view."""
        window = self.window
        tab = window.workbench.active_tab
        if tab == '2d_view':
            tab = window.workbench.resolve_2d_view_card()
        if tab == 'pareto':
            current = window.optimization.result_tabs.currentWidget()
            if current is window.optimization.field_canvas:
                tab = 'opt_field'
            elif current is window.optimization.volume_host:
                tab = 'opt_3d'
        canvas = {
            'temp': getattr(window, 'canvas_temp', None),
            'pres': getattr(window, 'canvas_pres', None),
            'vel': getattr(window, 'canvas_vel', None),
            '3d': getattr(window, 'canvas_3d', None),
            'layout': getattr(window, 'canvas_layout', None),
            'pareto': window.optimization.pareto_canvas,
            'opt_field': window.optimization.field_canvas,
            'opt_3d': window.optimization.volume_panel,
        }.get(tab)
        if tab == 'pareto':
            ready = window.optimization.pareto_ready()
        elif tab == 'opt_field':
            ready = window.optimization.field_ready()
        elif tab == 'opt_3d':
            ready = window.optimization.volume_ready()
        elif tab == '3d':
            ready = self.single_3d_ready()
        elif tab in ('temp', 'pres', 'vel'):
            ready = (
                tab in window.cache.get_drawn_tabs()
                or window.cache.get_result('2d') is not None
                or window.cache.get_result('3d') is not None
            )
        else:
            ready = tab in window.cache.get_drawn_tabs()
        return tab, canvas, bool(canvas is not None and ready)

    def can_copy_current_figure(self) -> bool:
        """Return True when the active workbench view has a capturable image."""
        _, _, ready = self._active_copy_target()
        return ready

    def refresh_export_button(self):
        window = self.window
        has_results = window.cache.has_any_results()
        has_figures = bool(self.available_figure_entries())
        can_copy = self.can_copy_current_figure()
        button = getattr(window, 'btn_export', None)
        if button is not None:
            button.setEnabled(has_results or has_figures)
        act_results = getattr(window, '_act_export_results', None)
        if act_results is not None:
            act_results.setEnabled(has_results)
        act_fig = getattr(window, '_act_export_figure', None)
        if act_fig is not None:
            act_fig.setEnabled(has_figures)
        btn_drawer_fig = getattr(window, '_btn_drawer_export_figure', None)
        if btn_drawer_fig is not None:
            btn_drawer_fig.setEnabled(has_figures)
        act_copy = getattr(window, '_act_copy_figure', None)
        if act_copy is not None:
            act_copy.setEnabled(can_copy)

    def copy_figure_clipboard(self):
        """Copy the currently active canvas image to the system clipboard
        (ui-batch4 ③) — one click from result plot to WeChat / PPT.
        Matplotlib canvases use widget.grab(); VTK needs its own screenshot
        because Qt grabs do not reliably capture the OpenGL surface."""
        window = self.window
        tab, canvas, ready = self._active_copy_target()
        if tab in ('temp', 'pres', 'vel') and ready:
            from tm1.applications.gui.ui.plot_2d_results import ensure_result_plot
            if not ensure_result_plot(window, tab):
                return
            ready = tab in window.cache.get_drawn_tabs()
        if canvas is None or not ready:
            window.dialogs.notify(
                "当前无可复制的图像 — 请先计算或预览。",
                kind="warn",
                duration_ms=TOAST_MS_SHORT,
            )
            return
        from PySide6.QtGui import QGuiApplication
        if tab in ('3d', 'opt_3d'):
            try:
                image = canvas.capture_image()
            except Exception as e:
                QMessageBox.warning(window, "复制失败", str(e))
                return
        else:
            image = canvas.grab().toImage()
        QGuiApplication.clipboard().setImage(image)
        window.dialogs.notify(
            f"已复制 {tab} 图像到剪贴板。",
            kind="success",
            duration_ms=TOAST_MS_SHORT,
        )

    def export_figure(self):
        """Export a 2D figure with DPI/metadata, or a composited 3D PNG."""
        window = self.window
        tab_canvas = {
            'temp': window.canvas_temp,
            'pres': window.canvas_pres,
            'vel': window.canvas_vel,
            '3d': getattr(window, 'canvas_3d', None),
            'layout': window.canvas_layout,
            'pareto': window.optimization.pareto_canvas,
            'opt_field': window.optimization.field_canvas,
            'opt_3d': window.optimization.volume_panel,
        }
        entries = self.available_figure_entries()
        items = [name for name, _key in entries]
        tab_keys = [key for _name, key in entries]
        if not items:
            window.dialogs.notify(
                "当前没有可导出的图像。",
                kind="warn",
                duration_ms=TOAST_MS_SHORT,
            )
            return
        choice, ok = QInputDialog.getItem(
            window, "导出图像", "选择要导出的图像：",
            items, 0, False)
        if not ok:
            return
        key = tab_keys[items.index(choice)]
        canvas = tab_canvas[key]
        if key in ('3d', 'opt_3d'):
            ts = datetime.now().strftime('%Y%m%d-%H%M%S')
            default = f"volume_{canvas._field}_{canvas._scale_mode}_{ts}.png"
            path, _ = QFileDialog.getSaveFileName(
                window, "保存三维视图为 PNG", default, "PNG 图像 (*.png)")
            if not path:
                return
            try:
                image = canvas.capture_image()
                if image.isNull() or not image.save(path, "PNG"):
                    raise RuntimeError(f"无法将三维图像保存到 {path}")
            except Exception as e:
                QMessageBox.warning(window, "导出失败", str(e))
                return
            window.dialogs.notify(f"已导出：{path}", kind="success", duration_ms=TOAST_MS_MED)
            return

        # DPI picker — common research-paper presets.
        dpi_items = ["150（屏幕）", "300（打印）",
                     "450（论文）", "600（海报）"]
        dpi_choice, ok2 = QInputDialog.getItem(
            window, "分辨率", "输出分辨率（DPI）：", dpi_items, 1, False)
        if not ok2:
            return
        m_dpi = re.match(r"\s*(\d+)", str(dpi_choice))
        if m_dpi is None:
            return
        dpi = int(m_dpi.group(1))

        default = f"SJTU-TPMSHX_{key}_{dpi}dpi.png"
        path, _ = QFileDialog.getSaveFileName(
            window, "导出图像", default,
            "PNG 图像 (*.png);;SVG 矢量图 (*.svg);;PDF 文档 (*.pdf);;所有文件 (*)")
        if not path:
            return
        try:
            if key in ('temp', 'pres', 'vel'):
                from tm1.applications.gui.ui.plot_2d_results import ensure_result_plot
                if not ensure_result_plot(window, key):
                    raise RuntimeError("当前字段绘图失败，未导出图像。")
            # Build reproducibility metadata embedded in PNG tEXt / PDF
            # keywords. Matplotlib respects this via savefig's `metadata`
            # kwarg.
            import datetime as _dt_ef
            meta = {
                'Title': f"SJTU-TPMSHX {key}",
                'Author': 'alexlu997',
                'Software': f"SJTU-TPMSHX v{__version__}",
                'CreationDate': _dt_ef.datetime.now().isoformat(timespec='seconds'),
                'Source': 'https://github.com/alexlu997/SJTU-TPMSHX-TM1',
            }
            commit = (repository_revision(SOURCE_ROOT)['revision'] or '')[:7]
            if commit:
                meta['Keywords'] = f"commit={commit}"
            preset = window.case_files.active_preset_name
            if key in ('temp', 'pres', 'vel'):
                result = window.cache.get_result('3d') or window.cache.get_result('2d')
                preset = (result.metadata.get('run_provenance', {}).get('preset_source')
                          if result is not None else None)
            # The retained optimization figure can precede the current Compute
            # preset. Their originating study / field configuration is separate.
            if preset and key not in ('pareto', 'opt_field'):
                meta['Subject'] = f"Preset: {preset}"

            ext = path.lower().rsplit('.', 1)[-1] if '.' in path else 'png'
            save_kwargs = dict(dpi=dpi, bbox_inches='tight',
                                facecolor=canvas.fig.get_facecolor())
            if ext in ('png', 'pdf'):
                save_kwargs['metadata'] = meta
            from tm1.applications.gui.ui.typography import publication_export_fonts

            with publication_export_fonts(canvas.fig):
                canvas.fig.savefig(path, **save_kwargs)
            canvas.draw_idle()
            window.dialogs.notify(
                f"已导出 {dpi} DPI 图像：{path}",
                kind="success",
                duration_ms=6000,
            )
        except Exception as e:
            QMessageBox.warning(window, "导出失败", str(e))
