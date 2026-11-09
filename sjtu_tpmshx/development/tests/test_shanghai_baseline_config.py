"""Test the Shanghai baseline config loader + schema invariants.

Per audit Item 3 / AR8 (2026-05-28).
"""


def test_load_returns_dict():
    from sjtu_tpmshx.shared.configs import load_shanghai_baseline
    cfg = load_shanghai_baseline()
    assert isinstance(cfg, dict)


def test_schema_required_keys():
    from sjtu_tpmshx.shared.configs import load_shanghai_baseline
    cfg = load_shanghai_baseline()
    assert 'geometry' in cfg
    assert 'domain' in cfg
    for key in ('tpms', 'L_cell_mm', 't_wall_mm', 'k_s_W_mK'):
        assert key in cfg['geometry'], f"missing geometry.{key}"
    for key in ('L_dom_m', 'H_dom_m', 'Lz_m', 'n_units', 'a_flow_per_unit_m2'):
        assert key in cfg['domain'], f"missing domain.{key}"


def test_canonical_values_pinned():
    """Pin the canonical Shanghai values. Future deliberate changes update this test."""
    from sjtu_tpmshx.shared.configs import load_shanghai_baseline
    cfg = load_shanghai_baseline()
    assert cfg['geometry']['tpms'] == 'Gyroid'
    assert cfg['geometry']['L_cell_mm'] == 7.0
    assert cfg['geometry']['t_wall_mm'] == 0.6
    assert cfg['geometry']['k_s_W_mK'] == 16.0
    assert cfg['domain']['L_dom_m'] == 0.182
    assert cfg['domain']['H_dom_m'] == 0.042
    assert cfg['domain']['Lz_m'] == 0.042
    assert cfg['domain']['n_units'] == 36
    assert abs(cfg['domain']['a_flow_per_unit_m2'] - 1.80565e-5) < 1e-12


def test_types_correct():
    from sjtu_tpmshx.shared.configs import load_shanghai_baseline
    cfg = load_shanghai_baseline()
    assert isinstance(cfg['geometry']['tpms'], str)
    assert isinstance(cfg['geometry']['L_cell_mm'], (int, float))
    assert isinstance(cfg['domain']['L_dom_m'], (int, float))
    assert isinstance(cfg['domain']['n_units'], int)


def test_idempotent_calls_equal():
    """Two calls return equal dicts (JSON re-load is deterministic)."""
    from sjtu_tpmshx.shared.configs import load_shanghai_baseline
    cfg1 = load_shanghai_baseline()
    cfg2 = load_shanghai_baseline()
    assert cfg1 == cfg2
