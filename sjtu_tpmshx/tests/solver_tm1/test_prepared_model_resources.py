"""Prepared resources keep their identity and dimension-specific check order."""
from dataclasses import replace

import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.backends import prepared_2d, prepared_3d


@pytest.fixture(params=[2, 3])
def prepared(request):
    dimension = request.param
    config = ComputeConfig()
    config.geometry.Lz_m = .03 if dimension == 3 else None
    config.solver.Nx, config.solver.Ny, config.solver.Nz = 6, 5, 4 if dimension == 3 else 1
    case = prepare_case(config, case_id='model-resources')
    builder = prepared_2d if dimension == 2 else prepared_3d
    return case, builder.build_execution_inputs


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'unassigned'])
def test_model_roles_account_for_every_resource(prepared, fault):
    case, build = prepared
    roles = dict(case.metadata['model_roles'])
    refs = list(case.model_refs)
    if fault == 'missing':
        roles.pop('geometry')
    elif fault == 'duplicate':
        roles['fluid_B'] = roles['fluid_A']
    else:
        refs.append(refs[0])
    invalid = replace(case, model_refs=refs, metadata={**case.metadata, 'model_roles': roles})
    with pytest.raises(ValueError, match=f"{case.grid['dimension']}D model roles must account"):
        build(invalid)


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('fault', ['fluid', 'nu', 'both'])
def test_fluid_identity_and_nu_checks_keep_their_order(prepared, side, fault):
    case, build = prepared
    dimension = case.grid['dimension']
    parameters = mutable_data(case.parameters)
    if fault in ('fluid', 'both'):
        parameters[('fluid_' if dimension == 2 else 'fluid_type_') + side] = 'water'
    refs = list(case.model_refs)
    if fault in ('nu', 'both'):
        index = case.metadata['model_roles']['fluid_' + side]
        ref = refs[index]
        nu = {**ref.parameters['sco2_nu'], 'alpha_G': 1.1}
        refs[index] = replace(ref, parameters={**ref.parameters, 'sco2_nu': nu})
    invalid = replace(case, parameters=parameters, model_refs=refs)
    nu_first = fault == 'nu' or (fault == 'both' and dimension == 2)
    message = (f'prepared Nu settings and fluid {side} resource disagree' if nu_first else
               f"prepared fluid {side} and {'its ' if dimension == 2 else ''}model resource disagree")
    with pytest.raises(ValueError) as caught:
        build(invalid)
    assert str(caught.value) == message


def test_topology_must_match_recorded_resource(prepared):
    case, build = prepared
    topology = 'Diamond' if case.parameters['tpms_type'] == 'Gyroid' else 'Gyroid'
    invalid = replace(case, parameters={**case.parameters, 'tpms_type': topology})
    with pytest.raises(ValueError, match='prepared topology and Darcy-Forchheimer resource disagree'):
        build(invalid)


@pytest.mark.parametrize('prepared', [3], indirect=True)
def test_3d_axis_checks_stay_between_each_sides_resource_checks(prepared):
    case, build = prepared
    parameters = mutable_data(case.parameters)
    parameters['prepared']['axes']['A']['stream_real_axis'] = -1
    parameters['fluid_type_B'] = 'water'
    with pytest.raises(ValueError, match='prepared fluid A direction and axis map disagree'):
        build(replace(case, parameters=parameters))


def test_resource_order_follows_roles_not_tuple_positions(prepared):
    case, build = prepared
    refs = tuple(reversed(case.model_refs))
    roles = {role: len(refs) - 1 - index for role, index in case.metadata['model_roles'].items()}
    reordered = replace(case, model_refs=refs, metadata={**case.metadata, 'model_roles': roles})
    actual = build(reordered)[0]['_input_resolution']
    expected = build(case)[0]['_input_resolution']
    resources = actual.pop('resources')
    expected.pop('resources')
    assert actual == expected
    assert {role: resource['model_ref'] for role, resource in resources.items()} == roles
