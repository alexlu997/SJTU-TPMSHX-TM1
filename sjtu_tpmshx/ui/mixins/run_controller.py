"""Compute-run orchestration handlers for ``Main_Menu``.

Extracted verbatim from the ``main`` god object: the Compute entry
points (run_calculation / _run_calculation_3d),
the ComputeOrchestrator signal handlers (_on_orch_started / _progress /
_finished / _error / _cancelled), and the compute-UI lifecycle helpers
(_begin_compute_ui / _end_compute_ui / _on_cancel_compute /
_active_compute_mode / _begin_btn_ticker / _tick_btn /
_drain_live_residuals). 13 methods.

Result presentation (write_result / _finalize_plots /
_update_result_summary / _diag_summary_text / _show_diag_dialog) moved
verbatim to ``ui/mixins/run_results.py`` (P2.5a, 2026-07-20); handlers
here reach it via ``self`` through the ``Main_Menu`` MRO.

UI orchestration reaches prepare_case / run_case / evaluate through
Pipeline2D/3D on ComputeOrchestrator workers. Numerical execution lives under
solvers/backends/python; presentation stays in the UI. Deps are stable
imports (PySide6 widgets, ui.fmt._fmt_dur, ui.ui_constants constants,
time) — no main.py module state. Adopted via
``class Main_Menu(..., RunControllerMixin, QMainWindow)``; external wiring
(ui_builders btn_run, command_palette, signal_router, orch signal
connections) resolves on the live window through the MRO.
"""

from __future__ import annotations

import time as _time
from copy import deepcopy
from functools import partial

from PySide6.QtWidgets import QMessageBox

from sjtu_tpmshx.ui.fmt import duration as _fmt_dur
from sjtu_tpmshx.ui.icons import icon
from sjtu_tpmshx.ui.ui_constants import VV_VELOCITY_LIMIT_MS, TOAST_MS_MED, TOAST_MS_SHORT
from sjtu_tpmshx.ui.window_config import validate_domain_shape


