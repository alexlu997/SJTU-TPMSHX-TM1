"""Tests for the ``domain.validator`` field-unit helpers added in
audit C5 Phase 4 (L-b, 2026-05-28).

Covers:

- ``FIELD_UNITS`` / ``POSITIVE_FIELDS`` / ``COUNT_TOKEN_WHITELIST``
  module constants — moved here from ``Main_Menu._FIELD_UNITS``.
- ``format_unit_value`` — display formatter (count vs scientific
  vs compact).
- ``parse_field_value`` — one-shot lookup → conversion that the
  unified ``_make_field_handler`` calls.
"""
from __future__ import annotations

import pytest

from sjtu_tpmshx.domain.validator import (
    FIELD_UNITS,
    POSITIVE_FIELDS,
    COUNT_TOKEN_WHITELIST,
    format_unit_value,
    parse_field_value,
)


def test_field_units_covers_pipe_widgets():
    """All 2D + 3D pipe-BC widgets carry a length-m mapping."""
    for side in ('A', 'B'):
        for slot in ('in_ctr', 'in_w', 'out_ctr', 'out_w'):
            attr = f'le_pipe{side}_{slot}'
            assert FIELD_UNITS[attr] == ('length', 'm'), attr


def test_field_units_lcell_and_t_are_mm():
    assert FIELD_UNITS['le_Lcell'] == ('length', 'mm')
    assert FIELD_UNITS['le_t'] == ('length', 'mm')


def test_field_units_counts_have_no_target_unit():
    for attr in ('le_Nx', 'le_Ny', 'le_Nz'):
        fam, target = FIELD_UNITS[attr]
        assert fam == 'count'
        assert target is None


def test_positive_fields_is_superset_of_field_units_intersect_positive():
    """Every numeric-positive widget in FIELD_UNITS appears in
    POSITIVE_FIELDS (counts + temps included)."""
    expected_positive_overlap = {
        'le_L', 'le_H', 'le_Lz', 'le_Lcell', 'le_t',
        'le_uA', 'le_uB',
        'le_TinA', 'le_TinB', 'le_PinA', 'le_PinB',
        'le_Nx', 'le_Ny', 'le_Nz',
    }
    assert expected_positive_overlap.issubset(POSITIVE_FIELDS)


def test_positive_fields_has_le_rho_s_and_le_ks():
    """Non-FIELD_UNITS positives (no unit parsing, just positive
    validation) survive in POSITIVE_FIELDS."""
    assert 'le_rho_s' in POSITIVE_FIELDS
    assert 'le_ks' in POSITIVE_FIELDS


def test_count_token_whitelist_known_tokens():
    for tok in ('cells', 'cell', 'pts', 'points', 'nodes'):
        assert tok in COUNT_TOKEN_WHITELIST


# ── format_unit_value ───────────────────────────────────────────────


def test_format_count_returns_int_str():
    assert format_unit_value(30.0, 'count') == '30'
    assert format_unit_value(30.4, 'count') == '30'
    assert format_unit_value(30.6, 'count') == '31'


def test_format_compact_mid_range():
    """Values in [0.01, 1000) use 4g compact format."""
    assert format_unit_value(0.005, 'length').startswith('0.005')
    assert format_unit_value(7.0, 'length') == '7'


def test_format_scientific_outside_mid_range():
    """Above 1000 or below 0.01 use 6g (scientific allowed)."""
    out = format_unit_value(2000.0, 'pressure')
    assert '2000' in out or '2e' in out  # 2000 or 2e+03


# ── parse_field_value ───────────────────────────────────────────────


def test_parse_5mm_into_le_L_meters():
    assert parse_field_value('le_L', 5.0, 'mm') == pytest.approx(0.005)


def test_parse_7mm_into_le_Lcell_stays_mm():
    """Lcell is mm-native; "7 mm" returns 7.0 (no further conversion)."""
    assert parse_field_value('le_Lcell', 7.0, 'mm') == pytest.approx(7.0)


def test_parse_count_field_with_whitelisted_unit():
    assert parse_field_value('le_Nx', 30.0, 'cells') == pytest.approx(30.0)
    assert parse_field_value('le_Nx', 30.0, 'nodes') == pytest.approx(30.0)


def test_parse_count_field_rejects_unknown_unit():
    assert parse_field_value('le_Nx', 30.0, 'm') is None
    assert parse_field_value('le_Nx', 30.0, 'lbs') is None


def test_parse_unknown_field_returns_none():
    """Field attr not in FIELD_UNITS → return None gracefully."""
    assert parse_field_value('le_unknown', 5.0, 'mm') is None


def test_parse_temp_field_honours_temp_unit():
    """``le_TinA`` is temp family; "25 °C" with temp_unit='K' returns
    Kelvin."""
    val_K = parse_field_value('le_TinA', 25.0, '°C', temp_unit='K')
    assert val_K == pytest.approx(298.15)
    # And vice versa.
    val_C = parse_field_value('le_TinA', 298.15, 'K', temp_unit='C')
    assert val_C == pytest.approx(25.0)


def test_parse_speed_kph_to_mps():
    """``le_uA`` is m/s native; "3.6 kph" returns 1.0 m/s."""
    val = parse_field_value('le_uA', 3.6, 'km/h')
    assert val == pytest.approx(1.0, rel=1e-3)


def test_parse_pressure_bar_to_pa():
    """``le_PinA`` is Pa native; "1 bar" returns 100000 Pa."""
    val = parse_field_value('le_PinA', 1.0, 'bar')
    assert val == pytest.approx(1e5)
