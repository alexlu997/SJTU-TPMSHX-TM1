"""Compute-run orchestration handlers for ``Main_Menu``.

Extracted verbatim from the ``main`` god object: the Compute entry
points (run_calculation / _run_calculation_3d),
the ComputeOrchestrator signal handlers (_on_orch_started / _progress /
_finished / _error / _cancelled), and the compute-UI lifecycle helpers
(_begin_compute_ui / _end_compute_ui / _on_cancel_compute /
_active_compute_mode / _begin_btn_ticker / _tick_btn).

Result presentation (write_result / _finalize_plots /
_update_result_summary / _diag_summary_text / _show_diag_dialog) moved
verbatim to ``ui/mixins/run_results.py`` (P2.5a, 2026-07-20); handlers
here reach it via ``self`` through the ``Main_Menu`` MRO.

UI orchestration reaches prepare_case / run_case / evaluate through
the common workflow on ComputeOrchestrator workers. RunControl selects the numerical
backend; presentation stays in the UI. Deps are stable
imports (PySide6 widgets, ui.fmt._fmt_dur, ui.ui_constants constants,
time) — no main.py module state. Adopted via
``class Main_Menu(..., RunControllerMixin, QMainWindow)``; external wiring
(ui_builders btn_run, command_palette, signal_router, orch signal
connections) resolves on the live window through the MRO.
"""

from __future__ import annotations

import time as _time
from time import perf_counter
from copy import deepcopy
from functools import partial
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PySide6.QtWidgets import QFileDialog, QMessageBox

from sjtu_tpmshx.ui.fmt import duration as _fmt_dur
from sjtu_tpmshx.ui.icons import icon
from sjtu_tpmshx.ui.ui_constants import HIGH_VELOCITY_NOTICE_MS, TOAST_MS_MED, TOAST_MS_SHORT
from sjtu_tpmshx.domain.module_ports import RunControl


def _run_compute(config, cancel_token, progress_cb, *, ui_hooks, control=RunControl(),
                 run_directory=None, checkpoint_interval_s=None, resume_checkpoint=None,
                 gui_provenance=None):
    from sjtu_tpmshx.controllers.module_adapter import compute_result, to_compute_result
    original_cancel = control.cancel_check

    def cancelled():
        return cancel_token.cancelled or (original_cancel is not None and original_cancel())

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

    control = replace(
        control, cancel_check=cancelled,
        iteration=with_ui_hook('iter_label_cb', control.iteration),
        outer_iteration=with_ui_hook('iter_cb', control.outer_iteration))
    if run_directory is None:
        return compute_result(config, progress_cb=progress_cb, control=control)
    from sjtu_tpmshx.workflows.recovery import compute_run, resume_run
    kwargs = dict(control=control, progress_cb=progress_cb,
                  checkpoint_interval_s=checkpoint_interval_s,
                  pause_check=cancel_token.pause_requested)
    if resume_checkpoint is None:
        _, result, performance = compute_run(config, run_directory,
                                             gui_provenance=gui_provenance, **kwargs)
    else:
        _, result, performance = resume_run(resume_checkpoint, run_directory, **kwargs)
    display = to_compute_result(result, performance)
    control.check_cancelled()
    return display


