#include "tpmshx/geometry_c_api.h"
#include "tpmshx/zones_c_api.h"
#include "tpmshx/zones.hpp"
#include "tpmshx/geometry.hpp"
#include "tpmshx/asym_geometry.hpp"
#include "tpmshx/scalar_precision.hpp"
#include <algorithm>
#include <array>
#include <cstdio>
#include <exception>
#include <limits>
#include <memory>
#include <optional>
#include <stdexcept>
#include <utility>
#include <vector>

namespace g = tpmshx::geometry;
namespace a = tpmshx::geometry::asym;

struct tpmshx_geometry_index_v1 {
    g::PhiIndex value;
    std::optional<tpmshx::Topology> generated_topology;
    tpmshx_geometry_index_v1(g::PhiIndex field, std::optional<tpmshx::Topology> topology)
        : value(std::move(field)), generated_topology(topology) {}
};

namespace {
bool error_buffer_valid(char* error, std::size_t capacity) {
    if (!error || !capacity) return false;
    const auto address = reinterpret_cast<std::uintptr_t>(error);
    return capacity - 1 <= std::numeric_limits<std::uintptr_t>::max() - address;
}

void error_message(char* error, std::size_t capacity, const char* message) {
    std::snprintf(error, capacity, "%s", message);
}

template <class Operation>
int boundary(char* error, std::size_t capacity, Operation operation) {
    if (!error_buffer_valid(error, capacity)) return TPMSHX_GEOMETRY_INVALID;
    try {
        operation();
        error[0] = '\0';
        return TPMSHX_GEOMETRY_OK;
    } catch (const std::invalid_argument& exception) {
        error_message(error, capacity, exception.what());
        return TPMSHX_GEOMETRY_INVALID;
    } catch (const std::domain_error& exception) {
        error_message(error, capacity, exception.what());
        return TPMSHX_GEOMETRY_DOMAIN;
    } catch (const std::exception& exception) {
        error_message(error, capacity, exception.what());
        return TPMSHX_GEOMETRY_RUNTIME;
    } catch (...) {
        error_message(error, capacity, "unexpected native geometry exception");
        return TPMSHX_GEOMETRY_RUNTIME;
    }
}

std::size_t product(std::size_t first, std::size_t second) {
    if (second && first > std::numeric_limits<std::size_t>::max() / second)
        throw std::invalid_argument("geometry element count overflows size_t");
    return first * second;
}

template <class T>
void require_buffer(const T* pointer, std::size_t count) {
    const auto bytes = product(count, sizeof(T));
    if (!count) return;
    if (!pointer) throw std::invalid_argument("nonempty geometry buffer is null");
    const auto address = reinterpret_cast<std::uintptr_t>(pointer);
    if (address % alignof(T) || bytes - 1 > std::numeric_limits<std::uintptr_t>::max() - address)
        throw std::invalid_argument("geometry buffer address or alignment is invalid");
}

template <class T>
void require_output(T* pointer, std::size_t actual, std::size_t expected) {
    if (actual != expected) throw std::invalid_argument("geometry output element count is incorrect");
    require_buffer(pointer, actual);
}

template <class T>
tpmshx::ArrayView<const T> input(const T* pointer, std::size_t count) {
    require_buffer(pointer, count);
    return {pointer, count};
}

g::Shape input_shape(const std::size_t* values) {
    require_buffer(values, 3);
    return {values[0], values[1], values[2]};
}

std::size_t shape_size(const g::Shape& shape) {
    if (!shape[0] || !shape[1] || !shape[2]) return 0;
    std::size_t count = 1;
    for (const auto length : shape) count = product(count, length);
    if (count > static_cast<std::size_t>(std::numeric_limits<std::int64_t>::max() / 6))
        throw std::invalid_argument("geometry face count exceeds int64 range");
    return count;
}

tpmshx::ArrayView<const double> shaped_phi(const g::Shape& shape, const double* phi, std::size_t count) {
    if (count != shape_size(shape))
        throw std::invalid_argument("geometry phi size disagrees with shape");
    return input(phi, count);
}

tpmshx::Topology topology(uint32_t value) {
    switch (value) {
    case TPMSHX_GEOMETRY_DIAMOND: return tpmshx::Topology::diamond;
    case TPMSHX_GEOMETRY_GYROID: return tpmshx::Topology::gyroid;
    default: throw std::invalid_argument("TPMS geometry supports Diamond and Gyroid only");
    }
}

const tpmshx_geometry_index_v1& owner(const tpmshx_geometry_index_v1* index) {
    require_buffer(index, 1);
    return *index;
}

g::Calibration model(const tpmshx_geometry_index_v1& index, uint32_t code) {
    const auto selected = topology(code);
    if (index.generated_topology && *index.generated_topology != selected)
        throw std::invalid_argument("geometry index and requested topology disagree");
    return g::calibration(selected);
}

std::optional<double> override_constant(uint32_t present, double value) {
    if (present > 1) throw std::invalid_argument("geometry has_override must be zero or one");
    return present ? std::optional<double>{value} : std::nullopt;
}

bool marching_cubes(uint32_t method) {
    if (method > TPMSHX_GEOMETRY_MARCHING_CUBES)
        throw std::invalid_argument("geometry area method must be voxel or marching cubes");
    return method == TPMSHX_GEOMETRY_MARCHING_CUBES;
}

a::Levels raw_levels(const tpmshx_geometry_levels_v1* levels) {
    require_buffer(levels, 1);
    for (const auto precision : {levels->lower_precision, levels->upper_precision})
        g::detail::require_precision(precision);
    return {levels->lower, levels->upper, levels->comparison_lower, levels->comparison_upper,
            levels->lower_precision, levels->upper_precision};
}

bool zero_offset(uint32_t zero_delta) {
    if (zero_delta > 1) throw std::invalid_argument("geometry zero_delta must be zero or one");
    return zero_delta != 0;
}

std::int64_t int64_count(std::size_t value) {
    if (value > static_cast<std::size_t>(std::numeric_limits<std::int64_t>::max()))
        throw std::invalid_argument("geometry count exceeds int64 range");
    return static_cast<std::int64_t>(value);
}

template <class Range, class T>
void publish(const Range& values, T* output) {
    if (!values.empty()) std::copy(values.begin(), values.end(), output);
}

std::array<double, 6> material_row(const g::MaterialGeometry& value) {
    const auto& field = value.geometry;
    return {field.epsilon, field.epsilon_a, field.epsilon_b, field.area_density,
            field.hydraulic_diameter, value.solid_conductivity};
}

std::vector<double> material_rows(const std::vector<g::MaterialGeometry>& geometry) {
    std::vector<double> result(product(geometry.size(), 6));
    for (std::size_t i = 0; i < geometry.size(); ++i) {
        const auto row = material_row(geometry[i]);
        std::copy(row.begin(), row.end(), result.data() + i*6);
    }
    return result;
}

std::array<double, 3> minimum_values(const g::MinimumGeometry& value) {
    return {value.cell_mm, value.wall_mm, value.epsilon};
}

g::Bounds bounds(const double* values) {
    require_buffer(values, 2);
    return {values[0], values[1]};
}

tpmshx_geometry_prepared_sides_v1 prepared_values(const a::PreparedSides& value) {
    tpmshx_geometry_prepared_sides_v1 result{};
    result.split_a = value.split_a;
    result.has_sides = value.sides ? 1u : 0u;
    if (value.sides)
        for (std::size_t side = 0; side < 2; ++side) {
            const auto& field = (*value.sides)[side];
            result.sides[side][0] = field.area;
            result.sides[side][1] = field.diameter;
            result.sides[side][2] = field.reference_area;
            result.sides[side][3] = field.reference_diameter;
        }
    return result;
}
}  // namespace

