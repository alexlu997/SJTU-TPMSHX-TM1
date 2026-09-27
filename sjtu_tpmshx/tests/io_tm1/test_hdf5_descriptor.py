"""The shared reader rejects descriptor storage outside its own HDF5 file."""
import h5py
import pytest

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.io.case_io import load_case, save_case
from sjtu_tpmshx.io.result_io import load_result, save_result
from sjtu_tpmshx.tests.io_tm1.test_case_io import sample_case


@pytest.mark.parametrize('kind', ['case', 'result'])
@pytest.mark.parametrize('storage', ['virtual', 'external', 'group', 'soft_link', 'external_link'])
def test_descriptor_must_be_a_local_dataset(tmp_path, kind, storage):
    path = tmp_path / 'record.h5'
    case = sample_case()
    if kind == 'case':
        record, save, load = case, save_case, load_case
    else:
        record = FieldResult('result', case.case_id, 'fixture', grid=case.grid,
                             run_status={'execution': 'completed', 'converged': False})
        save, load = save_result, load_result
    save(record, path)
    assert load(path).case_id == record.case_id

    sidecar = tmp_path / 'descriptor.h5'
    raw_path = tmp_path / 'descriptor.bin'
    with h5py.File(path, 'r+') as source:
        text = source['descriptor'][()]
        dtype = h5py.string_dtype('utf-8', length=len(text))
        del source['descriptor']
        if storage in ('virtual', 'external_link'):
            with h5py.File(sidecar, 'w') as external:
                external.create_dataset('text', data=text, dtype=dtype)
        if storage == 'virtual':
            layout = h5py.VirtualLayout(shape=(), dtype=dtype)
            layout[()] = h5py.VirtualSource(str(sidecar), 'text', shape=())
            source.create_virtual_dataset('descriptor', layout)
        elif storage == 'external':
            dataset = source.create_dataset('descriptor', shape=(1,), dtype=dtype,
                external=[(str(raw_path), 0, len(text))])
            dataset[0] = text
        elif storage == 'group':
            source.create_group('descriptor')
        elif storage == 'soft_link':
            source.create_dataset('other', data=text, dtype=dtype)
            source['descriptor'] = h5py.SoftLink('/other')
        else:
            source['descriptor'] = h5py.ExternalLink(str(sidecar), 'text')

    if storage == 'external':
        # Reject the dependency before attempting to read the missing sidecar.
        raw_path.unlink()
    with pytest.raises(ValueError, match='descriptor.*local|external dataset storage'):
        load(path)
