"""Plot a native 2D field or an explicitly selected 3D z-cell slice."""
import numpy as np


def plot_field(result, name, path, *, z_index=None):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    values = np.asarray(result.fields[name])
    title = f'{name}: {result.field_metadata[name]["state"]}'
    if result.grid['dimension'] == 3:
        if z_index is None:
            raise ValueError('3D field plots require an explicit z cell index')
        values = values[:, :, z_index]
        z = .5 * (result.grid['z_edges'][z_index] + result.grid['z_edges'][z_index+1])
        title += f'\nz cell {z_index}, z={z:g} m'
    elif z_index is not None:
        raise ValueError('2D fields have no z cell index')
    figure, axis = plt.subplots(figsize=(7, 4), layout='constrained')
    try:
        artist = axis.pcolormesh(result.grid['x_edges'], result.grid['y_edges'], values.T, shading='flat')
        axis.set(xlabel='x (m)', ylabel='y (m)', title=title)
        axis.set_aspect('equal')
        figure.colorbar(artist, ax=axis, label=result.field_metadata[name]['unit'])
        figure.savefig(path, dpi=150)
    finally:
        plt.close(figure)
    return path
