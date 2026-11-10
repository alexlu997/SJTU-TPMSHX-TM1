#include "tpmshx/geometry.hpp"
#include "tpmshx/model_coefficients.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <numeric>
#include <set>
#include <stdexcept>
#include <utility>

namespace tpmshx::geometry {
namespace {
namespace data = model_coefficients;

std::size_t topology_row(Topology topology) {
    switch (topology) {
    case Topology::diamond: return 0;
    case Topology::gyroid: return 1;
    }
    throw std::invalid_argument("TPMS geometry supports Diamond and Gyroid only");
}

std::size_t voxel_count(const Shape& shape) {
    std::size_t count = 1;
    for (const auto length : shape) {
        if (!length || count > std::numeric_limits<std::size_t>::max() / length)
            throw std::invalid_argument("geometry shape must have positive representable dimensions");
        count *= length;
    }
    if (count > static_cast<std::size_t>(std::numeric_limits<std::int64_t>::max() / 6))
        throw std::invalid_argument("geometry face count exceeds int64 range");
    return count;
}

void check_view(ArrayView<const double> values) {
    if (values.size && !values.data)
        throw std::invalid_argument("geometry input has a null buffer");
}

void check_pair(ArrayView<const double> cells, ArrayView<const double> walls) {
    check_view(cells);
    check_view(walls);
    if (cells.size != walls.size)
        throw std::invalid_argument("L/t fields must have the same array shape");
}

double hydraulic_diameter(double epsilon, double area_density) {
    return 4.0 * (0.5 * epsilon) / area_density;
}

Geometry geometry_values(const RawGeometry& raw, double diameter) {
    return {raw.epsilon, 0.5 * raw.epsilon, 0.5 * raw.epsilon,
            raw.area_density, diameter};
}

struct Bracket {
    std::size_t lower, upper;
    double weight;
};

template <std::size_t Size>
Bracket co2_bracket(double value, const std::array<double, Size>& nodes) {
    if (!std::isfinite(value) || value < nodes.front() - 1e-12 || value > nodes.back() + 1e-12)
        throw std::invalid_argument(
            "CO2 geometry requires 4 <= L <= 8 mm and 0.3 <= t <= 0.6 mm; no extrapolation");
    value = std::min(std::max(value, nodes.front()), nodes.back());
    const auto upper = static_cast<std::size_t>(
        std::lower_bound(nodes.begin(), nodes.end(), value) - nodes.begin());
    if (upper == 0 || std::abs(value - nodes[upper]) < 1e-12)
        return {upper, upper, 0.};
    return {upper - 1, upper, (value - nodes[upper - 1]) / (nodes[upper] - nodes[upper - 1])};
}
}  // namespace

Calibration calibration(Topology topology) {
    const auto row = topology_row(topology);
    return {data::geometry_level_set[row], data::geometry_solid_tortuosity[row],
            data::geometry_area_correction};
}

std::vector<double> phi_grid(Topology topology, std::size_t n) {
    topology_row(topology);
    const auto count = voxel_count({n, n, n});
    constexpr double pi = 3.141592653589793238462643383279502884;
    const double h = 2.0 * pi / static_cast<double>(n);
    const double start = h / 2.0, stop = 2.0 * pi - h / 2.0;
    const double step = n > 1 ? (stop - start) / static_cast<double>(n - 1) : 0.;
    std::vector<double> s(n), c(n);
    for (std::size_t i = 0; i < n; ++i) {
        const double x = n > 1 && i == n - 1 ? stop : static_cast<double>(i) * step + start;
        s[i] = std::sin(x);
        c[i] = std::cos(x);
    }
    std::vector<double> phi(count);
    for (std::size_t i = 0; i < n; ++i)
        for (std::size_t j = 0; j < n; ++j)
            for (std::size_t k = 0; k < n; ++k)
                phi[(i * n + j) * n + k] = topology == Topology::diamond
                    ? s[i]*s[j]*s[k] + s[i]*c[j]*c[k] + c[i]*s[j]*c[k] + c[i]*c[j]*s[k]
                    : s[i]*c[j] + s[j]*c[k] + s[k]*c[i];
    return phi;
}

double level_set_threshold(const Coefficients& coefficients, double wall_over_cell) {
    return coefficients[0] * wall_over_cell + coefficients[1] * std::pow(wall_over_cell, 2.0);
}

double hydraulic_radius(double hydraulic_diameter) {
    return hydraulic_diameter / 2.0;
}

PhiIndex::PhiIndex(Shape shape, std::vector<double> phi) : shape_(shape), phi_(std::move(phi)) {
    const auto count = voxel_count(shape_);
    if (phi_.size() != count)
        throw std::invalid_argument("phi shape and buffer size disagree");
    std::vector<double> values(count);
    for (std::size_t i = 0; i < count; ++i) {
        if (!std::isfinite(phi_[i]))
            throw std::invalid_argument("phi values must be finite");
        values[i] = std::abs(phi_[i]);
    }
    std::vector<std::int8_t> weights(count, 0);
    const auto edge = [&](std::size_t first, std::size_t second) {
        const int delta = static_cast<int>(values[first] < values[second])
                        - static_cast<int>(values[first] > values[second]);
        weights[first] = static_cast<std::int8_t>(weights[first] + delta);
        weights[second] = static_cast<std::int8_t>(weights[second] - delta);
    };
    for (std::size_t i = 0; i < shape_[0]; ++i)
        for (std::size_t j = 0; j < shape_[1]; ++j)
            for (std::size_t k = 0; k < shape_[2]; ++k) {
                const auto first = (i * shape_[1] + j) * shape_[2] + k;
                if (i + 1 < shape_[0]) edge(first, first + shape_[1] * shape_[2]);
                if (j + 1 < shape_[1]) edge(first, first + shape_[2]);
                if (k + 1 < shape_[2]) edge(first, first + 1);
            }
    std::vector<std::size_t> order(count);
    std::iota(order.begin(), order.end(), std::size_t{0});
    std::sort(order.begin(), order.end(), [&](std::size_t first, std::size_t second) {
        return values[first] < values[second];
    });
    ordered_abs_.resize(count);
    face_prefix_.resize(count + 1);
    face_prefix_[0] = 0;
    for (std::size_t i = 0; i < count; ++i) {
        ordered_abs_[i] = values[order[i]];
        face_prefix_[i + 1] = face_prefix_[i] + static_cast<std::int64_t>(weights[order[i]]);
    }
}

PhiIndex PhiIndex::from_topology(Topology topology, std::size_t n) {
    return PhiIndex({n, n, n}, phi_grid(topology, n));
}

std::size_t PhiIndex::resolution() const {
    if (shape_[0] != shape_[1] || shape_[1] != shape_[2])
        throw std::invalid_argument("standard TPMS geometry requires a cubic phi grid");
    return shape_[0];
}

Counts PhiIndex::counts(double inclusive_threshold) const {
    const auto occupied = static_cast<std::size_t>(
        std::upper_bound(ordered_abs_.begin(), ordered_abs_.end(), inclusive_threshold) - ordered_abs_.begin());
    return {occupied, ordered_abs_.size(), face_prefix_[occupied]};
}

RawGeometry raw_geometry(const PhiIndex& index, const Calibration& model,
                         double cell_mm, double wall_mm) {
    const auto n = index.resolution();
    const double cell_m = cell_mm / 1000.0;
    const double ratio = wall_mm / cell_mm;
    const double threshold = std::max(level_set_threshold(model.level_set, ratio), 0.0);
    const auto count = index.counts(threshold);
    const double epsilon = 1.0 - static_cast<double>(count.occupied) / static_cast<double>(count.voxels);
    const double area = static_cast<double>(count.faces) * std::pow(cell_m / static_cast<double>(n), 2.0)
                      / (2.0 * std::pow(cell_m, 3.0) * model.area_correction);
    return {epsilon, area};
}

Geometry standard_geometry(const PhiIndex& index, const Calibration& model,
                           double cell_mm, double wall_mm) {
    if (cell_mm <= 0.) throw std::invalid_argument("L_mm must be positive");
    if (wall_mm <= 0.) throw std::invalid_argument("t_mm must be positive");
    if (2.0 * wall_mm >= cell_mm)
        throw std::invalid_argument("Wall thickness must satisfy 2*t < L, with usable pore space");
    const auto raw = raw_geometry(index, model, cell_mm, wall_mm);
    const double diameter = raw.area_density > 0. ? hydraulic_diameter(raw.epsilon, raw.area_density) : 0.;
    if (raw.epsilon <= 1e-9 || raw.area_density <= 0. || diameter <= 0.)
        throw std::invalid_argument("Degenerate TPMS geometry: no usable pore space");
    return geometry_values(raw, diameter);
}

std::vector<Geometry> standard_geometry_batch(const PhiIndex& index, const Calibration& model,
                                              ArrayView<const double> cells_mm,
                                              ArrayView<const double> walls_mm) {
    check_pair(cells_mm, walls_mm);
    for (std::size_t i = 0; i < cells_mm.size; ++i)
        if (!std::isfinite(cells_mm[i]) || !std::isfinite(walls_mm[i]))
            throw std::invalid_argument("L/t fields must be finite");
    for (std::size_t i = 0; i < cells_mm.size; ++i)
        if (cells_mm[i] <= 0.) throw std::invalid_argument("L_mm must be positive");
    for (std::size_t i = 0; i < walls_mm.size; ++i)
        if (walls_mm[i] <= 0.) throw std::invalid_argument("t_mm must be positive");
    for (std::size_t i = 0; i < cells_mm.size; ++i)
        if (2.0 * walls_mm[i] >= cells_mm[i])
            throw std::invalid_argument("Wall thickness must satisfy 2*t < L, with usable pore space");
    index.resolution();
    std::vector<Geometry> result(cells_mm.size);
    for (std::size_t i = 0; i < cells_mm.size; ++i) {
        const auto raw = raw_geometry(index, model, cells_mm[i], walls_mm[i]);
        result[i] = geometry_values(raw, 0.);
    }
    for (const auto& value : result)
        if (!(value.epsilon > 1e-9 && value.area_density > 0.
              && std::isfinite(value.epsilon) && std::isfinite(value.area_density)))
            throw std::invalid_argument("Degenerate TPMS geometry: no usable pore space");
    for (auto& value : result)
        value.hydraulic_diameter = hydraulic_diameter(value.epsilon, value.area_density);
    for (const auto& value : result)
        if (!(value.hydraulic_diameter > 0. && std::isfinite(value.hydraulic_diameter)))
            throw std::invalid_argument("Degenerate TPMS geometry: no usable hydraulic diameter");
    return result;
}

MinimumGeometry minimum_solid_geometry(const PhiIndex& index, const Calibration& model,
                                      Bounds cell_bounds_mm, Bounds wall_bounds_mm) {
    const auto& coefficient = model.level_set;
    if (std::min(coefficient[0], coefficient[0] + coefficient[1]) <= 0.)
        throw std::invalid_argument("The level-set model does not certify monotone solid volume");
    const double cell = cell_bounds_mm[1], wall = wall_bounds_mm[0];
    return {cell, wall, standard_geometry(index, model, cell, wall).epsilon};
}

double effective_chi(const Coefficients& coefficients, double epsilon,
                     std::optional<double> override_value) {
    if (override_value) return *override_value;
    return coefficients[0] + coefficients[1] * (1.0 - epsilon);
}

std::vector<double> effective_chi(const Coefficients& coefficients, ArrayView<const double> epsilon,
                                 std::optional<double> override_value) {
    check_view(epsilon);
    std::vector<double> result(epsilon.size);
    for (std::size_t i = 0; i < epsilon.size; ++i)
        result[i] = effective_chi(coefficients, epsilon[i], override_value);
    return result;
}

double solid_conductivity(const Coefficients& coefficients, double epsilon, double conductivity,
                          std::optional<double> override_value) {
    return effective_chi(coefficients, epsilon, override_value) * (1.0 - epsilon) * conductivity;
}

std::vector<double> solid_conductivity(const Coefficients& coefficients,
                                      ArrayView<const double> epsilon, double conductivity,
                                      std::optional<double> override_value) {
    check_view(epsilon);
    std::vector<double> result(epsilon.size);
    for (std::size_t i = 0; i < epsilon.size; ++i)
        result[i] = solid_conductivity(coefficients, epsilon[i], conductivity, override_value);
    return result;
}

MaterialGeometry with_material(const Geometry& geometry, const Coefficients& coefficients,
                               double conductivity, std::optional<double> override_value) {
    return {geometry, solid_conductivity(coefficients, geometry.epsilon, conductivity, override_value)};
}

LutGeometry lut_geometry(const Coefficients& coefficients, double epsilon,
                        double area_density, double conductivity,
                        std::optional<double> override_value) {
    // LUT extrapolation retains its original denominator and arithmetic order.
    const double diameter = 2.0 * epsilon / (area_density + 1e-30);
    const Geometry geometry{epsilon, epsilon / 2.0, epsilon / 2.0, area_density, diameter};
    return {with_material(geometry, coefficients, conductivity, override_value), hydraulic_radius(diameter)};
}

std::vector<MaterialGeometry> standard_material_geometry_batch(
    const PhiIndex& index, const Calibration& model, ArrayView<const double> cells_mm,
    ArrayView<const double> walls_mm, double conductivity, std::optional<double> override_value) {
    const auto geometry = standard_geometry_batch(index, model, cells_mm, walls_mm);
    std::vector<MaterialGeometry> result;
    result.reserve(geometry.size());
    for (const auto& value : geometry)
        result.push_back(with_material(value, model.solid_tortuosity, conductivity, override_value));
    return result;
}

Co2GeometryTable::Co2GeometryTable(const std::vector<Co2GeometryNode>& nodes,
                                 Coefficients solid_tortuosity)
    : cells_mm_{4., 5., 6., 7., 8.}, walls_mm_{.3, .4, .5, .6},
      solid_tortuosity_(solid_tortuosity) {
    std::map<std::pair<double, double>, Co2GeometryNode> lookup;
    std::set<double> cell_values, wall_values;
    for (const auto& node : nodes) {
        if (!std::isfinite(node.cell_mm) || !std::isfinite(node.wall_mm))
            throw std::invalid_argument("CO2 geometry requires a complete, unique 5 by 4 grid");
        const auto inserted = lookup.emplace(std::make_pair(node.cell_mm, node.wall_mm), node);
        if (!inserted.second)
            throw std::invalid_argument("CO2 geometry requires a complete, unique 5 by 4 grid");
        cell_values.insert(node.cell_mm);
        wall_values.insert(node.wall_mm);
    }
    if (lookup.size() != cells_mm_.size() * walls_mm_.size()
        || std::vector<double>(cell_values.begin(), cell_values.end())
            != std::vector<double>(cells_mm_.begin(), cells_mm_.end())
        || std::vector<double>(wall_values.begin(), wall_values.end())
            != std::vector<double>(walls_mm_.begin(), walls_mm_.end()))
        throw std::invalid_argument("CO2 geometry requires a complete, unique 5 by 4 grid");
    for (std::size_t i = 0; i < cells_mm_.size(); ++i)
        for (std::size_t j = 0; j < walls_mm_.size(); ++j) {
            const auto position = lookup.find({cells_mm_[i], walls_mm_[j]});
            if (position == lookup.end())
                throw std::invalid_argument("CO2 geometry requires a complete, unique 5 by 4 grid");
            const auto& node = position->second;
            const double cell_m = cells_mm_[i] * 1e-3;
            dimensionless_[i][j] = {node.epsilon_single,
                                    node.hydraulic_diameter_m / cell_m,
                                    node.area_density_per_m * cell_m};
        }
    for (const auto& row : dimensionless_)
        for (const auto& node : row) {
            for (const double value : node)
                if (!std::isfinite(value) || value <= 0.)
                    throw std::invalid_argument("CO2 geometry contains invalid porosity, diameter or area");
            if (node[0] >= .5)
                throw std::invalid_argument("CO2 geometry contains invalid porosity, diameter or area");
        }
}

Co2GeometryTable Co2GeometryTable::from_generated(Topology topology) {
    const auto row = topology_row(topology);
    std::vector<Co2GeometryNode> nodes;
    nodes.reserve(data::co2_geometry_nodes[row].size());
    for (const auto& node : data::co2_geometry_nodes[row])
        nodes.push_back({node[0], node[1], node[2], node[3], node[4]});
    return Co2GeometryTable(nodes, data::geometry_solid_tortuosity[row]);
}

MaterialGeometry Co2GeometryTable::evaluate(double cell_mm, double wall_mm, double conductivity,
                                          std::optional<double> override_value) const {
    const auto cell = co2_bracket(cell_mm, cells_mm_);
    const auto wall = co2_bracket(wall_mm, walls_mm_);
    std::array<double, 3> value{};
    for (std::size_t quantity = 0; quantity < value.size(); ++quantity) {
        const double low = (1. - cell.weight) * dimensionless_[cell.lower][wall.lower][quantity]
                         + cell.weight * dimensionless_[cell.upper][wall.lower][quantity];
        const double high = (1. - cell.weight) * dimensionless_[cell.lower][wall.upper][quantity]
                          + cell.weight * dimensionless_[cell.upper][wall.upper][quantity];
        value[quantity] = (1. - wall.weight) * low + wall.weight * high;
    }
    const double cell_m = cell_mm * 1e-3;
    const Geometry geometry{2. * value[0], value[0], value[0], value[2] / cell_m, value[1] * cell_m};
    return with_material(geometry, solid_tortuosity_, conductivity, override_value);
}

std::vector<MaterialGeometry> Co2GeometryTable::evaluate_batch(
    ArrayView<const double> cells_mm, ArrayView<const double> walls_mm, double conductivity,
    std::optional<double> override_value) const {
    check_pair(cells_mm, walls_mm);
    std::vector<MaterialGeometry> result;
    result.reserve(cells_mm.size);
    for (std::size_t i = 0; i < cells_mm.size; ++i)
        result.push_back(evaluate(cells_mm[i], walls_mm[i], conductivity, override_value));
    return result;
}

MinimumGeometry Co2GeometryTable::minimum_solid_geometry(
    Bounds cell_bounds_mm, Bounds wall_bounds_mm, std::optional<double> override_value) const {
    for (const double cell : cell_bounds_mm) co2_bracket(cell, cells_mm_);
    for (const double wall : wall_bounds_mm) co2_bracket(wall, walls_mm_);
    std::set<double> cells{cell_bounds_mm[0], cell_bounds_mm[1]};
    std::set<double> walls{wall_bounds_mm[0], wall_bounds_mm[1]};
    for (const double cell : cells_mm_)
        if (cell_bounds_mm[0] < cell && cell < cell_bounds_mm[1]) cells.insert(cell);
    for (const double wall : walls_mm_)
        if (wall_bounds_mm[0] < wall && wall < wall_bounds_mm[1]) walls.insert(wall);
    MinimumGeometry best{};
    bool first = true;
    for (const double cell : cells)
        for (const double wall : walls) {
            const double epsilon = evaluate(cell, wall, 1., override_value).geometry.epsilon;
            if (first || epsilon > best.epsilon) {
                best = {cell, wall, epsilon};
                first = false;
            }
        }
    return best;
}

}  // namespace tpmshx::geometry
