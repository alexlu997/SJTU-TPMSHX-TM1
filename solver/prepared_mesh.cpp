#include "tpmshx/result_core.hpp"
#include "tpmshx/stage_run_c_api.h"

#include <array>
#include <cmath>
#include <cstring>

namespace {
using Raw = tpmshx_result_array_v1;
using Shape = std::array<size_t, 3>;

struct Values {
    const unsigned char* data = nullptr;
    size_t count = 0;
    bool single = false;

    double operator[](size_t i) const {
        if (single) {
            float value;
            std::memcpy(&value, data + i * sizeof(value), sizeof(value));
            return value;
        }
        double value;
        std::memcpy(&value, data + i * sizeof(value), sizeof(value));
        return value;
    }
};

// Check bounds once, then walk the same borrowed buffer without cell temporaries.
bool read_values(const Raw& raw, size_t rank, const Shape& shape, Values& out) {
    const unsigned short one = 1;
    const auto native_order = *reinterpret_cast<const unsigned char*>(&one)
        ? TPMSHX_RESULT_LITTLE_ENDIAN : TPMSHX_RESULT_BIG_ENDIAN;
    if (raw.rank != rank || (raw.byte_order != TPMSHX_RESULT_NATIVE_ENDIAN && raw.byte_order != native_order)
        || (raw.dtype != TPMSHX_RESULT_F64 && raw.dtype != TPMSHX_RESULT_F32)) return false;
    const tpmshx::result::Array array(raw);
    if (!array.size()) return false;
    size_t stride = raw.dtype == TPMSHX_RESULT_F64 ? sizeof(double) : sizeof(float);
    for (size_t i = rank; i-- > 0;) {
        if (raw.shape[i] != shape[i] || raw.strides[i] < 0 || static_cast<size_t>(raw.strides[i]) != stride)
            return false;
        stride *= shape[i];
    }
    out = {array.address(0), array.size(), raw.dtype == TPMSHX_RESULT_F32};
    return true;
}

bool positive(double x) { return std::isfinite(x) && x > 0.; }
bool fraction(double x) { return x > 0. && x < 1.; }

bool valid(const tpmshx_stage_mesh_v1& mesh) {
    if (mesh.dimension != 2 && mesh.dimension != 3) return false;
    Shape shape{};
    for (size_t axis = 0; axis < mesh.dimension; ++axis) {
        const auto& dx = mesh.widths[axis];
        if (dx.rank != 1 || !dx.shape) return false;
        shape[axis] = dx.shape[0];
        Values widths, edges;
        if (!read_values(dx, 1, {shape[axis]}, widths)
            || !read_values(mesh.edges[axis], 1, {shape[axis] + 1}, edges) || edges[0] != 0.) return false;
        double edge = 0.;
        for (size_t i = 0; i < widths.count; ++i) {
            const double width = widths[i];
            if (!positive(width)) return false;
            edge += width;
            if (widths.single) edge = static_cast<float>(edge);
            if (!std::isfinite(edge) || edges[i + 1] != edge) return false;
        }
    }
    if (!positive(mesh.area_density) || !positive(mesh.hydraulic_diameter)
        || !fraction(mesh.porosity) || !fraction(mesh.split_a)) return false;
    if (mesh.fields[0].dtype || mesh.fields[1].dtype || mesh.fields[2].dtype) {
        Values area, diameter, epsilon;
        if (!read_values(mesh.fields[0], mesh.dimension, shape, area)
            || !read_values(mesh.fields[1], mesh.dimension, shape, diameter)
            || !read_values(mesh.fields[2], mesh.dimension, shape, epsilon)) return false;
        for (size_t i = 0; i < area.count; ++i)
            if (!positive(area[i]) || !positive(diameter[i]) || !fraction(epsilon[i])) return false;
    }
    if (mesh.side_geometry[0].dtype || mesh.side_geometry[1].dtype) {
        for (const auto& side : mesh.side_geometry) {
            Values values;
            if (!read_values(side, 1, {4}, values)) return false;
            for (size_t i = 0; i < values.count; ++i) if (!positive(values[i])) return false;
        }
    }
    for (const auto axes : mesh.axes) {
        if (!axes) continue;
        for (int i = 0; i < 3; ++i)
            if (axes[i] < 0 || axes[i] > 2 || axes[3 + axes[i]] != i) return false;
    }
    return true;
}
}

extern "C" int TPMSHX_THERMAL_CALL tpmshx_stage_mesh_valid_v1(const tpmshx_stage_mesh_v1* mesh) {
    try {
        return mesh && valid(*mesh);
    } catch (const std::exception&) {
        return 0;
    }
}
