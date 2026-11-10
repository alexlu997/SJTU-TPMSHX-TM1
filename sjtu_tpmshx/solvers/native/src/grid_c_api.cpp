#include "tpmshx/grid_c_api.h"
#include "tpmshx/grid.hpp"
#include <algorithm>
#include <cstdio>
#include <exception>
#include <limits>
#include <stdexcept>

namespace g = tpmshx::grid;

namespace {
std::size_t product(std::size_t a, std::size_t b) {
    if (b && a > std::numeric_limits<std::size_t>::max() / b)
        throw std::invalid_argument("grid element count overflows size_t");
    return a * b;
}

std::size_t sum(std::size_t a, std::size_t b) {
    if (a > std::numeric_limits<std::size_t>::max() - b)
        throw std::invalid_argument("grid element count overflows size_t");
    return a + b;
}

template <class T>
void buffer(const T* data, std::size_t count) {
    const auto bytes = product(count, sizeof(T));
    if (!count) return;
    if (!data) throw std::invalid_argument("nonempty grid buffer is null");
    const auto address = reinterpret_cast<std::uintptr_t>(data);
    if (address % alignof(T) || bytes - 1 > std::numeric_limits<std::uintptr_t>::max() - address)
        throw std::invalid_argument("grid buffer address or alignment is invalid");
}

template <class T>
void output(T* data, std::size_t actual, std::size_t expected) {
    if (actual != expected)
        throw std::invalid_argument("grid output element count is incorrect");
    buffer(data, actual);
}

template <class Operation>
int boundary(char* error, std::size_t capacity, Operation operation) {
    if (!error || !capacity || capacity - 1 > std::numeric_limits<std::uintptr_t>::max()
            - reinterpret_cast<std::uintptr_t>(error))
        return TPMSHX_GEOMETRY_INVALID;
    try {
        operation();
        error[0] = '\0';
        return TPMSHX_GEOMETRY_OK;
    } catch (const std::invalid_argument& exception) {
        std::snprintf(error, capacity, "%s", exception.what());
        return TPMSHX_GEOMETRY_INVALID;
    } catch (const std::domain_error& exception) {
        std::snprintf(error, capacity, "%s", exception.what());
        return TPMSHX_GEOMETRY_DOMAIN;
    } catch (const std::exception& exception) {
        std::snprintf(error, capacity, "%s", exception.what());
        return TPMSHX_GEOMETRY_RUNTIME;
    } catch (...) {
        std::snprintf(error, capacity, "%s", "unexpected native grid exception");
        return TPMSHX_GEOMETRY_RUNTIME;
    }
}

void flag(std::uint32_t value) {
    if (value > 1) throw std::invalid_argument("grid flag must be zero or one");
}

g::Scalar scalar(tpmshx_grid_scalar_v1 value) {
    return g::checked({value.value, value.precision, value.strong});
}

tpmshx_grid_scalar_v1 scalar(g::Scalar value) {
    return {value.value, value.precision, value.strong};
}

g::Scalars scalars(const tpmshx_grid_scalar_v1* values, std::size_t count) {
    buffer(values, count);
    g::Scalars result;
    result.reserve(count);
    for (std::size_t i = 0; i < count; ++i)
        result.push_back(scalar(values[i]));
    return result;
}

g::Values values(const double* data, std::size_t count) {
    buffer(data, count);
    return count ? g::Values(data, data + count) : g::Values{};
}

g::Port port(const tpmshx_grid_port_v1& value) {
    flag(value.active);
    g::Port result{value.direction, value.active != 0, {}};
    for (std::size_t i = 0; i < 2; ++i) {
        std::optional<g::Scalar>* fields[] = {
            &result.ends[i].center, &result.ends[i].width,
            &result.ends[i].center2, &result.ends[i].width2};
        for (std::size_t j = 0; j < 4; ++j) {
            flag(value.present[i][j]);
            if (value.present[i][j]) *fields[j] = scalar(value.values[i][j]);
        }
    }
    return result;
}

std::vector<g::Port> ports(const tpmshx_grid_port_v1* data, std::size_t count) {
    buffer(data, count);
    std::vector<g::Port> result;
    result.reserve(count);
    for (std::size_t i = 0; i < count; ++i)
        result.push_back(port(data[i]));
    return result;
}

void copy_scalars(const g::Scalars& data, tpmshx_grid_scalar_v1* result) {
    for (std::size_t i = 0; i < data.size(); ++i) result[i] = scalar(data[i]);
}

void edges_output(const g::Scalars& data, tpmshx_grid_scalar_v1* result,
                  std::size_t capacity, std::size_t* count) {
    buffer(result, capacity);
    buffer(count, 1);
    if (capacity < data.size())
        throw std::invalid_argument("grid edge output capacity is too small");
    copy_scalars(data, result);
    *count = data.size();
}
}

