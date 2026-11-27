"""Verify in-place widget reuse for ExpandedNavRail and ReadoutStrip."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from sjtu_tpmshx.applications.gui.ui.nav_rail import ExpandedNavRail, RecentRunItem
from sjtu_tpmshx.applications.gui.ui.readout_strip import (
    ReadoutItem,
    ReadoutNotice,
    ReadoutStrip,
)
from sjtu_tpmshx.applications.gui.ui.theme import _THEMES

DARK = _THEMES["dark"]
LIGHT = _THEMES["light"]


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication(["pytest", "-platform", "offscreen"])


def test_expanded_nav_rail_reuses_rows_and_flushes_hidden_updates_on_show():
    _ensure_app()
    rail = ExpandedNavRail(
        active_page="run",
        workspaces=("A", "B", "C"),
        active_workspace="A",
        tokens=DARK,
    )
    page_rows_before = dict(rail._page_rows)
    ws_rows_before = list(rail._ws_rows)
    action_rows_before = dict(rail._action_rows)

    # While hidden, setters defer UI sync and still flush full state on show().
    rail.set_active_page("result")
    rail.set_page_enabled("opt", False)
    rail.set_page_meta({"result": ("ok", "3D")})
    rail.set_workspaces(("A", "B", "C"), "B")
    rail.set_recent_runs([RecentRunItem("0", "12:00 · 3D", "<i>Q</i> = 338 W")])
    rail.apply_theme(LIGHT)
    assert rail._dirty is True

    rail.show()
    QApplication.processEvents()
    assert rail._dirty is False

    assert rail._page_rows == page_rows_before
    for key, row in page_rows_before.items():
        assert rail._page_rows[key] is row
    assert rail._ws_rows == ws_rows_before
    for old, cur in zip(ws_rows_before, rail._ws_rows):
        assert cur is old
    for key, row in action_rows_before.items():
        assert rail._action_rows[key] is row

    assert not rail._page_rows["opt"].isEnabled()
    assert rail._page_rows["result"]._meta_label.text() == "3D"
    assert rail._page_rows["result"]._dot_label.isVisibleTo(rail)
    assert rail._ws_rows[1]._check_label.isVisibleTo(rail)
    assert not rail._ws_rows[0]._check_label.isVisibleTo(rail)
    assert len(rail._recent_rows) == 1
    assert rail._recent_rows[0]._text_label.text() == "12:00 · 3D"

    # Visible updates also reuse existing rows and emit expected signals.
    recent_row_before = rail._recent_rows[0]
    selected_ws: list[str] = []
    selected_recent: list[str] = []
    rail.workspace_selected.connect(selected_ws.append)
    rail.recent_run_selected.connect(selected_recent.append)

    rail.set_recent_runs([RecentRunItem("7", "12:05 · 2D", "<i>Q</i> = 400 W/m")])
    assert rail._recent_rows[0] is recent_row_before
    assert rail._recent_rows[0]._text_label.text() == "12:05 · 2D"

    rail._ws_rows[2].click()
    rail._recent_rows[0].click()
    assert selected_ws == ["C"]
    assert selected_recent == ["7"]

    rail.set_recent_runs([])
    assert rail._recent_box.isHidden()
    rail.close()


def test_readout_strip_reuses_cells_across_updates():
    _ensure_app()
    first_items = [
        ReadoutItem("换热量 Q", "338.3", "W"),
        ReadoutItem("出口温度 T_out,A", "359.2", "K"),
    ]
    strip = ReadoutStrip(first_items, tokens=DARK)
    strip.show()
    QApplication.processEvents()

    cells_before = list(strip._cells)
    labels_before = [(c.name_label, c.value_label, c.unit_label) for c in cells_before]

    updated_items = [
        ReadoutItem("换热量 Q", "338.3", "W"),
        ReadoutItem("出口温度 T_out,A", "86.1", "°C"),
    ]
    strip.set_items(updated_items)
    strip.set_stale(True)
    strip.set_notice(ReadoutNotice("运行提示", "存在 1 项外推", kind="warn"))
    strip.set_compact(True)
    strip.apply_theme(LIGHT)

    assert strip._cells == cells_before
    for cell, old_cell, (n_lbl, v_lbl, u_lbl) in zip(strip._cells, cells_before, labels_before):
        assert cell is old_cell
        assert cell.name_label is n_lbl
        assert cell.value_label is v_lbl
        assert cell.unit_label is u_lbl

    assert strip.items() == updated_items
    assert strip.is_stale() is True
    assert strip._stale_box.isVisibleTo(strip)
    assert strip._notice_box.isVisibleTo(strip)
    assert strip._cells[1].value_label.text() == "86.1"
    assert strip._cells[1].unit_label.text() == "°C"

    # Shrinking hides surplus cells without destroying them.
    strip.set_items([updated_items[0]])
    assert len(strip._cells) == 2
    assert strip._cells[0].cell.isVisibleTo(strip)
    assert strip._cells[1].cell.isHidden()
    strip.set_notice(None)
    assert strip._notice_box.isHidden()
    strip.close()
