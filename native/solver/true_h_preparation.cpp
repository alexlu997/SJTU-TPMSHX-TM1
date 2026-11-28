#include "true_h_preparation.hpp"

#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>

namespace tpmshx {
namespace {

std::size_t product(std::size_t a, std::size_t b) {
    if (!a || !b || a > std::numeric_limits<std::size_t>::max() / b)
        throw std::invalid_argument("invalid temperature grid extent");
    return a * b;
}

template <typename T>
void check_array(ArrayView<T> x, std::size_t size, bool finite = true) {
    if (!x.data || x.size != size)
        throw std::invalid_argument("temperature array length does not match grid");
    if (finite)
        for (std::size_t i = 0; i < size; ++i)
            if (!std::isfinite(x[i])) throw std::invalid_argument("nonfinite temperature input");
}

void coefficient(ArrayView<const double> x, std::size_t n, bool positive = false) {
    check_array(x, n);
    for (std::size_t i = 0; i < n; ++i)
        if (positive ? x[i] <= 0.0 : x[i] < 0.0)
            throw std::invalid_argument("invalid temperature coefficient");
}

template <typename T, typename U>
void disjoint(ArrayView<T> a, ArrayView<U> b) {
    if (!a.size || !b.size) return;
    const auto ap = reinterpret_cast<std::uintptr_t>(a.data);
    const auto bp = reinterpret_cast<std::uintptr_t>(b.data);
    const auto maximum = std::numeric_limits<std::uintptr_t>::max();
    if (a.size > (maximum-ap)/sizeof(double) || b.size > (maximum-bp)/sizeof(double)
        || (ap < bp+b.size*sizeof(double) && bp < ap+a.size*sizeof(double)))
        throw std::invalid_argument("temperature input/output arrays overlap");
}

} // namespace

void validate_true_h_preparation(TemperatureScheme scheme, const GridView& grid,
    const TemperatureFluidView& a, const TemperatureFluidView& b,
    ArrayView<const double> k_ss, TemperatureStateView state,
    const TemperatureControl& control, bool red_black) {
    if (scheme != TemperatureScheme::cell_centered_2d && scheme != TemperatureScheme::cell_centered_3d)
        throw std::invalid_argument("unsupported temperature scheme");
    const bool two_d = scheme == TemperatureScheme::cell_centered_2d;
    if (red_black && !two_d)
        throw std::invalid_argument("cell-centred RB requires a 2D temperature scheme");
    const auto cells = product(product(grid.nx,grid.ny),grid.nz);
    if ((two_d && grid.nz != 1) || (!two_d && grid.nz <= 1))
        throw std::invalid_argument("temperature dimension does not match scheme");
    coefficient(grid.dx,grid.nx,true); coefficient(grid.dy,grid.ny,true);
    coefficient(grid.dz,grid.nz,true); coefficient(k_ss,cells);
    if (!control.chunk_iterations || !std::isfinite(control.q_relative_tolerance)
        || control.q_relative_tolerance <= 0.0)
        throw std::invalid_argument("invalid temperature chunk or stopping tolerance");
    for (const double alpha : {control.alpha_a,control.alpha_solid,control.alpha_b})
        if (!std::isfinite(alpha) || alpha <= 0.0 || alpha > 1.0)
            throw std::invalid_argument("invalid temperature relaxation");
    if ((two_d && (control.alpha_a != .7 || control.alpha_solid != 1. || control.alpha_b != 1.))
        || (!two_d && !control.second_order_b))
        throw std::invalid_argument("unsupported temperature phase policy");
    const std::array<ArrayView<double>,3> outputs{state.a,state.b,state.solid};
    for (auto out : outputs) check_array(out,cells,control.warm_start);
    for (std::size_t i = 0; i < outputs.size(); ++i) {
        for (std::size_t j = 0; j < i; ++j) disjoint(outputs[i],outputs[j]);
        for (auto input : {grid.dx,grid.dy,grid.dz,k_ss}) disjoint(outputs[i],input);
    }
    for (const auto* f : {&a,&b}) {
        coefficient(f->conductivity,cells); coefficient(f->hv,cells);
        coefficient(f->epsilon,cells); coefficient(f->rho_cp,cells,true);
        check_array(f->u,cells); check_array(f->v,cells);
        if (!two_d || f->w.size) check_array(f->w,cells);
        const auto& bc = f->boundary;
        if (bc.direction < 0 || bc.direction >= (two_d ? 4 : 6)
            || !std::isfinite(bc.inlet_temperature))
            throw std::invalid_argument("invalid temperature inlet direction or value");
        const auto face_size = bc.direction < 2 ? product(grid.ny,grid.nz)
            : (bc.direction < 4 ? product(grid.nx,grid.nz) : product(grid.nx,grid.ny));
        for (auto input : {bc.profile,bc.opening,bc.capacity_flux})
            if (input.size) check_array(input,face_size);
        for (std::size_t i = 0; i < bc.opening.size; ++i)
            if (bc.opening[i] < 0. || bc.opening[i] > 1.)
                throw std::invalid_argument("inlet opening must lie in [0,1]");
        for (auto out : outputs)
            for (auto input : {f->conductivity,f->hv,f->epsilon,f->rho_cp,f->u,f->v,f->w,
                               bc.profile,bc.opening,bc.capacity_flux}) disjoint(out,input);
    }
}
} // namespace tpmshx
