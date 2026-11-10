#include "tpmshx/preparation_df.hpp"
#include "tpmshx/scalar_precision.hpp"
#include "contiguous_sum.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <vector>

namespace tpmshx::preparation {
namespace {
namespace precision = geometry::detail;
double sum(const std::vector<double>& values, std::uint32_t bits, bool contiguous) {
    if (bits == 64) {
        if (contiguous) return 0. + detail::contiguous_sum({values.data(), values.size()});
        double result = 0.;
        for (double value : values) result += value;
        return result;
    }
    std::vector<float> packed(values.begin(), values.end());
    float result = 0.;
    if (contiguous) result += detail::contiguous_sum<float>({packed.data(), packed.size()});
    else if (bits == 16) {
        for (float value : packed)
            result = static_cast<float>(precision::round_scalar(result + value, bits));
    } else for (float value : packed) result += value;
    return precision::round_scalar(result, bits);
}
std::vector<double> means(std::size_t nx, std::size_t ny, ArrayView<const double> field,
    std::uint32_t bits, std::uint32_t direction, ArrayView<const double> weights,
    std::uint32_t weight_bits, bool column_major) {
    precision::require_precision(bits);
    const bool stream_x = direction < 2;
    const std::size_t rows = stream_x ? nx : ny, cross = stream_x ? ny : nx;
    const bool weighted = weights.size != 0;
    if (weighted) precision::require_precision(weight_bits);
    const auto result_bits = weighted ? std::max(bits, weight_bits) : bits;
    const auto accumulation_bits = !weighted && bits == 16 ? 32u : result_bits;
    std::vector<double> output(rows), samples(cross);
    std::vector<double> weight_values;
    if (weighted) weight_values.assign(weights.data, weights.data + weights.size);
    const double denominator = weighted ? sum(weight_values, result_bits, true) : static_cast<double>(cross);
    if (weighted && denominator == 0.) throw std::domain_error("Weights sum to zero, can't be normalized");
    for (std::size_t row = 0; row < rows; ++row) {
        for (std::size_t j = 0; j < cross; ++j) {
            const double value = field[stream_x ? row * ny + j : j * ny + row];
            samples[j] = weighted ? precision::multiply(value, weights[j], result_bits) : value;
        }
        const double numerator = sum(samples, accumulation_bits, rows == 1 || stream_x != column_major);
        output[row] = precision::round_scalar(precision::divide(numerator, denominator, accumulation_bits), result_bits);
    }
    return output;
}
}  // namespace

DfRows df_project_rows(std::size_t nx, std::size_t ny,
    ArrayView<const double> lengths, ArrayView<const double> walls,
    std::uint32_t length_precision, std::uint32_t wall_precision,
    bool length_column_major, bool wall_column_major,
    std::uint32_t direction, std::size_t target_count,
    ArrayView<const double> dx, std::uint32_t dx_precision,
    ArrayView<const double> dy, std::uint32_t dy_precision,
    ArrayView<const double> target_widths) {
    if (direction > 3 || !nx || !ny)
        throw std::invalid_argument("projection needs nonempty physical axes and direction 0, 1, 2 or 3");
    const bool stream_x = direction < 2;
    const auto cross_weights = stream_x ? dy : dx;
    const auto cross_precision = stream_x ? dy_precision : dx_precision;
    auto l = means(nx, ny, lengths, length_precision, direction, cross_weights, cross_precision, length_column_major);
    auto t = means(nx, ny, walls, wall_precision, direction, cross_weights, cross_precision, wall_column_major);
    auto stream_widths = stream_x ? dx : dy;
    const auto stream_precision = stream_x ? dx_precision : dy_precision;
    std::vector<double> widths;
    if (stream_widths.size) widths.assign(stream_widths.data, stream_widths.data + stream_widths.size);
    if (direction == 1 || direction == 3) {
        std::reverse(l.begin(), l.end()); std::reverse(t.begin(), t.end());
        std::reverse(widths.begin(), widths.end());
    }
    std::vector<double> fractions(target_count);
    if (!target_widths.size) {
        for (std::size_t i = 0; i < target_count; ++i)
            fractions[i] = (static_cast<double>(i) + .5) / static_cast<double>(target_count);
    } else {
        std::vector<double> target(target_widths.data, target_widths.data + target_widths.size);
        const double total = sum(target, 64, true);
        double previous = 0.;
        for (std::size_t i = 0; i < target_count; ++i) {
            const double next = previous + target[i];
            fractions[i] = .5 * (previous + next) / total;
            previous = next;
        }
    }
    std::vector<double> ends(widths.size());
    double total = 0.;
    if (!widths.empty()) {
        precision::require_precision(stream_precision);
        for (std::size_t i = 0; i < widths.size(); ++i) {
            total = precision::round_scalar(total + widths[i], stream_precision);
            ends[i] = total;
        }
        total = sum(widths, stream_precision, true);
    }
    DfRows output{std::vector<double>(target_count), std::vector<double>(target_count),
                  std::vector<std::int64_t>(target_count)};
    for (std::size_t i = 0; i < target_count; ++i) {
        std::size_t index;
        if (widths.empty()) {
            const double sample = fractions[i] * static_cast<double>(l.size());
            if (!std::isfinite(sample) || sample < 0.) index = 0;
            else index = sample >= static_cast<double>(l.size()) ? l.size() - 1 : static_cast<std::size_t>(sample);
        } else {
            const double sample = fractions[i] * total;
            index = std::isnan(sample) ? ends.size()
                : static_cast<std::size_t>(std::upper_bound(ends.begin(), ends.end(), sample) - ends.begin());
            index = std::min(index, l.size() - 1);
        }
        output.lengths[i] = l[index]; output.walls[i] = t[index];
        output.source_index[i] = static_cast<std::int64_t>(index);
    }
    return output;
}

std::vector<DfPair> df_row_means(std::size_t rows, std::size_t columns,
    ArrayView<const double> permeability, ArrayView<const double> inertial,
    bool permeability_column_major, bool inertial_column_major) {
    std::vector<DfPair> output(columns);
    std::vector<double> k_samples(rows), f_samples(rows);
    for (std::size_t column = 0; column < columns; ++column) {
        for (std::size_t row = 0; row < rows; ++row) {
            k_samples[row] = permeability[row * columns + column];
            f_samples[row] = inertial[row * columns + column];
        }
        output[column] = {sum(k_samples, 64, columns == 1 || permeability_column_major) / static_cast<double>(rows),
                          sum(f_samples, 64, columns == 1 || inertial_column_major) / static_cast<double>(rows)};
    }
    return output;
}

}  // namespace tpmshx::preparation
