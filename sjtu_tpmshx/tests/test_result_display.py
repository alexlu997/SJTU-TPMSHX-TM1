"""Keep display values and recorded field descriptions stable."""
import numpy as np
import pytest

from sjtu_tpmshx.result_display import describe_fields, display_fields_2d


@pytest.fixture
def inputs():
    pulse = np.array([[1., 0., 0.], [0., 0., 0.]])
    temperature = [pulse + value for value in (300., 400., 350.)]
    pressure = [pulse + value for value in (1e5, 2e5)]
    velocity = [(pulse + 1., pulse + 2.), (pulse + 3., pulse + 4.)]
    openings = {side: {port + '_profile_frac': np.ones(3) for port in ('in', 'out')}
                for side in 'AB'}
    return temperature, pressure, velocity, openings


@pytest.mark.parametrize('fraction', [1., .99])
def test_full_ports_keep_aliases_without_display_velocity_copies(inputs, fraction):
    temperature, pressure, velocity, openings = inputs
    for ports in openings.values():
        for profile in ports.values():
            profile[:] = fraction
    fields = display_fields_2d(*inputs)
    assert list(fields) == ['Ta_display', 'Tb_display', 'Ts_display',
                            'P_fA_display', 'ucA', 'vcA', 'P_fB_display', 'ucB', 'vcB']
    for name, source in zip(('Ta', 'Tb', 'Ts'), temperature):
        assert fields[name + '_display'] is source
    for index, side in enumerate('AB'):
        assert fields['P_f' + side + '_display'] is pressure[index]
        for name, source in zip(('uc', 'vc'), velocity[index]):
            assert fields[name + side] is source


@pytest.mark.parametrize('sides', [('A',), ('B',), ('A', 'B')])
@pytest.mark.parametrize('port', ['in', 'out'])
def test_partial_ports_preserve_raw_fields_and_existing_smoothing(inputs, sides, port):
    temperature, pressure, velocity, openings = inputs
    raw = temperature + pressure + [field for pair in velocity for field in pair]
    before = [field.copy() for field in raw]
    for side in sides:
        openings[side][port + '_profile_frac'][0] = .98
    fields = display_fields_2d(*inputs)
    # Fixed reference values use the existing sigma 1.5 and sigma 2 filters.
    thermal_pulse = np.array([[.2550251086951181, .17577546831490007, .1003485577439484],
                              [.22511331572921658, .15515883396222027, .08857871555459672]])
    flow_pulse = np.array([[.19597114142770147, .16784213577509446, .1397834680485025],
                           [.19317184505031967, .16544464051520907, .1377867691831729]])
    for name, offset in zip(('Ta', 'Tb', 'Ts'), (300., 400., 350.)):
        np.testing.assert_allclose(fields[name + '_display'], thermal_pulse + offset,
                                   rtol=0., atol=1e-12)
    for index, side in enumerate('AB'):
        if side in sides:
            np.testing.assert_allclose(fields['P_f' + side + '_display'],
                                       thermal_pulse + (index + 1) * 1e5, rtol=0., atol=6e-11)
        else:
            assert fields['P_f' + side + '_display'] is pressure[index]
        for component, name in enumerate(('uc', 'vc')):
            assert fields[name + side] is velocity[index][component]
            key = name + side + '_display'
            if side in sides:
                np.testing.assert_allclose(fields[key], flow_pulse + index * 2 + component + 1,
                                           rtol=0., atol=1e-14)
            else:
                assert key not in fields
    for field, source in zip(raw, before):
        np.testing.assert_array_equal(field, source)


@pytest.mark.parametrize('dimension,expected', [
    (2, {
        'Ta': ('K', 'raw last main thermal return'),
        'Tb': ('K', 'raw last main thermal return'),
        'Ts': ('K', 'raw last main thermal return'),
        'Ta_display': ('K', 'display'),
        'P_thermal_A': ('Pa', 'last thermal input'),
        'P_report_B': ('Pa', 'final flow/report'),
        'P_fA_display': ('Pa', 'display'),
        'h_vA': ('W/(m3 K)', 'last thermal input'),
        'h_vB': ('W/(m3 K)', 'last thermal input'),
        'K_ss': ('W/(m K)', 'last thermal input'),
        'ucA': ('m/s', 'final flow/report'),
        'vcB': ('m/s', 'final flow/report'),
        'ucA_display': ('m/s', 'display'),
        'vcB_display': ('m/s', 'display'),
    }),
    (3, {
        'Ta': ('K', 'last thermal solve'),
        'Tb': ('K', 'last thermal solve'),
        'Ts': ('K', 'last thermal solve'),
        'Ts_display': ('K', 'display'),
        'P_thermal_B': ('Pa', 'last thermal solve'),
        'P_report_A': ('Pa', 'final SIMPLE flow'),
        'P_gauge_B': ('Pa', 'final SIMPLE flow'),
        'P_fB_display': ('Pa', 'display'),
        'h_vA': ('W/(m3 K)', 'last thermal solve'),
        'h_vB': ('W/(m3 K)', 'last thermal solve'),
        'K_ss': ('W/(m K)', 'last thermal solve'),
        'ucA': ('m/s', 'final flow/report'),
        'vcB': ('m/s', 'final flow/report'),
        'wcA': ('m/s', 'final flow/report'),
        'vmag_B': ('m/s', 'final flow/report'),
    }),
])
def test_field_descriptions_keep_units_axes_and_distinct_states(dimension, expected):
    metadata = describe_fields(expected, dimension)
    assert list(metadata) == list(expected)
    for name, (unit, state) in expected.items():
        assert metadata[name] == dict(unit=unit, state=state, location='cell',
                                      axes=('x', 'y') if dimension == 2 else ('x', 'y', 'z'))
