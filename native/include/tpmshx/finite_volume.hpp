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

struct TemperatureStateView {
    ArrayView<double> a, b, solid;
};

}  // namespace tpmshx
