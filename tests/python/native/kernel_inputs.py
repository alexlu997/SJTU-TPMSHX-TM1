"""Read saved production cases for the full 2D and 3D C++ test bridges.

The functions only select inputs. The production stage validators and the
bridge tests keep all checks.
"""
from tm1.solvers import full_2d, full_3d
from tm1.data_types.portable_data import mutable_data


def _no_experiment(*_):
    raise AssertionError('the full 2D bridge cases do not use experimental drag')


def full_2d_record(case, *, pressure_shooting=True):
    """Return the 2D settings and grid that the saved production stage packs."""
    shape = full_2d.execution_grid(case)
    cfg, prepared, _ = full_2d.saved_inputs(case, shape, check_experiment=_no_experiment,
                                            port_windows_fit=None)
    cfg['p_in_shooting'] = pressure_shooting
    return dict(cfg=cfg, prepared=prepared, settings=full_2d._run_settings(cfg))


def full_3d_record(case, **controls):
    """Return mutable 3D parameters and the saved axis, opening and design data."""
    _, _, _, nu = full_3d.validate_saved_case(case)
    cfg = mutable_data(case.parameters)
    prepared = cfg.pop('prepared')
    prepared.update({'d' + axis: case.grid['d' + axis] for axis in 'xyz'}, design=case.design_fields)
    cfg['sco2_nu'] = nu
    cfg.update(controls)
    return cfg, prepared
