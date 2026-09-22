"""
ui/optimize_panel.py — UI bindings for the continuous-field qNEHVI optimizer.

Main window callbacks delegate run/cancel and Pareto picking here. The
worker reports progress and hypervolume while the UI previews the design
fields and saves results. Picking a design restores its mean scalar
parameters as a uniform Compute seed, not the full graded geometry.
"""

from __future__ import annotations

import os
import time
from copy import deepcopy

import numpy as np

from sjtu_tpmshx.logutil import get_logger
from sjtu_tpmshx.controllers.user_storage import optimization_output_dir

_log = get_logger(__name__)

# Time module already imported above; alias for the closures below

# Qt imports are kept lazy so this module can be imported by non-GUI tools
# (CLI scripts, headless tests) without forcing a Qt dependency.


# ─── Background worker thread (lazy QtCore import) ──────────────────


def _make_worker_class():
    """Return a QThread subclass that runs the BO loop. Constructed at first
    call to keep import-time cheap and avoid Qt at module import.

    The project is built on PySide6 (see main.py + controllers/*); the v1
    panel was written against PyQt6 by mistake, which silently broke the
    entire Optimize button — `from PyQt6.QtCore import ...` either raised
    ImportError or, worse, succeeded but produced QObjects of the wrong
    kind that won't bind to the host UI's signal/slot machinery.
    """
    from PySide6.QtCore import QThread, Signal

    class _OptimizeWorker(QThread):
        finished_with_result = Signal(object)
        progress_signal = Signal(int, int, float)  # count, total, best_Q
        # Phase 2 — separate HV signal fires once per BO iter (after the
        # DominatedPartitioning HV update). iter_idx is 1-based; hv_hist is
        # the full per-iter HV trace for the live plot.
        hv_signal = Signal(int, float, list)        # iter_idx, hv, hv_hist
        error_signal = Signal(str)

        def __init__(self, cfg, n_init, n_iter, q_batch, seed, save_dir,
                     evaluator_fn=None):
            super().__init__()
            self.cfg = cfg
            self.n_init = n_init
            self.n_iter = n_iter
            self.q_batch = q_batch
            self.seed = seed
            self.save_dir = save_dir
            # M0 (2026-07-09): dimension-follows-Compute. None → 2D
            # evaluate_design (run_qnehvi's default); the launcher passes
            # evaluate_design_3d when the Compute page is in 3D mode.
            self.evaluator_fn = evaluator_fn
            self._last_hv_iter = 0

        def run(self):
            try:
                from sjtu_tpmshx.optimization.optimizer_qnehvi import run_qnehvi

                def _cb(count, total, prog):
                    self.progress_signal.emit(int(count), int(total),
                                               float(prog['best_Q']))
                    # Fire HV signal only when iter index advances (the BO
                    # loop calls progress_cb once per eval AND once per iter
                    # at the HV update; we deduplicate by iter index).
                    hv_iter = int(prog.get('hv_iter', 0))
                    if hv_iter > self._last_hv_iter:
                        self._last_hv_iter = hv_iter
                        self.hv_signal.emit(
                            hv_iter,
                            float(prog.get('hv', 0.0)),
                            list(prog.get('hv_hist', [])),
                        )

                # Parallel candidates are capped by the current BO batch size.
                n_jobs_inner = max(1, min(int(self.q_batch),
                                          int(self.cfg.get('n_jobs', 4))))
                res = run_qnehvi(
                    config=self.cfg,
                    n_init=self.n_init, n_iter=self.n_iter,
                    q_batch=self.q_batch, seed=self.seed,
                    verbose=True,
                    save_dir=self.save_dir,
                    progress_cb=_cb,
                    n_jobs=n_jobs_inner,
                    evaluator_fn=self.evaluator_fn,
                    cancel_check=self.isInterruptionRequested,
                )
                self.finished_with_result.emit(res)
            except Exception as e:
                self.error_signal.emit(f"{type(e).__name__}: {e}")

    return _OptimizeWorker


# ─── Window-side helpers ────────────────────────────────────────────


