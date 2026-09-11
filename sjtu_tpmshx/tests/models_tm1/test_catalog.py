"""Recorded versions resolve existing providers without fallback or refitting."""
import numpy as np
import pytest

from sjtu_tpmshx.domain.model_refs import ModelRef
from sjtu_tpmshx.models.catalog import MODEL_VERSIONS, resolve_model


def test_resolve_records_and_reject_unknown_versions():
    from sjtu_tpmshx.models.fluid_props import get
    from sjtu_tpmshx.models.tpms_props import geometry
    from sjtu_tpmshx.df_surrogate.full_core_3cell_fixed_v2 import FullCore3CellFixedDFV2
    assert resolve_model(ModelRef('fluid', MODEL_VERSIONS['fluid'], {'fluid': 'air'})) is get('air')
    assert resolve_model(ModelRef('geometry', MODEL_VERSIONS['geometry'])) is geometry
    resource = resolve_model(ModelRef('darcy_forchheimer', MODEL_VERSIONS['darcy_forchheimer'], {'topology': 'Gyroid'}))
    np.testing.assert_array_equal(resource.predict(7.0, 0.5), FullCore3CellFixedDFV2('Gyroid').predict(7.0, 0.5))
    for ref in (ModelRef('fluid', 'unknown'), ModelRef('unknown', 'v1'),
                ModelRef('fluid', MODEL_VERSIONS['fluid'], {'fluid': 'air', 'ignored': True})):
        with pytest.raises(ValueError):
            resolve_model(ref)
