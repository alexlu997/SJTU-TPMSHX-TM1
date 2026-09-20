"""The compute card reports worker evidence and preserves terminal outcomes."""
import threading

import pytest
from PySide6.QtWidgets import QApplication, QBoxLayout

from sjtu_tpmshx.controllers.compute_pipeline import CancelledError, Pipeline2D, Pipeline3D
from sjtu_tpmshx.domain.compute_result import ComputeResult
from sjtu_tpmshx.tests.test_worker_result_handoff import (
    _configure, _wait_for, win as win,
)
from sjtu_tpmshx.ui.responsive import ResponsiveRow
from sjtu_tpmshx.ui.run_status import RunStatusCard
from sjtu_tpmshx.ui.icons import icon


@pytest.mark.parametrize('outcome', ['success', 'error', 'cancelled', 'warning', 'unconverged'])
def test_worker_lifecycle_keeps_cancel_logs_and_verdict(win, monkeypatch, tmp_path, outcome):
    _configure(win, monkeypatch, '2d')
    card = win._run_status_card
    card.hide()  # Focus mode may hide an idle card before Ctrl+R starts a run.
    action_icons = []

    def action_icon(name, color):
        action_icons.append((name, color))
        return icon(name, color)

    monkeypatch.setattr('sjtu_tpmshx.ui.mixins.run_controller.icon', action_icon)
    released = threading.Event()
    callbacks_sent = threading.Event()

    def run(pipe):
        print('captured solver log')
        pipe.ui_hooks['iter_label_cb']('SIMPLE A · 2')
        pipe.ui_hooks['live_residuals']['A'].extend([(1, .1), (2, .01)])
        pipe.ui_hooks['live_residuals']['B'].append((1, .2))
        callbacks_sent.set()
        assert released.wait(10)
        if outcome == 'error':
            raise RuntimeError('controlled failure')
        if outcome == 'cancelled':
            assert pipe.cancel.cancelled
            raise CancelledError('controlled cancellation')
        return ComputeResult(Q_W=42, converged=outcome != 'unconverged',
                             warnings=['domain notice'] if outcome == 'warning' else [])

    monkeypatch.setattr(Pipeline2D, 'run', run)
    try:
        win.run_calculation()
        _wait_for(callbacks_sent.is_set)
        _wait_for(lambda: card.iteration.text() == 'SIMPLE A · 2')
        assert card.state == 'running'
        assert not card.isHidden(), 'a new run must reveal the focused-view cancel control'
        assert action_icons[-1] == ('square', 'white')
        assert card.log_button.isHidden(), 'old logs must not appear during a fresh run'
        win._drain_live_residuals()
        win._drain_live_residuals()
        assert card.trails['A']._data == pytest.approx([-1., -2.])
        assert len(card.trails['B']._data) == 1
        assert '1.00e-02' in card.residual_labels['A'].text()
        win.le_Nx.setText('77')  # Parameters remain an editable next-run draft.
        assert win.le_Nx.isEnabled()
        if outcome == 'cancelled':
            card.cancel_button.click()
            assert card.state == 'cancelling'
            assert not card.cancel_button.isEnabled()
            win._tick_btn()
            assert win.btn_compute.text() == '正在取消…'
    finally:
        released.set()
    _wait_for(win.compute.is_idle)
    assert card.state == outcome
    assert card.cancel_button.isHidden()
    assert not card.log_button.isHidden()
    assert 'captured solver log' in win._last_solve_log
    assert card.iteration.text() == 'SIMPLE A · 2'
    assert win.le_Nx.text() == '77'
    assert win.btn_compute.isEnabled()
    assert action_icons[-1] == ('play', 'white')
    if outcome == 'error':
        assert 'controlled failure' in card.note.text()
    if outcome == 'unconverged':
        assert '未收敛' in card.title.text()


