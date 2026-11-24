"""Recorded versions resolve existing providers without fallback or refitting."""
import numpy as np
import pytest

from sjtu_tpmshx.data_types.model_refs import ModelRef
from sjtu_tpmshx.physical_models.catalog import MODEL_VERSIONS, resolve_model


def test_resolve_each_registered_resource():
    from sjtu_tpmshx.model_configs.model_parameters import load_quick_design_parameters
    from sjtu_tpmshx.physical_models.co2_correlations import geometry as co2_geometry
    from sjtu_tpmshx.physical_models.fluid_props import get
    from sjtu_tpmshx.physical_models.tpms_props import geometry
    from sjtu_tpmshx.physical_models.df_surrogate.full_core_3cell_fixed_v2 import FullCore3CellFixedDFV2

    parameters = {'fluid': {'fluid': 'air'}, 'co2_fluid': {'fluid': 'co2'},
                  'darcy_forchheimer': {'topology': 'Gyroid'}}
    models = {name: resolve_model(ModelRef(name, version, parameters.get(name, {})))
              for name, version in MODEL_VERSIONS.items()}
    assert models.pop('quick_design') == load_quick_design_parameters()
    resource = models.pop('darcy_forchheimer')
    np.testing.assert_array_equal(resource.predict(7.0, 0.5), FullCore3CellFixedDFV2('Gyroid').predict(7.0, 0.5))
    providers = {'fluid': get('air'), 'co2_fluid': get('co2'),
                 'geometry': geometry, 'co2_geometry': co2_geometry}
    assert models.keys() == providers.keys()
    for name, provider in providers.items():
        assert models[name] is provider


def test_reject_invalid_records():
    for ref in (ModelRef('fluid', 'unknown'), ModelRef('unknown', 'v1'),
                ModelRef('fluid', MODEL_VERSIONS['fluid'], {'fluid': 'air', 'ignored': True})):
        with pytest.raises(ValueError):
            resolve_model(ref)


def test_version_without_a_provider_rejects_darcy_forchheimer_parameters(monkeypatch):
    monkeypatch.setitem(MODEL_VERSIONS, 'test_model', 'v1')
    with pytest.raises(ValueError, match='test_model@v1'):
        resolve_model(ModelRef('test_model', 'v1', {'topology': 'Gyroid'}))
