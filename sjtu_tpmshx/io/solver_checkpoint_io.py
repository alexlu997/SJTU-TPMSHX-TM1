"""Publish and read a complete solver checkpoint with typed HDF5 arrays."""
from sjtu_tpmshx.domain.solver_checkpoint import SolverCheckpoint
from .case_io import load_case
from .hdf5_data import read_record, write_record


def save_solver_checkpoint(checkpoint, path):
    if not isinstance(checkpoint, SolverCheckpoint):
        raise TypeError('expected SolverCheckpoint')
    return write_record(path, checkpoint, 'SolverCheckpoint')


def load_solver_checkpoint(path):
    return read_record(path, SolverCheckpoint, 'SolverCheckpoint')


def load_checkpoint_case(checkpoint, *, case_file=None):
    case = load_case(checkpoint.case_file if case_file is None else case_file)
    if case.case_id != checkpoint.case_id or case.model_refs != checkpoint.model_refs:
        raise ValueError('solver checkpoint and prepared-case identity differ')
    return case
