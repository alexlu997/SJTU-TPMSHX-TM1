"""Input mutation must not change an already constructed continuous field."""
import numpy as np
import pytest

from sjtu_tpmshx.models.continuous_field import ContinuousFieldConfig, from_decision_vector


def test_asymmetric_decision_input_cannot_diverge_from_cached_xy_field():
    original = np.r_[np.linspace(5., 7., 16), np.linspace(.35, .5, 16)]
    decision = np.repeat(original, 2)[::2]  # float64 noncontiguous input view
    field = from_decision_vector(decision, 'Gyroid', 17., .1, .05,
                                 n_ctrl_x=4, n_ctrl_y=4, symmetric_y=False)
    before = field.evaluate_grid(8, 8)
    decision[0], decision[16] = 8., .6
    np.testing.assert_array_equal(field.L_ctrl, original[:16].reshape(4, 4))
    np.testing.assert_array_equal(field.t_ctrl, original[16:].reshape(4, 4))
    assert not np.shares_memory(field.L_ctrl, decision)
    assert not np.shares_memory(field.t_ctrl, decision)
    for current, expected in zip(field.evaluate_grid(8, 8), before):
        np.testing.assert_array_equal(current, expected)
    rebuilt = from_decision_vector(decision, 'Gyroid', 17., .1, .05,
                                    n_ctrl_x=4, n_ctrl_y=4, symmetric_y=False)
    for changed, expected in zip(rebuilt.evaluate_grid(8, 8), before):
        assert not np.array_equal(changed, expected)


@pytest.mark.parametrize('dimension', [2, 3])
def test_direct_constructor_owns_all_control_axes_and_values(dimension):
    lengths = (.1, .05, .04)[:dimension]
    axes = [np.linspace(0., length, 4) for length in lengths]
    shape = (4,) * dimension
    cells = np.linspace(5., 7., 4**dimension).reshape(shape)
    walls = np.linspace(.35, .5, 4**dimension).reshape(shape)
    field = ContinuousFieldConfig(axes[0], axes[1], cells, walls, 'Gyroid',
        17., *lengths[:2], **(dict(ctrl_z=axes[2], Lz_domain=lengths[2])
                            if dimension == 3 else {}))
    sample = field.evaluate_grid if dimension == 2 else field.evaluate_volume
    before = sample(*((8,) * dimension))
    supplied = [*axes, cells, walls]
    owned = [field.ctrl_x, field.ctrl_y]
    if dimension == 3:
        owned.append(field.ctrl_z)
    owned += [field.L_ctrl, field.t_ctrl]
    snapshots = [values.copy() for values in supplied]
    for axis in axes:
        axis[1] *= .9  # keep the modified source axis valid and ordered
    cells.flat[0], walls.flat[0] = 8., .6
    for current, source, expected in zip(owned, supplied, snapshots):
        np.testing.assert_array_equal(current, expected)
        assert not np.shares_memory(current, source)
    for current, expected in zip(sample(*((8,) * dimension)), before):
        np.testing.assert_array_equal(current, expected)
        assert current.flags.writeable
