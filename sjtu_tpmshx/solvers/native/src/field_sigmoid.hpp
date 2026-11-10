#pragma once
#include "tpmshx/grid.hpp"
#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace tpmshx::fields {
using FieldScalar = tpmshx::grid::Scalar;
enum class ExpMode : std::uint32_t { libm=0, numpy_fma=1 };
struct SigmoidResult {
    std::vector<double> values;
    std::uint32_t precision;
    std::vector<std::uint32_t> exp_overflow;
};
SigmoidResult sigmoid_values(const double* values, std::size_t count,
    FieldScalar kind, FieldScalar center, FieldScalar width, ExpMode mode);
SigmoidResult sigmoid_blend(const double* x, std::size_t count, FieldScalar x_kind,
    const FieldScalar* boundaries, std::size_t boundary_count,
    const double* layers, const FieldScalar* layer_kinds, std::size_t layer_count,
    FieldScalar width, ExpMode mode);
SigmoidResult sigmoid_field(const double* x, const double* y, std::size_t count,
    FieldScalar x_kind, FieldScalar y_kind, const std::array<FieldScalar, 9>& inlet,
    const std::array<FieldScalar, 9>& outlet, FieldScalar uniform,
    const std::array<FieldScalar, 6>& boundaries, FieldScalar width_x, FieldScalar width_y,
    ExpMode mode);
}  // namespace tpmshx::fields

namespace tpmshx::fields {
SigmoidResult clip_values(const double* values, std::size_t count,
    FieldScalar kind, FieldScalar lower, FieldScalar upper);
}