extern "C" {
int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_adaptive_v1(
    const tpmshx_grid_scalar_v1* lengths, tpmshx_grid_scalar_v1 diameter,
    tpmshx_grid_scalar_v1 alpha, double* result, size_t result_count,
    char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        output(result, result_count, 2);
        const auto data = g::adaptive_grid(scalars(lengths, 2), scalar(diameter), scalar(alpha));
        std::copy(data.begin(), data.end(), result);
    });
}

int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_uniform_v1(
    size_t count, tpmshx_grid_scalar_v1 length, double* result, size_t result_count,
    char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        output(result, result_count, count);
        const auto data = g::uniform(count, scalar(length));
        std::copy(data.begin(), data.end(), result);
    });
}

int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_aligned_filter_v1(
    tpmshx_grid_scalar_v1 length, const tpmshx_grid_scalar_v1* points,
    size_t count, uint8_t* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        output(result, result_count, count);
        const auto data = g::aligned_filter(scalar(length), scalars(points, count));
        std::copy(data.begin(), data.end(), result);
    });
}

int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_aligned_v1(
    size_t count, const tpmshx_grid_scalar_v1* bounds, size_t bounds_count,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        output(result, result_count, count);
        const auto data = g::aligned(count, scalars(bounds, bounds_count)).widths;
        if (data.size() != count)
            throw std::runtime_error("aligned grid extent differs from count");
        std::copy(data.begin(), data.end(), result);
    });
}

int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_wall_v1(
    tpmshx_grid_scalar_v1 length, size_t bulk, size_t layers,
    tpmshx_grid_scalar_v1 first, tpmshx_grid_scalar_v1 growth,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        output(result, result_count, sum(bulk, product(2, layers)));
        const auto data = g::wall(scalar(length), bulk, layers, scalar(first), scalar(growth));
        std::copy(data.begin(), data.end(), result);
    });
}

int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_port_edges_v1(
    const tpmshx_grid_scalar_v1* lengths, size_t dimensions,
    const tpmshx_grid_port_v1* input, size_t count, size_t axis,
    tpmshx_grid_scalar_v1* result, size_t result_capacity, size_t* result_count,
    char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto data = g::port_edges(scalars(lengths, dimensions), ports(input, count), axis);
        edges_output(data, result, result_capacity, result_count);
    });
}

int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_breaks_2d_v1(
    const tpmshx_grid_scalar_v1* lengths, const tpmshx_grid_port_v1* input,
    size_t count, size_t axis, tpmshx_grid_scalar_v1* result,
    size_t result_capacity, size_t* result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        const auto data = g::breaks_2d(scalars(lengths, 2), ports(input, count), axis);
        edges_output(data, result, result_capacity, result_count);
    });
}

int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_wall_spec_v1(
    size_t dimensions, size_t knots, tpmshx_grid_wall_spec_v1* result,
    char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        buffer(result, 1);
        const auto data = g::wall_spec(dimensions, knots);
        *result = {data.layers, data.minimum, data.first, data.growth};
    });
}

int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_port_wall_axis_v1(
    size_t dimensions, size_t axis, size_t count,
    const tpmshx_grid_scalar_v1* bounds, size_t bounds_count,
    const tpmshx_grid_scalar_v1* bulk_bounds, size_t bulk_count,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        output(result, result_count, count);
        std::size_t minimum = 0;
        const auto data = g::port_wall_axis(
            dimensions, count, scalars(bounds, bounds_count),
            scalars(bulk_bounds, bulk_count), minimum, axis);
        if (data.size() != count)
            throw std::runtime_error("port-wall grid extent differs from count");
        std::copy(data.begin(), data.end(), result);
    });
}

