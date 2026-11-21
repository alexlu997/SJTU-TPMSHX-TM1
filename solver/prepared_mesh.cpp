#include "tpmshx/result_core.hpp"
#include "tpmshx/stage_run_c_api.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

namespace {
using Shape = std::array<size_t, 3>;
using View = tpmshx_preparation_array_v1;

View borrow(const tpmshx_result_array_v1& raw, size_t rank, const Shape* shape = nullptr) {
    const unsigned short one = 1;
    const std::uint32_t native_order = *reinterpret_cast<const unsigned char*>(&one)
        ? TPMSHX_RESULT_LITTLE_ENDIAN : TPMSHX_RESULT_BIG_ENDIAN;
    if (raw.rank != rank || raw.dtype != TPMSHX_RESULT_F64
        || (raw.byte_order != TPMSHX_RESULT_NATIVE_ENDIAN && raw.byte_order != native_order)) return {};
    const tpmshx::result::Array array(raw);
    if (!array.size()) return {};
    size_t stride = sizeof(double);
    for (size_t i = rank; i-- > 0;) {
        if ((shape && raw.shape[i] != (*shape)[i]) || raw.strides[i] < 0
            || static_cast<size_t>(raw.strides[i]) != stride) return {};
        stride *= raw.shape[i];
    }
    const auto* start = array.address(0);
    if (reinterpret_cast<std::uintptr_t>(start) % alignof(double)) return {};
    return {reinterpret_cast<const double*>(start), array.size()};
}

bool positive(double x) { return std::isfinite(x) && x > 0.; }
bool fraction(double x) { return x > 0. && x < 1.; }

bool prepare(tpmshx_stage_mesh_v1& mesh) {
    if (mesh.dimension != 2 && mesh.dimension != 3) return false;
    Shape shape{};
    for (size_t axis = 0; axis < mesh.dimension; ++axis) {
        const auto widths = borrow(mesh.widths[axis], 1), edges = borrow(mesh.edges[axis], 1);
        if (!widths.size || edges.size != widths.size + 1 || edges.data[0] != 0.) return false;
        double edge = 0.;
        for (size_t i = 0; i < widths.size; ++i) {
            if (!positive(widths.data[i])) return false;
            edge += widths.data[i];
            if (!std::isfinite(edge) || edge != edges.data[i + 1]) return false;
        }
        mesh.solver_widths[axis] = widths;
        shape[axis] = widths.size;
    }
    if (!positive(mesh.area_density) || !positive(mesh.hydraulic_diameter)
        || !fraction(mesh.porosity) || !fraction(mesh.split_a)) return false;
    if (mesh.fields[0].dtype || mesh.fields[1].dtype || mesh.fields[2].dtype) {
        mesh.solver_area = borrow(mesh.fields[0], mesh.dimension, &shape);
        mesh.solver_diameter = borrow(mesh.fields[1], mesh.dimension, &shape);
        const auto epsilon = borrow(mesh.fields[2], mesh.dimension, &shape);
        if (!mesh.solver_area.size || !mesh.solver_diameter.size || !epsilon.size) return false;
        for (size_t i = 0; i < epsilon.size; ++i)
            if (!positive(mesh.solver_area.data[i]) || !positive(mesh.solver_diameter.data[i])
                || !fraction(epsilon.data[i])) return false;
    } else {
        mesh.solver_area = {&mesh.area_density, 1};
        mesh.solver_diameter = {&mesh.hydraulic_diameter, 1};
    }
    if (mesh.side_geometry[0].dtype || mesh.side_geometry[1].dtype) {
        for (const auto& side : mesh.side_geometry) {
            const auto v = borrow(side, 1);
            if (v.size != 4 || !std::all_of(v.data, v.data + v.size, positive)) return false;
        }
    }
    for (size_t side = 0; side < 2; ++side) {
        if (!mesh.axis_present[side]) continue;
        const auto& axes = mesh.axes[side];
        for (int i = 0; i < 3; ++i)
            if (axes[i] < 0 || axes[i] > 2 || axes[3 + axes[i]] != i) return false;
    }
    return true;
}
}

extern "C" int TPMSHX_THERMAL_CALL tpmshx_stage_borrow_mesh_v1(tpmshx_stage_mesh_v1* mesh) {
    try {
        return mesh && prepare(*mesh);
    } catch (const std::exception&) {
        return 0;
    }
}
