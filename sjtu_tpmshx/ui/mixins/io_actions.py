"""Export results and figures, and save/load GUI configuration JSON."""
from __future__ import annotations

import json

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from sjtu_tpmshx._version import __version__
from sjtu_tpmshx.domain.provenance import SOURCE_ROOT, repository_revision
from sjtu_tpmshx.ui.ui_constants import TOAST_MS_SHORT, TOAST_MS_MED


class IOActionsMixin:
    def _export_results(self):
        """Export last compute results to CSV + optional NPZ."""
        import csv
        from pathlib import Path
        from sjtu_tpmshx.io.file_set import staged_files
        res_3d = self.cache.get_result('3d')
        has_2d = self.cache.has_results('2d')
        # Export accepted numerical data independently of renderer readiness.
        has_3d = res_3d is not None
        if not has_2d and not has_3d:
            QMessageBox.information(self, "No Results",
                "Run Compute first to generate exportable results.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Results", "results.csv",
            "CSV (*.csv);;All Files (*)")
        if not path:
            return
        try:
            rows = []
            if res_3d is not None:
                # B3 C5: res_3d is the ComputeResult (raw_3d dict retired).
                # Scalars come off the dataclass / props; arrays off fields.
                _rf = res_3d.fields
                diag = res_3d.diagnostics or {}
                status = {
                    'converged': getattr(res_3d, 'converged', None),
                    'envelope_valid': diag.get('envelope_valid'),
                    'outer_converged': (diag.get('convergence_detail') or {}
                                        ).get('outer_converged'),
                    'metadata': res_3d.metadata,
                    'warnings': res_3d.warnings,
                    'extrap_reasons': res_3d.extrap_reasons,
                }
                rows.append(["Q [W]", f"{res_3d.Q_W:.4f}"])
                rows.append(["dP_A [Pa]", f"{res_3d.dP_A_Pa:.2f}"])
                rows.append(["dP_B [Pa]", f"{res_3d.dP_B_Pa:.2f}"])
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
                    rows.append(["Grid Nz", str(Ta.shape[2])])
                rows.append(["Lx [m]", f"{_rf.get('Lx', 0) or 0:.6f}"])
                rows.append(["Ly [m]", f"{_rf.get('Ly', 0) or 0:.6f}"])
                rows.append(["Lz [m]", f"{_rf.get('Lz', 0) or 0:.6f}"])
            else:
                res_2d = self.cache.get_result('2d')
                status = {key: res_2d.get(key) for key in
                          ('converged', 'envelope_valid', 'outer_converged',
                           'warnings', 'extrap_reasons', 'metadata')}
                rows.append(["Q [W/m]", f"{res_2d['Q_total']:.4f}"])
                rows.append(["dP_A [Pa]", f"{res_2d['dP_A']:.2f}"])
                rows.append(["dP_B [Pa]", f"{res_2d['dP_B']:.2f}"])
                Ta = res_2d.get('Ta')
                if Ta is not None:
                    rows.append(["Ta_min [K]", f"{float(Ta.min()):.2f}"])
                    rows.append(["Ta_max [K]", f"{float(Ta.max()):.2f}"])
                    rows.append(["Grid Nx", str(Ta.shape[0])])
                    rows.append(["Grid Ny", str(Ta.shape[1])])
                rows.append(["Lx [m]", f"{res_2d.get('L', 0) or 0:.6f}"])
                rows.append(["Ly [m]", f"{res_2d.get('H', 0) or 0:.6f}"])
            # Same UTF-8 JSON values in CSV and Unicode NPZ scalars. Missing
            # legacy state is explicitly unknown, never assumed converged.
            status = {key: ('unknown' if value is None else
                            json.dumps(value, ensure_ascii=False))
                      for key, value in status.items()}
            rows.extend(status.items())
            # Optional: save 3D fields as NPZ alongside. Keep the legacy
            # NPZ schema (vmag, P_kPa) stable: map from ComputeResult.fields
            # (vmag_A → vmag; P_fA/1000 → P_kPa).
            path = Path(path)
            npz_path = path.with_name(path.stem + '_fields.npz')
            if res_3d is not None:
                _rf = res_3d.fields
                save_dict = dict(status)
                for npz_key, src in (('Ta', 'Ta'), ('Tb', 'Tb'),
                                     ('Ts', 'Ts'), ('vmag', 'vmag_A'),
                                     ('L_mm', 'L_mm'), ('dx', 'dx'),
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
            self.statusBar().showMessage(f"Exported: {path}", TOAST_MS_MED)
        except Exception as e:
            self.statusBar().showMessage(f"Export failed: {path}", TOAST_MS_MED)
            QMessageBox.critical(self, "Export Error", str(e))

    # ─────────────────────────────────────────────────────────
    #  Save / Load configuration
    # ─────────────────────────────────────────────────────────
    def _load_sco2_nu_parameters(self):
        """Resolve a local parameter file now; snapshots never reread its path."""
        path, _ = QFileDialog.getOpenFileName(self, "导入 sCO₂ Nu 标定参数", "", "JSON (*.json)")
        if not path:
            return False
        try:
            from pathlib import Path
            from dataclasses import asdict, replace
            from sjtu_tpmshx.domain.compute_config import Sco2NuConfig
            settings = Sco2NuConfig(**json.loads(Path(path).read_text(encoding='utf-8')))
            replace(settings, mode='experimental').validate()
            self._set_sco2_nu_parameters(asdict(settings))
            return True
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "标定参数无法加载", str(exc))
            return False

    def save_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Config", "SJTU-TPMSHX_config.json",
            "JSON Files (*.json)")
        if not path:
            return False
        try:
            from pathlib import Path
            preset = self._capture_current_preset(Path(path).stem)
            self._validate_preset(preset, complete=True)
            payload = {'config_format': 1, 'preset': preset}
            if not self.sm._atomic_write_json(Path(path), payload):
                raise OSError(f"Cannot save configuration: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))
            return False
        self.statusBar().showMessage(f"Saved configuration: {path}", TOAST_MS_MED)
        return True

    def load_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Config", "", "JSON Files (*.json)")
        if not path:
            return False
        return self._load_config_path(path)

    def _load_config_path(self, path):
        """Apply one configuration file through the same menu/drop validation."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("Configuration must be a JSON object.")
            legacy = False
            if 'config_format' in payload:
                if (type(payload['config_format']) is not int or
                        payload['config_format'] != 1 or
                        set(payload) != {'config_format', 'preset'}):
                    raise ValueError("Unsupported configuration format.")
                preset = payload['preset']
                self._validate_preset(preset, complete=True)
            elif 'line_edits' in payload:
                preset = payload
                self._validate_preset(preset)
            elif 'presets' in payload:
                presets = payload['presets']
                if not isinstance(presets, list) or not presets:
                    raise ValueError("Preset library must contain at least one preset.")
                preset = presets[0]
                self._validate_preset(preset)
            else:
                legacy = True
                preset = self._legacy_config_preset(payload)
            self._apply_user_preset(preset)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", str(e))
            return False
        if legacy:
            message = ("已导入旧文件中保存的字段；这不是完整工况恢复。旧格式没有"
                       "保存流体、温度单位、维度/Lz/Nz、第二横向端口、外推、"
                       "flags 和分区；这些输入保持当前值，请核对后计算。")
            QMessageBox.warning(self, "旧配置不完整", message)
        else:
            message = f"Loaded configuration: {path}"
        self.statusBar().showMessage(message, TOAST_MS_MED)
        return True

    def _legacy_config_preset(self, payload):
        """Import only fields the former flat writer actually saved."""
        edits = {
            'L': 'le_L', 'H': 'le_H', 'rho_s': 'le_rho_s',
            'Nx': 'le_Nx', 'Ny': 'le_Ny', 'L_cell': 'le_Lcell',
            't': 'le_t', 'k_s': 'le_ks',
            'u_A': 'le_uA', 'T_inA': 'le_TinA', 'P_inA': 'le_PinA',
            'u_B': 'le_uB', 'T_inB': 'le_TinB', 'P_inB': 'le_PinB',
        }
        for side in ('A', 'B'):
            for port in ('in', 'out'):
                for field in ('ctr', 'w'):
                    key = f'pipe{side}_{port}_{field}'
                    edits[key] = f'le_{key}'
        known = set(edits) | {'tpms_type', 'df_mode', 'dir_A', 'dir_B', 'T_s_init'}
        if not payload or set(payload) - known:
            raise ValueError("Incomplete or unsupported configuration payload.")
        if payload.get('T_s_init', '') != '':
            raise ValueError("T_s_init is no longer a GUI input; cannot restore it.")
        preset = {'temp_unit': self._temp_unit,
                  'line_edits': {name: payload[key] for key, name in edits.items()
                                 if key in payload},
                  'combos': {}, 'checks': {}}
        for key, name, by_data in (
                ('tpms_type', 'combo_tpms', False),
                ('df_mode', 'combo_df_mode', True)):
            if key in payload:
                combo = getattr(self, name)
                idx = (combo.findData(payload[key]) if by_data else
                       combo.findText(payload[key]))
                if idx < 0:
                    raise ValueError(f"Unsupported {key}: {payload[key]}")
                preset['combos'][name] = idx
        for side in ('A', 'B'):
            if f'dir_{side}' in payload:
                preset['combos'][f'combo_dir{side}'] = payload[f'dir_{side}']
        self._validate_preset(preset)
        return preset

    def _pareto_figure_ready(self):
        """Optimization figures belong to their own run, not the field cache."""
        front = getattr(self, '_pareto_F', None)
        return (getattr(self, 'canvas_pareto', None) is not None
                and front is not None and len(front) > 0)

    def _opt_field_figure_ready(self):
        canvas = getattr(self, 'canvas_opt_field', None)
        return (canvas is not None
                and sum(bool(axis.images) for axis in canvas.figure.axes) == 2)

    def _opt_3d_figure_ready(self):
        panel = getattr(self, 'canvas_opt_3d', None)
        return (panel is not None and bool(getattr(self, '_opt_3d_ready', False))
                and panel._volume_actor is not None)

    def _refresh_export_button(self):
        button = getattr(self, 'btn_export', None)
        if button is not None:
            button.setEnabled(self.cache.has_any_results()
                              or bool(self.cache.get_drawn_tabs())
                              or self._pareto_figure_ready()
                              or self._opt_field_figure_ready()
                              or self._opt_3d_figure_ready())

    def _copy_figure_clipboard(self):
        """Copy the currently active canvas image to the system clipboard
        (ui-batch4 ③) — one click from result plot to WeChat / PPT.
        Matplotlib canvases use widget.grab(); VTK needs its own screenshot
        because Qt grabs do not reliably capture the OpenGL surface."""
        tab = getattr(self, '_active_tab', None)
        if tab == '2d_view':
            tab = self._resolve_2d_view_card()
        if tab == 'pareto':
            current = self._opt_result_tabs.currentWidget()
            if current is self.canvas_opt_field:
                tab = 'opt_field'
            elif current is getattr(self, '_opt_3d_host', None):
                tab = 'opt_3d'
        if tab in ('temp', 'pres', 'vel'):
            from sjtu_tpmshx.ui.plot_2d_results import ensure_result_plot
            if not ensure_result_plot(self, tab):
                return
        canvas = {'temp': getattr(self, 'canvas_temp', None),
                  'pres': getattr(self, 'canvas_pres', None),
                  'vel': getattr(self, 'canvas_vel', None),
                  'layout': getattr(self, 'canvas_layout', None),
                  'pareto': getattr(self, 'canvas_pareto', None),
                  'opt_field': getattr(self, 'canvas_opt_field', None),
                  'opt_3d': getattr(self, 'canvas_opt_3d', None)}.get(tab)
        ready = (self._pareto_figure_ready() if tab == 'pareto'
                 else self._opt_field_figure_ready() if tab == 'opt_field'
                 else self._opt_3d_figure_ready() if tab == 'opt_3d'
                 else tab in self.cache.get_drawn_tabs())
        if canvas is None or not ready:
            self.statusBar().showMessage("当前无可复制的图像 — 请先计算或预览。",
                                         TOAST_MS_SHORT)
            return
        from PySide6.QtGui import QGuiApplication
        if tab == 'opt_3d':
            import numpy as np
            from PySide6.QtGui import QImage
            try:
                pixels = np.ascontiguousarray(canvas.plotter.screenshot(return_img=True))
                image_format = (QImage.Format.Format_RGBA8888 if pixels.shape[2] == 4
                                else QImage.Format.Format_RGB888)
                # Own the pixels after this local NumPy buffer is released.
                image = QImage(pixels.data, pixels.shape[1], pixels.shape[0],
                               pixels.strides[0], image_format).copy()
            except Exception as e:
                QMessageBox.warning(self, "Copy failed", str(e))
                return
        else:
            image = canvas.grab().toImage()
        QGuiApplication.clipboard().setImage(image)
        self.statusBar().showMessage(f"已复制 {tab} 图像到剪贴板。", TOAST_MS_SHORT)

    def _export_figure(self):
        """Export a 2D figure with DPI/metadata, or a native 3D PNG screenshot."""
        all_items = [("温度", 'temp'), ("压力", 'pres'),
                     ("速度", 'vel'), ("几何布局", 'layout'),
                     ("Pareto / 优化", 'pareto'), ("优化尺寸/壁厚场", 'opt_field'),
                     ("优化三维场", 'opt_3d')]
        tab_canvas = {'temp': self.canvas_temp, 'pres': self.canvas_pres,
                      'vel': self.canvas_vel, 'layout': self.canvas_layout,
                      'pareto': self.canvas_pareto, 'opt_field': self.canvas_opt_field,
                      'opt_3d': getattr(self, 'canvas_opt_3d', None)}
        drawn = self.cache.get_drawn_tabs()
        available = set(drawn)
        if self._pareto_figure_ready():
            available.add('pareto')
        if self._opt_field_figure_ready():
            available.add('opt_field')
        if self._opt_3d_figure_ready():
            available.add('opt_3d')
        if (self.cache.get_result('2d') is not None
                or self.cache.get_result('3d') is not None):
            available.update(('temp', 'pres', 'vel'))
        items = [name for name, key in all_items if key in available]
        tab_keys = [key for name, key in all_items if key in available]
        if not items:
            self.statusBar().showMessage("No figures to export yet.", TOAST_MS_SHORT)
            return
        choice, ok = QInputDialog.getItem(
            self, "Export Figure", "Select figure to export:",
            items, 0, False)
        if not ok:
            return
        key = tab_keys[items.index(choice)]
        canvas = tab_canvas[key]
        if key == 'opt_3d':
            try:
                canvas._on_screenshot()
            except Exception as e:
                QMessageBox.warning(self, "Export failed", str(e))
            return

        # DPI picker — common research-paper presets.
        dpi_items = ["150 (screen)", "300 (print)",
                     "450 (publication)", "600 (poster)"]
        dpi_choice, ok2 = QInputDialog.getItem(
            self, "Resolution", "DPI:", dpi_items, 1, False)
        if not ok2:
            return
        dpi = int(dpi_choice.split()[0])

        default = f"SJTU-TPMSHX_{key}_{dpi}dpi.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Figure", default,
            "PNG (*.png);;SVG (*.svg);;PDF (*.pdf);;All Files (*)")
        if not path:
            return
        try:
            if key in ('temp', 'pres', 'vel'):
                from sjtu_tpmshx.ui.plot_2d_results import ensure_result_plot
                if not ensure_result_plot(self, key):
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
            preset = getattr(self, '_active_preset_name', None)
            # The retained optimization figure can precede the current Compute
            # preset. Their originating study / field configuration is separate.
            if preset and key not in ('pareto', 'opt_field'):
                meta['Subject'] = f"Preset: {preset}"

            ext = path.lower().rsplit('.', 1)[-1] if '.' in path else 'png'
            save_kwargs = dict(dpi=dpi, bbox_inches='tight',
                                facecolor=canvas.fig.get_facecolor())
            if ext in ('png', 'pdf'):
                save_kwargs['metadata'] = meta
            canvas.fig.savefig(path, **save_kwargs)
            self.statusBar().showMessage(
                f"Exported {dpi} DPI → {path}", 6000)
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))
