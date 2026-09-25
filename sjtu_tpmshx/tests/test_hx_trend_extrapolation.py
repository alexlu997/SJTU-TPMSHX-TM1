"""Explicit geometry-transfer studies retain fixed factors and source limits."""
import numpy as np
import pytest

from sjtu_tpmshx.df_surrogate.experimental_correction import apply_correction, correction_scale


@pytest.mark.parametrize('fluid, speed, factor', [('air', 30., 2.649010286988306),
                                                ('water', .3, 4.198913430360186)])
def test_frozen_hx_transfer_is_explicit_and_does_not_reselect_a_geometry_fit(fluid, speed, factor):
    base_k, base_f = np.array([1e-8, 2e-8]), np.array([300., 600.])
    with pytest.raises(ValueError, match='requires'):
        apply_correction('Gyroid', fluid, 7., .6, base_k, base_f, speed)
    k, f, metadata = apply_correction('Gyroid', fluid, 7., .6, base_k, base_f, speed,
                                      allow_hx_extrapolation=True)
    np.testing.assert_array_equal(k, base_k)
    np.testing.assert_array_equal(f, base_f * factor)
    assert metadata['extrapolated'] is True
    assert metadata['transfer_policy'] == 'frozen-hx-7-0.6-trend'
    assert metadata['velocity_window_mps']['max'] < speed
    with pytest.raises(ValueError, match='matching D/G-7-6'):
        correction_scale('Gyroid', fluid, 6., .4, speed, allow_hx_extrapolation=True)


@pytest.mark.parametrize('fluid, topology, speed', [('sco2', 'Gyroid', 1.),
                                                  ('air', 'Diamond', 30.),
                                                  ('air', 'Gyroid', float('nan'))])
def test_transfer_does_not_relax_other_fluid_or_state_boundaries(fluid, topology, speed):
    with pytest.raises(ValueError):
        correction_scale(topology, fluid, 7., .6, speed, allow_hx_extrapolation=True)
