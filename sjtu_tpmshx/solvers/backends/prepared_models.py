"""Shared resource checks; each input builder keeps its validation order."""
from sjtu_tpmshx.models.catalog import resolve_model


def resolve_models(case):
    roles = case.metadata['model_roles']
    if set(roles) != {'fluid_A', 'fluid_B', 'geometry', 'darcy_forchheimer'} or sorted(roles.values()) != list(range(len(case.model_refs))):
        raise ValueError(f"{case.grid['dimension']}D model roles must account for every recorded resource")
    return {role: resolve_model(case.model_refs[index]) for role, index in roles.items()}


def validate_fluid(case, providers, side, expected):
    if providers['fluid_' + side].name != expected:
        article = 'its ' if case.grid['dimension'] == 2 else ''
        raise ValueError(f'prepared fluid {side} and {article}model resource disagree')


def validate_nu_settings(case, side, expected):
    ref = case.model_refs[case.metadata['model_roles']['fluid_' + side]]
    if dict(ref.parameters['sco2_nu']) != expected:
        raise ValueError(f'prepared Nu settings and fluid {side} resource disagree')


def validate_topology(case, expected):
    ref = case.model_refs[case.metadata['model_roles']['darcy_forchheimer']]
    if ref.parameters['topology'] != expected:
        raise ValueError('prepared topology and Darcy-Forchheimer resource disagree')