class RunControllerMixin:
    """Compute entry points + orchestrator signal handlers + UI lifecycle."""

    def run_calculation(self):
        """Full-domain solve: SIMPLE velocity → coupled energy on L × H.

        2026-05-06 refactor (audit fix #4 / Plan #4 Phase 1.2): solver thread
        lifecycle delegated to ComputeOrchestrator. Re-entrancy guard, cancel,
        result distribution, error handling all flow through orch signals.
        """
        if getattr(self, '_close_pending', False):
            return
        # Re-entrancy guard — orchestrator rejects start() while running, but
        # we surface it as a user-visible modal here for parity with the prior
        # UX (memory: 2026-05-05 audit user pain point).
        if self.compute.is_running() or getattr(self, '_compute_running', False):
            QMessageBox.information(
                self, "Compute Busy",
                "A computation is already running.\n\n"
                "Click Cancel (the Compute button while it's red) and wait "
                "for the solver to reach its next checkpoint, then re-Compute.")
            return
        # E10 — pre-flight: if the user has any invalid fields flagged by
        # the inline validator, surface them together in a modal instead
        # of letting the solver hit them one at a time.
        if not self._validate_inputs_preflight():
            return
        from sjtu_tpmshx.ui.window_config import config_from_window
        is_3d = hasattr(self, 'combo_dim') and self.combo_dim.currentIndex() == 1
        try:
            compute_cfg = config_from_window(self, strict=True, force_3d=is_3d)
        except ValueError as error:
            QMessageBox.warning(self, "Invalid Input", str(error))
            return
        # Grid-legality preflight — refined shape, inlet/outlet coverage,
        # Richardson budget. Errors block, warnings prompt continue?.
        if not self._preflight_grid(compute_cfg):
            return
        self._maybe_highvel_notice(compute_cfg)
        if compute_cfg.is_3d:
            self._run_calculation_3d(compute_cfg)
            return

        self._compute_t0 = _time.time()
        worker = self._new_compute_worker('2d', {
            'iter_label_cb': self.compute.iteration.emit,
        })

        self._compute_error = None
        if not self.compute.start('2d', worker, cfg=compute_cfg):
            self._pending_run_provenance = self._active_run_directory = None
            # Should be unreachable due to is_running() guard above; defensive.
            QMessageBox.information(
                self, "Compute Busy",
                "Compute orchestrator rejected start — already running.")
            return
        # Lifecycle now driven entirely by orchestrator signals; the legacy
        # threading.Thread + QTimer poll block is gone (~100 lines deleted).
        return

    def _maybe_highvel_notice(self, compute_cfg):
        """Report prescribed speeds; preparation resolves mass-flow speeds."""
        speeds = [(side, fluid.u_mps) for side, fluid in
                  (('A', compute_cfg.fluid_A), ('B', compute_cfg.fluid_B))
                  if fluid.mass_flow_kg_s is None]
        if any(speed > HIGH_VELOCITY_NOTICE_MS for _, speed in speeds):
            values = ", ".join(f"u_{side}={speed:.1f}" for side, speed in speeds)
            self.statusBar().showMessage(
                f"入口速度较高：{values} m/s。"
                "请关注收敛与压降；适用范围以当前模型检查为准。",
                15000)

    def _preflight_3d(self, compute_cfg):
        """Confirm large grids from the captured total cell counts."""
        solver = compute_cfg.solver
        Nx_u, Ny_u, Nz_u = solver.Nx, solver.Ny, solver.Nz
        est_cells = Nx_u * Ny_u * Nz_u
        if est_cells > 100_000:
            _expand = f"User grid {Nx_u}x{Ny_u}x{Nz_u}. "
            # robustness-hardening (2026-07-03): give the user a RAM number
            # before they click Yes — ~50 float64 field arrays per solve
            # (u/v/w/P/T ×2 fluids + props + AMG hierarchies, empirical
            # ballpark), so 8M cells ≈ 3+ GB and an OOM on a blind Yes.
            _ram_gb = est_cells * 50 * 8 / 1e9
            reply = QMessageBox.question(
                self, "Large 3D Grid",
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

    def _run_calculation_3d(self, compute_cfg):
        """Run a 3D solve and show the selected field on completion."""
        if getattr(self, '_close_pending', False):
            return
        # Re-entrancy guard — same rationale as 2D run_calculation. Without
        # this a fast re-Compute spawned two QTimer instances + two threads,
        # both alive, racing to call _finalize_plots_3d().
        if self.compute.is_running() or getattr(self, '_compute_running', False):
            QMessageBox.information(
                self, "Compute Busy",
                "A 3D computation is already running.\n\n"
                "Click Cancel (red Compute button) and wait for the solver "
                "to reach its next checkpoint, then re-Compute.")
            return
        # Do not initialise PyVista/VTK on button click. The GL context is
        # expensive and made Compute feel frozen before progress appeared;
        # The first volume-view request creates and fills the panel.

        ok, est_cells_r, _cell_label = self._preflight_3d(compute_cfg)
        if not ok:
            return

        self._compute_t0 = _time.time()

        # ComputeOrchestrator path (Plan #4 P1.3 — A.3, 2026-05-06).
        # Replaces the legacy threading.Thread + 600 s poll _check closure.
        # Hard wall-clock budget implemented as a separate QTimer
        # that calls self.compute.cancel() — orchestrator forwards as
        # cooperative cancel to the worker, which exits at next checkpoint.
        from PySide6.QtCore import QTimer

        emit_iteration = self.compute.iteration.emit
        worker = self._new_compute_worker('3d', {
            'iter_cb': lambda k, n: emit_iteration(f"outer {k}/{n}"),
        })

        self._compute_error = None
        if not self.compute.start('3d', worker, cfg=compute_cfg):
            self._pending_run_provenance = self._active_run_directory = None
            QMessageBox.information(
                self, "Compute Busy",
                "3D compute orchestrator rejected start — already running.")
            return
        self.statusBar().showMessage(
            f"Computing 3D ({_cell_label} = {est_cells_r:,} cells, "
            "compressible dual-fluid SIMPLE)…")

        # Status updater on a separate QTimer (orchestrator handles the
        # thread; this is a UI-only ticker that reports elapsed wall-clock +
        # the solver's outer-iteration label, and enforces a hard wall-clock
        # budget). ETA *prediction* was dropped 2026-06-01 — see _tick_3d.
        wd = QTimer(self)
        self._compute_3d_watchdog = wd
        _hard_timeout_s = 1800.0   # 30 min — generous for high-u + dense grids

        def _tick_3d():
            if not self.compute.is_running():
                wd.stop()
                return
            elapsed = _time.time() - self._compute_t0
            if elapsed > _hard_timeout_s:
                self._on_cancel_compute()
                self.statusBar().showMessage(
                    f"3D compute exceeded {int(_hard_timeout_s)}s budget "
                    "— auto-cancelling at next checkpoint.", 8000)
                wd.stop()
                return
            # ETA prediction removed 2026-06-01: the linear cell-scaling model
            # (cells/35k × 150s × (u/10)²) was calibrated on low-Re Shanghai
            # cases and wildly under-estimated high-u / dense-3D runs (e.g.
            # 8k cells @ u=20 estimated ~2 min, actually 8 min+). 3D LTNE wall-
            # clock is non-linear in cells AND Re, so any cheap projection
            # misleads. Show honest live progress instead: elapsed + cells +
            # the outer-iteration label (set by the solver via _iter_label_now).
            from sjtu_tpmshx.ui.fmt import duration as _fmt
            label = getattr(self, '_iter_label_now', None)
            iter_txt = f" • {label}" if label else ""
            self.statusBar().showMessage(
                f"Computing 3D… {_fmt(elapsed)} elapsed "
                f"({est_cells_r:,} cells){iter_txt} • solver running")
        wd.timeout.connect(_tick_3d)
        wd.start(500)
        return

    def _capture_run_provenance(self, mode):
        preset = deepcopy(self._capture_current_preset('Run inputs'))
        axes = ('x', 'y', 'z') if mode == '3d' else ('x', 'y')
        return dict(preset=preset,
            preset_source=getattr(self, '_active_preset_name', '') or '—', mode=mode,
            input_grid=[preset['line_edits'].get(f'le_N{axis}', '?') for axis in axes])

    def _new_compute_worker(self, mode, ui_hooks):
        control = getattr(self, 'run_control', RunControl())
        options = dict(control=control, ui_hooks=ui_hooks)
        provenance = self._capture_run_provenance(mode)
        directory = self.sm.base_dir / 'runs' / ('run-' + uuid4().hex)
        self._pending_run_provenance = provenance
        self._active_run_directory = directory
        options.update(run_directory=directory, checkpoint_interval_s=60.,
                       gui_provenance=provenance)
        return partial(_run_compute, **options)

    def _on_orch_started(self, mode):
        """Compute kicked off. Lock UI + start progress widgets."""
        # started is emitted synchronously on the GUI thread, only after
        # start accepts the run and before dispatch or UI event processing.
        provenance = getattr(self, '_pending_run_provenance', None)
        self._pending_run_provenance = None
        if provenance is None:
            provenance = self._capture_run_provenance(mode)
        self._run_provenance = provenance
        # Backwards-compat: tests / external code still read _compute_running.
        # We mirror it from the orchestrator's authoritative flag.
        self._compute_running = True
        self._begin_compute_ui()
        # Fresh per-run log buffer for the D9 solve-log viewer.
        self._last_solve_log = ""
        self._compute_progress = 10

    def _on_orch_progress(self, percent):
        """Receive pipeline progress on the GUI thread."""
        self._compute_progress = min(100, max(0, int(percent)))
        self.progress.setValue(self._compute_progress)

    def _on_orch_iteration(self, label):
        self._iter_label_now = label
        card = getattr(self, '_run_status_card', None)
        if card is not None:
            card.set_iteration(label)

    def _on_orch_finished(self, result):
        """Publish once on the GUI thread; unlock only after rendering."""
        if getattr(self, '_close_pending', False):
            self._run_provenance = None
            return
        if not getattr(self, '_compute_running', False):
            return
        self._last_solve_log = self.compute.last_log()
        for name in ('_compute_3d_watchdog', '_btn_ticker_timer'):
            timer = getattr(self, name, None)
            if timer is not None:
                timer.stop()
        self.btn_compute.setEnabled(False)
        self.btn_compute.setText("正在显示结果…")
        card = getattr(self, '_run_status_card', None)
        if card is not None:
            card.title.setText("正在显示结果")
            card.cancel_button.setEnabled(False)
            card.pause_button.setEnabled(False)
        display_started = perf_counter()
        self._present_compute_result(result, display_started)

    def _present_compute_result(self, result, display_started):
        """Publish scalars and render the selected field."""
        if getattr(self, '_close_pending', False):
            self._run_provenance = None
            return
        if not getattr(self, '_compute_running', False):
            return
        success = False
        published = False
        try:
            provenance = getattr(self, '_run_provenance', None)
            if provenance is not None:
                keys = ('dx', 'dy', 'dz') if provenance['mode'] == '3d' else ('dx_arr', 'dy_arr')
                provenance['actual_grid'] = [
                    len(result.fields[key]) if result.fields.get(key) is not None else '?'
                    for key in keys]
                result.metadata['run_provenance'] = deepcopy(provenance)
            self.write_result(result)
            published = True
            if provenance is None or not provenance.get('resumed_from'):
                for side, inlet in result.metadata.get('inlet_inputs', {}).items():
                    if inlet['mass_flow_kg_s'] is not None:
                        getattr(self, 'le_u' + side).setText(format(inlet['u_mps'], '.17g'))
            success = self._render_compute_result()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            stage = 'display' if published else 'publication'
            self.statusBar().showMessage(f"Result {stage} failed: {exc}", 12000)
        finally:
            display_s = perf_counter() - display_started
            if published:
                self.cache.get_result().metadata.setdefault('timings_s', {})['display'] = display_s
            try:
                if published:
                    # Numerical publication survives a renderer error. All
                    # accepted-result surfaces must advance together.
                    if not success:
                        for field in ('temp', 'pres', 'vel'):
                            canvas = getattr(self, f'canvas_{field}', None)
                            if canvas is not None and not self.cache.is_drawn(field):
                                # A failed redraw cannot stand in for this run
                                # with the preceding run's pixels or probe data.
                                canvas.fig.clear()
                                canvas._hover_data = None
                                canvas.draw_idle()
                    self._update_result_summary()
                    self._update_tab_visibility()
                    self.btn_export.setEnabled(True)
                    elapsed = self.compute.last_elapsed() + display_s
                    self._last_elapsed_s = elapsed
                    self._refresh_status_bar()
                    self._stamp_result_provenance(elapsed)
            finally:
                try:
                    self._end_compute_ui(success=success)
                finally:
                    self._run_provenance = None

    def _render_compute_result(self):
        """Render the published result and report presentation success."""
        mode = self.compute.current_mode()
        if mode == '3d':
            from sjtu_tpmshx.ui.plot_2d_results import ensure_result_plot
            field = self._resolve_2d_view_card()
            success = ensure_result_plot(self, field)
            self._rendered_3d_slices = success
            self._update_tab_visibility()
            if success:
                self._switch_tab(field)
                self.statusBar().showMessage('场图已显示；首次选择三维时加载体视图。', 8000)
            for key, dialog in getattr(self, '_detached_canvases', {}).items():
                if key in ('temp', 'pres', 'vel') and dialog.isVisible():
                    ensure_result_plot(self, key)
            detached = getattr(self, '_3d_detached_window', None)
            if detached is not None and detached.isVisible():
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, self, lambda: self._request_3d_view(
                    lambda: None, background=True))
            return success

        # 2D mode (default).
        # 2026-05-09 — wrap finalize_plots so a panel crash (e.g. NaN
        # contourf, water-side LTNE divergence) does NOT block 2D results
        # from unlocking. The user still benefits from valid velocity /
        # pressure canvases even when one panel fails to render.
        _finalize_ok = True
        try:
            self._finalize_plots()
        except Exception as _fe:
            _finalize_ok = False
            import traceback
            traceback.print_exc()
            self.statusBar().showMessage(
                f"Plot finalize failed: {_fe!r} — partial 2D results available.",
                8000)
        self._update_tab_visibility()
        for _bname in ('btn_export',):
            if hasattr(self, _bname):
                getattr(self, _bname).setEnabled(True)
        self._switch_tab('temp')
        if _finalize_ok:
            self.statusBar().showMessage("Done.", TOAST_MS_MED)
        return _finalize_ok

    def _on_orch_error(self, message, log_text):
        """Report a failed attempt without replacing the accepted result."""
        self._run_provenance = None
        if getattr(self, '_close_pending', False):
            return
        self._compute_running = False
        self._compute_error = message
        self._last_solve_log = log_text
        wd = getattr(self, '_compute_3d_watchdog', None)
        if wd is not None:
            try:
                wd.stop()
            except Exception:
                pass

        mode = self.compute.current_mode()
        if mode == '3d':
            self._update_tab_visibility()
            self._end_compute_ui(success=False)
            # User-cancel or timeout already surfaced as cancelled signal —
            # if we reach here it's a real error.
            QMessageBox.critical(self, "3D Compute Error", message)
            return

        self._update_tab_visibility()
        self._end_compute_ui(success=False)
        QMessageBox.critical(self, "Compute Error", message)
        try:
            from sjtu_tpmshx.ui.microanim import toast as _toast
            _toast(self, f"Compute failed — {message[:80]}",
                   kind='error',
                   copy_payload=log_text or message)
        except Exception:
            pass

    def _on_orch_cancelled(self, log_text):
        """Cancel the pending attempt; retain the complete accepted snapshot."""
        self._run_provenance = None
        if getattr(self, '_close_pending', False):
            return
        self._compute_running = False
        self._compute_cancel = True
        self._last_solve_log = log_text
        wd = getattr(self, '_compute_3d_watchdog', None)
        if wd is not None:
            try:
                wd.stop()
            except Exception:
                pass

        mode = self.compute.current_mode()
        if mode == '3d':
            self._update_tab_visibility()
            self._end_compute_ui(success=False)
            self.statusBar().showMessage(
                "3D compute aborted (cancelled or timed-out).", 6000)
            return

        self._end_compute_ui(success=False)
        self.statusBar().showMessage("Cancelled.", TOAST_MS_SHORT)

    def _begin_compute_ui(self, status="Computing…"):
        """Lock the header Compute button + surface the progress bar so the
        user sees an obvious "I'm working" signal. Also hides the canvas
        empty-state hint in case it was still showing."""
        self.progress.show()
        self.progress.setValue(10)
        card = getattr(self, '_run_status_card', None)
        if card is not None:
            directory = getattr(self, '_active_run_directory', None)
            card.start(self.compute.current_mode(), recoverable=directory is not None)
            if directory is not None:
                card.note.setText(f'在完整计算步结束后自动保存。保存目录：{directory}')
        self._compute_paused = None
        # Cooperative cancel: clear the flag at compute start, then repurpose
        # the Compute button as a Cancel button. The worker polls
        # `_compute_cancel` at outer-iteration boundaries (the only safe
        # interrupt point — JIT'd inner sweeps can't be killed mid-run).
        self._compute_cancel = False
        if hasattr(self, 'btn_compute'):
            # Preserve the Compute label if UI setup is repeated.
            _cur_btn_text = self.btn_compute.text()
            if not _cur_btn_text.startswith("取消"):
                self._btn_compute_text_saved = _cur_btn_text
            # ETA text removed 2026-05-14 — median-of-history misled when
            # config changed. Live elapsed + iter counter via _tick_btn.
            self._iter_label_now = None
            self.btn_compute.setText("取消  ·  0.0s")
            self.btn_compute.setIcon(icon('square', 'white'))
            self.btn_compute.setEnabled(True)
            self._begin_btn_ticker()
            # Surgical disconnect of the *exact* current handler (run_calculation
            # or a stale Cancel handler from prior run). disconnect() with no
            # args was nuking *all* clicked slots, which let stray reconnects
            # accumulate after a failed compute (compute hang on re-click).
            prev = getattr(self, '_compute_btn_handler', None)
            if prev is not None:
                try:
                    self.btn_compute.clicked.disconnect(prev)
                except (TypeError, RuntimeError):
                    pass
            else:
                # First-time path — drop the constructor's run_calculation
                # connection (we'll re-add via _end_compute_ui).
                try:
                    self.btn_compute.clicked.disconnect(self.run_calculation)
                except (TypeError, RuntimeError):
                    pass
            self._compute_btn_handler = self._on_cancel_compute
            self.btn_compute.clicked.connect(self._compute_btn_handler)
        if hasattr(self, '_empty_state_label'):
            self._empty_state_label.setVisible(False)
        self.statusBar().showMessage(status)

    def _end_compute_ui(self, success):
        """Restore Compute button and either fade out progress (success) or
        hide immediately (failure). Successful presentation records history.

        Stop the UI tickers and restore Compute after result display finishes.
        The task-lifetime gate also waits for any import worker to finish.
        """
        if success:
            result = self.cache.get_result()
            # Worker time includes validation/setup as well as the three phases.
            # User interaction and queued delivery do not belong to compute time.
            elapsed = self.compute.last_elapsed() + result.metadata['timings_s']['display']
        else:
            elapsed = _time.time() - getattr(self, '_compute_t0', _time.time())
        card = getattr(self, '_run_status_card', None)
        if card is not None:
            message = ''
            if success:
                notices = list(dict.fromkeys((*result.warnings, *result.extrap_reasons)))
                view_missing = (self.compute.current_mode() == '3d'
                                and getattr(self, '_3d_view_error', False))
                state = ('unconverged' if not result.converged else
                         'warning' if notices or view_missing else 'success')
                if state == 'unconverged':
                    message = '求解器未达到收敛条件；请查看诊断，结果仅供参考。'
                elif notices:
                    message = f'本次计算有 {len(notices)} 条提示，请查看诊断。'
                if view_missing:
                    message += ' 三维视图不可用；计算结果仍可导出。'
            elif getattr(self, '_compute_error', None):
                state, message = 'error', str(self._compute_error)
            elif getattr(self, '_compute_paused', None):
                state = 'paused'
                message = f'可从载入菜单继续本次计算：{self._compute_paused}'
            elif getattr(self, '_compute_cancel', False):
                state, message = 'cancelled', '求解器已响应取消请求。'
            else:
                state, message = 'error', '计算结束，但结果显示未完成。请查看诊断与日志。'
            directory = getattr(self, '_active_run_directory', None)
            checkpoint = Path(directory) / 'checkpoint.h5' if directory is not None else None
            if checkpoint is not None and checkpoint.is_file():
                self._last_checkpoint_file = str(checkpoint)
                if not success and state != 'paused':
                    message += f' 可从载入菜单继续已保存的状态：{checkpoint}'
            if not success and self.cache.has_any_results():
                message += ' 已保留最近完成的计算结果，摘要与导出仍对应该结果。'
            card.finish(state, elapsed,
                        log_available=bool(getattr(self, '_last_solve_log', '').strip()),
                        message=message)
        self._compute_running = False
        # Stop the elapsed/iter button-text ticker (paired with
        # _begin_btn_ticker). Idempotent — silently no-ops when absent.
        bt = getattr(self, '_btn_ticker_timer', None)
        if bt is not None:
            try:
                bt.stop()
            except Exception:
                pass
        self._iter_label_now = None
        if hasattr(self, 'btn_compute'):
            self.btn_compute.setEnabled(True)
            self.btn_compute.setText(
                getattr(self, '_btn_compute_text_saved', '开始计算'))
            self.btn_compute.setIcon(icon('play', 'white'))
            # Restore the original Compute click handler. Surgical
            # disconnect of the *exact* current handler avoids dropping
            # third-party connections (e.g. shortcut bridges).
            prev = getattr(self, '_compute_btn_handler', None)
            if prev is not None:
                try:
                    self.btn_compute.clicked.disconnect(prev)
                except (TypeError, RuntimeError):
                    pass
            self._compute_btn_handler = self.run_calculation
            self.btn_compute.clicked.connect(self._compute_btn_handler)
        if success:
            self.progress.setValue(100)
            from PySide6.QtCore import QTimer as _QT
            _QT.singleShot(500, self.progress.hide)
            self._push_recent_run()
            # Notify completion; result values are published in the footer.
            try:
                from sjtu_tpmshx.ui.microanim import pulse_glow, toast
                from sjtu_tpmshx.ui.theme import get_theme as _gt
                toast(self, f"Compute done · {_fmt_dur(elapsed)}", kind='success')
                # If the user is still on Geometry, pulse the visible result tab.
                if getattr(self, '_active_tab', None) == 'layout':
                    nxt = self.btn_tab_result
                    if nxt is not None and nxt.isEnabled():
                        pulse_glow(nxt, color=_gt().get('accent_primary', '#3B82F6'),
                                    blur_peak=22, duration_ms=700)
            except Exception:
                pass
        else:
            self.progress.hide()
        self._active_run_directory = None

    def _resume_saved_run(self, checkpoint_file=None):
        """Resume saved physical inputs while the current GUI draft stays separate."""
        from sjtu_tpmshx.ui.background_tasks import has_active_tasks
        from sjtu_tpmshx.domain.compute_config import ComputeConfig
        from sjtu_tpmshx.domain.portable_data import mutable_data
        from sjtu_tpmshx.workflows.recovery import read_run_checkpoint

        if getattr(self, '_close_pending', False):
            return
        if has_active_tasks(self):
            QMessageBox.information(self, '正在计算', '请等待当前任务结束，再继续已保存的计算。')
            return
        if checkpoint_file is None:
            checkpoint_file, _ = QFileDialog.getOpenFileName(self, '继续已保存的计算',
                str(getattr(self, '_last_checkpoint_file', self.sm.base_dir / 'runs')),
                'Solver checkpoint (checkpoint.h5)')
        if not checkpoint_file:
            return
        checkpoint_file = Path(checkpoint_file).resolve()
        try:
            _, case, record = read_run_checkpoint(checkpoint_file)
            config = ComputeConfig.from_dict(mutable_data(case.config_snapshot))
            saved_provenance = record.get('gui_provenance')
            if saved_provenance is not None and not isinstance(saved_provenance, dict):
                raise ValueError('saved GUI provenance must be a record')
            if (saved_provenance and saved_provenance.get('preset') is not None
                    and not isinstance(saved_provenance['preset'], dict)):
                raise ValueError('saved GUI preset must be a record')
            checkpoint_interval = record['checkpoint_interval_s']
        except (OSError, ValueError, KeyError, TypeError) as error:
            QMessageBox.warning(self, '无法继续计算', str(error))
            return
        mode = f"{case.grid['dimension']}d"
        axes = ('Nx', 'Ny', 'Nz') if config.is_3d else ('Nx', 'Ny')
        self._pending_run_provenance = dict(
            preset=deepcopy(saved_provenance.get('preset')) if saved_provenance else None,
            preset_source=(saved_provenance.get('preset_source', '') if saved_provenance
                           else f'保存的工况：{case.case_id}'), mode=mode,
            input_grid=[getattr(config.solver, axis) for axis in axes],
            resumed_from=str(checkpoint_file))
        directory = checkpoint_file.parent.parent / ('run-' + uuid4().hex)
        self._active_run_directory = directory
        self._compute_error = None
        self._compute_t0 = _time.time()
        worker = partial(_run_compute, control=self.run_control,
            ui_hooks={'iter_label_cb': self.compute.iteration.emit,
                      'iter_cb': lambda k, n: self.compute.iteration.emit(f'outer {k}/{n}')},
            run_directory=directory, checkpoint_interval_s=checkpoint_interval,
            resume_checkpoint=checkpoint_file)
        if not self.compute.start(mode, worker, cfg=config):
            self._pending_run_provenance = self._active_run_directory = None
            return
        self.statusBar().showMessage(f'正在继续已保存工况，结果目录：{directory}')

    def _on_cancel_compute(self):
        """User clicked the Compute button while a solve was running, so it
        is currently labelled "Cancel". Set the flag the worker polls; the
        button stays disabled until the worker reaches the next checkpoint
        and returns through `_check`."""
        self._compute_cancel = True
        card = getattr(self, '_run_status_card', None)
        if card is not None:
            card.request_cancel()
        # B2 2.1c: the Pipeline path polls the orchestrator CancelToken
        # (token.cancelled), not the window flag — bridge both cancel
        # mechanisms onto the token so either converges.
        try:
            self.compute.cancel()
        except Exception:
            pass
        if hasattr(self, 'btn_compute'):
            self.btn_compute.setEnabled(False)
            self.btn_compute.setText("正在取消…")
        self.statusBar().showMessage(
            "Cancel requested — waiting for solver to finish current sweep…",
            6000)

    def _on_pause_compute(self):
        """Request a saved pause while the current run owns its output directory."""
        if not self.compute.is_running() or getattr(self, '_active_run_directory', None) is None:
            return
        self.compute.pause()
        self._run_status_card.request_pause()
        self.statusBar().showMessage("正在等待完整迭代步，保存后暂停。")

    def _on_orch_paused(self, checkpoint_file, log_text):
        """Retain the accepted result and identify the saved numerical state."""
        self._run_provenance = None
        self._last_checkpoint_file = checkpoint_file
        if getattr(self, '_close_pending', False):
            return
        self._compute_paused = checkpoint_file
        self._last_solve_log = log_text
        watchdog = getattr(self, '_compute_3d_watchdog', None)
        if watchdog is not None:
            watchdog.stop()
        self._end_compute_ui(success=False)
        self.statusBar().showMessage(f"已保存并暂停：{checkpoint_file}")

    def _active_compute_mode(self):
        """'2d' / '3d' depending on current UI selection. Used by
        the ETA helper so 2D reheats don't skew 3D predictions."""
        try:
            if hasattr(self, 'combo_dim') and self.combo_dim.currentIndex() == 1:
                return '3d'
        except Exception:
            pass
        return '2d'

    def _begin_btn_ticker(self):
        """500 ms ticker driving the Compute/Cancel button live text."""
        from PySide6.QtCore import QTimer as _QT_btn
        t = getattr(self, '_btn_ticker_timer', None)
        if t is None:
            t = _QT_btn(self)
            t.setInterval(500)
            t.timeout.connect(self._tick_btn)
            self._btn_ticker_timer = t
        t.start()

    def _tick_btn(self):
        """Refresh button text with `Cancel · <dur> [· iter k/N]`. The iter
        suffix is omitted when the solver has not published a label
        (e.g. 3D path before its coupling loop starts)."""
        if not hasattr(self, 'btn_compute'):
            return
        t0 = getattr(self, '_compute_t0', None)
        if t0 is None:
            return
        elapsed = _time.time() - t0
        card = getattr(self, '_run_status_card', None)
        if card is not None:
            card.set_elapsed(elapsed)
        if getattr(self, '_compute_cancel', False):
            return
        label = getattr(self, '_iter_label_now', None)
        suffix = f"  ·  {label}" if label else ""
        new_text = f"取消  ·  {_fmt_dur(elapsed)}{suffix}"
        # Skip setText when nothing changed — saves Qt repaint churn at
        # 500 ms tick when sub-second elapsed rounds to same string.
        if self.btn_compute.text() != new_text:
            self.btn_compute.setText(new_text)
