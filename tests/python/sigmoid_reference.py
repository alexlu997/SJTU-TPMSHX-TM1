"""Independent float64 sigmoid bodies from the pre-port source at 8f850367.

Keep source operation order in float64. Production math does not supply
expected values. The locked SciPy RGI supplies the LUT reference.
"""
import numpy as np
from scipy.interpolate import RegularGridInterpolator


def _sigmoid(x, center, width):
    arr = np.asarray(x, dtype=np.float64)
    return 1.0 / (1.0 + np.exp(np.clip(-(arr - float(center)) / float(width), -50.0, 50.0)))


def _blend_1d(x, boundaries, values, width):
    arr = np.asarray(x, dtype=np.float64)
    result = (np.asarray(values[0], dtype=np.float64).copy()
              if hasattr(values[0], 'copy') else np.full_like(arr, float(values[0])))
    for index, boundary in enumerate(boundaries):
        alpha = _sigmoid(arr, boundary, width)
        following = (np.asarray(values[index + 1], dtype=np.float64).copy()
                     if hasattr(values[index + 1], 'copy') else np.full_like(arr, float(values[index + 1])))
        result = result * (1.0 - alpha) + following * alpha
    return result


def sigmoid_field_2d(XF, YF, ctrl_inlet, ctrl_outlet, val_uniform,
                     y_trans_in, y_trans_out, width_x=.05, width_y=.02):
    xf = np.asarray(XF, dtype=np.float64)
    yf = np.asarray(YF, dtype=np.float64)
    inlet = np.asarray(ctrl_inlet, dtype=np.float64)
    outlet = np.asarray(ctrl_outlet, dtype=np.float64)
    first = _sigmoid(xf, 1.0 / 3, width_x)
    second = _sigmoid(xf, 2.0 / 3, width_x)
    def xblend(row):
        value = np.full_like(xf, float(row[0]))
        value = value + (float(row[1]) - value) * first
        value = value + (float(row[2]) - value) * second
        return value
    layers = [xblend(inlet[row]) for row in range(3)]
    layers.append(np.full_like(xf, float(val_uniform)))
    layers.extend(xblend(outlet[row]) for row in range(3))
    di, dout = float(y_trans_in) / 3.0, float(y_trans_out) / 3.0
    boundaries = [di, 2 * di, float(y_trans_in), 1.0 - float(y_trans_out),
                  1.0 - float(y_trans_out) + dout, 1.0 - float(y_trans_out) + 2 * dout]
    return _blend_1d(yf, boundaries, layers, width_y)


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