def _gather_cfg(window, base: dict | None = None) -> dict:
    """Read the cfg fields off the window into a plain dict.

    ``base`` selects the dimension-specific default set (M0, 2026-07-09):
    None → 2D ``evaluator.DEFAULT_CONFIG``; the 3D launcher passes
    ``evaluator_3d.DEFAULT_CONFIG_3D`` so the 3D fast-mode budget is not
    stomped by 2D defaults. Widget reads always take precedence.
    """
    from sjtu_tpmshx.optimization.evaluator import DEFAULT_CONFIG as EVAL_DEFAULT

    cfg = dict(base) if base is not None else dict(EVAL_DEFAULT)

    # R3 wiring (M0, 2026-07-09): a typed OptimizerConfig on the window
    # (set by session-restore / script drivers — the UI itself keeps the
    # dimension defaults) overrides the cheap-eval budget keys. Applied
    # BEFORE the widget reads so explicit UI fields still win.
    _oc = getattr(window, '_optimizer_cfg', None)
    if _oc is not None:
        try:
            cfg['max_iter_simple'] = int(_oc.max_iter_simple)
            cfg['tol_energy']      = float(_oc.outer_tol_K)
            # 3D-only keys — harmless extras on the 2D path.
            cfg['max_outer_3d']    = int(_oc.max_outer_ltne)
            cfg['outer_tol_K']     = float(_oc.outer_tol_K)
            cfg['alpha_outer']     = float(_oc.alpha_T)
        except (AttributeError, TypeError, ValueError) as _e:
            _log.warning(f"[optimize] _optimizer_cfg ignored (bad shape): {_e}")
    def _get(attr, cast=float, key=None):
        if hasattr(window, attr):
            try:
                value = cast(getattr(window, attr).text())
                if not np.isfinite(value):
                    raise ValueError('must be finite')
            except (ValueError, AttributeError) as exc:
                raise ValueError(f"{attr}: enter a finite number") from exc
            cfg[key or attr] = value

    # Geometry (m) — UI defaults match Shanghai's cross-flow HX
    # (0.182 × 0.042 × 0.042 m³). Without these reads the optimizer would
    # silently fall back to the evaluator's hard-coded 0.10 × 0.05 m generic
    # case regardless of what the user typed in the Compute fields.
    _get('le_L',      float, 'L_domain')
    _get('le_H',      float, 'H_domain')
    if _is_3d_mode(window):
        _get('le_Lz', float, 'Lz')
        if cfg['Lz'] <= 0:
            raise ValueError('le_Lz: enter a positive depth')

    _get('le_ks',     float, 'k_s')
    _get('le_uA',     float, 'u_A')
    _get('le_uB',     float, 'u_B')
    _get('le_PinA',   float, 'P_inA')
    _get('le_PinB',   float, 'P_inB')

    # Material density — silently dropped in v1; the optimizer fell back to
    # evaluator's hard-coded 2700 (aluminium) regardless of the UI setting
    # (Shanghai's 304 SS at 7900 was being ignored).
    _get('le_rho_s',  float, 'rho_s')

    for side in ('A', 'B'):
        widget = getattr(window, 'le_Tin' + side, None)
        if widget is not None:
            try:
                converter = getattr(window, '_temp_to_K', lambda w: float(w.text()))
                value = float(converter(widget))
                if not np.isfinite(value) or value <= 0:
                    raise ValueError('must be finite and positive')
            except (ValueError, AttributeError) as exc:
                raise ValueError(f"le_Tin{side}: enter a valid absolute temperature") from exc
            cfg['T_in' + side] = value
        direction = getattr(window, 'combo_dir' + side, None)
        if direction is not None:
            cfg['dir_' + side] = int(direction.currentIndex())

    if hasattr(window, 'combo_tpms'):
        cfg['tpms_type'] = window.combo_tpms.currentText()

    from sjtu_tpmshx.ui.window_config import _parse_fluid_label
    for side in ('A', 'B'):
        combo = getattr(window, 'combo_fluid' + side, None)
        if combo is not None:
            cfg['fluid_type_' + side] = _parse_fluid_label(combo)

    # Search space (M0, 2026-07-09): the 搜索空间 card's widgets. L/t bounds
    # are clamped to the current CFD geometry grid. Each fluid's Nu window
    # remains a separate applicability condition. Degenerate ranges fail.
    _sp = getattr(window, '_opt_space_params', None)
    if _sp:
        try:
            from sjtu_tpmshx.df_surrogate._domain import TRAIN_L, TRAIN_T

            def _clamped(lo_w, hi_w, hull):
                lo = max(hull[0], min(float(lo_w.value()), float(hi_w.value())))
                hi = min(hull[1], max(float(lo_w.value()), float(hi_w.value())))
                if not np.isfinite(lo + hi) or lo >= hi:
                    raise ValueError('search bounds require a finite lower < upper')
                return (lo, hi)

            cfg['L_bounds'] = _clamped(_sp['L_min'], _sp['L_max'], TRAIN_L)
            cfg['t_bounds'] = _clamped(_sp['t_min'], _sp['t_max'], TRAIN_T)
            _grid = _sp['ctrl_grid'].currentData()
            if _grid:
                cfg['n_ctrl_x'], cfg['n_ctrl_y'] = int(_grid[0]), int(_grid[1])
            cfg['symmetric_y'] = bool(_sp['symmetric_y'].isChecked())
        except Exception as _e:
            raise ValueError(f"invalid search-space settings: {_e}") from _e

    return cfg


def _set_status(window, text: str) -> None:
    """Push a one-line status onto the Optimize tab status label.

    Targets ``window._opt_status`` (built by ui_builders) when present, falls
    back to the global status bar, then prints to stdout.
    """
    target = getattr(window, '_opt_status', None)
    if target is not None and hasattr(target, 'setText'):
        try:
            target.setText(text)
            return
        except Exception:
            pass
    sb = getattr(window, 'statusBar', None)
    if callable(sb):
        try:
            sb().showMessage(text)
            return
        except Exception:
            pass
    _log.info(f"[optimize] {text}")


