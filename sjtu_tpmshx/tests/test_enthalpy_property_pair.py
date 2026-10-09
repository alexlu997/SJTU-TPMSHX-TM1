"""Multi-output CoolProp retains the single-property values and field layout."""
import numpy as np
import pytest

from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent


@pytest.mark.parametrize('fluid, pressure', [('sco2', 8e6), ('co2', 8e6), ('water', 2e5), ('air', 2e5)])
@pytest.mark.parametrize('layout', ['scalar', 'single', 'vector', '2d', '3d', 'strided'])
def test_cp_k_matches_separate_queries(fluid, pressure, layout, monkeypatch):
    values = np.linspace(300., 350., 24)
    temperatures = dict(scalar=310., single=np.array([310.]), vector=values,
                        **{'2d': values.reshape(6, 4), '3d': values.reshape(3, 4, 2),
                           'strided': values.reshape(3, 4, 2)[:, ::2, :]})[layout]
    shape = np.ascontiguousarray(temperatures).shape
    # Exercise a scalar pressure and a spatially varying broadcast pressure.
    for p in (pressure, pressure + np.arange(shape[-1]) * 1000.):
        expected = [ent._prop_field(key, temperatures, p, fluid) for key in ('C', 'L')]
        calls = []
        original = ent._PropsSI
        with monkeypatch.context() as patch:
            def query(*args):
                calls.append(args[0])
                return original(*args)
            patch.setattr(ent, '_PropsSI', query)
            actual = ent._prop_field(('C', 'L'), temperatures, p, fluid)
        assert calls == [('C', 'L')]
        for field, reference in zip(actual, expected):
            assert field.shape == shape and field.flags.c_contiguous
            np.testing.assert_array_equal(field, reference)


@pytest.mark.parametrize('temperature, pressure', [(np.nan, 8e6), (320., -1.)])
def test_pair_preserves_sco2_state_rejection(temperature, pressure):
    with pytest.raises(ValueError) as before:
        ent._prop_field('C', [temperature], pressure, 'sco2')
    with pytest.raises(type(before.value)) as after:
        ent._prop_field(('C', 'L'), [temperature], pressure, 'sco2')
    assert str(after.value) == str(before.value)


def test_pair_does_not_swallow_coolprop_error():
    for key in ('C', ('C', 'L')):
        with pytest.raises(ValueError):
            ent._prop_field(key, [-1.], 2e5, 'air')