def test_plot_publication_failure_is_not_a_success_card(win, monkeypatch, tmp_path):
    _configure(win, monkeypatch, '2d')
    monkeypatch.setattr(Pipeline2D, 'run', lambda pipe: ComputeResult(Q_W=42))

    def broken_plot():
        raise RuntimeError('controlled rendering failure')

    monkeypatch.setattr(win, '_finalize_plots', broken_plot)
    win.run_calculation()
    _wait_for(win.compute.is_idle)
    assert win._run_status_card.state == 'error'
    assert '结果显示未完成' in win._run_status_card.note.text()
    assert win.btn_export.isEnabled(), 'solver result must remain exportable'


def test_card_expansion_narrow_width_and_restart_clear_previous_run():
    card = RunStatusCard()
    try:
        card.resize(400, 60)
        card.show()
        _wait_for(lambda: card.findChild(ResponsiveRow).direction == QBoxLayout.Direction.TopToBottom)
        card.toggle.click()
        assert card.details.isVisible()
        card.start('3d')
        card.finish('cancelled', 12, log_available=True)
        assert '本次未发布实时残差' in card.residual_labels['A'].text()
        card.start('2d')
        assert card.toggle.isChecked(), 'keep the user detail preference'
        assert card.log_button.isHidden()
        assert card.cancel_button.isEnabled()
        assert not card.trails['A']._data
        assert card.iteration.text() == '等待求解器迭代信息'
        card.toggle.setChecked(False)
        card.finish('unconverged', 3599, log_available=True)
        for width in (480, 533, 573):
            card.resize(width, card.sizeHint().height())
            QApplication.processEvents()
            header = card.findChild(ResponsiveRow)
            expected = (QBoxLayout.Direction.TopToBottom if width == 480
                        else QBoxLayout.Direction.LeftToRight)
            assert header.direction == expected
            for label in (card.title, card.elapsed):
                assert label.contentsRect().width() >= label.fontMetrics().horizontalAdvance(label.text())
            for button in (card.log_button, card.toggle):
                assert button.height() == 32
                assert button.width() >= button.sizeHint().width()
        assert card.cancel_button.minimumHeight() == 32
        from PySide6.QtCore import QSize, Qt
        assert card.toggle.iconSize() == QSize(14, 14)
        assert card.toggle.layoutDirection() == Qt.LayoutDirection.RightToLeft
    finally:
        card.close()
        card.deleteLater()


def test_3d_missing_view_reports_warning_without_discarding_result(win, monkeypatch, tmp_path):
    _configure(win, monkeypatch, '3d')
    monkeypatch.setattr(Pipeline3D, 'run', lambda pipe: ComputeResult(
        Q_W=42, diagnostics={'mode': '3d'}))
    win.run_calculation()
    _wait_for(win.compute.is_idle)
    assert win._run_status_card.state == 'warning'
    assert '三维视图不可用' in win._run_status_card.note.text()
    assert win._result_3d.Q_W == 42
    assert win.btn_export.isEnabled()


def test_rapid_details_reveal_keeps_latest_visibility_and_terminal_actions(monkeypatch):
    monkeypatch.delenv('QT_REDUCED_MOTION', raising=False)
    card = RunStatusCard()
    log_requests = []
    card.log_requested.connect(lambda: log_requests.append(True))
    try:
        card.toggle.click()
        assert card.details.graphicsEffect() is None, 'hidden cards do not animate'
        card.start('2d')
        card.toggle.click()  # Collapse the previously expanded details.
        assert card.details.isHidden()
        card.toggle.click()
        first_effect = card.details.graphicsEffect()
        assert first_effect is not None
        card.toggle.click()
        assert card.details.isHidden(), 'collapse must take effect immediately'
        card.toggle.click()
        assert card.details.isVisible()
        assert card.details.graphicsEffect() is not first_effect
        card.finish('success', 12, log_available=True)
        card.log_button.click()
        assert log_requests == [True], 'the animation must not block terminal actions'
        _wait_for(lambda: card.details.graphicsEffect() is None)
        assert card.toggle.isChecked() and card.details.isVisible()
        assert card.state == 'success'
    finally:
        card.close()
        card.deleteLater()
