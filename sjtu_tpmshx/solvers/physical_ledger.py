"""Check physical ports for direct and archived result capture."""
import numpy as np


def ports_complete(mass, direction, inlet, outlet):
    """Check actual boundary mass against the prepared physical ports."""
    for axis, faces in enumerate(mass):
        for end, sign in ((0, -1), (-1, 1)):
            outward = sign * np.take(faces, end, axis=axis)
            if axis != direction // 2:
                if np.any(outward != 0.):
                    return False
                continue
            is_inlet = end == (0 if direction % 2 == 0 else -1)
            opening = np.asarray(inlet if is_inlet else outlet)
            if opening.shape != outward.shape:
                raise ValueError('physical port mask shape disagrees with mass faces')
            if np.any((opening == 0.) & (outward != 0.)) or (not is_inlet and np.any(outward < 0.)):
                return False
    return True
