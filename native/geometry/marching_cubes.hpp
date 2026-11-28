// Derived from scikit-image 0.26.0. See THIRD_PARTY_NOTICES.md for source and licenses.
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace tpmshx::geometry::marching_cubes {
struct Mesh {
    // Unscaled float32 coordinates in NumPy axis order; no normals or values.
    std::vector<std::array<float, 3>> vertices;
    // The existing descent winding and all degenerate triangles are retained.
    std::vector<std::array<std::int32_t, 3>> faces;
};

// Input layout: NumPy C-order shape (Nx, Ny, Nz), with Nz contiguous.
Mesh mesh(const float* volume, std::size_t Nx, std::size_t Ny, std::size_t Nz,
          double level);
double area(const float* volume, std::size_t Nx, std::size_t Ny, std::size_t Nz,
            double level, const std::array<double, 3>& spacing);
}  // namespace tpmshx::geometry::marching_cubes
