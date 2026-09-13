"""Input sections and physical ports survive application configuration boundaries."""
from dataclasses import replace
import json

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, GeometryConfig, PartialBCConfig, SolverConfig,
)
from sjtu_tpmshx.models.screening import DEFAULT_CONFIG, validate_screening_config
from sjtu_tpmshx.optimization.evaluator import _compute_cfg_to_evaluator_dict
from sjtu_tpmshx.optimization.evaluator_3d import _compute_cfg_to_evaluator_dict_3d
from sjtu_tpmshx.preprocess.api import prepare_screening_2d
from sjtu_tpmshx.models.continuous_field import uniform_field


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


def _config():
    return ComputeConfig(geometry=GeometryConfig(L_dom_m=.1, H_dom_m=.05),
                         solver=SolverConfig(Nx=10, Ny=10),
                         bc_A=PartialBCConfig(dir=0, in_ctr=.025, in_w=.014,
                                              out_ctr=.03, out_w=.02),
                         bc_B=PartialBCConfig(dir=3))


def test_typed_ports_reach_2d_preparation_and_3d_rejection():
    source = _config()
    mapped = _compute_cfg_to_evaluator_dict(source)
    np.testing.assert_allclose(mapped['ports_A'], (.018, .032, .02, .04))
    assert mapped['ports_B'] is None
    fc = uniform_field(6., .4, 'Gyroid', 16., .1, .05)
    case = prepare_screening_2d(None, mapped, fc=fc, case_id='typed-port')
    flow = case.parameters['flow']['A']['initial']
    assert flow['inlet_hi'] - flow['inlet_lo'] == pytest.approx(.014)
    source = replace(source, geometry=replace(source.geometry, Lz_m=.03),
                     solver=replace(source.solver, Nz=3))
    with pytest.raises(ValueError, match='full-face ports only'):
        validate_screening_config({**DEFAULT_CONFIG, **_compute_cfg_to_evaluator_dict_3d(source)}, dimension=3)


def test_explicit_fullface_and_z_partial_ports():
    source = _config()
    source.bc_A = PartialBCConfig(dir=0, in_ctr=.025, in_w=.05,
                                 out_ctr=.025, out_w=.05)
    source.geometry.Lz_m = .03
    source.solver.Nz = 3
    assert _compute_cfg_to_evaluator_dict_3d(source)['ports_A'] is None
    source.bc_A.in_z_ctr, source.bc_A.in_z_w = .015, .03
    assert _compute_cfg_to_evaluator_dict_3d(source)['ports_A'] is None
    source.bc_A.out_z_ctr, source.bc_A.out_z_w = .015, .03
    assert _compute_cfg_to_evaluator_dict_3d(source)['ports_A'] is None
    source.bc_A.in_z_ctr = source.bc_A.out_z_ctr = .015
    source.bc_A.in_z_w = source.bc_A.out_z_w = .01
    with pytest.raises(ValueError, match='full-face ports only'):
        _compute_cfg_to_evaluator_dict_3d(source)
