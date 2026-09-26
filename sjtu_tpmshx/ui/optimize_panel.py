"""Desktop bindings for the native multi-condition continuous-field search."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import time
from traceback import format_exception_only

import numpy as np

from sjtu_tpmshx.controllers.user_storage import optimization_output_dir
from sjtu_tpmshx.domain.compute_config import ComputeConfig, ZoneInputConfig
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.logutil import get_logger
from sjtu_tpmshx.ui.theme import FIELD_CMAP, get_theme

_log = get_logger(__name__)


def _make_worker_class():
    from PySide6.QtCore import QThread, Signal

    class _OptimizeWorker(QThread):
        finished_with_result = Signal(object)
        cancelled_before_search = Signal()
        progress_signal = Signal(int)
        error_signal = Signal(str)

        def __init__(self, config, condition_rows, field_spec, method, n_init, n_iter, q_batch, seed, save_dir):
            super().__init__()
            self.config = deepcopy(config)
            self.condition_rows = deepcopy(condition_rows)
            self.field_spec = deepcopy(field_spec)
            self.method = method
            self.n_init, self.n_iter, self.q_batch, self.seed = n_init, n_iter, q_batch, seed
            self.save_dir = save_dir

        def run(self):
            from sjtu_tpmshx.domain.cancellation import CancelledError
            try:
                control = RunControl(progress=self.progress_signal.emit,
                                     cancel_check=self.isInterruptionRequested)
                control.check_cancelled()
                conditions = _condition_inputs(self.config, self.condition_rows)
                control.check_cancelled()
                from sjtu_tpmshx.optimization.multi_condition_optimizer import run_multi_condition_optimization
                report = run_multi_condition_optimization(
                    conditions, output_dir=self.save_dir, method=self.method,
                    n_init=self.n_init, n_iter=self.n_iter, q_batch=self.q_batch,
                    seed=self.seed, field_spec=self.field_spec, control=control)
                self.finished_with_result.emit(report)
            except CancelledError as exc:
                if getattr(exc, '__notes__', None):
                    self.error_signal.emit(''.join(format_exception_only(exc)).strip())
                    return
                checkpoint = Path(self.save_dir) / 'optimization.json'
                try:
                    if checkpoint.exists():
                        with checkpoint.open(encoding='utf-8') as source:
                            report = json.load(source)
                        if not isinstance(report, dict) or report.get('status') != 'cancelled':
                            raise ValueError('Cancellation checkpoint does not record cancelled status')
                        self.finished_with_result.emit(report)
                    else:
                        self.cancelled_before_search.emit()
                except (OSError, ValueError) as exc:
                    self.error_signal.emit(''.join(format_exception_only(exc)).strip())
            except Exception as exc:
                self.error_signal.emit(''.join(format_exception_only(exc)).strip())

    return _OptimizeWorker


def _is_3d_mode(window):
    return window.combo_dim.currentIndex() == 1


def _positive(value, label):
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError(f'{label}: enter a finite positive number') from None
    if not np.isfinite(result) or result <= 0:
        raise ValueError(f'{label}: enter a finite positive number')
    return result


def _gather_cfg(window):
    from sjtu_tpmshx.ui.window_config import config_from_window
    cfg = config_from_window(window, strict=True)
    if not cfg.is_3d:
        depth = _positive(window._opt_depth.text(), '2D total-flow depth [m]')
        cfg = replace(cfg, geometry=replace(cfg.geometry, Lz_m=depth))
    return cfg.validate()


def _field_spec(window):
    from sjtu_tpmshx.models.continuous_field import decision_bounds
    widgets = window._opt_space_params
    spec = dict(n_ctrl_x=3, n_ctrl_y=3, symmetric_y=False, spline_order=2,
                L_bounds=[widgets['L_min'].value(), widgets['L_max'].value()],
                t_bounds=[widgets['t_min'].value(), widgets['t_max'].value()])
    if _is_3d_mode(window):
        spec['n_ctrl_z'] = 3
    low, high = decision_bounds(3, 3, False, spec['L_bounds'], spec['t_bounds'],
                                n_ctrl_z=spec.get('n_ctrl_z'))
    ZoneInputConfig(enabled=True, axis='continuous',
                    config={**spec, 'x_decision': ((low+high)/2).tolist()}).validate()
    return spec


def validate_condition_table(payload):
    keys = {'condition_id'} | {f'{name}_{side}_{unit}' for side in 'AB'
        for name, unit in (('T_in', 'K'), ('P_in', 'Pa'), ('mass_flow', 'kg_s'))}
    if not isinstance(payload, dict) or set(payload) != {'conditions'}:
        raise ValueError('Condition JSON requires only a conditions list')
    rows = payload['conditions']
    if not isinstance(rows, list) or not rows:
        raise ValueError('Condition JSON requires a nonempty conditions list')
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != keys:
            raise ValueError('Each condition requires condition_id and A/B T_in_K, P_in_Pa, mass_flow_kg_s')
        name = row['condition_id']
        if not isinstance(name, str) or not name.strip() or name in ids:
            raise ValueError('Condition IDs must be unique nonempty strings')
        ids.add(name)
        for key in keys - {'condition_id'}:
            if type(row[key]) not in (int, float):
                raise ValueError(f'{name}: {key} must be a positive number')
            _positive(row[key], f'{name}: {key}')
    return deepcopy(rows)


def import_conditions(window):
    from PySide6.QtWidgets import QFileDialog
    path, _ = QFileDialog.getOpenFileName(window, '导入优化工况表', '', 'JSON (*.json)')
    if not path:
        return
    try:
        with open(path, encoding='utf-8') as source:
            rows = validate_condition_table(json.load(source))
    except (OSError, ValueError, TypeError) as exc:
        _set_status(window, f'工况导入失败：{exc}')
        return
    window._opt_conditions = rows
    refresh_setup(window)
    _set_status(window, f'已导入 {len(rows)} 个工况：{Path(path).name}')


def use_current_condition(window):
    window._opt_conditions = None
    refresh_setup(window)


def refresh_setup(window):
    is_3d = _is_3d_mode(window)
    depth = getattr(window, '_opt_depth', None)
    if depth is not None:
        depth.setVisible(not is_3d)
        window._opt_depth_label.setVisible(not is_3d)
    label = getattr(window, '_opt_field_layout', None)
    if label is not None:
        label.setText('3 × 3 × 3 · 54 个变量 · XYZ 连续场' if is_3d
                      else '3 × 3 · 18 个变量 · XY 连续场')
    rows = getattr(window, '_opt_conditions', None)
    n = len(rows) if rows else 1
    label = getattr(window, '_opt_condition_summary', None)
    if label is not None:
        label.setText(f'{n} 个工况 · 等权：' + '、'.join(row['condition_id'] for row in rows)
                      if rows else '单工况 · 当前窗口输入；总流量由入口速度和真实孔隙开口面积换算')
    params = getattr(window, '_opt_inline_params', {})
    label = getattr(window, '_opt_eval_preview', None)
    if label is not None and params:
        budget = params['n_init'].value() + params['n_iter'].value()*params['q_batch'].value()
        label.setText(f'{budget} 个候选 + 1 个均匀基准，最多 {(budget+1)*n} 次 '
                      f'{"3D" if is_3d else "2D"} 工况求解')
    label = getattr(window, '_opt_selected_field', None)
    if label is not None:
        spec = getattr(window, '_continuous_field_spec', None)
        label.setText('当前计算使用完整 ' + ('XYZ' if 'n_ctrl_z' in spec else 'XY') + ' 连续场'
                      if spec else '当前计算未加载优化连续场')
        if hasattr(window, 'zone_table'):
            window.zone_table.setEnabled(spec is None)
            window.combo_zone_axis.setEnabled(spec is None)


def _condition_inputs(cfg, rows):
    """Build native inputs from captured values; preparation runs in the worker."""
    if rows:
        return [(row['condition_id'], replace(cfg, **{
            f'fluid_{side}': replace(getattr(cfg, f'fluid_{side}'),
                T_in_K=row[f'T_in_{side}_K'], P_in_Pa=row[f'P_in_{side}_Pa'])
            for side in 'AB'}), row['mass_flow_A_kg_s'], row['mass_flow_B_kg_s']) for row in rows]
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.optimization.multi_condition import _total_inlet_mass_capacity
    case = prepare_case(cfg, case_id='gui-current-condition')
    flows = [_total_inlet_mass_capacity(case.design_fields, case.parameters, case.grid, side)
             * getattr(cfg, f'fluid_{side}').u_mps for side in 'AB']
    return [('current', cfg, *flows)]


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
            try: lbl.setText(f"{best_q:.3g}" if isinstance(best_q, (int, float)) else str(best_q))
            except Exception: pass
    if best_dp is not None:
        lbl = getattr(window, '_opt_kpi_dp', None)
        if lbl is not None:
            try: lbl.setText(f"{best_dp:.4g}" if isinstance(best_dp, (int, float)) else str(best_dp))
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


def run_optimize(window):
    if (getattr(window, '_close_pending', False) or getattr(window, '_opt_launching', False)
            or getattr(window, '_opt_worker', None) is not None):
        return
    window._opt_launching = True
    _toggle_buttons(window, True)
    try:
        cfg = _gather_cfg(window)
        rows = getattr(window, '_opt_conditions', None)
        rows = validate_condition_table({'conditions': rows}) if rows is not None else None
        spec = _field_spec(window)
        params = {key: spin.value() for key, spin in window._opt_inline_params.items()}
        method = window._opt_method.currentData()
        save_dir = str(optimization_output_dir() / f'{method}_{time.strftime("%Y%m%d_%H%M%S")}_{time.time_ns()%1000000:06d}')
        worker = _make_worker_class()(cfg, rows, spec, method, save_dir=save_dir, **params)
    except Exception as exc:
        window._opt_launching = False
        _toggle_buttons(window, False)
        _set_status(window, f'启动失败：{exc}')
        return
    window._opt_t_start = time.monotonic()
    window._opt_total_evals = params['n_init'] + params['n_iter']*params['q_batch']
    sparkline = getattr(window, '_opt_sparkline', None)
    if sparkline is not None:
        sparkline.clear_data()
    caption = getattr(window, '_opt_sparkline_caption', None)
    if caption is not None:
        caption.setText('总预算进度 [%]（含均匀基准）')

    def progress(percent):
        if getattr(window, '_close_pending', False):
            return
        _set_progress_pct(window, percent)
        _push_sparkline(window, percent)
        elapsed = time.monotonic() - window._opt_t_start
        eta = f'{elapsed*(100-percent)/percent/60:.1f} min' if percent else '—'
        _set_kpi(window, gen=f'{percent}%', eta=eta)

    def done(report):
        if getattr(window, '_close_pending', False):
            return
        window._last_opt_report = deepcopy(report)
        window._last_opt_output_dir = save_dir
        window._selected_pareto_x = None
        render_error = show_pareto(window, report)
        _set_status(window, f'{_termination_label(report)} · {report["n_evaluated"]} 个候选 · {save_dir}'
                    + (f' · Pareto 绘图失败：{render_error}' if render_error else ''))

    def error(message):
        if getattr(window, '_close_pending', False):
            return
        _set_status(window, f'ERROR: {message} · 输出目录：{save_dir}')
        _set_kpi(window, gen='ERROR', best_q='—', best_dp='—', eta='—')
        _set_stage_pill(window, 'running', 'idle')
        _set_stage_pill(window, 'config', 'active')

    def cancelled_before_search():
        if getattr(window, '_close_pending', False):
            return
        _set_status(window, '已取消 · 工况准备结束，尚未启动优化搜索')
        _set_kpi(window, gen='已取消', best_q='—', best_dp='—', eta='—')
        _set_stage_pill(window, 'running', 'idle')
        _set_stage_pill(window, 'config', 'active')

    def finished():
        if not worker.wait(0):
            from PySide6.QtCore import QTimer
            QTimer.singleShot(10, finished)
            return
        window._opt_worker = None
        _toggle_buttons(window, False)
        worker.deleteLater()

    try:
        worker.progress_signal.connect(progress)
        worker.finished_with_result.connect(done)
        worker.cancelled_before_search.connect(cancelled_before_search)
        worker.error_signal.connect(error)
        worker.finished.connect(finished)
        window._opt_worker = worker
        _set_kpi(window, gen='starting', best_q='—', best_dp='—', eta='—')
        _set_progress_pct(window, 0)
        _set_stage_pill(window, 'config', 'done')
        _set_stage_pill(window, 'running', 'active')
        _set_stage_pill(window, 'result', 'idle')
        _set_summary_banner(window, '', show=False)
        _set_status(window, f'{method} · {len(rows) if rows else 1} 个工况 · {"3D" if cfg.is_3d else "2D"}')
        worker.start()
    except Exception as exc:
        window._opt_worker = None
        _toggle_buttons(window, False)
        _set_status(window, f'启动失败：{exc}')
    finally:
        window._opt_launching = False


def cancel_optimize(window):
    worker = getattr(window, '_opt_worker', None)
    if worker is not None:
        worker.requestInterruption()
        _set_status(window, '正在取消；等待当前数值步骤结束并保存记录')


def _termination_label(report):
    return {'completed': '完成', 'cancelled': '已取消', 'failed': '失败'}.get(report['status'], '运行中')


def show_pareto(window, report):
    """Render native objectives, returning a display error without changing the report."""
    history = report['history']
    rows = [history[index] for index in report['pareto_indices']]
    window._pareto_X = np.asarray([row['x_decision'] for row in rows]) if rows else None
    # Keep the existing figure-export readiness contract, with explicit G/C meaning.
    window._pareto_F = np.asarray([[-row['objectives']['heat_gain_percent'],
                                    row['objectives']['pressure_ratio']] for row in rows]) if rows else None
    render_error = None
    canvas = getattr(window, 'canvas_pareto', None)
    if canvas is not None:
        window._opt_3d_data = None
        window._opt_3d_ready = False
        window._opt_result_tabs.setTabEnabled(2, False)
        window.canvas_opt_field.figure.clear()
        window._opt_result_tabs.setTabEnabled(1, False)
        window._opt_result_tabs.setCurrentWidget(canvas)
        previous = getattr(window, '_pareto_pick_cid', None)
        if previous is not None:
            canvas.mpl_disconnect(previous)
        window._pareto_pick_cid = None
        try:
            canvas.figure.clear()
            theme = get_theme()
            canvas.figure.set_facecolor(theme['fig_bg'])
            ax = canvas.figure.add_subplot(111)
            ax.set_facecolor(theme['ax_bg'])
            usable = [row for row in history if row['status'] == 'completed']
            if usable:
                ax.scatter([r['objectives']['pressure_ratio'] for r in usable],
                           [r['objectives']['heat_gain_percent'] for r in usable],
                           color=theme['mpl_subtitle'], label=f'usable ({len(usable)})')
            if rows:
                order = np.argsort(window._pareto_F[:, 1])
                ax.plot(window._pareto_F[order, 1], -window._pareto_F[order, 0], 'o-',
                        color=theme['accent_orange'], picker=True, pickradius=6, label=f'Pareto ({len(rows)})')
                window._pareto_pick_cid = canvas.mpl_connect('pick_event', lambda event: on_pareto_pick(window, event))
                ax.legend(facecolor=theme['ax_bg'], edgecolor=theme['ax_spine'],
                          labelcolor=theme['ax_text'])
            ax.set_xlabel('Mean relative pressure drop [1]', color=theme['ax_text'])
            ax.set_ylabel('Mean useful heat gain [%]', color=theme['ax_text'])
            ax.set_title(f'{report["method"]} · {report["n_evaluated"]} designs', color=theme['ax_text'])
            ax.tick_params(colors=theme['ax_text'])
            for spine in ax.spines.values():
                spine.set_edgecolor(theme['ax_spine'])
            ax.grid(True, alpha=.15, color=theme['ax_text'])
            canvas.draw()
            canvas.show()
        except Exception as exc:
            _log.exception('Could not render optimization Pareto figure')
            render_error = f'{type(exc).__name__}: {exc}'
            window._pareto_X = window._pareto_F = None
            if window._pareto_pick_cid is not None:
                canvas.mpl_disconnect(window._pareto_pick_cid)
            window._pareto_pick_cid = None
            canvas.figure.clear()
            canvas.hide()
    label = _termination_label(report)
    _set_kpi(window, gen=label, best_q=max((r['objectives']['heat_gain_percent'] for r in rows), default='—'),
             best_dp=min((r['objectives']['pressure_ratio'] for r in rows), default='—'), eta='—')
    _set_stage_pill(window, 'running', 'done')
    _set_stage_pill(window, 'result', 'active')
    summary = (f'{label} · {len(rows)} 个 Pareto 方案 · '
               f'{report["n_usable"]}/{report["n_evaluated"]} 个候选数值合格')
    summary += f' · {report["reason"]}' if report.get('reason') else ''
    summary += f' · Pareto 绘图失败：{render_error}' if render_error else ''
    _set_summary_banner(window, summary)
    _set_status(window, summary)
    if hasattr(window, '_refresh_export_button'):
        window._refresh_export_button()
    return render_error


def on_pareto_pick(window, event):
    X, F = getattr(window, '_pareto_X', None), getattr(window, '_pareto_F', None)
    if X is None or F is None or not hasattr(event, 'ind') or len(event.ind) == 0:
        return
    index = int(event.ind[0])
    if 0 <= index < len(X):
        selected = X[np.argsort(F[:, 1])[index]]
        load_pareto_solution(window, selected)
        show_field_preview(window, selected)


def _result_field_config(window):
    report = getattr(window, '_last_opt_report', None)
    if report is None:
        raise ValueError('缺少原始优化 study；无法恢复连续场')
    cfg = ComputeConfig.from_dict(report['conditions'][0]['config'])
    return cfg, deepcopy(report['field_spec'])


def clear_continuous_field(window):
    window._continuous_field_spec = None
    window._selected_pareto_x = None
    window.chk_zones.setChecked(False)
    refresh_setup(window)


def load_pareto_solution(window, x_decision):
    from sjtu_tpmshx.io.case_io import load_case
    from sjtu_tpmshx.domain.portable_data import mutable_data
    from sjtu_tpmshx.optimization.multi_condition import _total_inlet_mass_capacity
    try:
        source, spec = _result_field_config(window)
        current = _gather_cfg(window)
        a, b = asdict(source), asdict(current)
        fixed = ('geometry', 'solver', 'bc_A', 'bc_B', 'flags', 'df_mode', 'sco2_nu', 'extrap', 'envelope_mode')
        if any(a[key] != b[key] for key in fixed):
            raise ValueError('当前算例与优化来源不同，请先恢复原几何、端口和求解设置')
        if (source.fluid_A.type, source.fluid_B.type) != (current.fluid_A.type, current.fluid_B.type):
            raise ValueError('当前流体类型与优化来源不同')
        spec['x_decision'] = np.asarray(x_decision, dtype=float).tolist()
        zones = ZoneInputConfig(enabled=True, axis='continuous', config=spec).validate()
        report = window._last_opt_report
        matches = [report['history'][index] for index in report['pareto_indices']
                   if np.array_equal(report['history'][index]['x_decision'], x_decision)]
        if not matches or matches[0]['status'] != 'completed':
            raise ValueError('所选连续场不属于已完成的 Pareto 方案')
        output_dir = getattr(window, '_last_opt_output_dir', None)
        if output_dir is None:
            raise ValueError('缺少原始优化归档目录')
        directory = Path(output_dir) / matches[0]['directory']
        with (directory / 'batch.json').open(encoding='utf-8') as saved:
            batch = json.load(saved)
        row = report['conditions'][0]
        archived = batch['conditions'][0]
        if (batch['status'] != 'completed' or archived['status'] != 'completed'
                or archived['condition_id'] != row['condition_id']
                or any(archived[f'mass_flow_{side}_kg_s'] != row[f'mass_flow_{side}_kg_s']
                       for side in 'AB')):
            raise ValueError('归档工况或总质量流量与优化 study 不一致')
        case = load_case(directory / archived['case_file'])
        cfg = ComputeConfig.from_dict(mutable_data(case.config_snapshot)).validate()
        expected = replace(source, zones=zones, **{
            f'fluid_{side}': replace(getattr(source, f'fluid_{side}'),
                                    u_mps=getattr(cfg, f'fluid_{side}').u_mps)
            for side in 'AB'})
        if case.case_id != archived['case_id'] or asdict(cfg) != asdict(expected):
            raise ValueError('归档算例的完整连续场或固定设置与优化 study 不一致')
        for side in 'AB':
            prescribed = getattr(cfg, f'fluid_{side}').u_mps * _total_inlet_mass_capacity(
                case.design_fields, case.parameters, case.grid, side)
            # Same serialized-input arithmetic tolerance as the batch baseline check.
            if not np.isclose(prescribed, row[f'mass_flow_{side}_kg_s'], rtol=1e-12, atol=0.):
                raise ValueError(f'归档入口速度未保持工况 {side} 总质量流量')
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        _set_status(window, f'连续场载入失败：{exc}')
        return
    window._continuous_field_spec = deepcopy(spec)
    window._selected_pareto_x = np.asarray(x_decision).copy()
    window._pareto_x_decision = None
    window.chk_zones.setChecked(True)
    for side in 'AB':
        fluid = getattr(cfg, f'fluid_{side}')
        temperature = fluid.T_in_K - (273.15 if getattr(window, '_temp_unit', 'K') == 'C' else 0.)
        for attr, value in ((f'le_Tin{side}', temperature), (f'le_Pin{side}', fluid.P_in_Pa),
                            (f'le_u{side}', fluid.u_mps)):
            getattr(window, attr).setText(format(value, '.17g'))
    if hasattr(window, '_invalidate_results_for_preset_load'):
        window._invalidate_results_for_preset_load()
    if hasattr(window, '_resync_undo_baseline'):
        window._resync_undo_baseline()
    refresh_setup(window)
    _set_status(window, f'已载入完整 {"XYZ" if source.is_3d else "XY"} 连续场 · 工况 {row["condition_id"]} · 总质量流量保持不变')


def show_field_preview(window, x_decision=None):
    from matplotlib.ticker import MaxNLocator
    from sjtu_tpmshx.models.continuous_field import from_decision_vector, decision_bounds
    try:
        current_spec = getattr(window, '_continuous_field_spec', None)
        if x_decision is None and current_spec is not None and window.chk_zones.isChecked():
            cfg, spec = _gather_cfg(window), deepcopy(current_spec)
            x_decision = spec.pop('x_decision')
        elif x_decision is None:
            cfg, spec = _gather_cfg(window), _field_spec(window)
            low, high = decision_bounds(spec['n_ctrl_x'], spec['n_ctrl_y'], spec['symmetric_y'],
                spec['L_bounds'], spec['t_bounds'], n_ctrl_z=spec.get('n_ctrl_z'))
            x_decision = (low+high)/2
        else:
            cfg, spec = _result_field_config(window)
        geom = cfg.geometry
        field = from_decision_vector(x_decision, geom.tpms, geom.k_s_W_mK,
            geom.L_dom_m, geom.H_dom_m, **spec,
            **({'Lz_domain': geom.Lz_m} if 'n_ctrl_z' in spec else {}))
        volume = None
        if 'n_ctrl_z' in spec:
            # Sample the complete continuous design for display. Odd Nz keeps
            # the central cell exactly at z=Lz/2; this is not a solver mesh.
            L_volume, t_volume = field.evaluate_volume(80, 40, 41)
            volume = dict(L_mm=L_volume, t_mm=t_volume,
                          dx=np.full(80, geom.L_dom_m/80),
                          dy=np.full(40, geom.H_dom_m/40),
                          dz=np.full(41, geom.Lz_m/41), flow_dir=None)
            L, t = L_volume[:, :, 20], t_volume[:, :, 20]
            suffix = f' · z = {geom.Lz_m*500:g} mm'
        else:
            L, t = field.evaluate_grid(80, 40)
            suffix = ''
    except (ValueError, TypeError, KeyError) as exc:
        window._opt_3d_data = None
        window._opt_3d_ready = False
        window._opt_result_tabs.setTabEnabled(2, False)
        if window.canvas_opt_3d is not None:
            window.canvas_opt_3d.hide()
        _set_status(window, f'连续场预览失败：{exc}')
        return
    canvas = getattr(window, 'canvas_opt_field', None)
    if canvas is None:
        return
    fig = canvas.figure
    fig.clear()
    theme = get_theme()
    fig.set_facecolor(theme['fig_bg'])
    axes = fig.subplots(2, 1, sharex=True)
    for ax, (name, values) in zip(axes, (('L', L), ('t', t))):
        ax.set_facecolor(theme['ax_bg'])
        im = ax.imshow(values.T, origin='lower', aspect='equal', cmap=FIELD_CMAP,
                       vmin=spec[f'{name}_bounds'][0], vmax=spec[f'{name}_bounds'][1],
                       extent=[0, geom.L_dom_m*1e3, 0, geom.H_dom_m*1e3])
        ax.set_title(f'{name}(x,y){suffix}', color=theme['ax_text'], fontsize=11,
                     loc='left')
        ax.set_ylabel('y [mm]', color=theme['ax_text'])
        ax.tick_params(colors=theme['ax_text'], labelsize=9, length=3)
        for spine in ax.spines.values():
            spine.set_edgecolor(theme['ax_spine'])
        cb = fig.colorbar(im, ax=ax, orientation='vertical',
                          fraction=.025, pad=.025, aspect=25,
                          ticks=MaxNLocator(nbins=4, steps=[1, 2, 5, 10]), format='%g')
        cb.set_label(f'{name} [mm]', color=theme['ax_text'], fontsize=9)
        cb.ax.tick_params(colors=theme['ax_text'], labelsize=8, length=2)
        cb.outline.set_visible(False)
    axes[-1].set_xlabel('x [mm]', color=theme['ax_text'])
    canvas.axes = [[ax] for ax in axes]
    window._opt_3d_data = volume
    window._opt_3d_ready = False
    window._opt_result_tabs.setTabEnabled(2, volume is not None)
    window._opt_result_tabs.setTabEnabled(1, True)
    window._opt_result_tabs.setCurrentWidget(canvas)
    _set_stage_pill(window, 'result', 'active')
    window._switch_tab('pareto')
    canvas.draw_idle()
    window._refresh_export_button()


def show_field_volume(window):
    """Populate the optimization volume only when its result tab is opened."""
    if window._opt_result_tabs.currentWidget() is not window._opt_3d_host:
        return
    data = window._opt_3d_data
    if data is None or window._opt_3d_figure_ready():
        return
    if getattr(window, '_opt_3d_loading', False):
        return
    placeholder = window._opt_3d_placeholder
    panel = window.canvas_opt_3d
    if panel is not None:
        panel.hide()
    placeholder.show()
    window._opt_3d_ready = False
    window._opt_3d_loading = True
    try:
        if panel is None:
            if getattr(window, '_vis3d_import_error', None):
                raise RuntimeError(window._vis3d_import_error)
            from .panel_vis_3d import ThreeDVisPanel
            panel = ThreeDVisPanel(window._opt_3d_host)
            panel.hide()
            window._opt_3d_host.layout().addWidget(panel, 1)
            window.canvas_opt_3d = panel
        panel.set_fields(**data)
        if panel._volume_actor is None:
            raise RuntimeError('未能生成三维体图，请检查显示设备或重新打开预览')
        window._opt_3d_ready = True
        placeholder.hide()
        panel.show()
    except Exception as exc:
        _log.exception('Could not render optimization volume')
        placeholder.setText(f'三维连续场显示失败：{exc}')
    finally:
        window._opt_3d_loading = False
        window._refresh_export_button()
