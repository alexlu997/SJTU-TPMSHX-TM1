#pragma once
#include "tpmshx/finite_volume.hpp"
#include <array>
#include <vector>

namespace tpmshx {

// Bisect each actual cell while retaining every original cumulative endpoint:
// first=width/2; second=coarse_endpoint-current_fine_position.
std::vector<double> split_refinement_cells(ArrayView<const double> widths);

// Original Richardson cell-centre RGI(linear, bounds_error=false, fill=None).
// Coordinates are cumsum(width)-width/2. Extrapolates beyond the coarse
// centres; a one-cell axis extends constantly. Field shape is (dx.size,dy.size)
// and output is (fine_dx.size,fine_dy.size), C order. Scalar/1D caller values
// are passed through by the outer driver and do not use this 2D primitive.
// No physical clamp, property evaluation or temperature guard is performed.
std::vector<double> refine_cell_field_2d(
    ArrayView<const double> dx,ArrayView<const double> dy,
    ArrayView<const double> fine_dx,ArrayView<const double> fine_dy,
    ArrayView<const double> field);

// Transfer actual signed integrated faces, including nonnested partitions.
// Shapes: coarse mass_x(nx+1,ny), mass_y(nx,ny+1); corresponding fine shapes.
// Linear interpolation in the normal direction and physical overlap integral
// transversely preserve the original coarse divergence as an overlap integral.
// Domain equality uses original isclose(rtol=1e-12,atol=1e-15); only the fine
// final edges are then replaced by coarse final edges to remove cumsum drift.
// No fine momentum solve, balancing, port masking or mass normalization.
std::array<std::vector<double>,2> prolong_mass_faces_2d(
    const std::array<ArrayView<const double>,2>& mass,
    ArrayView<const double> dx,ArrayView<const double> dy,
    ArrayView<const double> fine_dx,ArrayView<const double> fine_dy);

// Original diff(interp(fine_edges,coarse_edges,cumsum(inlet_capacity))).
// Already integrated and signed: no extra area/opening factor. np.interp's
// constant endpoint extension is preserved; no endpoint normalization occurs.
std::vector<double> refine_inlet_capacity(
    ArrayView<const double> coarse_widths,ArrayView<const double> fine_widths,
    ArrayView<const double> capacity);

}  // namespace tpmshx
