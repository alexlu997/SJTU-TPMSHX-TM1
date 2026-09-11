"""The backend returns physical zone boundaries and area-weighted statistics."""
import numpy as np
import pytest

from sjtu_tpmshx.models.zone_config import Zone, ZoneConfig
from sjtu_tpmshx.solvers.backends.python.two_d.coupling import _zone_statistics_2d


@pytest.mark.parametrize('axis', [None, 'x', 'y', 'grid'])
def test_zone_result(axis):
    zones = [Zone('first', 0., .5, 7., .4), Zone('second', .5, 1., 7., .4)]
    config = ZoneConfig(zones=zones, tpms_type='Gyroid', k_s=16.)
    design = dict(zone_id=np.array([[0, 0], [1, 1]]),
                  x_bounds=[.5], y_bounds=[.25],
                  grid_cells=[dict(y0=z.y_frac_start, y1=z.y_frac_end,
                                   L=z.L_mm, t=z.t_mm) for z in zones])
    temperature = np.array([[300., 340.], [400., 420.]])
    result = _zone_statistics_2d(
        axis, config if axis else None, design if axis else None, 2., 4.,
        np.array([.5, 1.5]), np.array([1., 3.]),
        temperature, temperature + 10., temperature + 20.)
    if axis is None:
        assert result is None
        return
    assert result['axis_dir'] == axis
    assert [s['n_cells'] for s in result['stats']] == [2, 2]
    assert [s['Ta_mean'] for s in result['stats']] == [330., 415.]
    assert [s['Tb_mean'] for s in result['stats']] == [340., 425.]
    assert [s['Ts_mean'] for s in result['stats']] == [350., 435.]
    assert result['boundaries'] == ([] if axis == 'grid' else [2. if axis == 'y' else 1.])
    assert result['boundaries_x'] == ([1.] if axis == 'grid' else None)
    assert result['boundaries_y'] == ([1.] if axis == 'grid' else None)