def _set_kpi(window, gen=None, best_q=None, best_dp=None, eta=None) -> None:
    """Update the Optimize tab KPI cards."""
    if gen is not None:
        lbl = getattr(window, '_opt_kpi_gen', None)
        if lbl is not None:
            try: lbl.setText(str(gen))
            except Exception: pass
    if best_q is not None:
        lbl = getattr(window, '_opt_kpi_q', None)
        if lbl is not None:
            try: lbl.setText(f"{best_q:.0f}" if isinstance(best_q, (int, float)) else str(best_q))
            except Exception: pass
    if best_dp is not None:
        lbl = getattr(window, '_opt_kpi_dp', None)
        if lbl is not None:
            try: lbl.setText(f"{best_dp:.0f}" if isinstance(best_dp, (int, float)) else str(best_dp))
            except Exception: pass
    if eta is not None:
        lbl = getattr(window, '_opt_kpi_eta', None)
        if lbl is not None:
            try: lbl.setText(str(eta))
            except Exception: pass


def _set_progress_pct(window, pct: float) -> None:
    pb = getattr(window, '_opt_progress', None)
    if pb is None:
        return
    try:
        pb.show()
        pb.setValue(int(np.clip(pct, 0, 100)))
    except Exception:
        pass


def _toggle_buttons(window, running: bool) -> None:
    """Disable Launch / enable Cancel while running, opposite when idle."""
    btn = getattr(window, '_opt_btn', None)
    cancel = getattr(window, '_opt_cancel_btn', None)
    try:
        if btn is not None:    btn.setEnabled(not running)
        if cancel is not None: cancel.setEnabled(running)
    except Exception:
        pass


def _push_sparkline(window, value: float) -> None:
    sl = getattr(window, '_opt_sparkline', None)
    if sl is None:
        return
    sl.push(value)


def _set_stage_pill(window, key: str, state: str) -> None:
    """Update one of the three stage pills (config/running/result) to one of
    the three theme states (idle/active/done). The styles are stored on the
    window as a 3-tuple by ui_builders — we index it by state name.
    """
    pills = getattr(window, '_opt_stage_pills', None)
    styles = getattr(window, '_opt_pill_styles', None)
    if not pills or not styles:
        return
    pill = pills.get(key)
    if pill is None:
        return
    state_idx = {'idle': 0, 'active': 1, 'done': 2}.get(state, 0)
    try:
        pill.setStyleSheet(styles[state_idx])
    except Exception:
        pass
    # ui-plan-b-wizard: the ACTIVE pill also flips the wizard page, so the
    # engine's existing stage transitions drive the page flow for free
    # (launch → 运行, finish → 结果).
    if state == 'active':
        stack = getattr(window, '_opt_stack', None)
        page = {'config': 0, 'running': 1, 'result': 2}.get(key)
        if stack is not None and page is not None:
            try:
                stack.setCurrentIndex(page)
            except Exception:
                pass


def _set_summary_banner(window, text: str, *, show: bool = True) -> None:
    """Show / update the summary banner under the Optimize cards."""
    banner = getattr(window, '_opt_summary_banner', None)
    if banner is None:
        return
    try:
        banner.setText(text)
        banner.setVisible(show)
    except Exception:
        pass


# ─── P1: qNEHVI inline parameters ───────────────────


def _outer_budget_parameter(window, cfg: dict | None = None) -> tuple:
    """Current dimension's budget, with explicit edits ahead of typed defaults."""
    from sjtu_tpmshx.optimization.evaluator import DEFAULT_CONFIG
    from sjtu_tpmshx.optimization.evaluator_3d import DEFAULT_CONFIG_3D

    if _is_3d_mode(window):
        key = 'max_outer_3d'
        default = DEFAULT_CONFIG_3D[key]
        typed = getattr(window, '_optimizer_cfg', None)
        if typed is not None:
            default = typed.max_outer_ltne
        label = '最大耦合迭代次数'
        tip = '三维 SIMPLE 与热量方程的最大耦合迭代预算；1 可用于筛选，但不保证收敛。'
    else:
        key = 'n_rho_loops'
        default = DEFAULT_CONFIG[key]
        label = '<i>ρ</i>(<i>T</i>) 外循环'
        tip = '二维密度与温度更新的循环预算；增加次数不保证收敛或实验精度。'
    cached = getattr(window, '_opt_param_cache', None) or {}
    value = int(cached.get(key, (cfg or {}).get(key, default)))
    return key, value, label, tip


def _sync_outer_budget(window) -> None:
    """Refresh the visible budget without treating defaults as user edits."""
    spin = getattr(window, '_opt_outer_budget', None)
    if spin is None:
        return
    key, value, label, tip = _outer_budget_parameter(window)
    for old_key in ('n_rho_loops', 'max_outer_3d'):
        window._opt_inline_params.pop(old_key, None)
    window._opt_inline_params[key] = spin
    blocked = spin.blockSignals(True)
    spin.setRange(1, max(8, value))
    spin.setValue(value)
    spin.blockSignals(blocked)
    spin.setToolTip(tip)
    window._opt_outer_label.setText(label)






# ─── Dimension detection (M0, 2026-07-09) ───────────────────────────


def _is_3d_mode(window) -> bool:
    """True when the Compute page's dimensionality combo is on 3D. The
    optimizer follows the Compute dimension: 2D compute → 2D evaluator,
    3D compute → evaluate_design_3d (same qNEHVI machinery)."""
    combo = getattr(window, 'combo_dim', None)
    if combo is None:
        return False
    try:
        return combo.currentIndex() == 1
    except Exception:
        return False


