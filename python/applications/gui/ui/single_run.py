"""Submit, pause, resume and finish one full-domain calculation."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from functools import partial
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox

from tm1.applications.gui.controllers.compute_orchestrator import ComputeOrchestrator
from tm1.applications.gui.ui.fmt import duration
from tm1.applications.gui.ui.icons import icon
from tm1.applications.gui.ui.theme import get_theme
from tm1.applications.gui.ui.ui_constants import HIGH_VELOCITY_NOTICE_MS, TOAST_MS_SHORT


def _run_compute(config, cancel_token, progress_cb, *, control, ui_hooks, run_directory,
                 checkpoint_interval_s, resume_checkpoint=None, gui_provenance=None):
    from tm1.applications.execution.recovery import compute_run, resume_loaded_run
    from tm1.applications.result_adapter import to_compute_result

    host_cancel = control.cancel_check

    def cancelled():
        return cancel_token.cancelled or (host_cancel is not None and host_cancel())

    def with_ui_hook(name, callback):
        hook = ui_hooks.get(name)
        if hook is None:
            return callback
        if callback is None:
            return hook

        def report(*args):
            hook(*args)
            callback(*args)

        return report

    control = replace(control, cancel_check=cancelled,
                      iteration=with_ui_hook('iter_label_cb', control.iteration),
                      outer_iteration=with_ui_hook('iter_cb', control.outer_iteration))
    options = dict(control=control, progress_cb=progress_cb, gui_provenance=gui_provenance,
                   checkpoint_interval_s=checkpoint_interval_s, pause_check=cancel_token.pause_requested)
    if resume_checkpoint is None:
        _, result, performance = compute_run(config, run_directory, **options)
    else:
        _, result, performance = resume_loaded_run(*resume_checkpoint, config, run_directory, **options)
    display = to_compute_result(result, performance)
    control.check_cancelled()
    return display


class SingleRun(QObject):
    """Keep the captured inputs until the GUI receives the terminal outcome."""

    activity_changed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.compute = ComputeOrchestrator(self)
        self.compute.started.connect(self._started)
        self.compute.progress.connect(self._progress)
        self.compute.iteration.connect(self._iteration)
        self.compute.finished.connect(self._finished)
        self.compute.error.connect(self._error)
        self.compute.cancelled.connect(self._cancelled)
        self.compute.paused.connect(self._paused)

        self._state = 'idle'
        self.provenance = None
        self.active_directory = None
        self.checkpoint_file = None
        self._grid_cells = None
        self._ticker = QTimer(self)
        self._ticker.setInterval(500)
        self._ticker.timeout.connect(self._tick)
        self._hide_progress = QTimer(self)
        self._hide_progress.setSingleShot(True)
        self._hide_progress.timeout.connect(lambda: self.window.progress.hide())

    def is_idle(self):
        return self._state == 'idle'

    @Slot()
    def toggle(self):
        if self.is_idle():
            self.submit()
        else:
            self.cancel()

    @Slot()
    def submit(self):
        from tm1.applications.gui.ui.window_config import config_from_window

        window = self.window
        if window._close_pending:
            return
        if not self.is_idle():
            QMessageBox.information(
                window, "Compute Busy",
                "A computation is already running.\n\n"
                "Click Cancel (the Compute button while it's red) and wait "
                "for the solver to reach its next checkpoint, then re-Compute.")
            return
        if not self.validate_inputs():
            return
        try:
            config = config_from_window(window, strict=True, force_3d=window.combo_dim.currentIndex() == 1)
        except ValueError as error:
            QMessageBox.warning(window, "Invalid Input", str(error))
            return
        if not self.preflight_grid(config):
            return
        self._maybe_highvel_notice(config)
        mode = '3d' if config.is_3d else '2d'
        grid_cells = None
        if config.is_3d:
            confirmed, grid_cells, label = self._preflight_3d(config)
            if not confirmed:
                return

        from dataclasses import asdict as _asdict
        files = window.case_files
        preset = deepcopy(files.capture_current_preset('Run inputs'))
        axes = 'xyz' if config.is_3d else 'xy'
        provenance = dict(preset=preset, preset_source=files.active_preset_name or '—', mode=mode,
                          config_snapshot=_asdict(config),
                          input_grid=[preset['line_edits']['le_N' + axis] for axis in axes])
        directory = files.store.base_dir / 'runs' / ('run-' + uuid4().hex)
        started = self._start(config, directory, provenance, checkpoint_interval=60.,
                              saved_provenance=provenance, grid_cells=grid_cells)
        if started and config.is_3d:
            window.dialogs.notify(
                f"正在求解三维算例（{label} = {grid_cells:,} 网格）…",
                kind="info",
                duration_ms=4000,
            )

    def resume(self, checkpoint_file=None):
        """Use the saved configuration and keep the current draft."""
        from tm1.applications.execution.recovery import read_run_checkpoint
        from tm1.applications.gui.ui.background_tasks import has_active_tasks
        from tm1.data_types.compute_config import ComputeConfig
        from tm1.data_types.portable_data import mutable_data

        window = self.window
        if window._close_pending:
            return
        if has_active_tasks(window):
            QMessageBox.information(window, '正在计算', '请等待当前任务结束，再继续已保存的计算。')
            return
        if checkpoint_file is None:
            start_path = self.checkpoint_file or window.case_files.store.base_dir / 'runs'
            checkpoint_file, _ = QFileDialog.getOpenFileName(
                window, '继续已保存的计算', str(start_path), 'Solver checkpoint (checkpoint.h5)')
        if not checkpoint_file:
            return
        path = Path(checkpoint_file).resolve()
        try:
            saved, case, record = read_run_checkpoint(path)
            config = ComputeConfig.from_dict(mutable_data(case.config_snapshot), prepared_grid=True)
            source = record.get('gui_provenance')
            if source is not None and not isinstance(source, dict):
                raise ValueError('saved GUI provenance must be a record')
            if source and source.get('preset') is not None and not isinstance(source['preset'], dict):
                raise ValueError('saved GUI preset must be a record')
            interval = record['checkpoint_interval_s']
        except (OSError, ValueError, KeyError, TypeError) as error:
            QMessageBox.warning(window, '无法继续计算', str(error))
            return

        axes = ('Nx', 'Ny', 'Nz') if config.is_3d else ('Nx', 'Ny')
        provenance = dict(preset=source.get('preset') if source else None,
                          preset_source=source.get('preset_source', '') if source else f'已保存算例：{case.case_id}',
                          mode=f"{case.grid['dimension']}d", resumed_from=str(path),
                          config_snapshot=mutable_data(case.config_snapshot),
                          input_grid=[getattr(config.solver, axis) for axis in axes])
        directory = path.parent.parent / ('run-' + uuid4().hex)
        if self._start(config, directory, provenance, checkpoint_interval=interval,
                       saved_provenance=source, resume_checkpoint=(path, saved, case)):
            window.dialogs.notify(
                f'正在继续已保存算例，结果目录：{directory}', kind="info", duration_ms=5000
            )

    def _start(self, config, directory, provenance, *, checkpoint_interval, saved_provenance,
               grid_cells=None, resume_checkpoint=None):
        # A preflight or checkpoint dialog can run a nested Qt event loop.
        if self.window._close_pending or not self.is_idle():
            return False
        mode = provenance['mode']
        emit = self.compute.iteration.emit
        hooks = {}
        if mode == '2d' or resume_checkpoint is not None:
            hooks['iter_label_cb'] = emit
        if mode == '3d' or resume_checkpoint is not None:
            hooks['iter_cb'] = lambda k, n: emit(f"outer {k}/{n}")
        worker = partial(_run_compute, control=self.window.run_control, ui_hooks=hooks,
                         run_directory=directory, checkpoint_interval_s=checkpoint_interval,
                         gui_provenance=saved_provenance, resume_checkpoint=resume_checkpoint)
        self.active_directory = directory
        self.provenance = provenance
        self._grid_cells = grid_cells
        if self.compute.start(mode, worker, cfg=config):
            return True
        self.active_directory = self.provenance = self._grid_cells = None
        if resume_checkpoint is None:
            message = ("3D compute orchestrator rejected start — already running." if mode == '3d'
                       else "Compute orchestrator rejected start — already running.")
            QMessageBox.information(self.window, "Compute Busy", message)
        return False

    @Slot(str)
    def _started(self, mode):
        window = self.window
        self._state = 'running'
        self._started_at = perf_counter()
        self._iteration_label = ''
        self._cancelling = False
        self._button_label = window.btn_compute.text()
        self._hide_progress.stop()
        window.progress.show()
        window.progress.setValue(10)
        card = window._run_status_card
        card.start(mode, recoverable=self.active_directory is not None)
        if self.active_directory is not None:
            card.note.setText(f'在完整计算步结束后自动保存。保存目录：{self.active_directory}')
        window.btn_compute.setText("取消  ·  0.0s")
        window.btn_compute.setIcon(icon('square', get_theme()['primary_fg']))
        window.btn_compute.setEnabled(True)
        window._empty_state_label.hide()
        self._ticker.start()
        from tm1.applications.gui.ui.builders_sidebar import refresh_header_status
        refresh_header_status(window)
        if hasattr(window, '_refresh_workbench_navigation'):
            window._refresh_workbench_navigation()
        self.activity_changed.emit()

    @Slot(int)
    def _progress(self, percent):
        if self._state == 'running':
            self.window.progress.setValue(min(100, max(0, percent)))

    @Slot(str)
    def _iteration(self, label):
        if self._state == 'running':
            self._iteration_label = label
            self.window._run_status_card.set_iteration(label)

    @Slot()
    def _tick(self):
        window = self.window
        elapsed = perf_counter() - self._started_at
        window._run_status_card.set_elapsed(elapsed)
        if self._cancelling:
            return
        if self._grid_cells is not None:
            timeout = 1800
            if elapsed > timeout:
                self.cancel()
                window.dialogs.notify(
                    f"三维求解超出 {timeout}s 预算，将在下一个检查点自动取消。",
                    kind="warn",
                    duration_ms=8000,
                )
                return
        suffix = f"  ·  {self._iteration_label}" if self._iteration_label else ''
        window.btn_compute.setText(f"取消  ·  {duration(elapsed)}{suffix}")

    @Slot()
    def cancel(self):
        if self._state != 'running':
            return
        self._cancelling = True
        self._ticker.stop()
        self.compute.cancel()
        if self.window._close_pending:
            return
        self.window._run_status_card.request_cancel()
        self.window.btn_compute.setEnabled(False)
        self.window.btn_compute.setText("正在取消…")
        self.window.dialogs.notify(
            "已请求取消 — 等待求解器完成当前计算步…", kind="info", duration_ms=5000
        )

    @Slot()
    def pause(self):
        if self._state != 'running' or self.active_directory is None:
            return
        self.compute.pause()
        self.window._run_status_card.request_pause()
        self.window.dialogs.notify(
            "正在等待完整迭代步，保存后暂停。", kind="info", duration_ms=5000
        )

    def _begin_terminal(self):
        if self._state != 'running':
            return False
        self._state = 'finishing'
        self._ticker.stop()
        return True

    @Slot(object)
    def _finished(self, result):
        if not self._begin_terminal():
            return
        window = self.window
        success = False
        try:
            if window._close_pending:
                return
            window.btn_compute.setEnabled(False)
            window.btn_compute.setText("正在显示结果…")
            card = window._run_status_card
            card.title.setText("正在显示结果")
            card.cancel_button.setEnabled(False)
            card.pause_button.setEnabled(False)
            if isinstance(self.provenance, dict):
                import datetime
                from tm1.run_control.provenance import SOURCE_ROOT, repository_revision

                self.provenance.setdefault(
                    'completed_at', datetime.datetime.now().isoformat(timespec='seconds')
                )
                result_rev = (
                    (result.metadata.get('provenance') or {}).get('revision')
                    if isinstance(getattr(result, 'metadata', None), dict)
                    and isinstance(result.metadata.get('provenance'), dict)
                    else None
                )
                rev = str(result_rev or (repository_revision(SOURCE_ROOT)['revision'] or ''))[:7]
                if rev:
                    self.provenance.setdefault('commit', rev)
            success = window.results.present(result, mode=self.compute.current_mode(),
                                             provenance=self.provenance, elapsed=self.compute.last_elapsed())
        finally:
            self._finish('success' if success else 'error',
                         '' if success else '计算结束，但结果显示未完成。请查看诊断与日志。')

    @Slot(str, str)
    def _error(self, message, log_text):
        if not self._begin_terminal():
            return
        window = self.window
        self._finish('error', message)
        if window._close_pending:
            return
        window.workbench.update_tab_visibility()
        if self.compute.current_mode() == '3d':
            QMessageBox.critical(window, "3D Compute Error", message)
        else:
            from tm1.applications.gui.ui.microanim import toast
            QMessageBox.critical(window, "Compute Error", message)
            toast(window, f"Compute failed — {message[:80]}", kind='error', copy_payload=log_text or message)

    @Slot(str)
    def _cancelled(self, log_text):
        if not self._begin_terminal():
            return
        self._finish('cancelled', '求解器已响应取消请求。')
        if self.window._close_pending:
            return
        if self.compute.current_mode() == '3d':
            self.window.workbench.update_tab_visibility()
            self.window.dialogs.notify("三维计算已取消或超时中止。", kind="warn", duration_ms=6000)
        else:
            self.window.dialogs.notify("已取消计算。", kind="info", duration_ms=TOAST_MS_SHORT)

    @Slot(str, str)
    def _paused(self, checkpoint_file, log_text):
        if not self._begin_terminal():
            return
        self.checkpoint_file = checkpoint_file
        self._finish('paused', f'可从载入菜单继续本次计算：{checkpoint_file}')
        if not self.window._close_pending:
            self.window.dialogs.notify(
                f"已保存并暂停：{checkpoint_file}", kind="info", duration_ms=5000
            )

    def _finish(self, state, message):
        try:
            if self.window._close_pending:
                return
            from tm1.applications.gui.ui.fmt import recorded_elapsed_s

            window = self.window
            window.btn_compute.setEnabled(False)
            elapsed = perf_counter() - self._started_at
            elapsed_label = '端到端'
            total_elapsed = None
            solve_elapsed = None
            success = state == 'success'
            if success:
                result = window.cache.get_result()
                total_elapsed = self.compute.last_elapsed() + result.metadata['timings_s']['display']
                solve_elapsed = recorded_elapsed_s(result)
                if isinstance(solve_elapsed, (int, float)):
                    elapsed, elapsed_label = solve_elapsed, '求解耗时'
                elif isinstance(total_elapsed, (int, float)):
                    elapsed, elapsed_label = total_elapsed, '端到端'
                else:
                    elapsed, elapsed_label = None, ''
                notices = set(result.warnings + result.extrap_reasons)
                view_missing = self.compute.current_mode() == '3d' and window.workbench.volume_error
                if not result.converged:
                    state = 'unconverged'
                    message = '求解器未达到收敛条件；请查看诊断，结果仅供参考。'
                elif notices or view_missing:
                    state = 'warning'
                    if notices:
                        message = f'本次计算有 {len(notices)} 条提示，请查看诊断。'
                if view_missing:
                    message += ' 三维视图不可用；计算结果仍可导出。'
            if self.active_directory is not None:
                checkpoint = self.active_directory / 'checkpoint.h5'
                if checkpoint.is_file():
                    self.checkpoint_file = str(checkpoint)
                    if not success and state != 'paused':
                        message += f' 可从载入菜单继续已保存的状态：{checkpoint}'
            if not success and window.cache.has_any_results():
                message += ' 已保留最近完成的计算结果，摘要与导出仍对应该结果。'
            window._run_status_card.finish(
                state,
                elapsed,
                log_available=bool(self.compute.last_log().strip()),
                message=message,
                elapsed_label=elapsed_label,
            )
            if success:
                from tm1.applications.gui.ui.microanim import pulse_glow
                window.progress.setValue(100)
                self._hide_progress.start(500)
                if isinstance(solve_elapsed, (int, float)):
                    done_msg = f"计算完成 · 求解耗时 {duration(solve_elapsed)}"
                else:
                    done_msg = f"计算完成 · 端到端 {duration(elapsed)}"
                window.dialogs.notify(done_msg, kind='success')
                if window.workbench.active_tab == 'layout' and window.btn_tab_result.isEnabled():
                    pulse_glow(window.btn_tab_result, color=get_theme()['accent_primary'],
                               blur_peak=22, duration_ms=700)
            else:
                window.progress.hide()
        finally:
            self.active_directory = self.provenance = self._grid_cells = None
            QTimer.singleShot(0, self, self._release)

    @Slot()
    def _release(self):
        # Terminal delivery precedes the return from QRunnable.run().
        if not self.compute.is_idle():
            QTimer.singleShot(10, self, self._release)
            return
        self._state = 'idle'
        if not self.window._close_pending:
            self.window.btn_compute.setText(self._button_label)
            self.window.btn_compute.setIcon(icon('play', get_theme()['primary_fg']))
            self.window.btn_compute.setEnabled(True)
            from tm1.applications.gui.ui.builders_sidebar import refresh_header_status
            refresh_header_status(self.window)
            if hasattr(self.window, '_refresh_workbench_navigation'):
                self.window._refresh_workbench_navigation()
        self.activity_changed.emit()

    def _maybe_highvel_notice(self, compute_cfg):
        """Report prescribed speeds; preparation resolves mass-flow speeds."""
        speeds = [(side, fluid.u_mps) for side, fluid in
                  (('A', compute_cfg.fluid_A), ('B', compute_cfg.fluid_B))
                  if fluid.mass_flow_kg_s is None]
        if any(speed > HIGH_VELOCITY_NOTICE_MS for _, speed in speeds):
            values = ", ".join(f"u_{side}={speed:.1f}" for side, speed in speeds)
            self.window.dialogs.notify(
                f"入口速度较高：{values} m/s。"
                "请关注收敛与压降；适用范围以当前模型检查为准。",
                kind="warn",
                duration_ms=10000,
            )

    def _preflight_3d(self, compute_cfg):
        """Confirm large grids from the captured total cell counts."""
        solver = compute_cfg.solver
        Nx_u, Ny_u, Nz_u = solver.Nx, solver.Ny, solver.Nz
        est_cells = Nx_u * Ny_u * Nz_u
        if est_cells > 100_000:
            _expand = f"User grid {Nx_u}x{Ny_u}x{Nz_u}. "
            # Estimate the working set with 50 float64 arrays per cell.
            _ram_gb = est_cells * 50 * 8 / 1e9
            reply = QMessageBox.question(
                self.window, "Large 3D Grid",
                f"Estimated cells: ~{est_cells:,}"
                f"  (≈ {_ram_gb:.1f} GB working memory)\n\n"
                f"{_expand}This can take many minutes.\n\n"
                "Mesh requirements depend on the selected scheme and port "
                "positions; review Grid preflight before reducing counts.\n\n"
                "Proceed anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return False, 0, ''

        return True, est_cells, f"{Nx_u}×{Ny_u}×{Nz_u}"

    def validate_inputs(self):
        """Check active fields before configuration capture.

        Keep field errors and required blanks visible. A complete blank second
        transverse span is valid.
        """
        from html import escape
        from tm1.applications.gui.ui.window_config import LINE_EDITS, blank_second_span, field_active

        window = self.window
        bad = []
        is_3d = window.combo_dim.currentIndex() == 1
        for name, spec in LINE_EDITS.items():
            if not field_active(window, spec, is_3d=is_3d):
                continue
            le = getattr(window, name)
            if name in ('le_TinA', 'le_TinB'):
                # The Compute shortcut can leave the inlet edit in focus.
                window._field_validators[name]()
            if le.property('inpError') == 'true':
                label = (le.accessibleName() or name)
                val = le.text() or '(empty)'
                bad.append((label, name, val))
            elif not le.text().strip() and not blank_second_span(window, name):
                # Keep required empty fields in the same error list.
                label = (le.accessibleName() or name)
                bad.append((label, name, '(empty)'))
        if not bad:
            return True
        t = get_theme()
        rows = "".join(
            f"<tr><td style='padding:4px 14px 4px 0;'>{escape(str(lbl))}</td>"
            f"<td style='padding:4px 14px 4px 0; color:{t['sub_fg']};'>"
            f"<code>{escape(str(name))}</code></td>"
            f"<td style='padding:4px 0; color:{t['err']};'>"
            f"{escape(str(val))}</td></tr>"
            for lbl, name, val in bad[:30])
        html = (
            f"<h3 style='margin:0 0 8px 0;'>"
            f"{len(bad)} 个无效输入</h3>"
            f"<p style='margin:0 0 10px 0; color:{t['sub_fg']};'>"
            "运行计算前请先修正下列字段；悬停字段可查看原因。</p>"
            "<table style='border-collapse:collapse;'>"
            f"{rows}</table>")
        msg = QMessageBox(self.window)
        msg.setWindowTitle("检查输入")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(html)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
        # Focus the first invalid field so Tab navigation works from there.
        from tm1.applications.gui.ui.ui_builders import reveal_parameter
        first = getattr(window, bad[0][1])
        reveal_parameter(window, first)
        first.setFocus()
        first.selectAll()
        return False

    def preflight_grid(self, compute_cfg):
        """Check captured inputs and request confirmation for grid warnings."""
        from tm1.data_types.compute_config import bc_to_dict
        from tm1.applications.gui.ui.preflight import FluidCfg, compute_preflight
        geometry, solver = compute_cfg.geometry, compute_cfg.solver

        def _cfg(bc):
            # Keep mixed widths for validation; typed configurations always have two fluids.
            port = bc_to_dict(bc, geometry.L_dom_m, geometry.H_dom_m,
                              side='B', with_z=compute_cfg.is_3d)
            if port is None:
                port = bc_to_dict(bc, geometry.L_dom_m, geometry.H_dom_m,
                                  side='A', with_z=compute_cfg.is_3d)
            return FluidCfg(
                dir=port['dir'], in_ctr=port['in_ctr'], in_w=port['in_w'],
                out_ctr=port['out_ctr'], out_w=port['out_w'],
                z_in_ctr=port.get('in_z_ctr'), z_in_w=port.get('in_z_w'),
                z_out_ctr=port.get('out_z_ctr'), z_out_w=port.get('out_z_w'))

        # Geometry/D-F coverage is separate from Nu and calibration limits.
        # Hard invalid geometry blocks; soft findings join the grid report.
        try:
            from tm1.data_types.validator import validate_geometry
            geometry_warnings = validate_geometry(
                geometry.L_dom_m, geometry.H_dom_m, geometry.Lz_m,
                geometry.L_cell_mm, geometry.t_wall_mm,
                ks=geometry.k_s_W_mK, is_3d=compute_cfg.is_3d)
        except ValueError as error:
            QMessageBox.critical(
                self.window, "几何输入不合法", str(error))
            return False

        report = compute_preflight(
            L=geometry.L_dom_m, H=geometry.H_dom_m, Lz=geometry.Lz_m,
            Nx=solver.Nx, Ny=solver.Ny, Nz=solver.Nz,
            is_3d=compute_cfg.is_3d,
            port_wall_refine=compute_cfg.flags.port_wall_refine,
            zone_axis=compute_cfg.zones.axis if compute_cfg.zones.enabled else None,
            fluid_A=_cfg(compute_cfg.bc_A), fluid_B=_cfg(compute_cfg.bc_B),
            T_inA=compute_cfg.fluid_A.T_in_K, T_inB=compute_cfg.fluid_B.T_in_K)
        for warning in geometry_warnings:
            if warning.severity == 'error':
                report.errors.append(warning.message)
            else:
                report.warnings.append(warning.message)

        if not report.errors and not report.warnings:
            if report.info:
                self.window.dialogs.notify(" · ".join(report.info[:2]), kind="info", duration_ms=5000)
            return True

        import html as _h
        t = get_theme()

        def _rows(items, color):
            return "".join(
                f"<li style='margin:4px 0; color:{color};'>{_h.escape(s)}</li>"
                for s in items)

        sev_html = []
        if report.errors:
            sev_html.append(
                f"<h4 style='margin:8px 0 4px 0; color:{t['err']};'>"
                f"{len(report.errors)} error"
                f"{'s' if len(report.errors) != 1 else ''}</h4>"
                f"<ul style='margin:0;'>{_rows(report.errors, t['err'])}</ul>")
        if report.warnings:
            sev_html.append(
                f"<h4 style='margin:8px 0 4px 0; color:{t['search_hl']};'>"
                f"{len(report.warnings)} warning"
                f"{'s' if len(report.warnings) != 1 else ''}</h4>"
                f"<ul style='margin:0;'>{_rows(report.warnings, t['search_hl'])}</ul>")
        if report.info:
            sev_html.append(
                f"<h4 style='margin:8px 0 4px 0; color:{t['sub_fg']};'>Info</h4>"
                f"<ul style='margin:0;'>{_rows(report.info, t['sub_fg'])}</ul>")

        html = (
            "<h3 style='margin:0 0 8px 0;'>Grid preflight</h3>"
            f"<p style='margin:0 0 8px 0; color:{t['sub_fg']};'>"
            "Reviewed wall-refine fit, inlet/outlet coverage, "
            "and Richardson budget.</p>" + "".join(sev_html))

        msg = QMessageBox(self.window)
        msg.setWindowTitle("Grid preflight")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(html)
        if report.errors:
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
            return False
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        return msg.exec() == QMessageBox.StandardButton.Yes