from sjtu_tpmshx.ui.compute_api_adapter import run as _run_pipeline

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
        try:
            validate_domain_shape(self)
        except ValueError as error:
            QMessageBox.warning(self, "不支持的计算域", str(error))
            return
        if not self._validate_inputs_preflight():
            return
        # Grid-legality preflight — refined shape, inlet/outlet coverage,
        # Richardson budget. Errors block, warnings prompt continue?.
        if not self._preflight_grid():
            return
        self._maybe_highvel_notice()
        # Mark compute start so `_end_compute_ui` records elapsed for the
        # status bar clock. 3D branch overwrites with its own clock.
        self._compute_t0 = _time.time()
        # 3D dispatch: uniform MVP path (no zoning, Shanghai-style uniform TPMS)
        if hasattr(self, 'combo_dim') and self.combo_dim.currentIndex() == 1:
            self._run_calculation_3d()
            return

        # Validate inputs BEFORE launching solver (Qt-safe on main thread)
        if self._K_ffA is None:
            QMessageBox.warning(self, "Missing Input",
                                "Please click 'Auto-fill Fluid A' first."); return
        if self._K_ffB is None:
            QMessageBox.warning(self, "Missing Input",
                                "Please click 'Auto-fill Fluid B' first."); return

        # B2 2.1b (2026-06-13): the 2D compute path now drives Pipeline2D —
        # the legacy run_calculation_inner(window) entrypoint is deleted.
        # Qt widgets are read EXACTLY ONCE here on the main thread; the
        # worker thread only ever sees the pure ComputeConfig. strict=True
        # reproduces the legacy blank/non-numeric widget validation.
        from sjtu_tpmshx.ui.window_config import config_from_window
        try:
            compute_cfg = config_from_window(self, strict=True,
                                             force_3d=False)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Input", str(e))
            return

        live_residuals = {'A': [], 'B': []}
        from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D
        worker = partial(_run_pipeline, pipeline_cls=Pipeline2D, ui_hooks={
            'live_residuals': live_residuals,
            'iter_label_cb': self.compute.iteration.emit,
        })

        self._compute_error = None
        if not self.compute.start('2d', worker, cfg=compute_cfg):
            # Should be unreachable due to is_running() guard above; defensive.
            QMessageBox.information(
                self, "Compute Busy",
                "Compute orchestrator rejected start — already running.")
            return
        self._live_residuals = live_residuals
        # Lifecycle now driven entirely by orchestrator signals; the legacy
        # threading.Thread + QTimer poll block is gone (~100 lines deleted).
        return

    def _maybe_highvel_notice(self):
        """Non-modal V&V off-domain velocity notice (UI report 2, 2026-05-07).

        The V&V Standard Tier domain sweep validated u ≤ 10 m/s; above that the
        SIMPLE outer loop needs ~5-10× the converge time on the Forchheimer
        branch. Demoted from a blocking dialog to a status-bar message on
        2026-05-14 (the modal interrupted every off-domain run).

        U5 (2026-06-28): parse each velocity independently and let a blank u_B
        inherit u_A — the solver contract (ComputeConfig defaults fluid_B.u_mps
        to fluid_A.u_mps). The old single try-block zeroed BOTH on the blank-u_B
        ValueError, so a high-throughput run (u_A=20, u_B blank) silently lost
        this notice.
        """
        def _vel(attr, dflt):
            le = getattr(self, attr, None)
            try:
                return float(le.text())
            except (ValueError, AttributeError):
                return dflt
        uA = _vel('le_uA', 0.0)
        uB = _vel('le_uB', uA)          # blank u_B inherits u_A
        if uA > VV_VELOCITY_LIMIT_MS or uB > VV_VELOCITY_LIMIT_MS:
            slow = max(uA, uB)
            lo = int(5 * (slow / VV_VELOCITY_LIMIT_MS) ** 2)
            hi = int(10 * (slow / VV_VELOCITY_LIMIT_MS) ** 2)
            self.statusBar().showMessage(
                f"u_A={uA:.1f}, u_B={uB:.1f} m/s outside V&V domain "
                f"(u≤{VV_VELOCITY_LIMIT_MS:.0f} m/s validated). "
                f"Forchheimer-dominated; expect {lo}–{hi}× runtime.",
                15000)

    def _preflight_3d(self):
        """3D-only input guards (B1 1.4 — extracted from
        _run_calculation_3d so future preflights have ONE home).
        Returns (proceed, est_cells_refined, cell_label).
        """
        # 2026-05-20 UI sweep (Tier 22): pre-initialise Nx_u/Ny_u/Nz_u
        # BEFORE the try. Previously a parse failure (empty field, stray
        # unit text) left `Nz_u` undefined and the guard below raised
        # NameError — turning a bad-input case into a hard crash.
        # U4 (2026-06-28): the cell estimate must honour the ACTUAL wall-refine
        # setting. wall-refine adds 16 cells/axis; with it OFF (the default) the
        # unconditional +16 inflated a 40^3=64000 grid to 56^3=175616 and popped
        # a spurious 'Large 3D Grid' confirm whose message described an expansion
        # that won't happen (the displayed label below was already refine-aware).
        _refine_on = bool(getattr(self, 'chk_wall_refine_3d', None)
                          and self.chk_wall_refine_3d.isChecked())
        _pad = 16 if _refine_on else 0
        Nx_u = Ny_u = Nz_u = 0
        try:
            Nx_u = int(self.le_Nx.text()); Ny_u = int(self.le_Ny.text())
            Nz_u = int(self.le_Nz.text())
            est_cells = (Nx_u + _pad) * (Ny_u + _pad) * (Nz_u + _pad)
        except Exception:
            est_cells = 0

        # Nz guard: Nz=1 under 3D dispatch degenerates the z-momentum / z-energy
        # transport and returns a z-uniform field that looks like "T_a = T_inA
        # everywhere" — the user sees a flat-colour cube with scalar-bar min==max
        # and mistakes it for a broken solver. Force at least 2 z-cells for the
        # 3D path; suggest 2D mode otherwise.
        if Nz_u < 2:
            QMessageBox.warning(
                self, "Nz too small for 3D",
                f"Grid Nz = {Nz_u} is too small for 3D compute — the solver "
                f"degenerates to a z-uniform slab and fields look flat.\n\n"
                "Options:\n"
                "  • Increase Nz to 5 or more for a real 3D run (recommended).\n"
                "  • Switch Dimensionality to 2D for single-layer homogeneous cases.")
            return False, 0, ''
        # Large-grid warning. est_cells already reflects the actual refine
        # setting (U4); the message only mentions the wall-refine expansion when
        # it is actually on.
        if est_cells > 100_000:
            _expand = (f"With user grid {Nx_u}x{Ny_u}x{Nz_u}, wall-refine "
                       f"expands to ~{Nx_u+16}x{Ny_u+16}x{Nz_u+16}. "
                       if _refine_on
                       else f"User grid {Nx_u}x{Ny_u}x{Nz_u}. ")
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
                "Suggested 3D defaults: Nx=30, Ny=20, Nz=5 (~30 s).\n\n"
                "Proceed anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return False, 0, ''

        # Displayed cell count / label reuse the refine-aware _pad from above.
        Nx_r, Ny_r, Nz_r = Nx_u + _pad, Ny_u + _pad, Nz_u + _pad
        _cell_label = (f"refined {Nx_r}×{Ny_r}×{Nz_r}" if _refine_on
                       else f"{Nx_r}×{Ny_r}×{Nz_r}")
        return True, Nx_r * Ny_r * Nz_r, _cell_label

    def _run_calculation_3d(self):
        """Threaded 3D solve → auto-switch to 3D View tab on success."""
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
        # finalize_plots_3d creates/populates the panel after the solve.

        ok, est_cells_r, _cell_label = self._preflight_3d()
        if not ok:
            return

        # B2 2.1c (2026-06-13): the 3D compute path drives Pipeline3D —
        # the legacy run_calculation_3d_inner(window) entrypoint is
        # deleted. Qt widgets are read exactly once HERE on the main
        # thread (before the UI locks, so a validation error leaves the
        # window usable).
        from sjtu_tpmshx.ui.window_config import config_from_window
        try:
            compute_cfg = config_from_window(self, strict=True,
                                             force_3d=True)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Input", str(e))
            return

        self._compute_t0 = _time.time()

        # ComputeOrchestrator path (Plan #4 P1.3 — A.3, 2026-05-06).
        # Replaces the legacy threading.Thread + 600 s poll _check closure.
        # Hard wall-clock budget implemented as a separate QTimer
        # that calls self.compute.cancel() — orchestrator forwards as
        # cooperative cancel to the worker, which exits at next checkpoint.
        from PySide6.QtCore import QTimer

        emit_iteration = self.compute.iteration.emit
        from sjtu_tpmshx.controllers.compute_pipeline import Pipeline3D
        worker = partial(_run_pipeline, pipeline_cls=Pipeline3D, ui_hooks={
            'iter_cb': lambda k, n: emit_iteration(f"outer {k}/{n}"),
        })

        self._compute_error = None
        if not self.compute.start('3d', worker, cfg=compute_cfg):
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

    def _on_orch_started(self, mode):
        """Compute kicked off. Lock UI + start progress widgets."""
        # started is emitted synchronously on the GUI thread, only after
        # start accepts the run and before dispatch or UI event processing.
        preset = deepcopy(self._capture_current_preset('Run inputs'))
        axes = ('x', 'y', 'z') if mode == '3d' else ('x', 'y')
        self._run_provenance = {
            'preset': preset,
            'preset_source': getattr(self, '_active_preset_name', '') or '—',
            'mode': mode,
            'input_grid': [preset['line_edits'].get(f'le_N{axis}', '?')
                           for axis in axes],
        }
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
        success = False
        try:
            provenance = getattr(self, '_run_provenance', None)
            if provenance is not None:
                keys = ('dx', 'dy', 'dz') if provenance['mode'] == '3d' else ('dx_arr', 'dy_arr')
                provenance['actual_grid'] = [
                    len(result.fields[key]) if result.fields.get(key) is not None else '?'
                    for key in keys]
                result.metadata['run_provenance'] = deepcopy(provenance)
            self.write_result(result)
            success = self._render_compute_result()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.statusBar().showMessage(f"Result publication failed: {exc}", 12000)
        finally:
            try:
                self._end_compute_ui(success=success)
            finally:
                self._run_provenance = None

    def _render_compute_result(self):
        """Render the published result and report presentation success."""
        mode = self.compute.current_mode()
        if mode == '3d':
            from sjtu_tpmshx.ui.plot_3d_results import finalize_plots_3d
            # 2026-06-02 fix: do NOT pre-clear ``_has_results_3d`` here. In the
            # live window that flag is a ResultCache bridge whose setter
            # (main.Main_Menu._has_results_3d) DELETES ``_result_3d`` — which
            # finalize_plots_3d must read to render the panel. The old C5 H5
            # line ``self._has_results_3d = False`` destroyed the freshly-
            # computed result *before* finalize ran, so finalize saw
            # ``_result_3d is None`` and every 3D run rendered nothing. The
            # GUI slot writes a fresh result before rendering, so
            # there is no "stale True from a prior run" to guard against here;
            # the H5 invariant (no stale flag after a finalize *crash*) is now
            # enforced in the except branch below. (The H5 unit test passed
            # despite the prod bug because its DummyWindow used plain attrs,
            # decoupling the flag from the result — the real bridge couples
            # them.)
            _finalize_ok = False
            _3d_vis_ok = False
            try:
                # 2026-05-20 UI sweep: finalize_plots_3d now returns a bool
                # indicating whether the embedded PyVistaQt panel was
                # populated. Previously it returned None and all visualisation
                # failures were silently swallowed inside the function,
                # producing a "status bar says done but canvas is blank"
                # mismatch. We gate `_has_results_3d` + tab auto-switch on
                # the returned flag so the user is no longer routed to an
                # empty 3D tab.
                _3d_vis_ok = bool(finalize_plots_3d(self))
                _finalize_ok = True
            except Exception as _fe3d:
                # If finalise crashes, walk the button text back to a
                # benign state after this handler returns.
                # Surface the traceback (the 3D path used to swallow it,
                # leaving "status bar says done / canvas blank" with no
                # console clue — matches the 2D path's diagnostics now).
                import traceback
                traceback.print_exc()
                # H5 invariant: a finalize crash must not leave the 3D View tab
                # enabled (which would auto-switch the next run to a blank tab).
                # U1 (2026-06-28): gate the tab off via the dedicated readiness
                # flag — do NOT null _has_results_3d, whose bridge setter would
                # DESTROY the valid solver result. The ComputeResult was written
                # by the GUI slot before finalize and stays exportable even though
                # the PyVista panel never populated.
                self._3d_view_ready = False
                self.statusBar().showMessage(
                    f"3D visualisation failed: {_fe3d!r} — solver finished, "
                    f"render crashed; check console.", 12000)
            if not _finalize_ok:
                return False
            self._has_results = True
            # Only mark the 3D View tab as ready if the PyVistaQt panel
            # actually populated; otherwise the tab stays disabled and the user
            # is not silently switched to a blank canvas.
            # U1 (2026-06-28): tab-readiness is its OWN flag — do NOT route it
            # through the result-nulling _has_results_3d bridge setter, which on
            # a soft viz failure (headless/offscreen/GL/TPMSHX_DISABLE_3D_PANEL)
            # destroyed the valid solve's result, defeating the status branch
            # below and the Export data-presence gate. The result stays cached.
            self._3d_view_ready = bool(_3d_vis_ok)
            for _bname in ('btn_export',):
                if hasattr(self, _bname):
                    getattr(self, _bname).setEnabled(True)
            drawn = getattr(self, '_drawn_tabs', set())
            if _3d_vis_ok:
                drawn.add('3d')
            if getattr(self, '_rendered_3d_slices', False):
                for k in ('temp', 'pres', 'vel'):
                    drawn.add(k)
            self._drawn_tabs = drawn
            self._update_tab_visibility()
            if getattr(self, '_rendered_3d_slices', False):
                self._switch_tab('temp')
            elif _3d_vis_ok:
                self._switch_tab('3d')
            res = getattr(self, '_result_3d', None)
            # Outer-coupling convergence note: the SIMPLE↔LTNE loop exits
            # early once max|ΔTa| < tol, so it usually stops before the cap
            # (e.g. "3/5"). Surface that as "converged after k/N" instead of a
            # bare count, so the user does not read an early exit as an
            # unfinished run. len(_ltne_info) = outers actually executed.
            # B3 C5: res is a ComputeResult — outer-loop metrics live in
            # res.diagnostics ('_ltne_info' / '_max_outer').
            def _outer_note(r):
                try:
                    d = r.diagnostics
                    info = d.get('_ltne_info') or []
                    n_run = len(info)
                    n_max = int(d.get('_max_outer', n_run) or n_run)
                    if n_run and n_run < n_max:
                        return f"  ·  converged after {n_run}/{n_max} outer"
                    if n_run:
                        return f"  ·  ran full {n_run}/{n_max} outer (cap)"
                except Exception:
                    pass
                return ""
            try:
                if res is not None and _3d_vis_ok:
                    self.statusBar().showMessage(
                        f"3D done — Q={res.Q_W:.1f} W  "
                        f"dP={res.dP_A_Pa:.0f} Pa{_outer_note(res)}", 8000)
                elif res is not None:
                    # Solver succeeded but visualisation did not — surface
                    # explicitly so the user knows numbers are valid but the
                    # rendered canvas is not.
                    self.statusBar().showMessage(
                        f"3D solve done (Q={res.Q_W:.1f} W  "
                        f"dP={res.dP_A_Pa:.0f} Pa) — visualisation "
                        f"failed; check console.", 10000)
                else:
                    # finalize returned False with no stashed result dict —
                    # always clear the frozen "outer k/N running" left by the
                    # last _tick_3d paint so the status bar reflects reality.
                    self.statusBar().showMessage(
                        "3D compute finished but produced no result — "
                        "visualisation unavailable; check console.", 10000)
            except Exception:
                pass
            return True

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
        self._has_results = True
        self._has_results_2d = True
        self._update_tab_visibility()
        for _bname in ('btn_export',):
            if hasattr(self, _bname):
                getattr(self, _bname).setEnabled(True)
        self._switch_tab('temp')
        if _finalize_ok:
            self.statusBar().showMessage("Done.", TOAST_MS_MED)
        return _finalize_ok

    def _on_orch_error(self, message, log_text):
        """Compute raised. Show error + drop stale results (mode-aware)."""
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
            self._result_3d = None
            self._has_results_3d = False
            self._3d_view_ready = False
            if not getattr(self, '_has_results_2d', False):
                self._has_results = False
            for _bname in ('btn_export',):
                if hasattr(self, _bname):
                    getattr(self, _bname).setEnabled(False)
            self._update_tab_visibility()
            self._end_compute_ui(success=False)
            # User-cancel or timeout already surfaced as cancelled signal —
            # if we reach here it's a real error.
            QMessageBox.critical(self, "3D Compute Error", message)
            return

        # 2D / poly fallback
        self._compute_results = {}
        self._has_results_2d = False
        if not getattr(self, '_has_results_3d', False):
            self._has_results = False
        for _bname in ('btn_export',):
            if hasattr(self, _bname):
                getattr(self, _bname).setEnabled(False)
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
        """Worker observed cancel_token. Treat as soft completion (mode-aware)."""
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
            # 3D-specific: drop result + status message
            self._result_3d = None
            self._has_results_3d = False
            self._3d_view_ready = False
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
        # Reset + reveal the live residual sparkline. A timer drains the
        # shared buffer every 300 ms while the compute thread runs.
        self._live_residuals = {'A': [], 'B': []}
        self._live_resid_cursors = {'A': 0, 'B': 0}
        card = getattr(self, '_run_status_card', None)
        if card is not None:
            card.start(self.compute.current_mode())
        if hasattr(self, '_sb_live_resid'):
            self._sb_live_resid.clear_data()
            self._sb_live_resid.show()
        if not hasattr(self, '_live_resid_timer'):
            from PySide6.QtCore import QTimer as _QT_lr
            t = _QT_lr(self)
            # 120 ms poll (~8 Hz) — frequent enough that the sparkline
            # tracks the solver within a frame-ish budget on a 144 Hz
            # display, cheap enough that the drain is a no-op most ticks.
            t.setInterval(120)
            t.timeout.connect(self._drain_live_residuals)
            self._live_resid_timer = t
        self._live_resid_timer.start()
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
        hide immediately (failure). On success also refreshes the headline
        result summary bar from the detail-value labels.

        Called after terminal publication; stops the UI tickers and restores
        the Compute action. The orchestrator stays busy until its slots return.
        """
        card = getattr(self, '_run_status_card', None)
        if card is not None:
            self._drain_live_residuals()
            elapsed = _time.time() - getattr(self, '_compute_t0', _time.time())
            message = ''
            if success:
                result = self.compute.last_result()
                notices = list(dict.fromkeys((*result.warnings, *result.extrap_reasons)))
                view_missing = (self.compute.current_mode() == '3d'
                                and not getattr(self, '_3d_view_ready', False))
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
            elif getattr(self, '_compute_cancel', False):
                state, message = 'cancelled', '求解器已响应取消请求。'
            else:
                state, message = 'error', '计算结束，但结果显示未完成。请查看诊断与日志。'
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
            self._update_result_summary()
            # Record the elapsed wall-clock for the status bar clock.
            t0 = getattr(self, '_compute_t0', None)
            elapsed = None
            if t0 is not None:
                elapsed = _time.time() - t0
                self._last_elapsed_s = elapsed
            self._refresh_status_bar()
            # D8 — stamp provenance tooltip on every result label so users
            # can trace "where did this number come from" without guessing.
            self._stamp_result_provenance(elapsed or 0.0)
            # Stop the live-residual sparkline timer + hide widget.
            lrt = getattr(self, '_live_resid_timer', None)
            if lrt is not None:
                lrt.stop()
            if hasattr(self, '_sb_live_resid'):
                self._sb_live_resid.hide()
            self._live_resid_cursors = {'A': 0, 'B': 0}
            # Micro-anim polish: pulse the result chips + floating toast.
            try:
                from sjtu_tpmshx.ui.microanim import pulse_glow, toast
                from sjtu_tpmshx.ui.theme import get_theme as _gt
                for key in ('Q', 'dPA', 'dPB'):
                    chip = self._res_chips.get(key) if hasattr(
                        self, '_res_chips') else None
                    if chip is not None:
                        pulse_glow(chip,
                                    blur_peak=20, duration_ms=550)
                if elapsed is not None:
                    toast(self, f"Compute done · {_fmt_dur(elapsed)}", kind='success')
                else:
                    toast(self, "Compute done", kind='success')
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
            lrt = getattr(self, '_live_resid_timer', None)
            if lrt is not None:
                lrt.stop()
            if hasattr(self, '_sb_live_resid'):
                self._sb_live_resid.hide()
            self._live_resid_cursors = {'A': 0, 'B': 0}

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

    def _active_compute_mode(self):
        """'2d' / '3d' / 'poly' depending on current UI selection. Used by
        the ETA helper so 2D reheats don't skew 3D predictions."""
        try:
            if hasattr(self, 'combo_shape') and self.combo_shape.currentIndex() > 0:
                return 'poly'
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

    def _drain_live_residuals(self):
        """Drain new A/B samples on the existing 120 ms GUI timer.

        The status bar retains its Fluid A sparkline; the expandable card
        shows both actual streams without changing the worker callbacks.
        """
        buf = getattr(self, '_live_residuals', None) or {}
        spark = getattr(self, '_sb_live_resid', None)
        card = getattr(self, '_run_status_card', None)
        if (spark is None and card is None) or not buf:
            return
        cursors = getattr(self, '_live_resid_cursors', {'A': 0, 'B': 0})
        import math as _math_lr
        for side in ('A', 'B'):
            cursor = cursors[side]
            new_items = (buf.get(side) or [])[cursor:]
            cursors[side] = cursor + len(new_items)
            if card is not None:
                card.push_residuals(side, new_items)
            if side == 'A' and spark is not None:
                for _it, r in new_items:
                    spark.push(_math_lr.log10(max(r, 1e-20)))
        self._live_resid_cursors = cursors
