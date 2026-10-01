"""Input sections preserve their meaning at configuration boundaries."""
import json

import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig


@pytest.mark.parametrize('payload', [
    {'geometry': {'L_dom_m': .1, 'H_dom_m': .05, 'Lz_m': .07}},
    {'flags': {'wall_refine_3d': False}},
    {'envelope_mode': 'warn'},
    {'df_mode': 'experimental'},
])
def test_sparse_config_has_same_meaning_as_explicit_defaults(payload, tmp_path):
    path = tmp_path / 'case.json'
    path.write_text(json.dumps(payload))
    # Adding an otherwise empty section must not change format or semantics.
    try:
        expected = ComputeConfig.from_dict({'fluid_A': {}, **payload})
    except ValueError as exc:
        with pytest.raises(ValueError) as actual:
            ComputeConfig.from_json(path)
        assert str(actual.value) == str(exc)
    else:
        assert ComputeConfig.from_json(path) == expected


@pytest.mark.parametrize('payload', [
    {'fluid_A': {}, 'domain': {'L_dom_m': .1}},
    {'geometry': {'L_dom_m': .1}, 'domain': {'L_dom_m': .2}},
    {'geometery': {'L_dom_m': .1}},
])
def test_ambiguous_or_unknown_layout_is_rejected(payload):
    with pytest.raises(ValueError, match='unknown|canonical|mixed'):
        ComputeConfig.from_dict(payload)
