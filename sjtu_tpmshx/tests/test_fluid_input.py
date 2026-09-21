"""Auto-fill messages use the selected fluid's real correlation window."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QLabel

from sjtu_tpmshx.ui.mixins import fluid_input


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('label,fluid,bounds', [
    ('Air', 'air', (400., 16000.)),
    ('Water', 'water', (90., 51000.)),
    ('sCO₂', 'sco2', (2600., 128000.)),
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
        for name in ('rho', 'Re', 'Nu', 'dPL'):
            setattr(window, '_v_' + name + which, QLabel())
    styles = {'VAL': 'color: black;', 'VAL_WARN': 'color: red;'}
    monkeypatch.setattr(fluid_input, '_fluid_styles', lambda: styles)
    properties = dict(A_0=2., H_sf=3., Nu=4., dP_per_L=5.,
                      mu=1e-5, K_ff=6., rho=7.)
    compute = Mock()
    monkeypatch.setattr(fluid_input, 'tpms_compute', compute)
    lo, hi = bounds
    for re, tag in ((lo - 1, f'  (< {lo:g}!)'), (lo, ''),
                    (hi, ''), (hi + 1, f'  (> {hi:g}!)')):
        compute.return_value = dict(properties, Re=re)
        fluid_input.FluidInputMixin._auto_fill_fluid(window, side)
        shown = getattr(window, '_v_Re' + side)
        assert shown.text() == f'{re:.1f}{tag}'
        assert shown.styleSheet() == styles['VAL_WARN' if tag else 'VAL']
        assert f'Re={re:.0f}{tag}  Nu=' in status.showMessage.call_args.args[0]
        assert compute.call_args.kwargs['fluid_type'] == fluid
        assert getattr(window, '_h_v' + side) == 6.
