"""VTK rectilinear cell fields with physical axes and embedded metadata."""
import io
import json
from pathlib import Path
import re

import numpy as np

from sjtu_tpmshx.domain.persistence_validation import validate_result
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.io.text_file import write_text


def export_vtk(result, path):
    validate_result(result)
    axes = [np.asarray(result.grid[axis + '_edges']) for axis in result.grid['axis_order']]
    if len(axes) == 2:
        axes.append(np.array([0.]))
    stream = io.StringIO()
    stream.write('# vtk DataFile Version 3.0\nSJTU-TPMSHX native FieldResult\nASCII\nDATASET RECTILINEAR_GRID\n')
    stream.write('DIMENSIONS ' + ' '.join(str(len(axis)) for axis in axes) + '\n')
    for label, values in zip('XYZ', axes):
        stream.write(f'{label}_COORDINATES {len(values)} double\n')
        np.savetxt(stream, values.reshape(1, -1), fmt='%.17g')
    metadata = dict(schema_version=result.schema_version, result_id=result.result_id,
                    coordinate_unit='m', dimension=result.grid['dimension'],
                    field_metadata=mutable_data(result.field_metadata), run_status=mutable_data(result.run_status))
    data = json.dumps(metadata, ensure_ascii=False, allow_nan=False).encode('utf-8')
    stream.write(f'FIELD FieldData 1\nmetadata_utf8 1 {len(data)} unsigned_char\n')
    np.savetxt(stream, np.frombuffer(data, dtype=np.uint8).reshape(1, -1), fmt='%d')
    count = int(np.prod([max(len(axis)-1, 1) for axis in axes]))
    stream.write(f'CELL_DATA {count}\n')
    for key, values in result.fields.items():
        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key) is None:
            raise ValueError(f'field name cannot be represented in legacy VTK: {key}')
        stream.write(f'SCALARS {key} double 1\nLOOKUP_TABLE default\n')
        np.savetxt(stream, np.asarray(values).ravel(order='F'), fmt='%.17g')
    return write_text(Path(path), stream.getvalue())
