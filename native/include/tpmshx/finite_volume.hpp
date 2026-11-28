#pragma once

#include <cstddef>

namespace tpmshx {

namespace detail {
inline double diffusion_conductance(double a, double b, double dl, double dr) {
    return a <= 0.0 || b <= 0.0 ? 0.0 : a * b / (dl * b + dr * a);
}
}  // namespace detail

// Borrowed contiguous storage; the caller retains ownership for the whole call.
template <typename T> struct ArrayView {
    T* data;
    std::size_t size;
    T& operator[](std::size_t index) const { return data[index]; }
};

struct GridView {
    std::size_t nx, ny, nz;
    ArrayView<const double> dx, dy, dz;  // m; positive cell widths
};

struct TemperatureBoundary {
    int direction;  // 0:+x, 1:-x, 2:+y, 3:-y, 4:+z, 5:-z
    double inlet_temperature;
    // Optional materialized face arrays. Empty profile/opening means Tin/1.
    // A supplied capacity_flux is signed inward and already includes opening.
    // Shapes: (ny,nz), (nx,nz), or (nx,ny), according to direction.
    ArrayView<const double> profile{}, opening{}, capacity_flux{};
};

struct TemperatureStateView {
    ArrayView<double> a, b, solid;
};

}  // namespace tpmshx