extern "C" uint32_t TPMSHX_GEOMETRY_CALL tpmshx_geometry_abi_version_v1(void) {
    return TPMSHX_GEOMETRY_ABI_VERSION;
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_index_create_v1(
    uint32_t code, size_t n, tpmshx_geometry_index_v1** result, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        require_buffer(result, 1);
        const auto selected = topology(code);
        auto local = std::make_unique<tpmshx_geometry_index_v1>(
            g::PhiIndex::from_topology(selected, n), selected);
        *result = local.release();
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_index_create_from_phi_v1(
    const size_t* shape, const double* phi, size_t count,
    tpmshx_geometry_index_v1** result, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        require_buffer(result, 1);
        const auto dimensions = input_shape(shape);
        shaped_phi(dimensions, phi, count);
        if (!count) throw std::invalid_argument("a geometry index requires a nonempty phi grid");
        auto local = std::make_unique<tpmshx_geometry_index_v1>(
            g::PhiIndex(dimensions, std::vector<double>(phi, phi + count)), std::nullopt);
        *result = local.release();
    });
}

extern "C" void TPMSHX_GEOMETRY_CALL tpmshx_geometry_index_destroy_v1(tpmshx_geometry_index_v1* index) {
    delete index;
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_phi_grid_v1(
    uint32_t code, size_t n, double* result, size_t count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto selected = topology(code);
        if (!n) throw std::invalid_argument("geometry resolution N must be positive");
        require_output(result, count, shape_size({n, n, n}));
        const auto local = g::phi_grid(selected, n);
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_threshold_batch_v1(
    uint32_t code, const double* ratios, size_t count, uint32_t ratio_precision,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        input(ratios, count);
        g::detail::require_precision(ratio_precision);
        require_output(result, result_count, count);
        const auto calibration = g::calibration(topology(code));
        std::vector<double> local(count);
        for (std::size_t i = 0; i < count; ++i)
            local[i] = g::level_set_threshold(calibration.level_set,ratios[i],ratio_precision);
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_counts_v1(
    const tpmshx_geometry_index_v1* index, const double* thresholds, size_t count,
    int64_t* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto& field = owner(index).value;
        input(thresholds, count);
        require_output(result, result_count, product(count, 3));
        std::vector<std::int64_t> local(product(count, 3));
        for (std::size_t i = 0; i < count; ++i) {
            const auto value = field.counts(thresholds[i]);
            local[3*i] = int64_count(value.occupied);
            local[3*i+1] = value.faces;
            local[3*i+2] = int64_count(value.voxels);
        }
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_standard_batch_v1(
    const tpmshx_geometry_index_v1* index, uint32_t code,
    const double* cells, const double* walls, size_t count,
    double conductivity, uint32_t has_override, double override_value,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto& field = owner(index);
        const auto calibration = model(field, code);
        const auto selected = override_constant(has_override, override_value);
        const auto cell_view = input(cells, count), wall_view = input(walls, count);
        require_output(result, result_count, product(count, 6));
        const auto local = material_rows(g::standard_material_geometry_batch(
            field.value, calibration, cell_view, wall_view, conductivity, selected));
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_standard_scalar_v1(
    const tpmshx_geometry_index_v1* index, uint32_t code, double cell, double wall,
    uint32_t cell_precision, uint32_t ratio_precision,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto& field = owner(index);
        const auto calibration = model(field, code);
        g::detail::require_precision(cell_precision);
        g::detail::require_precision(ratio_precision);
        require_output(result, result_count, 5);
        const auto value = g::standard_geometry(
            field.value,calibration,cell,wall,cell_precision,ratio_precision);
        publish(std::array<double,5>{value.epsilon,value.epsilon_a,value.epsilon_b,
                                    value.area_density,value.hydraulic_diameter},result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_raw_batch_v1(
    const tpmshx_geometry_index_v1* index, uint32_t code,
    const double* cells, const double* walls, size_t count,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto& field = owner(index);
        const auto calibration = model(field, code);
        input(cells, count); input(walls, count);
        require_output(result, result_count, product(count, 2));
        std::vector<double> local(product(count, 2));
        for (std::size_t i = 0; i < count; ++i) {
            const auto value = g::raw_geometry(field.value, calibration, cells[i], walls[i]);
            local[2*i] = value.epsilon;
            local[2*i+1] = value.area_density;
        }
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_chi_batch_v1(
    uint32_t code, const double* epsilon, size_t count,
    uint32_t has_override, double override_value, double* result, size_t result_count,
    char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto calibration = g::calibration(topology(code));
        const auto selected = override_constant(has_override, override_value);
        const auto values = input(epsilon, count);
        require_output(result, result_count, count);
        const auto local = g::effective_chi(calibration.solid_tortuosity, values, selected);
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_material_batch_v1(
    uint32_t code, const double* epsilon, size_t count, double conductivity, uint32_t product_precision,
    uint32_t has_override, double override_value, double* result, size_t result_count,
    char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto calibration = g::calibration(topology(code));
        const auto selected = override_constant(has_override, override_value);
        g::detail::require_precision(product_precision);
        const auto values = input(epsilon, count);
        require_output(result, result_count, product(count, 2));
        const auto chi = g::effective_chi(calibration.solid_tortuosity, values, selected);
        const auto conductivity_values = g::solid_conductivity(
            calibration.solid_tortuosity,values,conductivity,selected,product_precision);
        std::vector<double> local(product(count, 2));
        for (std::size_t i = 0; i < count; ++i) {
            local[2*i] = chi[i];
            local[2*i+1] = conductivity_values[i];
        }
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_standard_minimum_v1(
    const tpmshx_geometry_index_v1* index, uint32_t code,
    const double* cell_bounds, const double* wall_bounds,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto& field = owner(index);
        const auto calibration = model(field, code);
        require_output(result, result_count, 3);
        const auto local = minimum_values(g::minimum_solid_geometry(
            field.value, calibration, bounds(cell_bounds), bounds(wall_bounds)));
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_co2_batch_v1(
    uint32_t code, const double* cells, const double* walls, size_t count,
    double conductivity, uint32_t has_override, double override_value,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto selected_topology = topology(code);
        const auto selected = override_constant(has_override, override_value);
        const auto cell_view = input(cells, count), wall_view = input(walls, count);
        require_output(result, result_count, product(count, 6));
        const auto table = g::Co2GeometryTable::from_generated(selected_topology);
        const auto local = material_rows(table.evaluate_batch(cell_view, wall_view, conductivity, selected));
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_co2_minimum_v1(
    uint32_t code, const double* cell_bounds, const double* wall_bounds,
    uint32_t has_override, double override_value,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto selected_topology = topology(code);
        const auto selected = override_constant(has_override, override_value);
        require_output(result, result_count, 3);
        const auto table = g::Co2GeometryTable::from_generated(selected_topology);
        const auto local = minimum_values(table.minimum_solid_geometry(
            bounds(cell_bounds), bounds(wall_bounds), selected));
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_eps_sides_v1(
    const double* phi, size_t count, const tpmshx_geometry_levels_v1* levels,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto values = input(phi, count);
        require_output(result, result_count, 3);
        const auto value = a::eps_sides(values, raw_levels(levels));
        publish(std::array<double, 3>{value.a, value.b, value.total}, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_hydraulic_radius_batch_v1(
    const double* diameter, size_t count,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto values = input(diameter, count);
        require_output(result, result_count, count);
        std::vector<double> local(count);
        for (std::size_t i = 0; i < count; ++i) local[i] = g::hydraulic_radius(values[i]);
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_area_sides_v1(
    const size_t* shape, const double* phi, size_t count,
    const tpmshx_geometry_levels_v1* levels,
    double length, double n, double correction, uint32_t method,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto dimensions = input_shape(shape);
        const auto values = shaped_phi(dimensions, phi, count);
        const bool mc = marching_cubes(method);
        const auto thresholds = raw_levels(levels);
        require_output(result, result_count, 2);
        const auto local = mc ? a::a0_sides_mc(values, dimensions, thresholds, length, n)
                              : a::a0_sides(values, dimensions, thresholds, length, n, correction);
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_dh_sides_v1(
    const size_t* shape, const double* phi, size_t count,
    const tpmshx_geometry_levels_v1* levels,
    double length, double n, double correction, uint32_t method,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto dimensions = input_shape(shape);
        const auto values = shaped_phi(dimensions, phi, count);
        const bool mc = marching_cubes(method);
        require_output(result, result_count, 2);
        const auto local = a::dh_sides(values, dimensions, raw_levels(levels), length, n, correction, mc);
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_dh_from_sides_v1(
    double epsilon_a, double epsilon_b, double area_a, double area_b,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        require_output(result, result_count, 2);
        const auto local = a::dh_from_sides(epsilon_a, epsilon_b, area_a, area_b);
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_wall_thickness_v1(
    const size_t* shape, const double* phi, size_t count,
    const tpmshx_geometry_levels_v1* levels, double length, double n, double correction,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto dimensions = input_shape(shape);
        const auto values = shaped_phi(dimensions, phi, count);
        require_output(result, result_count, 1);
        const std::array<double, 1> local{
            a::wall_thickness(values, dimensions, raw_levels(levels), length, n, correction)};
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_wall_from_sides_v1(
    double epsilon_total, double area_a, double area_b,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        require_output(result, result_count, 1);
        const std::array<double, 1> local{a::wall_thickness_from_sides(epsilon_total, area_a, area_b)};
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_split_a_v1(
    const double* phi, size_t count, const tpmshx_geometry_levels_v1* levels, uint32_t zero_delta,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto values = input(phi, count);
        require_output(result, result_count, 1);
        const auto thresholds = raw_levels(levels);
        const std::array<double, 1> local{a::split_a(values, thresholds, zero_offset(zero_delta))};
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_split_fields_v1(
    const double* epsilon, size_t count, double fraction_a,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto values = input(epsilon, count);
        require_output(result, result_count, product(count, 2));
        const auto split = a::split_porosity(values, fraction_a);
        std::vector<double> local(product(count, 2));
        for (std::size_t i = 0; i < count; ++i) {
            local[2*i] = split.a[i];
            local[2*i+1] = split.b[i];
        }
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_prepare_raw_sides_v1(
    const size_t* shape, const double* phi, size_t count,
    const tpmshx_geometry_levels_v1* levels, const tpmshx_geometry_levels_v1* reference_levels,
    uint32_t zero_delta, double length, double n, double correction,
    tpmshx_geometry_prepared_sides_v1* result, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto dimensions = input_shape(shape);
        const auto values = shaped_phi(dimensions, phi, count);
        require_buffer(result, 1);
        const auto thresholds = raw_levels(levels), reference = raw_levels(reference_levels);
        const auto local = prepared_values(a::prepare_sides(
            values, dimensions, thresholds, reference, zero_offset(zero_delta), length, n, correction));
        *result = local;
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_prepare_from_index_v1(
    const tpmshx_geometry_index_v1* index, uint32_t code,
    double cell, double wall, double delta,
    tpmshx_geometry_prepared_sides_v1* result, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto& field = owner(index);
        const auto calibration = model(field, code);
        require_buffer(result, 1);
        const auto local = prepared_values(a::prepare_from_index(field.value, calibration, cell, wall, delta));
        *result = local;
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_split_from_index_v1(
    const tpmshx_geometry_index_v1* index, uint32_t code,
    double cell, double wall, double delta,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto& field = owner(index);
        const auto calibration = model(field, code);
        require_output(result, result_count, 1);
        const std::array<double, 1> local{a::split_from_index(field.value, calibration, cell, wall, delta)};
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_lut_batch_v1(
    uint32_t code, const double* epsilon, const double* area, size_t count,
    double conductivity, uint32_t has_override, double override_value,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto calibration = g::calibration(topology(code));
        const auto eps_values = input(epsilon, count), area_values = input(area, count);
        const auto constant = override_constant(has_override, override_value);
        require_output(result, result_count, product(count, 7));
        std::vector<double> local(product(count, 7));
        for (std::size_t i = 0; i < count; ++i) {
            const auto value = g::lut_geometry(calibration.solid_tortuosity, eps_values[i],
                area_values[i], conductivity, constant);
            const auto row = material_row(value.material);
            std::copy(row.begin(), row.end(), local.data() + i*7);
            local[i*7+6] = value.hydraulic_radius;
        }
        publish(local, result);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_zone_ids_v1(
    uint32_t kind, size_t nx, size_t ny, int axis, tpmshx_grid_scalar_v1 domain,
    const tpmshx_grid_scalar_v1* rows, size_t row_count,
    const double* dx, size_t dx_count, const double* dy, size_t dy_count,
    int32_t* output, size_t output_count, char* error, size_t error_capacity) {
    return boundary(error, error_capacity, [&] {
        if (!nx || !ny) throw std::invalid_argument("zone dimensions must be positive");
        const auto count = product(nx, ny);
        require_output(output, output_count, count);
        require_buffer(rows, product(row_count, 4));
        if (dx_count != (dx ? nx : 0) || dy_count != (dy ? ny : 0))
            throw std::invalid_argument("zone width lengths disagree with the axes");
        require_buffer(dx, dx_count); require_buffer(dy, dy_count);
        std::vector<tpmshx::zones::Bounds> bounds(row_count);
        for (std::size_t i = 0; i < row_count; ++i)
            for (std::size_t j = 0; j < 4; ++j) {
                const auto& scalar = rows[4 * i + j];
                bounds[i][j] = tpmshx::grid::checked({scalar.value, scalar.precision, scalar.strong});
            }
        tpmshx::zones::Values widths_x, widths_y;
        if (dx) widths_x.assign(dx, dx + dx_count);
        if (dy) widths_y.assign(dy, dy + dy_count);
        const auto result = tpmshx::zones::assign(kind, nx, ny, axis,
            {domain.value, domain.precision, domain.strong}, bounds,
            dx ? &widths_x : nullptr, dy ? &widths_y : nullptr);
        std::copy(result.begin(), result.end(), output);
    });
}

extern "C" int TPMSHX_GEOMETRY_CALL tpmshx_geometry_zone_gaussian_v1(
    size_t nx, size_t ny, const double* input_values, size_t input_count,
    double* output, size_t output_count, char* error, size_t error_capacity) {
    return boundary(error, error_capacity, [&] {
        if (!nx || !ny) throw std::invalid_argument("zone dimensions must be positive");
        const auto count = product(nx, ny);
        if (input_count != count) throw std::invalid_argument("zone Gaussian input length differs");
        require_buffer(input_values, input_count);
        require_output(output, output_count, count);
        const auto result = tpmshx::zones::gaussian_sigma2(
            tpmshx::zones::Values(input_values, input_values + count), nx, ny);
        std::copy(result.begin(), result.end(), output);
    });
}
