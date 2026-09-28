"""Inlet-capacity geometry uses the full builders' fields without flow properties."""
from functools import partial

import numpy as np
import pytest

from sjtu_tpmshx.models import nu_correlations, sigmoid_field, tpms_calc
from sjtu_tpmshx.models.zone_config import Zone, ZoneConfig


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
def test_geometry_matches_full_builder_without_evaluating_flow_properties(mode, monkeypatch):
    nx, ny, length, height = 5, 4, .08, .06
    dx = np.arange(1., nx + 1) * length / sum(range(1, nx + 1))
    dy = np.arange(1., ny + 1) * height / sum(range(1, ny + 1))
    widths = dict(dx_arr=dx, dy_arr=dy)
    if mode in ('x', 'y'):
        zones = ZoneConfig([Zone('first', 0., .4, 4., .3),
                            Zone('last', .4, 1., 8., .6)], 'Gyroid', 15.)
        zones.compute_properties(5., 3., 380., 310.)
        args = (nx, ny, length if mode == 'x' else height, mode)
        full = zones.build_structured_arrays(*args, **widths)
        for zone in zones.zones:
            zone.props_A.clear()
            zone.props_B.clear()
        geometry = partial(zones.build_structured_geometry, *args, **widths)
    elif mode == 'grid':
        # Uncovered cells keep the first rectangle; physical cell centres
        # determine membership on this nonuniform grid.
        cells = [dict(x0=0., x1=.4, y0=0., y1=1., L=4., t=.3),
                 dict(x0=.5, x1=1., y0=.25, y1=.9, L=8., t=.6)]
        args = (nx, ny, cells, 'Gyroid', 15.)
        full = ZoneConfig.build_grid_arrays(*args, 5., 3., 380., 310., **widths)
        geometry = partial(ZoneConfig.build_grid_geometry, *args, **widths)
    else:
        controls = np.tile([3., .2, 6., .4, 9., .7], 6)
        lut = sigmoid_field.get_geometry_lut('Gyroid', n_L=3, n_t=2, N=32)
        args = (controls, 6., .4, .25, .3, nx, ny, length, height, 'Gyroid', 15.)
        full = sigmoid_field.build_continuous_arrays(
            *args, 5., 3., 380., 310., lut, allow_extrap=False, **widths)
        geometry = partial(sigmoid_field.build_continuous_geometry,
                           *args, lut, allow_extrap=False, **widths)

    def forbidden(*args, **kwargs):
        pytest.fail('Geometry preparation must not evaluate a velocity-dependent closure')

    monkeypatch.setattr(tpms_calc, 'compute', forbidden)
    monkeypatch.setattr(nu_correlations, 'nu_vec', forbidden)
    actual = geometry()
    assert not {'K_ffA_arr', 'K_ffB_arr', 'h_vA_arr', 'h_vB_arr'} & actual.keys()
    for key in ('zone_id', 'L_field', 't_field', 'eps_arr', 'eps_f_arr',
                'K_ss_arr', 'r_h_arr', 'A_0_arr'):
        np.testing.assert_array_equal(actual[key], full[key])
    assert actual['axis'] == full['axis']
    if mode == 'sigmoid':
        # Prove that the guard patches the symbol consumed by the full builder.
        with pytest.raises(pytest.fail.Exception, match='velocity-dependent closure'):
            sigmoid_field.build_continuous_arrays(
                *args, 5., 3., 380., 310., lut, allow_extrap=False, **widths)
