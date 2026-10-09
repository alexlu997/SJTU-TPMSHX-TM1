"""Auto-fill messages use the selected fluid's real correlation window."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QLabel

from sjtu_tpmshx.ui.mixins import fluid_input
from sjtu_tpmshx.tests.test_mass_flow_inputs import mass_window as mass_window
from sjtu_tpmshx.tests.gui_io_support import win as win


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('label,fluid,bounds', [
    ('Air', 'air', (400., 16000.)),
    ('Water', 'water', (90., 51000.)),
    ('sCO₂', 'sco2', (2600., 128000.)),
    ('CO₂', 'co2', (3000., 60000.)),
])
def test_autofill_re_label_and_status_follow_selected_fluid(
        monkeypatch, side, label, fluid, bounds):
    status = Mock()
    window = SimpleNamespace(compute_tpms=lambda: True, statusBar=lambda: status,
                             _temp_to_K=lambda field: float(field.text()),
                             combo_tpms=Mock(currentText=lambda: 'Gyroid'))
    for key, value in {'Lcell': '7', 't': '.6', 'ks': '16',
                       'uA': '1', 'uB': '1', 'TinA': '350', 'TinB': '350',
                       'PinA': '10000000', 'PinB': '10000000'}.items():
        setattr(window, 'le_' + key, Mock(text=lambda value=value: value))
    for which in ('A', 'B'):
        setattr(window, 'combo_fluid' + which, Mock(currentText=lambda: label))
        setattr(window, '_fluid_computed_' + which, Mock())
        for name in ('rho', 'Re', 'Nu', 'dPL'):
            setattr(window, '_v_' + name + which, QLabel())
    styles = {'VAL': 'color: black;', 'VAL_WARN': 'color: red;'}
    monkeypatch.setattr(fluid_input, '_fluid_styles', lambda: styles)
    properties = dict(Nu=4., dP_per_L=5., rho=7.)
    compute = Mock()
    monkeypatch.setattr(fluid_input, 'tpms_compute', compute)
    lo, hi = bounds
    for re, tag in ((lo - 1, f'  (< {lo:g}!)'), (lo, ''),
                    (hi, ''), (hi + 1, f'  (> {hi:g}!)')):
        compute.return_value = dict(properties, Re=re)
        details = getattr(window, '_fluid_computed_' + side)
        details.reset_mock()
        fluid_input.FluidInputMixin._auto_fill_fluid(window, side)
        shown = getattr(window, '_v_Re' + side)
        assert shown.text() == f'{re:.1f}{tag}'
        assert shown.styleSheet() == styles['VAL_WARN' if tag else 'VAL']
        assert status.showMessage.call_args.args[0] == (
            f'Fluid {side} filled.  Re={re:.0f}{tag}  Nu=4.00  dP/L=5.0 Pa/m')
        assert compute.call_args.kwargs['fluid_type'] == fluid
        for name, expected in (('rho', '7.0000'), ('Nu', '4.0000'), ('dPL', '5.0')):
            assert getattr(window, '_v_' + name + side).text() == expected
        details._set_expanded.assert_called_once_with(True)
        other_side = 'B' if side == 'A' else 'A'
        for name in ('rho', 'Re', 'Nu', 'dPL'):
            assert getattr(window, '_v_' + name + other_side).text() == ''
        getattr(window, '_fluid_computed_' + other_side)._set_expanded.assert_not_called()


@pytest.mark.parametrize('side', ['A', 'B'])
def test_co2_gui_defaults_save_and_fixed_preview_are_distinct_from_sco2(mass_window, monkeypatch, side):
    from PySide6.QtWidgets import QMessageBox
    from sjtu_tpmshx.ui.window_config import config_from_window
    from sjtu_tpmshx.models.tpms_calc import compute
    window = mass_window
    combo = getattr(window, 'combo_fluid' + side)
    combo.setCurrentIndex(3)
    config = config_from_window(window, strict=True)
    fluid = getattr(config, 'fluid_' + side)
    assert (fluid.type, fluid.T_in_K, fluid.P_in_Pa, fluid.u_mps) == ('co2', 340., 8e6, .3)
    assert not window._co2_fixed_notice.isHidden()
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args: pytest.fail(str(args)))
    expected = compute('Gyroid', 7., .6, .3, 340., 8e6, 16., fluid_type='co2')
    for mode in ('cfd_smooth', 'experimental'):
        window.combo_df_mode.setCurrentIndex(window.combo_df_mode.findData(mode))
        window._auto_fill_fluid(side)
        assert float(getattr(window, '_v_dPL' + side).text()) == pytest.approx(expected['dP_per_L'], abs=.05)
        assert float(getattr(window, '_v_Nu' + side).text()) == pytest.approx(expected['Nu'], abs=.00005)
    preset = window._capture_current_preset('co2 inputs')
    combo.setCurrentIndex(2)
    assert getattr(config_from_window(window), 'fluid_' + side).type == 'sco2'
    window._apply_user_preset(preset, show_notice=False)
    assert getattr(config_from_window(window, strict=True), 'fluid_' + side).type == 'co2'
