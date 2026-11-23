"""Evaluate independent formulas with the float64 operands that native kernels receive."""
import numpy as np


def operand(value):
    """Return a 0-d or n-d float64 array for one real operand; keep other objects."""
    if isinstance(value, (bool, np.bool_)) or value is None or isinstance(value, (str, bytes)):
        return value
    if isinstance(value, (int, float, np.integer, np.floating)):
        return np.asarray(float(value))
    if isinstance(value, (list, tuple, np.ndarray)):
        array = np.asarray(value)
        if array.dtype.kind in 'fiu':
            return array.astype(np.float64)
    return value


def result(value):
    """Return a Python float for a 0-d result and a float64 array otherwise."""
    if isinstance(value, tuple):
        return tuple(result(item) for item in value)
    array = np.asarray(value, dtype=np.float64)
    return float(array) if array.ndim == 0 else array


def call(function, *arguments, **keywords):
    """Call a reference with float64 array arithmetic, as the native core computes."""
    converted = [operand(value) for value in arguments]
    named = {key: operand(value) for key, value in keywords.items()}
    return result(function(*converted, **named))


def warning_text(text):
    """Remove the NumPy scalar-ufunc prefix; the float64 core has one event text per operation."""
    return text.replace(' encountered in scalar ', ' encountered in ')
