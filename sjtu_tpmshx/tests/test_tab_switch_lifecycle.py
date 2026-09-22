"""Tab switches publish one complete state without dispatching nested input."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from sjtu_tpmshx.tests.test_workbench_navigation import win as win


def test_queued_tab_request_runs_after_the_current_switch(win):
    requests = []

    def next_tab():
        requests.append('layout')
        win._switch_tab('layout')

    QTimer.singleShot(0, win, next_tab)
    win._switch_tab('pareto')
    assert requests == [], 'switching must not dispatch another input mid-update'
    assert win._active_tab == 'pareto'
    assert win._canvas_cards['pareto'].isVisible()
    QApplication.processEvents()
    assert requests == ['layout']
    assert win._active_tab == 'layout'
    assert win._canvas_cards['layout'].isVisible()
    assert win._canvas_cards['pareto'].isHidden()
    assert win._canvas_scroll.viewport().updatesEnabled()


def test_show_event_reentry_keeps_the_latest_empty_state(win, monkeypatch):
    win.cache.replace_drawn_tabs(win.cache.get_drawn_tabs() - {'layout'})
    win._canvas_cards['layout'].hide()
    card = win._canvas_cards['pareto']
    original_show = card.showEvent

    def return_to_layout(event):
        original_show(event)
        win._switch_tab('layout')

    monkeypatch.setattr(card, 'showEvent', return_to_layout)
    win._switch_tab('pareto')
    assert win._active_tab == 'layout'
    assert card.isHidden()
    assert win._empty_state_label.isVisible(), 'old show must not overwrite the latest state'
    assert win._canvas_scroll.viewport().updatesEnabled()
