"""Real YAML/HDF5 files with synthetic, explicitly non-physical test data."""
import json
import subprocess
import sys

import h5py
import numpy as np
import pytest

from sjtu_tpmshx.domain.case_data import CaseData
from sjtu_tpmshx.domain.model_refs import ModelRef
from sjtu_tpmshx.io.case_io import load_case, save_case


def sample_case():
    grid = dict(dimension=2, length_unit='m', axis_order=('x', 'y'))
    for axis in 'xy':
        grid['d' + axis] = np.array([.1, .2])
        grid[axis + '_edges'] = np.r_[0., np.cumsum(grid['d' + axis])]
    return CaseData('synthetic', grid=grid, design_fields={'eps_arr': np.full((2, 2), .7)},
                    model_refs=(ModelRef('geometry', 'v2-5f1cafb'),),
                    metadata={'warning': '人工样例', 'diagnostic': float('nan'), 'bytes': b'abc',
                              'collision': {'array': 'ordinary user mapping'}})


def test_case_hdf5_yaml_and_new_process(tmp_path):
    path = tmp_path / 'case.yaml'
    case = sample_case()
    save_case(case, path)
    assert h5py.is_hdf5(path.with_suffix('.h5'))
    restored = load_case(path)
    np.testing.assert_array_equal(restored.design_fields['eps_arr'], case.design_fields['eps_arr'])
    assert restored.model_refs == case.model_refs
    assert np.isnan(restored.metadata['diagnostic'])
    assert restored.metadata['bytes'] == b'abc'
    assert restored.metadata['collision']['array'] == 'ordinary user mapping'
    with pytest.raises(ValueError):
        restored.design_fields['eps_arr'].setflags(write=True)
    child = subprocess.run([sys.executable, '-c', '''
import sys
from sjtu_tpmshx.io.case_io import load_case
case = load_case(sys.argv[1])
assert case.case_id == 'synthetic'
assert case.design_fields['eps_arr'].shape == (2, 2)
for prefix in ('sjtu_tpmshx.solvers', 'sjtu_tpmshx.preprocess', 'numba', 'PySide6'):
    assert not any(n == prefix or n.startswith(prefix + '.') for n in sys.modules), prefix
''', str(path)], capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stderr


def test_reject_corrupt_version_shape_and_external_manifest(tmp_path):
    path = tmp_path / 'case.h5'
    save_case(sample_case(), path)
    with h5py.File(path, 'r+') as data:
        data.attrs['schema_version'] = 'unknown'
    with pytest.raises(ValueError, match='schema'):
        load_case(path)
    save_case(sample_case(), path)
    with h5py.File(path, 'r+') as data:
        descriptor = json.loads(data['descriptor'].asstr()[()])
        descriptor['mapping']['grid']['mapping']['dx']['shape'] = [3]
        data['descriptor'][()] = json.dumps(descriptor)
    with pytest.raises(ValueError, match='shape'):
        load_case(path)
    manifest = tmp_path / 'case.yaml'
    manifest.write_text('schema_version: three_module_v1\nrecord_kind: CaseData\ncase_id: synthetic\nhdf5: ../outside.h5\n')
    with pytest.raises(ValueError, match='sibling'):
        load_case(manifest)
    manifest.write_text('!!python/object/apply:os.system [echo unsafe]')
    import yaml
    with pytest.raises(yaml.constructor.ConstructorError):
        load_case(manifest)
