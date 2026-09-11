"""IOActionsMixin — export results / figures, save & load config JSON.

Extracted verbatim from main.py (openspec split-ui-main, 2026-07-03).
Mixed into Main_Menu; methods keep their exact names and behaviour.
``_export_figure`` reads ``__version__`` and ``_git_commit_hash`` as
module globals — both live in ``main`` (which imports us), so they
are resolved lazily here to keep the import graph acyclic (same
pattern as ``ui.mixins.run_history._git_commit_hash``).
"""
from __future__ import annotations

import json

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from sjtu_tpmshx.ui.ui_constants import TOAST_MS_SHORT, TOAST_MS_MED


def _git_commit_hash() -> str:
    """Short commit of the running tree, or ''. Lazy-resolved from ``main``
    so this module never imports ``main`` at load time (``main`` imports us).
    Tries both launch modes: ``python main.py`` / ``python -m sjtu_tpmshx.main``.
    """
    for mod in ("main", "sjtu_tpmshx.main"):
        try:
            return __import__(mod, fromlist=["_git_commit_hash"])._git_commit_hash()
        except Exception:
            continue
    return ""


class _LazyMainVersion:
    """Lazy str proxy for ``main.__version__`` (same acyclic-import
    rationale as ``_git_commit_hash`` above). Supports str() and
    f-string formatting, which is all ``_export_figure`` needs."""

    def _resolve(self) -> str:
        for mod in ("main", "sjtu_tpmshx.main"):
            try:
                return __import__(mod, fromlist=["__version__"]).__version__
            except Exception:
                continue
        return "?"

    def __str__(self) -> str:
        return self._resolve()

    def __format__(self, spec: str) -> str:
        return format(self._resolve(), spec)


__version__ = _LazyMainVersion()


class IOActionsMixin:
    def _export_results(self):
        """Export last compute results to CSV + optional NPZ."""
        import os, csv
        res_3d = getattr(self, '_result_3d', None)
        has_2d = getattr(self, '_has_results_2d', False)
        # 2026-05-20 UI sweep (Tier 14, user re-audit): previously this
        # gate used `_has_results_3d`, which only goes True if the 3D
        # PyVistaQt panel rendered successfully. When the solver
        # succeeded but visualisation failed, the export button was
        # enabled (gated on `_has_results`) yet clicking it landed on
        # the "No Results" dialog because both `has_2d` and `has_3d`
        # were False. Switch to a data-presence check: numerical results
        # are exportable independent of whether the 3D scene rendered.
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
                res_2d = self._compute_results
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
            with open(path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(["Parameter", "Value"])
                w.writerows(rows)
            # Optional: save 3D fields as NPZ alongside. Keep the legacy
            # NPZ schema (vmag, P_kPa) stable: map from ComputeResult.fields
            # (vmag_A → vmag; P_fA/1000 → P_kPa).
            npz_path = os.path.splitext(path)[0] + '_fields.npz'
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
                if save_dict:
                    import numpy as _np_exp
                    _np_exp.savez_compressed(npz_path, **save_dict)
            self.statusBar().showMessage(f"Exported: {path}", TOAST_MS_MED)
        except Exception as e:
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
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("Configuration must be a JSON object.")
            legacy = 'config_format' not in payload
            if legacy:
                preset = self._legacy_config_preset(payload)
            else:
                if (type(payload['config_format']) is not int or
                        payload['config_format'] != 1 or
                        set(payload) != {'config_format', 'preset'}):
                    raise ValueError("Unsupported configuration format.")
                preset = payload['preset']
                self._validate_preset(preset, complete=True)
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

    def _copy_figure_clipboard(self):
        """Copy the currently active canvas image to the system clipboard
        (ui-batch4 ③) — one click from result plot to WeChat / PPT.
        widget.grab() = what's on screen (theme background included); the
        high-fidelity path stays the PNG export."""
        tab = getattr(self, '_active_tab', None)
        if tab == '2d_view':
            tab = self._resolve_2d_view_card()
        canvas = {'temp': getattr(self, 'canvas_temp', None),
                  'pres': getattr(self, 'canvas_pres', None),
                  'vel': getattr(self, 'canvas_vel', None),
                  'layout': getattr(self, 'canvas_layout', None),
                  'pareto': getattr(self, 'canvas_pareto', None)}.get(tab)
        if canvas is None or tab not in getattr(self, '_drawn_tabs', set()):
            self.statusBar().showMessage("当前无可复制的图像 — 请先计算或预览。",
                                         TOAST_MS_SHORT)
            return
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setImage(canvas.grab().toImage())
        self.statusBar().showMessage(f"已复制 {tab} 图像到剪贴板。", TOAST_MS_SHORT)

    def _export_figure(self):
        """Export a chosen figure to PNG/SVG/PDF with user-selected DPI
        and embedded reproducibility metadata (preset, commit, timestamp,
        grid). Pops a 2-step picker: figure → format/DPI → save path."""
        all_items = [("温度", 'temp'), ("压力", 'pres'),
                     ("速度", 'vel'), ("几何布局", 'layout'),
                     ("Pareto / 优化", 'pareto')]
        tab_canvas = {'temp': self.canvas_temp, 'pres': self.canvas_pres,
                      'vel': self.canvas_vel, 'layout': self.canvas_layout,
                      'pareto': self.canvas_pareto}
        drawn = getattr(self, '_drawn_tabs', set())
        items = [name for name, key in all_items if key in drawn]
        tab_keys = [key for name, key in all_items if key in drawn]
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
            # Build reproducibility metadata embedded in PNG tEXt / PDF
            # keywords. Matplotlib respects this via savefig's `metadata`
            # kwarg.
            import datetime as _dt_ef
            meta = {
                'Title': f"SJTU-TPMSHX {key}",
                'Author': 'alexlu997',
                'Software': f"SJTU-TPMSHX v{__version__}",
                'CreationDate': _dt_ef.datetime.now().isoformat(timespec='seconds'),
                'Source': 'github.com/alexlu997/SJTU-TPMSHX',
            }
            commit = _git_commit_hash()
            if commit:
                meta['Keywords'] = f"commit={commit}"
            preset = getattr(self, '_active_preset_name', None)
            if preset:
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
