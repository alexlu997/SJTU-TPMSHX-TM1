"""Resolve recorded model versions in the process that evaluates them."""
from tm1.data_types.compute_config import Sco2NuConfig
from tm1.data_types.model_refs import ModelRef

from tm1.model_configs.model_parameters import MODEL_VERSIONS



def resolve_model(ref: ModelRef):
    """Return the provider for a recorded model name and version.

    Each registered spelling of CO2 requires the co2_fluid resource.
    """
    if not isinstance(ref, ModelRef):
        raise TypeError('model resource must be a ModelRef')
    if ref.name not in MODEL_VERSIONS or ref.version != MODEL_VERSIONS[ref.name]:
        raise ValueError(f'unknown model resource: {ref.name}@{ref.version}')
    parameters = dict(ref.parameters)
    if ref.name == 'quick_design':
        if parameters:
            raise ValueError('quick-design closure takes no fixed parameters')
        from tm1.model_configs.model_parameters import load_quick_design_parameters
        return load_quick_design_parameters()
    if ref.name in ('fluid', 'co2_fluid'):
        from .fluid_props import get
        if set(parameters) - {'fluid', 'sco2_nu'} or 'fluid' not in parameters:
            raise ValueError('fluid model requires fluid and optional sco2_nu parameters')
        provider = get(parameters['fluid'])
        required_resource = 'co2_fluid' if provider.name == 'co2' else 'fluid'
        if ref.name != required_resource:
            raise ValueError(
                f"Fluid {parameters['fluid']!r} requires resource {required_resource!r}. "
                f"The record specifies {ref.name!r}."
            )
        settings = parameters.get('sco2_nu')
        if settings is not None:
            settings = Sco2NuConfig(**settings).validate()
            return get(parameters['fluid'], sco2_nu=settings)
        return provider
    if ref.name == 'co2_geometry':
        from .co2_correlations import geometry as co2_geometry
        if parameters:
            raise ValueError('CO2 geometry resource takes no fixed parameters')
        return co2_geometry
    if ref.name == 'geometry':
        from .tpms_props import geometry
        if parameters:
            raise ValueError('geometry resource takes no fixed parameters')
        return geometry
    if ref.name == 'darcy_forchheimer':
        from .df_surrogate.full_core_3cell_fixed_v2 import FullCore3CellFixedDFV2
        if set(parameters) != {'topology'}:
            raise ValueError('Darcy-Forchheimer resource requires topology')
        return FullCore3CellFixedDFV2(parameters['topology'])
    raise ValueError(f'No provider for model resource {ref.name}@{ref.version}')
