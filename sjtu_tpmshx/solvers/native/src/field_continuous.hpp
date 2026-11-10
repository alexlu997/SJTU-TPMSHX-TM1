#pragma once
#include <cstddef>
#include <memory>
#include <vector>

namespace tpmshx::fields {
using Values = std::vector<double>;
class XYFit {
public:
    XYFit(const double* x, std::size_t nx, const double* y, std::size_t ny,
          const double* values, std::size_t count, int degree_x, int degree_y);
    ~XYFit();
    XYFit(const XYFit&) = delete;
    XYFit& operator=(const XYFit&) = delete;
    Values sample(const double* current_values, std::size_t current_count,
                  const double* x, std::size_t nx, const double* y, std::size_t ny,
                  double lower, double upper) const;
private:
    struct State;
    std::unique_ptr<State> state_;
};

Values sample_tensor(std::size_t dimension, const std::size_t* control_counts,
    const double* const* control_axes, const double* values, std::size_t value_count,
    int order, const std::size_t* sample_counts, const double* const* sample_axes,
    double lower, double upper);

std::size_t field_extent(std::size_t first, std::size_t second);
void sample_axis(const double* axis, std::size_t count);
bool constant_values(const double* values, std::size_t count);
void clip_field(Values& values, double lower, double upper);
}  // namespace tpmshx::fields
