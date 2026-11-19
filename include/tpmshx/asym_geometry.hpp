#pragma once
#include "tpmshx/geometry.hpp"
#include <array>
#include <cstdint>
#include <optional>
#include <vector>

namespace tpmshx::geometry::asym {
using Sides = std::array<double, 2>;
struct Levels {
    double lower, upper, comparison_lower, comparison_upper;
    std::uint32_t lower_precision, upper_precision;
};
struct Porosity { double a, b, total; };
struct SplitFields { std::vector<double> a, b; };
struct ThermalSide { double area, diameter, reference_area, reference_diameter; };
struct PreparedSides {
    double split_a;
    std::optional<std::array<ThermalSide, 2>> sides;
};

// All views borrow contiguous C-order input buffers for the call.
Porosity eps_sides(ArrayView<const double> phi, const Levels& levels);
std::int64_t count_interface(ArrayView<const std::uint8_t> a,
                             ArrayView<const std::uint8_t> b, const Shape& shape);
// N is an independent numerical divisor. It does not define the input shape.
Sides a0_sides(ArrayView<const double> phi, const Shape& shape, const Levels& levels,
               double length_m, double N, double area_correction);
Sides a0_sides_mc(ArrayView<const double> phi, const Shape& shape, const Levels& levels,
                  double length_m, double N);
Sides dh_from_sides(double eps_a, double eps_b, double area_a, double area_b);
Sides dh_sides(ArrayView<const double> phi, const Shape& shape, const Levels& levels,
               double length_m, double N, double area_correction, bool mc=false);
double wall_thickness_from_sides(double eps_total, double area_a, double area_b);
double wall_thickness(ArrayView<const double> phi, const Shape& shape, const Levels& levels,
                      double length_m, double N, double area_correction);
double split_a(ArrayView<const double> phi, const Levels& levels, bool zero_delta);
// The zero-delta Python path returns its original eps_f_arr for both sides.
SplitFields split_porosity(ArrayView<const double> eps_total, double fraction_a);
PreparedSides prepare_sides(ArrayView<const double> phi, const Shape& shape, const Levels& levels,
                            const Levels& reference_levels, bool zero_delta,
                            double length_m, double N, double area_correction);
double split_from_index(const PhiIndex& index, const Calibration& model,
                        double cell_mm, double wall_mm, double delta);
PreparedSides prepare_from_index(const PhiIndex& index, const Calibration& model,
                                 double cell_mm, double wall_mm, double delta);
}  // namespace tpmshx::geometry::asym
