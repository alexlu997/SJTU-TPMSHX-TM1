"""Shared model evaluation is usable without importing numerical backends."""
import subprocess
import sys


def test_model_evaluation_in_clean_process():
    code = '''
import importlib
import sys
import numpy as np
names = "tpms_calc tpms_props tpms_geometry fluid_props sco2_props nu_correlations zone_config continuous_field grid_schema".split()
for name in names:
    importlib.import_module("sjtu_tpmshx.models." + name)
from sjtu_tpmshx.models.fluid_props import get
from sjtu_tpmshx.models.catalog import MODEL_VERSIONS, resolve_model
from sjtu_tpmshx.domain.model_refs import ModelRef
resource = resolve_model(ModelRef("darcy_forchheimer", MODEL_VERSIONS["darcy_forchheimer"], {"topology": "Gyroid"}))
assert all(value > 0 for value in resource.predict(7.0, 0.5))
for fluid in ("air", "water", "sco2"):
    model = get(fluid)
    pressure = 8e6 if fluid == "sco2" else 101325.0
    temperatures = np.array([320.0, 330.0])
    for property_name in ("rho", "mu", "k", "cp"):
        evaluate = getattr(model, property_name)
        values = np.asarray(evaluate(temperatures, pressure))
        expected = np.array([evaluate(float(t), pressure) for t in temperatures])
        np.testing.assert_allclose(values, expected)
        assert np.all(np.isfinite(values)) and np.all(values > 0)
for prefix in ("sjtu_tpmshx.solvers", "sjtu_tpmshx.pipelines", "numba", "PySide6"):
    assert not any(name == prefix or name.startswith(prefix + ".") for name in sys.modules), prefix
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_concurrent_existing_model_imports_in_fresh_process():
    result = subprocess.run([sys.executable, '-c', '''
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from sjtu_tpmshx.models.zone_config import ZoneConfig
barrier = Barrier(2)
def load(_):
    barrier.wait()
    from sjtu_tpmshx.models.zone_config import ZoneConfig as imported
    return imported
with ThreadPoolExecutor(max_workers=2) as pool:
    assert all(cls is ZoneConfig for cls in pool.map(load, range(2)))
'''], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
