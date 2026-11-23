#include "tpmshx/result_core.hpp"
#include "tpmshx/stage_run_c_api.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

namespace {
using Shape = std::array<size_t, 3>;
using View = tpmshx_preparation_array_v1;

View borrow(const tpmshx_result_array_v2& raw, size_t rank, const Shape* shape = nullptr) {
    if (raw.rank != rank) return {};
    const tpmshx::result::Array array(raw);
    if (!array.size()) return {};
    if (shape) {
        for (size_t i = 0; i < rank; ++i) {
            if (raw.shape[i] != (*shape)[i]) return {};
        }
    }
    if (reinterpret_cast<std::uintptr_t>(raw.data) % alignof(double)) return {};
    return {raw.data, array.size()};
}

bool present(const tpmshx_result_array_v2& raw) {
    return raw.data != nullptr || raw.rank != 0 || raw.shape != nullptr;
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
    if (present(mesh.fields[0]) || present(mesh.fields[1]) || present(mesh.fields[2])) {
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
    if (present(mesh.side_geometry[0]) || present(mesh.side_geometry[1])) {
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
