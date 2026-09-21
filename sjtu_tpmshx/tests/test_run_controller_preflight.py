"""U4 + U5 preflight / runtime-notice fixes (full-debug audit 2026-06-28).

U4: the "Large 3D Grid" confirm dialog used the +16 wall-refine cell estimate
even when wall-refine was OFF (the documented default), popping a spurious
confirm for a moderate grid.

U5: the high-velocity V&V notice zeroed BOTH velocities when le_uB was left
blank — a valid 'u_B = u_A' state — so a high-throughput run lost the
off-domain notice.

Both live in ui/mixins/run_controller.py and touch no numerical path.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QMessageBox
from sjtu_tpmshx.ui.mixins.run_controller import RunControllerMixin


class _LE:
    def __init__(self, t): self._t = t
    def text(self): return self._t


class _Status:
    def __init__(self): self.msgs = []
    def showMessage(self, *a, **k): self.msgs.append(a)


# ── U5: high-velocity notice — blank u_B inherits u_A ───────────────────────
def _win_uv(uA, uB):
    st = _Status()
    return SimpleNamespace(le_uA=_LE(uA), le_uB=_LE(uB),
                           statusBar=lambda: st), st


def test_highvel_notice_blank_uB_inherits_uA():
    """uA=20 (off-domain), uB blank -> u_B inherits u_A -> notice must fire."""
    win, st = _win_uv("20", "")
    RunControllerMixin._maybe_highvel_notice(win)
    assert st.msgs, "blank u_B zeroed the high-velocity check (notice suppressed)"
    assert "outside V&V domain" in st.msgs[0][0]


def test_highvel_notice_in_domain_silent():
    win, st = _win_uv("5", "")          # both <= 10 m/s
    RunControllerMixin._maybe_highvel_notice(win)
    assert not st.msgs


def test_highvel_notice_both_blank_silent():
    win, st = _win_uv("", "")           # both blank -> 0 -> in domain -> silent
    RunControllerMixin._maybe_highvel_notice(win)
    assert not st.msgs


def test_highvel_notice_high_uB_only():
    win, st = _win_uv("5", "20")        # uB off-domain
    RunControllerMixin._maybe_highvel_notice(win)
    assert st.msgs


# ── U4: Large-grid confirm reflects the actual refine setting ───────────────
def _win_grid(nx, ny, nz):
    return SimpleNamespace(le_Nx=_LE(str(nx)), le_Ny=_LE(str(ny)),
                           le_Nz=_LE(str(nz)))


def test_large_grid_no_confirm_when_refine_off():
    """40^3 = 64000 actual cells with refine OFF is below the 100k threshold ->
    no confirm dialog. Pre-fix the unconditional +16 inflated it to
    56^3 = 175616 and popped a spurious 'Large 3D Grid' confirm."""
    win = _win_grid(40, 40, 40)
    with patch.object(QMessageBox, 'question') as q, \
         patch.object(QMessageBox, 'warning'):
        proceed, est, label = RunControllerMixin._preflight_3d(win)
    q.assert_not_called()
    assert proceed is True
    assert est == 64000
    assert label == "40×40×40"


def test_large_grid_confirms_using_total_input_counts():
    win = _win_grid(50, 50, 50)
    with patch.object(QMessageBox, 'question',
                      return_value=QMessageBox.StandardButton.Yes) as q, \
         patch.object(QMessageBox, 'warning'):
        proceed, est, label = RunControllerMixin._preflight_3d(win)
    q.assert_called_once()
    assert proceed is True
    assert est == 50 ** 3
    assert label == "50×50×50"
