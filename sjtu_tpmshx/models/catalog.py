"""Resolve recorded model versions in the process that evaluates them."""
from sjtu_tpmshx.domain.compute_config import Sco2NuConfig
from sjtu_tpmshx.domain.model_refs import ModelRef

# These versions identify the extracted V2 formulas, not experimental accuracy.
MODEL_VERSIONS = {
    'fluid': 'v2-5f1cafb',
    'geometry': 'v2-5f1cafb',
    'darcy_forchheimer': 'cfd_full_core_3cell_fixed_v2',
}


def resolve_model(ref: ModelRef):
    """Construct a runtime provider; unknown versions never select a default."""
    if not isinstance(ref, ModelRef):
        raise TypeError('model resource must be a ModelRef')
    if ref.name not in MODEL_VERSIONS or ref.version != MODEL_VERSIONS[ref.name]:
        raise ValueError(f'unknown model resource: {ref.name}@{ref.version}')
    parameters = dict(ref.parameters)
    if ref.name == 'fluid':
        from .fluid_props import get
        if set(parameters) - {'fluid', 'sco2_nu'} or 'fluid' not in parameters:
            raise ValueError('fluid model requires fluid and optional sco2_nu parameters')
        settings = parameters.get('sco2_nu')
        if settings is not None:
            settings = Sco2NuConfig(**settings).validate()
        return get(parameters['fluid'], sco2_nu=settings)
    if ref.name == 'geometry':
        from .tpms_props import geometry
        if parameters:
            raise ValueError('geometry resource takes no fixed parameters')
        return geometry
    from sjtu_tpmshx.df_surrogate.full_core_3cell_fixed_v2 import FullCore3CellFixedDFV2
    if set(parameters) != {'topology'}:
        raise ValueError('Darcy-Forchheimer resource requires topology')
    return FullCore3CellFixedDFV2(parameters['topology'])
