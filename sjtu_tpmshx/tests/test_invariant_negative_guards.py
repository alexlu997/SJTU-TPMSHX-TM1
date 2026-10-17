"""Roughness correction must not count the calibrated friction twice."""



# ── 1. ε-once contract: shared preparation callers ──────────────








# ── 2. massflux_inlet defaults ON ───────────────────────────────────






# ── 3. norris_1a friction no-op ─────────────────────────────────────


def test_norris_1a_friction_is_exactly_noop():
    """norris_1a remains a friction no-op. The original ROUGH-X guard prevented
    double-counting roughness in the historical gamma_df calibration; that
    model is now retired, while the no-op contract remains unchanged."""
    from sjtu_tpmshx.models.roughness import f_enhancement, nu_extra_factor
    for Re in (500.0, 2000.0, 8000.0, 16000.0):
        assert f_enhancement(Re, mode='norris_1a') == 1.0
        assert f_enhancement(Re, mode='baseline') == 1.0
        assert nu_extra_factor(Re, mode='norris_1a') == 1.0
