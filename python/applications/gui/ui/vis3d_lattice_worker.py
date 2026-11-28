"""Build and color one closed lattice domain on a dedicated worker thread."""
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import blake2b
import os
from threading import Event

import numpy as np
import pyvista as pv
from PySide6.QtCore import QObject, QThreadPool, Qt, Signal, Slot
from scipy.interpolate import RegularGridInterpolator
from vtkmodules.vtkFiltersCore import vtkStaticCleanPolyData

from tm1.physical_models.tpms_geometry import lattice_cell_size, signed_wall_grid
from tm1.run_control.cancellation import CancelledError


# Samples per cell length L for the 细节 levels 低, 中 and 高.
_DETAIL = {'low': 4.5, 'medium': 8, 'high': 12}
_STAGES = ('采样 φ', '壁面', '封口', '法线', '着色')


def _physical_memory_bytes():
    if os.name == 'nt':
        from ctypes import byref, c_ulonglong, windll, WinError
        kib = c_ulonglong()
        if not windll.kernel32.GetPhysicallyInstalledSystemMemory(byref(kib)):
            raise WinError()
        return kib.value * 1024
    return os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')


@dataclass(frozen=True, kw_only=True)
class LatticeRequest:
    """Snapshot of one recorded cell field in (x, y, z) order. Widths use m. L and t use mm."""

    result_id: str
    field_name: str
    topology: str
    phase: str
    dx: np.ndarray
    dy: np.ndarray
    dz: np.ndarray
    field: np.ndarray
    L_mm: float | np.ndarray
    t_mm: float | np.ndarray
    delta: float | np.ndarray = 0.
    detail: str = 'medium'

    def __post_init__(self):
        for name in ('dx', 'dy', 'dz', 'field', 'L_mm', 't_mm', 'delta'):
            values = np.array(getattr(self, name), dtype=np.float64, order='C', copy=True)
            values.flags.writeable = False
            object.__setattr__(self, name, values)
        widths = (self.dx, self.dy, self.dz)
        if any(w.ndim != 1 or not w.size or not np.isfinite(w).all() or np.any(w <= 0.)
               for w in widths):
            raise ValueError('dx, dy and dz must contain finite positive cell widths')
        shape = tuple(w.size for w in widths)
        if self.field.shape != shape:
            raise ValueError(f'the recorded field must have cell shape {shape}')
        for name in ('L_mm', 't_mm', 'delta'):
            values = getattr(self, name)
            if values.shape not in ((), shape):
                raise ValueError(f'{name} must be scalar or have cell shape {shape}')
            if values.ndim and np.all(values == values.flat[0]):
                object.__setattr__(self, name, values.flat[0])
        if self.phase not in ('A', 'B', 'S') or self.detail not in _DETAIL:
            raise ValueError('select phase A, B or S and detail low, medium or high')


def _check_cancel(cancel):
    if cancel.is_set():
        raise CancelledError()


def _sample_cells(values, centers, coordinates):
    """Interpolate cell-center values. Extend each end value to the box face."""
    if np.ndim(values) == 0:
        return values
    points = tuple(np.clip(x, axis[0], axis[-1]) for x, axis in zip(coordinates, centers))
    return RegularGridInterpolator(centers, values)(points)


def _contour(values, spacing):
    grid = pv.ImageData(dimensions=values.shape, spacing=spacing)
    grid.point_data['wall'] = values.ravel(order='F')
    return grid.contour([0.], scalars='wall', method='flying_edges', compute_scalars=False)


def _geometry(request, cell, centers, lengths, stage, cancel):
    stage(1)
    axes = [np.linspace(0., span, max(1, round(span * _DETAIL[request.detail] / cell)) + 1)
            for span in lengths]
    grid_points = np.ix_(*axes)
    walls = _sample_cells(request.t_mm, centers, grid_points)
    offsets = _sample_cells(request.delta, centers, grid_points)
    samples, _ = signed_wall_grid(request.topology, cell, lengths, tuple(map(len, axes)), walls, offsets)
    spacing = tuple(axis[1] for axis in axes)

    stage(2)
    fields = []
    if request.phase != 'B':
        fields.append(samples['phi'] - samples['lower'])
    if request.phase != 'A':
        fields.append(samples['phi'] - samples['upper'])
    del samples
    pieces = []
    for field in fields:
        _check_cancel(cancel)
        pieces.append(_contour(field, spacing))
    # Flying edges orients triangles towards decreasing values. Reverse A and the upper solid wall.
    if request.phase in ('A', 'S'):
        pieces[-1].flip_faces(inplace=True)

    stage(3)
    for axis, span in enumerate(lengths):
        for index in (0, -1):
            _check_cancel(cancel)
            face = fields[0].take(index, axis=axis)
            if request.phase == 'S':
                outer = fields[1].take(index, axis=axis)
            else:
                outer = np.full_like(face, 1. if request.phase == 'A' else -1.)
            # Project this two-layer contour onto the box face. Its edges match the wall cuts.
            cap = _contour(np.stack((face, outer), axis=axis), spacing)
            cap.points[:, axis] = 0. if index == 0 else span
            inward_face = -1 if request.phase == 'A' else 0
            if index == inward_face:
                cap.flip_faces(inplace=True)
            pieces.append(cap)

    # A level through a grid vertex can give several copies of that vertex at roundoff distance.
    # The merge collapses some triangles. Remove them: a collapsed triangle has no area.
    clean = vtkStaticCleanPolyData()
    clean.SetInputData(pv.merge(pieces, merge_points=False))
    clean.SetTolerance(8 * np.finfo(float).eps)
    clean.ConvertPolysToLinesOff()
    clean.Update()
    mesh = pv.wrap(clean.GetOutput()).triangulate()
    stage(4)
    if mesh.n_cells:
        mesh.compute_normals(point_normals=True, cell_normals=False, consistent_normals=False,
                             split_vertices=False, inplace=True)
    return mesh