int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_suggest_v1(
    const tpmshx_grid_scalar_v1* lengths, tpmshx_grid_scalar_v1 diameter,
    size_t budget, const size_t* minimum, size_t* result, size_t result_count,
    char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        output(result, result_count, 3);
        buffer(minimum, 3);
        const auto data = g::suggest_grid(
            scalars(lengths, 3), scalar(diameter), budget,
            {minimum[0], minimum[1], minimum[2]});
        std::copy(data.begin(), data.end(), result);
    });
}

int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_axis_map_v1(
    int32_t direction, int32_t* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        output(result, result_count, 7);
        const auto data = g::axis_map(direction);
        std::copy(data.begin(), data.end(), result);
    });
}

int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_rectangles_v1(
    const tpmshx_grid_port_v1* input, tpmshx_grid_scalar_v1 length,
    tpmshx_grid_scalar_v1* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        output(result, result_count, 8);
        buffer(input, 1);
        const auto data = g::rectangles(port(*input), scalar(length));
        copy_scalars(data, result);
    });
}

int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_overlap_v1(
    const double* widths, size_t count, uint32_t bits,
    tpmshx_grid_scalar_v1 lower, tpmshx_grid_scalar_v1 upper, uint32_t staggered,
    double* result, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        flag(staggered);
        output(result, result_count, sum(count, staggered));
        if (!count && staggered)
            throw std::invalid_argument("staggered grid overlap requires nonempty widths");
        const auto data = g::port_overlap(
            values(widths, count), scalar(lower), scalar(upper), staggered != 0, bits);
        std::copy(data.begin(), data.end(), result);
    });
}

int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_fractions_v1(
    const double* widths, size_t count, uint32_t bits,
    tpmshx_grid_scalar_v1 lower, tpmshx_grid_scalar_v1 upper, uint32_t uniform,
    double* raw, double* profile, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        flag(uniform);
        output(raw, result_count, count);
        output(profile, result_count, count);
        const auto data = g::port_fractions(
            values(widths, count), scalar(lower), scalar(upper), uniform != 0, bits);
        std::copy(data[0].begin(), data[0].end(), raw);
        std::copy(data[1].begin(), data[1].end(), profile);
    });
}

int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_partial_v1(
    const tpmshx_grid_port_v1* input, const double* cross1, size_t count1, uint32_t bits1,
    const double* cross2, size_t count2, uint32_t bits2, uint32_t has_cross2, size_t n_cross2,
    double* inlet, double* outlet, size_t result_count, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        flag(has_cross2);
        buffer(input, 1);
        output(inlet, result_count, product(count1, n_cross2));
        output(outlet, result_count, product(count1, n_cross2));
        const auto first = values(cross1, count1), second = values(cross2, count2);
        const auto data = g::partial_masks(
            port(*input), first, has_cross2 ? &second : nullptr, n_cross2, bits1, bits2);
        if (data[0].size() != result_count || data[1].size() != result_count)
            throw std::invalid_argument("partial mask cross2 extent is incorrect");
        std::copy(data[0].begin(), data[0].end(), inlet);
        std::copy(data[1].begin(), data[1].end(), outlet);
    });
}

int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_continuous_centres_v1(
    size_t count, tpmshx_grid_scalar_v1 length, const double* widths,
    size_t width_count, uint32_t has_widths, double* result, size_t result_count,
    char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        flag(has_widths);
        output(result, result_count, count);
        const auto width = values(widths, width_count);
        const auto data = g::continuous_centres(count, scalar(length), has_widths ? &width : nullptr);
        std::copy(data.begin(), data.end(), result);
    });
}

int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_sigmoid_centres_v1(
    size_t count, tpmshx_grid_scalar_v1 length, const double* widths,
    size_t width_count, uint32_t has_widths, uint32_t bits, double* result,
    size_t result_count, uint32_t* output_precision, char* error, size_t capacity) {
    return boundary(error, capacity, [&] {
        flag(has_widths);
        output(result, result_count, has_widths ? width_count : count);
        buffer(output_precision, 1);
        const auto width = values(widths, width_count);
        uint32_t precision = 64;
        const auto data = g::sigmoid_centres(
            count, scalar(length), has_widths ? &width : nullptr, bits, &precision);
        std::copy(data.begin(), data.end(), result);
        *output_precision = precision;
    });
}
}  // extern C