# ─── Live preview of L(x,y), t(x,y) field heatmap ───────────────────


def show_field_preview(window, x_decision=None) -> None:
    """Render L(x,y) and t(x,y) heatmaps for a decision vector.

    If ``x_decision`` is None, defaults to the centre of the bounds
    (uniform L = mean(L_bounds), t = mean(t_bounds)) so a click before any
    optimization still produces a meaningful preview.

    Drawn on ``window.canvas_layout`` if available (the dedicated 'Layout'
    tab), otherwise falls back to ``canvas_pareto`` so users see something.
    """
    from sjtu_tpmshx.models.screening import build_field
    from sjtu_tpmshx.models.continuous_field import decision_bounds
    if x_decision is None:
        x_decision = getattr(window, '_selected_pareto_x', None)
    try:
        cfg = _gather_cfg(window) if x_decision is None else _result_field_config(window)
        if x_decision is None:
            low, high = decision_bounds(cfg['n_ctrl_x'], cfg['n_ctrl_y'], cfg['symmetric_y'],
                                        cfg['L_bounds'], cfg['t_bounds'])
            x_decision = (low + high) / 2.
        fc = build_field(np.asarray(x_decision, dtype=np.float64), cfg)
    except (ValueError, KeyError) as exc:
        _set_status(window, f"field preview unavailable: {exc}")
        return
    L_dom = float(cfg['L_domain']); H_dom = float(cfg['H_domain'])

    Nx_p, Ny_p = 80, 40
    L_field, t_field = fc.evaluate_grid(Nx_p, Ny_p)
    extent_mm = [0, L_dom * 1e3, 0, H_dom * 1e3]

    canvas = (getattr(window, 'canvas_layout', None)
              or getattr(window, 'canvas_pareto', None))
    if canvas is None:
        _log.info("[optimize] field preview (no canvas):")
        _log.info(f"  L: {L_field.min():.2f}–{L_field.max():.2f} mm "
                  f"(avg {L_field.mean():.2f})")
        _log.info(f"  t: {t_field.min():.3f}–{t_field.max():.3f} mm "
                  f"(avg {t_field.mean():.3f})")
        return

    fig = canvas.figure
    fig.clear()
    ax_L = fig.add_subplot(1, 2, 1)
    im_L = ax_L.imshow(L_field.T, origin='lower', extent=extent_mm,
                       aspect='auto', cmap='viridis')
    ax_L.set_title(f"L(x, y)  [mm]  range [{L_field.min():.2f}, {L_field.max():.2f}]")
    ax_L.set_xlabel("x [mm]"); ax_L.set_ylabel("y [mm]")
    fig.colorbar(im_L, ax=ax_L, fraction=0.046, pad=0.04)

    ax_t = fig.add_subplot(1, 2, 2)
    im_t = ax_t.imshow(t_field.T, origin='lower', extent=extent_mm,
                       aspect='auto', cmap='magma')
    ax_t.set_title(f"t(x, y)  [mm]  range [{t_field.min():.3f}, {t_field.max():.3f}]")
    ax_t.set_xlabel("x [mm]"); ax_t.set_ylabel("y [mm]")
    fig.colorbar(im_t, ax=ax_t, fraction=0.046, pad=0.04)

    canvas.axes = [[ax_L, ax_t]]
    if hasattr(canvas, '_orig_wheel_event'):
        canvas.wheelEvent = canvas._orig_wheel_event
    fig.tight_layout()
    canvas.draw()
    if canvas is getattr(window, 'canvas_layout', None):
        if hasattr(window, 'cache'):
            window.cache.mark_drawn('layout')
        if hasattr(window, '_refresh_export_button'):
            window._refresh_export_button()
        if hasattr(window, '_switch_tab'):
            window._switch_tab('layout')
    _set_status(
        window,
        f"field preview: L ∈ [{L_field.min():.2f}, {L_field.max():.2f}] mm, "
        f"t ∈ [{t_field.min():.3f}, {t_field.max():.3f}] mm")


# ─── Public API (called by main.py) ─────────────────────────────────


