"""Portable data types and the public geometry validation helpers."""
__all__ = [
    'validate_geometry',
    'compute_volumetric_htc',
    'wall_for_dir',
    'cross_axes_for_dir',
    'parse_unit_value',
    'validate_pipe_config',
    'geometry_extrapolation_warning',
    'DomainWarning',
]


def __getattr__(name):
    if name in __all__:
        import sjtu_tpmshx.preprocess.validator as validator
        return getattr(validator, "Warning" if name == "DomainWarning" else name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
