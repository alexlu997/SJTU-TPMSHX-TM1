"""
unstructured_mesh.py — Triangular mesh for arbitrary polygon domains

Generates a quality triangular mesh inside a user-defined polygon,
builds cell-neighbour connectivity, and classifies boundary faces
for FVM solvers (wall / inlet / outlet).

Dependencies: numpy, scipy, matplotlib, triangle
"""

import numpy as np
from scipy.spatial import Delaunay
from matplotlib.path import Path


# ── Boundary type codes ─────────────────────────────────────────
BC_INTERIOR = 0
BC_WALL     = 1
BC_INLET_A  = 2
BC_OUTLET_A = 3
BC_INLET_B  = 4
BC_OUTLET_B = 5


class TriMesh:
    """Triangular mesh for 2D polygon domains with FVM connectivity."""

    def __init__(self):
        self.nodes       = None   # (N_nodes, 2) float64
        self.cells       = None   # (N_cells, 3) int32
        self.n_nodes     = 0
        self.n_cells     = 0

        # Derived geometry
        self.cell_centers = None  # (N_cells, 2)
        self.cell_areas   = None  # (N_cells,)

        # Neighbour connectivity (each tri has 3 faces)
        self.nbr     = None       # (N_cells, 3) neighbour cell, -1 = boundary
        self.face_len = None      # (N_cells, 3) face edge length
        self.face_nx  = None      # (N_cells, 3) outward unit-normal x
        self.face_ny  = None      # (N_cells, 3) outward unit-normal y
        self.dCF      = None      # (N_cells, 3) centre-to-centre distance

        # Boundary classification
        self.bc_type  = None      # (N_cells, 3) BC code per face
        self.polygon  = None      # original polygon vertices (N_verts, 2)

        # Boundary-face edge association
        self._bnd_edge_id = None  # (N_cells, 3) polygon edge index, -1 if interior

    # ────────────────────────────────────────────────────────────────
    #  Factory: build from polygon
    # ────────────────────────────────────────────────────────────────
    @staticmethod
    def from_polygon(vertices, max_area=None, n_edge_pts=20):
        """
        Build a triangular mesh inside a polygon.

        Parameters
        ----------
        vertices   : (N, 2) array-like, polygon vertices in CCW order.
        max_area   : float or None. Maximum triangle area for refinement.
                     If None, estimated from polygon bounding box.
        n_edge_pts : int, number of points per polygon edge.
        """
        mesh = TriMesh()
        verts = np.asarray(vertices, dtype=np.float64)
        if verts.shape[0] < 3:
            raise ValueError("Need at least 3 polygon vertices.")
        mesh.polygon = verts
        n_v = len(verts)

        # ── Try constrained Delaunay via `triangle` library ──────
        try:
            import triangle as tr

            # Build PSLG (Planar Straight-Line Graph)
            segments = np.array([[i, (i + 1) % n_v] for i in range(n_v)], dtype=np.int32)

            pslg = dict(vertices=verts, segments=segments)

            # Area constraint string (plain decimal — triangle rejects sci notation)
            if max_area is None:
                bbox = verts.max(axis=0) - verts.min(axis=0)
                max_area = bbox[0] * bbox[1] / (n_edge_pts ** 2)
            opts = f'pq30a{max_area:.12f}'

            tri = tr.triangulate(pslg, opts)
            mesh.nodes = np.asarray(tri['vertices'], dtype=np.float64)
            mesh.cells = np.asarray(tri['triangles'], dtype=np.int32)

        except Exception:
            # Fallback: scipy Delaunay + polygon filter
            mesh.nodes, mesh.cells = _fallback_mesh(verts, max_area, n_edge_pts)

        mesh.n_nodes = len(mesh.nodes)
        mesh.n_cells = len(mesh.cells)

        _compute_geometry(mesh)
        _build_connectivity(mesh)
        _classify_boundaries(mesh)

        return mesh

    # ────────────────────────────────────────────────────────────────
    #  Set pipe (inlet/outlet) locations on polygon edges
    # ────────────────────────────────────────────────────────────────
    def set_pipes(self, pipes):
        """
        Define inlet / outlet pipe regions on polygon edges.

        Parameters
        ----------
        pipes : list of dict, each with:
            'edge'      : int   — polygon edge index (0-based)
            'frac_start': float — start fraction along edge [0, 1]
            'frac_end'  : float — end fraction along edge [0, 1]
            'bc'        : int   — BC_INLET_A / BC_OUTLET_A / BC_INLET_B / BC_OUTLET_B
        """
        if self._bnd_edge_id is None:
            return

        verts = self.polygon
        n_v = len(verts)

        for pipe in pipes:
            eidx = pipe['edge']
            fs, fe = pipe['frac_start'], pipe['frac_end']
            bc = pipe['bc']

            # Edge endpoints
            p0 = verts[eidx]
            p1 = verts[(eidx + 1) % n_v]
            edge_vec = p1 - p0
            edge_len = np.linalg.norm(edge_vec)

            for ci in range(self.n_cells):
                for fi in range(3):
                    if self._bnd_edge_id[ci, fi] != eidx:
                        continue
                    # Face midpoint
                    n0, n1 = self._face_nodes(ci, fi)
                    fm = 0.5 * (self.nodes[n0] + self.nodes[n1])
                    # Project onto edge
                    t = np.dot(fm - p0, edge_vec) / (edge_len ** 2)
                    if fs <= t <= fe:
                        self.bc_type[ci, fi] = bc

    def _face_nodes(self, ci, fi):
        """Return the two node indices of face fi of cell ci."""
        c = self.cells[ci]
        return c[(fi + 1) % 3], c[(fi + 2) % 3]

    # ────────────────────────────────────────────────────────────────
    #  Convenience: compute inlet face normal direction for a pipe
    # ────────────────────────────────────────────────────────────────
    def inlet_normal(self, edge_idx):
        """Inward normal direction of a polygon edge (unit vector, into domain)."""
        verts = self.polygon
        p0 = verts[edge_idx]
        p1 = verts[(edge_idx + 1) % len(verts)]
        edge = p1 - p0
        length = np.linalg.norm(edge)
        if length < 1e-12:
            raise ValueError(f"Degenerate polygon edge {edge_idx}")
        # Outward normal for CCW polygon: (dy, -dx); return inward
        return np.array([-edge[1], edge[0]]) / length