def run_optimize(window) -> None:
    """Kick off a qNEHVI optimization in a background thread.

    Dimension follows the Compute page (M0, 2026-07-09): combo_dim on 3D
    injects ``evaluate_design_3d`` + the 3D fast-mode default budget;
    otherwise the 2D ``evaluate_design`` default path runs unchanged.
    """
    # Reserve launch before gathering inputs and starting the worker.
    if getattr(window, '_close_pending', False):
        return
    if getattr(window, '_opt_launching', False):
        _set_status(window, 'launch already in progress')
        return
    if getattr(window, '_opt_worker', None) is not None:
        _set_status(window, 'optimizer already running')
        return
    window._opt_launching = True
    # Disable Launch while parameters are gathered to prevent a double-click
    # from starting a second run. Worker.start() further down still
    # calls `_toggle_buttons(running=True)` for the full button matrix.
    _btn_launch = getattr(window, '_opt_btn', None)
    if _btn_launch is not None:
        try:
            _btn_launch.setEnabled(False)
        except Exception:
            pass

    # 2026-05-20 UI sweep (Tier 12, user re-audit): the synchronous
    # path between here and `worker.start()` does several things that
    # can raise — `_gather_cfg` parses line-edit text (ValueError on
    # bad input), `int(params[...])` requires the dialog payload to
    # have all keys, the `Worker(...)` constructor can fail. Before
    # this guard any such exception left `_opt_launching=True` and
    # the Launch button disabled forever, deadlocking the optimizer
    # entry. The helper ensures the latch + button are restored on
    # every exception path; the success path clears them just before
    # `worker.start()` so this becomes a no-op there.
    def _abort_launch(msg: str = '') -> None:
        window._opt_launching = False
        if _btn_launch is not None:
            try:
                _btn_launch.setEnabled(True)
            except Exception:
                pass
        if msg:
            try:
                _set_status(window, msg)
            except Exception:
                pass

    is_3d = _is_3d_mode(window)
    try:
        if is_3d:
            from sjtu_tpmshx.optimization.evaluator_3d import (
                DEFAULT_CONFIG_3D, evaluate_design_3d,
            )
            evaluator_fn = evaluate_design_3d
            cfg = _gather_cfg(window, base=DEFAULT_CONFIG_3D)
        else:
            evaluator_fn = None          # run_qnehvi defaults to 2D
            cfg = _gather_cfg(window)
        from sjtu_tpmshx.models.screening import validate_screening_config
        validate_screening_config(cfg, dimension=3 if is_3d else 2)
    except Exception as _e:
        _abort_launch(f"launch aborted — _gather_cfg failed: {_e}")
        return

    # The main window owns one inline optimization configuration.
    try:
        _sync_outer_budget(window)
        params = {k: sp.value() for k, sp in window._opt_inline_params.items()}
    except Exception as _e:
        _abort_launch(f"launch aborted — parameter setup failed: {_e}")
        return
    try:
        n_init  = int(params['n_init'])
        n_iter  = int(params['n_iter'])
        q_batch = int(params['q_batch'])
        seed    = int(params['seed'])
        budget_key = 'max_outer_3d' if is_3d else 'n_rho_loops'
        cfg[budget_key] = int(params[budget_key])
    except (KeyError, ValueError, TypeError) as _e:
        _abort_launch(f"launch aborted — bad params payload: {_e}")
        return

    try:
        save_dir = str(optimization_output_dir() /
                       f"qnehvi{'3d' if is_3d else ''}_{time.strftime('%Y%m%d_%H%M%S')}")
        Worker = _make_worker_class()
        worker = Worker(cfg, n_init, n_iter, q_batch, seed, save_dir,
                        evaluator_fn=evaluator_fn)
    except Exception as _e:
        _abort_launch(f"launch aborted — worker construct failed: {_e}")
        return
    window._opt_t_start = time.time()
    window._opt_total_evals = n_init + n_iter * q_batch
    # Each run and each quantity own a separate history: Q and HV cannot
    # share an axis because they have different units and scales.
    window._opt_sl_is_hv = False
    sparkline = getattr(window, '_opt_sparkline', None)
    caption = getattr(window, '_opt_sparkline_caption', None)
    if sparkline is not None:
        sparkline.clear_data()
    if caption is not None:
        caption.setText("初始采样 · 最优 Q [W/m]")

    def _on_progress(count, total, best_Q):
        if getattr(window, '_close_pending', False):
            return
        # Phase derived from count: first n_init evals are Sobol init, after
        # that we are inside the BO iteration loop.
        if count <= n_init:
            phase_label = f"Sobol {count}/{n_init}"
        else:
            it_done = (count - n_init) // max(1, q_batch)
            phase_label = f"BO iter {it_done}/{n_iter}"
        # ETA: extrapolate from elapsed × remaining/done
        t_now = time.time()
        elapsed = t_now - getattr(window, '_opt_t_start', t_now)
        remaining = max(0, total - count)
        if count > 0 and elapsed > 0:
            eta_s = elapsed * remaining / count
            eta_str = (f"{int(eta_s/60)}m{int(eta_s%60):02d}s"
                       if eta_s >= 60 else f"{int(eta_s)}s")
        else:
            eta_str = "—"
        _set_kpi(window, gen=phase_label, best_q=best_Q, eta=eta_str)
        _set_progress_pct(window, 100.0 * count / max(1, total))
        _set_status(window, f"qNEHVI {count}/{total}  best Q = {best_Q:.0f} W/m")
        # Push best_Q to sparkline only while still in Sobol init; once BO
        # iters start, the HV signal takes over (more informative than
        # best_Q which plateaus on greedy improvement).
        if not getattr(window, '_opt_sl_is_hv', False):
            _push_sparkline(window, best_Q)

    def _on_done(res):
        if getattr(window, '_close_pending', False):
            return
        window._last_opt_cfg = deepcopy(res.get('config', cfg))
        window._selected_pareto_x = None
        label = _termination_label(res)
        # Best Q + dP from the Pareto: highest Q point and lowest dP point
        if len(res['F']) > 0:
            Q_arr  = -res['F'][:, 0]
            dP_arr =  res['F'][:, 1]
            _set_kpi(window,
                     gen=f"{label} ({res['n_evals']} evals)",
                     best_q=float(Q_arr.max()),
                     best_dp=float(dP_arr.min()),
                     eta="—")
        else:
            # 2026-05-20 UI sweep: empty Pareto front used to leave KPI
            # stuck at the "starting" placeholder. Surface a DONE state
            # so the user knows the run finished (even if it produced no
            # non-dominated points).
            _set_kpi(window,
                     gen=f"{label} ({res['n_evals']} evals)",
                     best_q="—",
                     best_dp="—",
                     eta="—")
        _set_progress_pct(window, 100.0 * res['n_evals'] / max(1, window._opt_total_evals))
        _set_status(window,
                    f"qNEHVI {label}: {len(res['X'])} Pareto / {res['n_evals']} evals "
                    f"→ {res['save_dir']}")
        try:
            show_pareto(window, res)
        except Exception as e:
            _log.warning(f"[optimize] show_pareto failed: {e}")
        try:
            save_opt_results(window, res, window._last_opt_cfg)
        except Exception as e:
            _log.warning(f"[optimize] save_opt_results failed: {e}")

    def _on_error(msg):
        if getattr(window, '_close_pending', False):
            return
        _set_status(window, f"qNEHVI ERROR: {msg}")
        _set_kpi(window, gen="ERROR", best_q="—", best_dp="—", eta="—")
        # 2026-05-20 UI sweep: previously the error path only touched
        # status + the GENERATION KPI cell, leaving stage pills frozen at
        # `running:active`, the summary banner stale from the prior run,
        # and the worker reference dangling. Mirror the success-path
        # state reset so the user can see the failure and re-launch.
        # Wizard: an error sends the user back to 配置 to adjust and
        # re-launch (config 'active' also flips the stack to page 1).
        _set_stage_pill(window, 'config',  'active')
        _set_stage_pill(window, 'running', 'idle')
        _set_stage_pill(window, 'result',  'idle')
        try:
            _set_summary_banner(window, f"ERROR — {msg}", show=True)
        except Exception:
            pass
        # Release the reentrance latch in case the error fires before
        # worker.start() unblocked it (e.g. worker constructor raised).
        window._opt_launching = False
        _log.warning(f"[optimize] worker error: {msg}")

    def _on_hv(iter_idx, hv, hv_hist):
        if getattr(window, '_close_pending', False):
            return
        if not window._opt_sl_is_hv:
            window._opt_sl_is_hv = True
            if sparkline is not None:
                sparkline.clear_data()
            if caption is not None:
                caption.setText("贝叶斯优化 · 超体积 HV")
        _push_sparkline(window, hv)
        # Also surface as status snippet so the user sees the HV value
        # even if the sparkline is hidden.
        try:
            _set_status(window,
                        f"qNEHVI iter {iter_idx} — HV = {hv:.3e}  "
                        f"({len(hv_hist)} BO iters complete)")
        except Exception:
            pass

    def _on_finished():
        # QThread.finished precedes thread-local cleanup; wait(0) proves exit
        # without blocking the GUI or dropping the still-running object.
        if not worker.wait(0):
            from PySide6.QtCore import QTimer
            QTimer.singleShot(10, _on_finished)
            return
        window._opt_worker = None
        _toggle_buttons(window, running=False)
        worker.deleteLater()

    try:
        worker.progress_signal.connect(_on_progress)
        worker.hv_signal.connect(_on_hv)
        worker.finished_with_result.connect(_on_done)
        worker.error_signal.connect(_on_error)
        worker.finished.connect(_on_finished)
        window._opt_worker = worker
        _toggle_buttons(window, running=True)
        _set_kpi(window, gen="starting", best_q="—", best_dp="—", eta="—")
        _set_progress_pct(window, 0.0)
        _set_stage_pill(window, 'config',  'done')
        _set_stage_pill(window, 'running', 'active')
        _set_stage_pill(window, 'result',  'idle')
        _set_summary_banner(window, "", show=False)
        _set_status(window,
                    f"qNEHVI ({'3D' if is_3d else '2D'}) running … "
                    f"{n_init} Sobol + {n_iter}×{q_batch} BO")
        worker.start()
    except Exception as _e:
        # Signal wiring / start failure — restore launch latch + button so
        # the user can retry without an app restart.
        try:
            _toggle_buttons(window, running=False)
        except Exception:
            pass
        window._opt_worker = None
        _abort_launch(f"launch aborted — worker.start failed: {_e}")
        return
    # 2026-05-20 UI sweep: worker is now committed; release the reentrance
    # latch so the next legitimate launch (after done/error) is unblocked.
    # `_toggle_buttons(running=True)` above already disables the Launch
    # button for the duration of the run, so this does not re-open the
    # double-click window.
    window._opt_launching = False
    _log.info(f"[optimize] worker started ({'3D' if is_3d else '2D'}) — "
              f"{n_init + n_iter * q_batch} evals planned, save_dir={save_dir}")


