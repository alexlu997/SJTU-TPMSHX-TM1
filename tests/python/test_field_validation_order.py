"""Tests for ``Main_Menu._make_field_handler`` — audit C5 H4 fix.

The legacy split between ``_attach_input_validators`` and
``_install_inline_unit_parser`` connected two callbacks to the same
``editingFinished`` signal. Qt fires them in connection order: the
validator ran first, saw the raw "5 mm" text, flipped ``inpError``
red, *then* the parser converted to "5e-3" — leaving the red border
stuck on a now-valid field.

The unified handler does parse → validate → apply in one slot.  This
test verifies (a) parse fires before validate, (b) ``inpError`` ends
up ``'false'`` for "5 mm" length input, (c) the underlying QLineEdit
text gets the converted value.

Tests fully mock the Qt API surface ``_make_field_handler`` touches —
no QApplication needed.
"""
from __future__ import annotations

import pytest




# ── Qt-API mocks ────────────────────────────────────────────────────


class _MockLE:
    """Tiny QLineEdit-like stub recording every API call the handler
    makes (``text``, ``setText``, ``blockSignals``, ``setProperty``,
    ``setToolTip``, ``style().unpolish/polish``, ``objectName``)."""

    def __init__(self, text: str, tooltip: str = ""):
        self._text = text
        self._tip = tooltip
        self._props = {}
        self._signals_blocked = False
        self.set_text_calls = []
        self.set_property_calls = []

    def text(self):
        return self._text

    def raw_display_text(self):
        return self._text

    def display_scale(self):
        return 1.0

    def setText(self, v):
        self.set_text_calls.append(v)
        self._text = v

    def toolTip(self):
        return self._tip

    def setToolTip(self, v):
        self._tip = v

    def property(self, name):
        return self._props.get(name)

    def setProperty(self, name, value):
        self._props[name] = value
        self.set_property_calls.append((name, value))

    def blockSignals(self, flag):
        prev = self._signals_blocked
        self._signals_blocked = bool(flag)
        return prev

    def objectName(self):
        return 'mock_field'

    def style(self):
        return self  # unpolish/polish are no-ops on the stub itself

    def unpolish(self, _w):
        pass

    def polish(self, _w):
        pass


class _MockDialogs:
    def __init__(self):
        self.messages = []

    def notify(self, msg, **_kwargs):
        self.messages.append(msg)


class _MockWindow:
    """Minimal Main_Menu stand-in with just the handler dependencies."""

    def __init__(self, temp_unit='K'):
        self._temp_unit = temp_unit
        self._undo_last = {}
        self.dialogs = _MockDialogs()
        self._sb = self.dialogs


def _bind_handler(win, le, attr):
    from sjtu_tpmshx.applications.gui.ui.main_window import Main_Menu
    from sjtu_tpmshx.applications.gui.ui.window_config import LINE_EDITS
    return Main_Menu._make_field_handler(win, le, LINE_EDITS[attr])


# ── tests ───────────────────────────────────────────────────────────


def test_parse_then_validate_clears_inperror_on_5mm_length():
    """The H4 fix: "5 mm" on a length-positive field must end with
    ``inpError == 'false'`` and the QLineEdit text rewritten to
    ``"0.005"`` (5 mm → 5e-3 m)."""
    win = _MockWindow()
    le = _MockLE("5 mm")
    cb = _bind_handler(win, le, 'le_L')
    cb()  # simulate editingFinished
    # text rewritten to converted value
    assert le.text() == "0.005"
    # validator saw the converted (positive) value → no error
    assert le.property('inpError') == 'false'
    # notification received the conversion message
    assert any('已换算' in m for m in win._sb.messages)


@pytest.mark.parametrize('field,text,stored', [
    ('le_Lcell', '7 mm', '7'), ('le_pipeB_out_z_ctr', '21 mm', '0.021'),
    ('le_ks', '16 W/(m·K)', '16'), ('le_ks', '0.016 kW/(m·K)', '16'),
])
def test_unit_input_commits_to_the_bound_editor(field, text, stored):
    win, le = _MockWindow(), _MockLE(text)
    _bind_handler(win, le, field)()
    assert le.text() == stored
    assert le.property('inpError') == 'false'


