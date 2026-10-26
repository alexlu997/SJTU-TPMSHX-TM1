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
    return temperature, pressure, velocity


def test_display_aliases_keep_original_values_without_velocity_copies(inputs):
    temperature, pressure, velocity = inputs
    sources = temperature + pressure + [field for pair in velocity for field in pair]
    before = [field.copy() for field in sources]
    fields = display_fields_2d(*inputs)
    assert list(fields) == ['Ta_display', 'Tb_display', 'Ts_display',
                            'P_fA_display', 'ucA', 'vcA', 'P_fB_display', 'ucB', 'vcB']
    for name, source in zip(('Ta', 'Tb', 'Ts'), temperature):
        assert fields[name + '_display'] is source
    for index, side in enumerate('AB'):
        assert fields['P_f' + side + '_display'] is pressure[index]
        for name, source in zip(('uc', 'vc'), velocity[index]):
            assert fields[name + side] is source
    for field, source in zip(sources, before):
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
