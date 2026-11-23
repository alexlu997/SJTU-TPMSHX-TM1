#pragma once

#include "tpmshx/finite_volume.hpp"
#include "tpmshx/fluid_properties.hpp"
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

namespace tpmshx::geometry {

using Shape = std::array<std::size_t, 3>;
using Coefficients = std::array<double, 2>;
using Bounds = std::array<double, 2>;

struct Calibration {
    Coefficients level_set, solid_tortuosity;
    double area_correction;
};

Calibration calibration(Topology topology);
std::vector<double> phi_grid(Topology topology, std::size_t n);
double level_set_threshold(const Coefficients& coefficients, double wall_over_cell);
double hydraulic_radius(double hydraulic_diameter);

struct Counts {
    std::size_t occupied, voxels;
    std::int64_t faces;
};

class PhiIndex {
public:
    PhiIndex(Shape shape, std::vector<double> phi);
    static PhiIndex from_topology(Topology topology, std::size_t n);
    const Shape& shape() const noexcept { return shape_; }
    const std::vector<double>& phi() const noexcept { return phi_; }
    const std::vector<double>& ordered_abs() const noexcept { return ordered_abs_; }
    const std::vector<std::int64_t>& face_prefix() const noexcept { return face_prefix_; }
    std::size_t resolution() const;
    Counts counts(double inclusive_threshold) const;
private:
    Shape shape_;
    std::vector<double> phi_, ordered_abs_;
    std::vector<std::int64_t> face_prefix_;
};

struct RawGeometry {
    double epsilon, area_density;
};

struct Geometry {
    double epsilon, epsilon_a, epsilon_b, area_density, hydraulic_diameter;
};

struct MaterialGeometry {
    Geometry geometry;
    double solid_conductivity;
};

struct LutGeometry {
    MaterialGeometry material;
    double hydraulic_radius;
};

struct MinimumGeometry {
    double cell_mm, wall_mm, epsilon;
};

RawGeometry raw_geometry(const PhiIndex& index, const Calibration& model,
                         double cell_mm, double wall_mm);
Geometry standard_geometry(const PhiIndex& index, const Calibration& model,
                           double cell_mm, double wall_mm);
std::vector<Geometry> standard_geometry_batch(const PhiIndex& index, const Calibration& model,
                                              ArrayView<const double> cells_mm,
                                              ArrayView<const double> walls_mm);
MinimumGeometry minimum_solid_geometry(const PhiIndex& index, const Calibration& model,
                                      Bounds cell_bounds_mm, Bounds wall_bounds_mm);

double effective_chi(const Coefficients& coefficients, double epsilon,
                     std::optional<double> override_value = std::nullopt);
std::vector<double> effective_chi(const Coefficients& coefficients, ArrayView<const double> epsilon,
                                 std::optional<double> override_value = std::nullopt);
double solid_conductivity(const Coefficients& coefficients, double epsilon, double conductivity,
                          std::optional<double> override_value = std::nullopt);
std::vector<double> solid_conductivity(const Coefficients& coefficients,
                                      ArrayView<const double> epsilon, double conductivity,
                                      std::optional<double> override_value = std::nullopt);
MaterialGeometry with_material(const Geometry& geometry, const Coefficients& coefficients,
                               double conductivity,
                               std::optional<double> override_value = std::nullopt);
LutGeometry lut_geometry(const Coefficients& coefficients, double epsilon,
                        double area_density, double conductivity,
                        std::optional<double> override_value = std::nullopt);
std::vector<MaterialGeometry> standard_material_geometry_batch(
    const PhiIndex& index, const Calibration& model, ArrayView<const double> cells_mm,
    ArrayView<const double> walls_mm, double conductivity,
    std::optional<double> override_value = std::nullopt);

struct Co2GeometryNode {
    double cell_mm, wall_mm, epsilon_single, hydraulic_diameter_m, area_density_per_m;
};

class Co2GeometryTable {
public:
    Co2GeometryTable(const std::vector<Co2GeometryNode>& nodes, Coefficients solid_tortuosity);
    static Co2GeometryTable from_generated(Topology topology);
    MaterialGeometry evaluate(double cell_mm, double wall_mm, double conductivity = 1.,
                              std::optional<double> override_value = std::nullopt) const;
    std::vector<MaterialGeometry> evaluate_batch(
        ArrayView<const double> cells_mm, ArrayView<const double> walls_mm,
        double conductivity = 1., std::optional<double> override_value = std::nullopt) const;
    MinimumGeometry minimum_solid_geometry(
        Bounds cell_bounds_mm, Bounds wall_bounds_mm,
        std::optional<double> override_value = std::nullopt) const;
    const std::array<double, 5>& cells_mm() const noexcept { return cells_mm_; }
    const std::array<double, 4>& walls_mm() const noexcept { return walls_mm_; }
    const std::array<std::array<std::array<double, 3>, 4>, 5>& dimensionless() const noexcept {
        return dimensionless_;
    }
private:
    std::array<double, 5> cells_mm_;
    std::array<double, 4> walls_mm_;
    std::array<std::array<std::array<double, 3>, 4>, 5> dimensionless_;
    Coefficients solid_tortuosity_;
};

}  // namespace tpmshx::geometry
