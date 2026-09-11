"""Archive completed or explicitly rejected native results independently of solvers."""
from sjtu_tpmshx.domain.field_result import FieldResult
from .hdf5_data import read_record, write_record
from sjtu_tpmshx.domain.persistence_validation import validate_result


def save_result(result, path):
    validate_result(result)
    return write_record(path, result, 'FieldResult')


def load_result(path):
    return validate_result(read_record(path, FieldResult, 'FieldResult'))