def cancel_optimize(window) -> None:
    """Request graceful cancel of the running optimizer."""
    worker = getattr(window, '_opt_worker', None)
    if worker is not None:
        worker.requestInterruption()
        _set_status(window, '正在取消 — 等待当前候选批次或模型拟合结束…')


def _termination_label(res: dict) -> str:
    return {'completed': '完成', 'cancelled': '已取消',
            'plateau': '平台期提前结束'}.get(res.get('termination_reason', 'completed'), '结束')


def show_pareto(window, res: dict) -> None:
    """Plot the Pareto front (Q vs dP) on the window's matplotlib canvas
    if available; print to stdout otherwise. Wires the matplotlib pick_event
    to ``window._on_pareto_pick`` so clicking a point loads it back into the
    Compute fields.
    """
    F_min = res['F']                  # (-Q, dP)  shape (P, 2)
    label = _termination_label(res)

    # 2026-05-20 UI sweep: empty Pareto front guard. Previously the
    # closing banner's `Q.min() / Q.max()` would raise on an empty `F`,
    # the outer try in `_on_done` would log "show_pareto failed", and
    # the stage pills (already flipped to 'result:active' upstream) plus
    # the summary banner would freeze mid-update. Surface an explicit
    # "no Pareto points" state instead.
    if F_min is None or len(F_min) == 0:
        _set_stage_pill(window, 'config',  'done')
        _set_stage_pill(window, 'running', 'done')
        _set_stage_pill(window, 'result',  'idle')
        try:
            _set_summary_banner(
                window, f"{label} — 无 Pareto 点", show=True)
        except Exception:
            pass
        try:
            _set_kpi(window, gen=label, best_q="—", best_dp="—", eta="—")
        except Exception:
            pass
        # 2026-05-20 UI sweep (Tier 13, user re-audit): the prior version
        # of this early-return only updated pills/banner/KPI and left
        # the previous run's Pareto plot + click handler + cached X/F
        # in place. A subsequent click on the stale plot would call
        # `on_pareto_pick` with the OLD `_pareto_X / _pareto_F`,
        # silently loading a design from a different run. Tear them
        # down so an empty result presents an empty UI surface.
        _canvas = getattr(window, 'canvas_pareto', None)
        if _canvas is not None:
            try:
                _canvas.figure.clear()
                _canvas.draw_idle()
            except Exception:
                pass
            _prev_cid = getattr(window, '_pareto_pick_cid', None)
            if _prev_cid is not None:
                try:
                    _canvas.mpl_disconnect(_prev_cid)
                except Exception:
                    pass
                window._pareto_pick_cid = None
        window._pareto_X = None
        window._pareto_F = None
        if hasattr(window, '_refresh_export_button'):
            window._refresh_export_button()
        return

    Q  = -F_min[:, 0]
    dP =  F_min[:, 1]
    F_hist = res.get('history_F')

    canvas = getattr(window, 'canvas_pareto', None)
    if canvas is None:
        _log.info("[optimize] Pareto front (no canvas; showing top 10):")
        order = np.argsort(Q)[::-1][:10]
        for i in order:
            _log.info(f"  Q = {Q[i]:8.0f} W/m   dP = {dP[i]:8.0f} Pa")
        return

    fig = canvas.figure
    window._pareto_X = None
    window._pareto_F = None
    fig.clear()
    ax = fig.add_subplot(111)
    if F_hist is not None and F_hist.size:
        Qh = -F_hist[:, 0]; dPh = F_hist[:, 1]
        valid = np.array([error is None for error in res.get('history_errors', [None] * len(Qh))])
        ax.scatter(dPh[valid], Qh[valid], c='lightgray', s=14, alpha=0.6,
                   label=f'valid history (n={valid.sum()})')
        if (~valid).any():
            ax.scatter(dPh[~valid], Qh[~valid], c='gray', marker='x', s=14,
                       label=f'failed / capped (n={(~valid).sum()})')
    order = np.argsort(dP)
    ax.plot(dP[order], Q[order], 'o-', color='C1', lw=1.5, ms=6,
            label=f'Pareto (n={len(Q)})', picker=True, pickradius=6)
    ax.set_xlabel('dP [Pa]')
    ax.set_ylabel('Q [W/m]')
    ax.set_title(f"qNEHVI Pareto front  ({res['n_evals']} evals)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    canvas.draw()

    # Cache the Pareto data on the window for click-pick decoding
    window._pareto_X = res['X']
    window._pareto_F = F_min
    if hasattr(window, '_refresh_export_button'):
        window._refresh_export_button()

    # Wire the pick_event to window._on_pareto_pick. mpl supports multiple
    # cid registrations; if we already registered one previously, drop it
    # before re-registering so duplicate clicks don't fire the handler twice.
    prev_cid = getattr(window, '_pareto_pick_cid', None)
    if prev_cid is not None:
        try:
            canvas.mpl_disconnect(prev_cid)
        except Exception:
            pass
    handler = getattr(window, '_on_pareto_pick', None)
    if callable(handler):
        try:
            window._pareto_pick_cid = canvas.mpl_connect('pick_event', handler)
        except Exception as e:
            _log.warning(f"[optimize] mpl_connect(pick_event) failed: {e}")

    # Update stage pills: config (done), running (done), result (active)
    _set_stage_pill(window, 'config',  'done')
    _set_stage_pill(window, 'running', 'done')
    _set_stage_pill(window, 'result',  'active')

    # Update the summary banner
    _set_summary_banner(
        window,
        f"{label} — {len(res['X'])} Pareto points | "
        f"Q range [{Q.min():.0f}, {Q.max():.0f}] W/m | "
        f"dP range [{dP.min():.0f}, {dP.max():.0f}] Pa")


def on_pareto_pick(window, event) -> None:
    """Matplotlib pick_event handler. Decodes the picked design back to its
    control-point grids and forwards to ``load_pareto_solution``.
    """
    if not hasattr(event, 'ind') or len(event.ind) == 0:
        return
    idx = int(event.ind[0])
    X = getattr(window, '_pareto_X', None)
    F = getattr(window, '_pareto_F', None)
    # 2026-05-20 UI sweep (Tier 16, user re-audit): the prior gate
    # only bounded `idx` against `len(X)`. The `order` array a few
    # lines below has length `len(F)`, so a corrupted / mismatched
    # cache (`len(F) < len(X)`) would still IndexError on `order[idx]`.
    # Bound against the tighter of the two.
    if X is None or F is None or len(X) == 0 or len(F) == 0:
        return
    if idx >= min(len(X), len(F)):
        return

    # The Pareto plot was drawn in dP-sorted order; map the click index back.
    F_dP = F[:, 1]
    order = np.argsort(F_dP)
    real_idx = int(order[idx])
    x_decision = X[real_idx]
    Q = -F[real_idx, 0]; dP = F[real_idx, 1]
    _set_status(window,
                f"Pareto pick: Q={Q:.0f} W/m  dP={dP:.0f} Pa  → loading mean parameters")
    load_pareto_solution(window, x_decision)


def save_opt_results(window, res: dict, cfg: dict) -> None:
    """Persist Pareto + history CSVs (already done by run_qnehvi via
    save_dir) and dump cfg as JSON for traceability.
    """
    save_dir = res['save_dir']
    try:
        import json
        with open(os.path.join(save_dir, 'cfg_used.json'), 'w') as f:
            json.dump(cfg, f, indent=2, allow_nan=False)
    except Exception as e:
        _set_status(window, f"results configuration could not be saved: {e}")
        return
    _set_status(window, f'{_termination_label(res)} · 结果已保存 → {save_dir}')


def _result_field_config(window):
    from sjtu_tpmshx.models.screening import FIELD_CONFIG_KEYS
    cfg = getattr(window, '_last_opt_cfg', None)
    if cfg is None or any(key not in cfg for key in FIELD_CONFIG_KEYS):
        raise ValueError('original geometry configuration is missing; cannot restore this design')
    return cfg


def load_pareto_solution(window, x_decision: np.ndarray) -> None:
    """Decode using the saved control grid and apply average L / t back onto
    the window's Compute fields (``le_Lcell`` / ``le_t``).

    The continuous-field design is heterogeneous; only the spatial average is
    pushed back to scalar Compute inputs. The full graded geometry lives in
    the saved Pareto CSV and its accompanying configuration.
    """
    from sjtu_tpmshx.models.continuous_field import decode_decision_vector

    try:
        cfg_full = _result_field_config(window)
    except ValueError as exc:
        _set_status(window, str(exc))
        return
    # 2026-05-20 UI sweep: guard against a corrupt or mis-sized decision
    # vector. Previously a wrong shape (e.g. a stale cached `_pareto_X`
    # from a different `n_ctrl_x/y` setting) would crash inside
    # `decode_decision_vector`. Surface a status-bar warning instead.
    x_decision = np.asarray(x_decision, dtype=np.float64)
    _ncx = int(cfg_full.get('n_ctrl_x', 4))
    _ncy = int(cfg_full.get('n_ctrl_y', 4))
    _sym = bool(cfg_full.get('symmetric_y', True))
    _expected = _ncx * ((_ncy + 1) // 2 if _sym else _ncy) * 2  # L_ctrl + t_ctrl flat
    if x_decision.ndim != 1 or x_decision.size == 0:
        _set_status(window,
                    f"load Pareto: decision vector has bad shape "
                    f"{x_decision.shape}, expected 1-D length ~{_expected}.")
        return
    try:
        L_ctrl, t_ctrl = decode_decision_vector(
            x_decision,
            n_ctrl_x=_ncx,
            n_ctrl_y=_ncy,
            symmetric_y=_sym,
        )
    except Exception as _e:
        _set_status(window,
                    f"load Pareto: decode failed ({_e}). "
                    "Check that the cached n_ctrl_x/y match the current cfg.")
        return
    L_avg = float(L_ctrl.mean())
    t_avg = float(t_ctrl.mean())
    window._selected_pareto_x = x_decision.copy()

    # 2026-05-20 UI sweep (Tier 25): emit editingFinished after each
    # programmatic setText so loading a Pareto design is a real, undoable
    # edit (captured by the global undo stack + re-validated), instead of
    # silently mutating le_Lcell/le_t outside the commit chain.
    if hasattr(window, 'le_Lcell'):
        window.le_Lcell.setText(f"{L_avg:.3f}")
        try:
            window.le_Lcell.editingFinished.emit()
        except Exception:
            pass
    if hasattr(window, 'le_t'):
        window.le_t.setText(f"{t_avg:.3f}")
        try:
            window.le_t.editingFinished.emit()
        except Exception:
            pass

    _set_status(window,
                f"loaded mean parameters: L_avg = {L_avg:.3f} mm, "
                f"t_avg = {t_avg:.3f} mm  (uniform seed; not the full graded design)")
