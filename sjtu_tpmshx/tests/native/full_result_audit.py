"""Physical acceptance checks for portable full-solver results."""


def physical_gates(result):
    assert result.run_status['converged'], result.run_status
    diagnostics = result.metadata['diagnostics']
    if result.metadata['thermal_mode'] == 'true_h':
        balance = diagnostics['true_h_balance']
        assert balance['converged']
        assert max(balance['enthalpy_clip_counts']['total']) == 0
        settings = balance['effective_settings']
        for name in ('coupled', 'equation'):
            assert balance[name+'_energy_balance']['ratio'] <= settings[name+'_energy_tol']
    else:
        balance = diagnostics['model_h_balance']
        if 'main' in balance:
            assert balance['main']['passed'] and balance['fine']['passed']
        else:
            assert balance['converged'] and balance['physical_boundary_complete']
            for side in balance['sides'].values():
                scale = side['strict_normalization_W']
                assert abs(side['residual_sum_W']) / scale < .01
                assert side['residual_max_abs_W'] * balance['cell_count'] / scale < .01