# ===================================================================
#  Internal helpers
# ===================================================================

def _fallback_mesh(verts, max_area, n_edge_pts):
    """Fallback meshing using scipy Delaunay + polygon clipping."""
    n_v = len(verts)
    if max_area is None:
        bbox = verts.max(axis=0) - verts.min(axis=0)
        max_area = bbox[0] * bbox[1] / (n_edge_pts ** 2)

    # Boundary points
    bnd_pts = []
    for i in range(n_v):
        p0, p1 = verts[i], verts[(i + 1) % n_v]
        n = max(2, int(np.linalg.norm(p1 - p0) / np.sqrt(max_area)) + 1)
        for t in np.linspace(0, 1, n, endpoint=False):
            bnd_pts.append(p0 + t * (p1 - p0))
    bnd_pts = np.array(bnd_pts)

    # Interior grid points
    lo = verts.min(axis=0)
    hi = verts.max(axis=0)
    h = np.sqrt(max_area * 2)  # approximate spacing
    xs = np.arange(lo[0] + h / 2, hi[0], h)
    ys = np.arange(lo[1] + h / 2, hi[1], h)
    gx, gy = np.meshgrid(xs, ys)
    grid = np.column_stack([gx.ravel(), gy.ravel()])
    path = Path(verts)
    inside = path.contains_points(grid)
    int_pts = grid[inside]

    all_pts = np.vstack([bnd_pts, int_pts])

    # Delaunay triangulate
    tri = Delaunay(all_pts)
    cells = tri.simplices

    # Remove triangles outside polygon
    centroids = all_pts[cells].mean(axis=1)
    keep = path.contains_points(centroids)
    cells = cells[keep]

    # Re-index
    used = np.unique(cells)
    node_map = np.full(len(all_pts), -1, dtype=np.int32)
    node_map[used] = np.arange(len(used), dtype=np.int32)

    return all_pts[used], node_map[cells]


def _compute_geometry(mesh):
    """Compute cell centres and areas."""
    n = mesh.nodes
    c = mesh.cells
    # Cell centres (centroid)
    mesh.cell_centers = n[c].mean(axis=1)
    # Cell areas via cross product
    v01 = n[c[:, 1]] - n[c[:, 0]]
    v02 = n[c[:, 2]] - n[c[:, 0]]
    mesh.cell_areas = 0.5 * np.abs(v01[:, 0] * v02[:, 1] - v01[:, 1] * v02[:, 0])


