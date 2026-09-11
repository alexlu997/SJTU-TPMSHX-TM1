"""Read actual exported VTK using VTK, preserving cell order and metadata."""
import json

import numpy as np

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.postprocess.export import export_vtk
from sjtu_tpmshx.tests.io_tm1.test_case_io import sample_case


def test_vtk_native_cell_readback(tmp_path):
    from vtkmodules.vtkIOLegacy import vtkRectilinearGridReader
    from vtkmodules.util.numpy_support import vtk_to_numpy
    field = np.array([[1., 2.], [3., 4.]])
    result = FieldResult('vtk-test', 'synthetic', 'fixture', grid=sample_case().grid,
        fields={'Ta': field}, field_metadata={'Ta': dict(unit='K', axes=('x', 'y'), location='cell', state='raw')},
        run_status={'execution': 'completed', 'converged': False})
    path = export_vtk(result, tmp_path / 'results.vtk')
    reader = vtkRectilinearGridReader()
    reader.SetFileName(str(path))
    reader.Update()
    grid = reader.GetOutput()
    assert grid.GetNumberOfCells() == 4
    np.testing.assert_array_equal(vtk_to_numpy(grid.GetCellData().GetArray('Ta')), field.ravel(order='F'))
    metadata = json.loads(bytes(vtk_to_numpy(grid.GetFieldData().GetArray('metadata_utf8'))).decode('utf-8'))
    assert metadata['field_metadata']['Ta']['unit'] == 'K'
    assert metadata['run_status']['converged'] is False