class LatticeCache:
    """Share one byte limit across geometry and sampled colors on the serial worker."""

    def __init__(self, limit_bytes=None):
        if limit_bytes is not None and limit_bytes < 0:
            raise ValueError('cache size must be nonnegative')
        limit = 256_000_000 if _physical_memory_bytes() <= 8 * 1024**3 else 512_000_000
        self.limit_bytes = limit if limit_bytes is None else min(limit, limit_bytes)
        self._entries = OrderedDict()
        self.size_bytes = 0

    def clear(self):
        self._entries.clear()
        self.size_bytes = 0

    def _store(self, key, value, size):
        if key in self._entries:
            self.size_bytes -= self._entries.pop(key)[1]
        self._entries[key] = (value, size)
        self.size_bytes += size

    def build(self, request, cancel, progress):
        """Return the colored mesh and whether its geometry and colors remain in the cache."""
        def stage(number):
            progress(number, _STAGES[number - 1])
            _check_cancel(cancel)

        _check_cancel(cancel)
        cell, reason = lattice_cell_size(request.L_mm)
        if reason:
            raise ValueError(reason)
        widths = (request.dx, request.dy, request.dz)
        ends = tuple(np.cumsum(w * 1000.) for w in widths)
        lengths = tuple(axis[-1] for axis in ends)
        centers = tuple(axis - w * 500. for axis, w in zip(ends, widths))
        signature = tuple(blake2b(a, digest_size=16).digest() for a in (*widths, request.t_mm, request.delta))
        geometry_key = (request.topology, cell, signature, request.phase, request.detail)
        color_key = (geometry_key, request.result_id, request.field_name,
                     blake2b(request.field, digest_size=16).digest())
        geometry = self._entries.get(geometry_key)
        if geometry is None:
            mesh = _geometry(request, cell, centers, lengths, stage, cancel)
            geometry = (mesh, mesh.actual_memory_size * 1024)
        mesh, geometry_bytes = geometry
        color = self._entries.get(color_key)
        if color is None:
            stage(5)
            values = np.empty(mesh.n_points)
            # Bound interpolation scratch and check cancellation during a large color change.
            for start in range(0, mesh.n_points, 65_536):
                _check_cancel(cancel)
                part = slice(start, start + 65_536)
                values[part] = _sample_cells(request.field, centers, mesh.points[part].T)
            color = (values, values.nbytes)

        _check_cancel(cancel)
        output = mesh.copy(deep=False)
        output.point_data[request.field_name] = color[0]
        output.set_active_scalars(request.field_name)
        retained = geometry_bytes + color[1] <= self.limit_bytes
        if retained:
            self._store(color_key, *color)
        if geometry_bytes <= self.limit_bytes:
            # A geometry entry stays newer than all colors that use its point order.
            self._store(geometry_key, *geometry)
        while self.size_bytes > self.limit_bytes:
            self.size_bytes -= self._entries.popitem(last=False)[1][1]
        return output, retained


class LatticeBuilder(QObject):
    """Submit, cancel, and close from the GUI thread. Signals carry the request generation.

    The ready signal returns the mesh in mm and its cache status. Treat its shared arrays as read-only.
    """

    progress = Signal(int, int, str)
    ready = Signal(int, object, bool)
    failed = Signal(int, str)
    cancelled = Signal(int)
    _finished = Signal(int, object, bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cache = LatticeCache()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._generation = 0
        self._cancel = None
        self._finished.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    def submit(self, request: LatticeRequest) -> int:
        self.cancel()
        self._generation += 1
        generation = self._generation
        self._cancel = cancel = Event()

        def run():
            try:
                mesh, retained = self.cache.build(
                    request, cancel, lambda i, name: self.progress.emit(generation, i, name))
            except CancelledError:
                return
            except Exception as exc:
                self._finished.emit(generation, None, False, str(exc))
            else:
                self._finished.emit(generation, mesh, retained, '')

        self._pool.start(run)
        return generation

    @Slot(int, object, bool, str)
    def _deliver(self, generation, mesh, retained, error):
        if generation != self._generation or self._cancel is None:
            return
        self._cancel = None
        if mesh is None:
            self.failed.emit(generation, error)
        else:
            self.ready.emit(generation, mesh, retained)

    def cancel(self):
        if self._cancel is not None:
            self._cancel.set()
            self._cancel = None
            self._pool.clear()
            self.cancelled.emit(self._generation)

    def close(self):
        """Stop pending work before the panel releases the worker and its cache."""
        self.cancel()
        self._pool.waitForDone()
        self.cache.clear()
