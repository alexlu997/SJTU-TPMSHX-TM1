"""Independent sigmoid bodies from the pre-port source at 8f850367.

Keep source operation order and weak scalar types. Production math does not
supply expected values. The locked SciPy RGI supplies the LUT reference.
"""
import numpy as np
from scipy.interpolate import RegularGridInterpolator


def _sigmoid(x, center, width):
    return 1.0 / (1.0 + np.exp(np.clip(-(x - center) / width, -50, 50)))


def _blend_1d(x, boundaries, values, width):
    result = values[0].copy() if hasattr(values[0], 'copy') else np.full_like(x, values[0])
    for index, boundary in enumerate(boundaries):
        alpha = _sigmoid(x, boundary, width)
        following = values[index + 1] if hasattr(values[index + 1], 'copy') else np.full_like(x, values[index + 1])
        result = result * (1.0 - alpha) + following * alpha
    return result


def sigmoid_field_2d(XF, YF, ctrl_inlet, ctrl_outlet, val_uniform,
                     y_trans_in, y_trans_out, width_x=.05, width_y=.02):
    first = _sigmoid(XF, 1.0 / 3, width_x)
    second = _sigmoid(XF, 2.0 / 3, width_x)
    def xblend(row):
        value = np.full_like(XF, row[0])
        value = value + (row[1] - value) * first
        value = value + (row[2] - value) * second
        return value
    layers = [xblend(ctrl_inlet[row]) for row in range(3)]
    layers.append(np.full_like(XF, val_uniform))
    layers.extend(xblend(ctrl_outlet[row]) for row in range(3))
    di, dout = y_trans_in / 3.0, y_trans_out / 3.0
    boundaries = [di, 2 * di, y_trans_in, 1.0 - y_trans_out,
                  1.0 - y_trans_out + dout, 1.0 - y_trans_out + 2 * dout]
    return _blend_1d(YF, boundaries, layers, width_y)


class GeometryLUT:
    """Retain the original two RGI owners and query shape contract."""
    def __init__(self, length, wall, epsilon, area):
        self.epsilon = RegularGridInterpolator((length, wall), epsilon, method='linear',
                                                bounds_error=False, fill_value=None)
        self.area = RegularGridInterpolator((length, wall), area, method='linear',
                                             bounds_error=False, fill_value=None)

    def query(self, length, wall):
        points = np.stack([length.ravel(), wall.ravel()], axis=-1)
        return (self.epsilon(points).reshape(length.shape),
                self.area(points).reshape(length.shape))

    def modes(self):
        # This is the locked RGI fast-path condition, before buffer conversion.
        return tuple(int(owner.values.ndim == 2 and owner.values.flags.writeable
                         and owner.values.dtype == np.float64 and owner.values.dtype.byteorder == '=')
                     for owner in (self.epsilon, self.area))