def _build_connectivity(mesh):
    """Build neighbour, face normal, face length, and dCF arrays."""
    nc = mesh.n_cells
    cells = mesh.cells

    mesh.nbr     = np.full((nc, 3), -1, dtype=np.int32)
    mesh.face_len = np.zeros((nc, 3), dtype=np.float64)
    mesh.face_nx  = np.zeros((nc, 3), dtype=np.float64)
    mesh.face_ny  = np.zeros((nc, 3), dtype=np.float64)
    mesh.dCF      = np.zeros((nc, 3), dtype=np.float64)

    # Build edge → cell map
    # Face fi of cell ci is opposite vertex fi: nodes are (fi+1)%3 and (fi+2)%3
    edge_map = {}  # (n_lo, n_hi) → (cell_idx, face_idx)
    for ci in range(nc):
        for fi in range(3):
            n0 = cells[ci, (fi + 1) % 3]
            n1 = cells[ci, (fi + 2) % 3]
            key = (min(n0, n1), max(n0, n1))
            if key in edge_map:
                cj, fj = edge_map[key]
                mesh.nbr[ci, fi] = cj
                mesh.nbr[cj, fj] = ci
            else:
                edge_map[key] = (ci, fi)

    # Compute face geometry
    nodes = mesh.nodes
    cc = mesh.cell_centers
    for ci in range(nc):
        for fi in range(3):
            n0 = cells[ci, (fi + 1) % 3]
            n1 = cells[ci, (fi + 2) % 3]
            p0, p1 = nodes[n0], nodes[n1]

            # Face length
            edge = p1 - p0
            flen = np.linalg.norm(edge)
            mesh.face_len[ci, fi] = flen

            # Outward normal (perpendicular to edge, pointing away from vertex fi)
            # For CCW triangle, outward normal of edge opposite vertex fi:
            nx_raw, ny_raw = edge[1], -edge[0]  # rotate edge 90° CW
            # Check direction: should point away from vertex fi
            v_fi = nodes[cells[ci, fi]]
            face_mid = 0.5 * (p0 + p1)
            if nx_raw * (face_mid[0] - v_fi[0]) + ny_raw * (face_mid[1] - v_fi[1]) < 0:
                nx_raw, ny_raw = -nx_raw, -ny_raw
            # Normalise
            if flen > 1e-30:
                mesh.face_nx[ci, fi] = nx_raw / flen
                mesh.face_ny[ci, fi] = ny_raw / flen

            # Centre-to-neighbour (or centre-to-face for boundary)
            j = mesh.nbr[ci, fi]
            if j >= 0:
                mesh.dCF[ci, fi] = np.linalg.norm(cc[j] - cc[ci])
            else:
                mesh.dCF[ci, fi] = np.linalg.norm(face_mid - cc[ci])


def _classify_boundaries(mesh):
    """Classify boundary faces by polygon edge index. Default BC = wall."""
    nc = mesh.n_cells
    mesh.bc_type = np.zeros((nc, 3), dtype=np.int32)
    mesh._bnd_edge_id = np.full((nc, 3), -1, dtype=np.int32)

    verts = mesh.polygon
    n_v = len(verts)
    nodes = mesh.nodes
    cells = mesh.cells

    # Precompute edge directions and normals
    edge_dirs = []
    edge_lens = []
    for i in range(n_v):
        p0 = verts[i]
        p1 = verts[(i + 1) % n_v]
        d = p1 - p0
        edge_lens.append(np.linalg.norm(d))
        edge_dirs.append(d)

    for ci in range(nc):
        for fi in range(3):
            if mesh.nbr[ci, fi] >= 0:
                continue  # interior face
            mesh.bc_type[ci, fi] = BC_WALL  # default

            # Find which polygon edge this boundary face belongs to
            n0 = cells[ci, (fi + 1) % 3]
            n1 = cells[ci, (fi + 2) % 3]
            face_mid = 0.5 * (nodes[n0] + nodes[n1])

            best_dist = 1e30
            best_edge = -1
            for ei in range(n_v):
                p0 = verts[ei]
                d = edge_dirs[ei]
                elen = edge_lens[ei]
                if elen < 1e-30:
                    continue
                # Project face midpoint onto edge
                t = np.dot(face_mid - p0, d) / (elen ** 2)
                t = np.clip(t, 0.0, 1.0)
                proj = p0 + t * d
                dist = np.linalg.norm(face_mid - proj)
                if dist < best_dist:
                    best_dist = dist
                    best_edge = ei

            mesh._bnd_edge_id[ci, fi] = best_edge


# ===================================================================
#  Preset polygon shapes
# ===================================================================

def rectangle(W, H):
    """Return vertices for a W × H rectangle centred at origin."""
    return np.array([[0, 0], [W, 0], [W, H], [0, H]], dtype=np.float64)


def hexagon(W, H):
    """Elongated hexagon fitting inside W × H bounding box."""
    dx = W * 0.15
    return np.array([
        [dx, 0], [W - dx, 0], [W, H / 2], [W - dx, H], [dx, H], [0, H / 2]
    ], dtype=np.float64)


def octagon(W, H):
    """Octagon fitting inside W × H bounding box."""
    dx = W * 0.2
    dy = H * 0.2
    return np.array([
        [dx, 0], [W - dx, 0], [W, dy], [W, H - dy],
        [W - dx, H], [dx, H], [0, H - dy], [0, dy]
    ], dtype=np.float64)
