"""Case YAML manifest and actual HDF5 prepared-data transport."""
from pathlib import Path

from sjtu_tpmshx.domain.case_data import CaseData, SCHEMA_VERSION
from .hdf5_data import read_record, write_record
from .text_file import write_text
from .file_set import staged_files
from sjtu_tpmshx.domain.persistence_validation import validate_case as validate_physical_case


def validate_case(case):
    from sjtu_tpmshx.models.catalog import MODEL_VERSIONS
    validate_physical_case(case)
    for ref in case.model_refs:
        if MODEL_VERSIONS.get(ref.name) != ref.version:
            raise ValueError(f'unknown model resource {ref.name}@{ref.version}')
    return case


def save_case(case, path):
    path = Path(path)
    validate_case(case)
    if path.suffix == '.h5':
        return write_record(path, case, 'CaseData')
    if path.suffix not in ('.yaml', '.yml'):
        raise ValueError('prepared Case path must end in .yaml, .yml or .h5')
    import yaml
    payload = path.with_suffix('.h5')
    with staged_files([payload, path]) as stage:
        write_record(stage / payload.name, case, 'CaseData')
        write_text(stage / path.name, yaml.safe_dump(dict(
            schema_version=SCHEMA_VERSION, record_kind='CaseData',
            case_id=case.case_id, hdf5=payload.name), sort_keys=False))
    return path


def _read_case_manifest(path):
    """Read the validated manifest used by loading and CLI input protection."""
    import yaml
    manifest = yaml.safe_load(path.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or set(manifest) != {'schema_version', 'record_kind', 'case_id', 'hdf5'}:
        raise ValueError('invalid Case YAML manifest')
    if manifest['schema_version'] != SCHEMA_VERSION or manifest['record_kind'] != 'CaseData':
        raise ValueError('unsupported Case YAML schema')
    name = manifest['hdf5']
    if not isinstance(name, str) or Path(name).name != name or not name.endswith('.h5'):
        raise ValueError('Case payload must be a sibling HDF5 file')
    return manifest


def load_case(path):
    path = Path(path)
    if path.suffix == '.h5':
        return validate_case(read_record(path, CaseData, 'CaseData'))
    manifest = _read_case_manifest(path)
    case = read_record(path.parent / manifest['hdf5'], CaseData, 'CaseData')
    if case.case_id != manifest['case_id']:
        raise ValueError('Case YAML and HDF5 identifiers disagree')
    return validate_case(case)