def test_count_field_rejects_unit_keeps_inperror():
    """``le_Nx`` is a count; "30 cells" is allowed (whitelist),
    "30 m" is rejected → text unchanged, validator still sees
    "30 m" → fails float() → red border."""
    win = _MockWindow()
    le = _MockLE("30 cells")
    cb = _bind_handler(win, le, 'le_Nx')
    cb()
    assert le.text() == "30"
    assert le.property('inpError') == 'false'

    # Now try a disallowed unit on the same field.
    le2 = _MockLE("30 m")
    cb2 = _bind_handler(win, le2, 'le_Nx')
    cb2()
    # parser rejects → text unchanged → validator fails on "30 m"
    assert le2.text() == "30 m"
    assert le2.property('inpError') == 'true'


def test_negative_value_after_parse_flags_inperror():
    """Parse succeeds but value ≤ 0 still fails positive validation."""
    win = _MockWindow()
    le = _MockLE("-5 mm")
    cb = _bind_handler(win, le, 'le_L')
    cb()
    # text converted to -0.005 (or whatever the formatter writes)
    assert le.text().startswith("-")
    # validator caught the sign → red border
    assert le.property('inpError') == 'true'


def test_empty_input_no_callback_action():
    """Empty field returns immediately; no setText / setProperty."""
    win = _MockWindow()
    le = _MockLE("")
    cb = _bind_handler(win, le, 'le_L')
    cb()
    assert le.set_text_calls == []
    assert le.set_property_calls == []


def test_parse_leaves_previous_undo_value_for_the_undo_slot():
    win = _MockWindow()
    win._undo_last = {'le_L': '0.01'}
    le = _MockLE("5 mm")
    _bind_handler(win, le, 'le_L')()
    assert le.text() == '0.005'
    assert win._undo_last['le_L'] == '0.01'


def test_bare_number_validates_without_parse():
    """Bare "5" on length field skips parse, runs validator only."""
    win = _MockWindow()
    le = _MockLE("5")
    cb = _bind_handler(win, le, 'le_L')
    cb()
    # No conversion happened — text unchanged.
    assert le.text() == "5"
    # Positive numeric → no error.
    assert le.property('inpError') == 'false'


def test_non_numeric_bare_text_flags_inperror():
    """Garbage text on a positive field fails validation."""
    win = _MockWindow()
    le = _MockLE("abc")
    cb = _bind_handler(win, le, 'le_L')
    cb()
    assert le.property('inpError') == 'true'


@pytest.mark.parametrize('text,expected', [('0.042 / 2', '0.021'), ('sqrt(4) * 3', '6')])
def test_expression_is_evaluated_before_positive_validation(text, expected):
    win, le = _MockWindow(), _MockLE(text)
    _bind_handler(win, le, 'le_L')()
    assert le.text() == expected
    assert le.property('inpError') == 'false'


@pytest.mark.parametrize('text', ['1/0', 'sqrt(-1)', '-1 * 2', 'float(1)', 'nan', 'inf'])
def test_invalid_expression_or_nonpositive_value_stays_invalid(text):
    win, le = _MockWindow(), _MockLE(text)
    _bind_handler(win, le, 'le_L')()
    assert le.property('inpError') == 'true'


@pytest.mark.parametrize('unit,text,valid', [
    ('C', '0', True), ('C', '-5', True), ('C', '273.15 K', True),
    ('K', '268.15', True), ('K', '0', False), ('C', '-273.15', False),
    ('C', '-274', False), ('C', 'nan', False), ('C', 'inf', False),
    ('C', '26.85_', False),  # Decimal() accepts this text, but Compute and Save use float().
])
def test_temperature_validates_absolute_value_without_changing_display_unit(unit, text, valid):
    win, le = _MockWindow(temp_unit=unit), _MockLE(text)
    _bind_handler(win, le, 'le_TinA')()
    assert le.property('inpError') == ('false' if valid else 'true')
    if text == '273.15 K':
        assert le.text() == '0'


@pytest.mark.parametrize('text,expected,invalid', [
    ('10^1000', '10^1000', True),
    ('(10^1000)/(10^1000)', '1', False),
])
def test_expression_float_boundary_preserves_input_semantics(text, expected, invalid):
    win, le = _MockWindow(), _MockLE(text)
    _bind_handler(win, le, 'le_L')()
    assert le.text() == expected
    assert le.property('inpError') == ('true' if invalid else 'false')
    if invalid:
        assert 'Must be a number' in le.toolTip()
        assert any('Invalid input' in message for message in win._sb.messages)
