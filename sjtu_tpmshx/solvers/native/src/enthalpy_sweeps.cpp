#include "tpmshx/enthalpy_sweeps.hpp"
#include "energy_fv_rows.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace tpmshx {
namespace {

std::size_t product(std::size_t a, std::size_t b) {
    if (!a || !b || a > std::numeric_limits<std::size_t>::max() / b)
        throw std::invalid_argument("invalid grid extent");
    return a * b;
}

template <typename T>
void check_array(ArrayView<T> a, std::size_t size) {
    if (!a.data || a.size != size)
        throw std::invalid_argument("array length does not match grid");
    for (std::size_t i = 0; i < size; ++i)
        if (!std::isfinite(a[i]))
            throw std::invalid_argument("nonfinite array value");
}

void check_coefficient(ArrayView<const double> a, std::size_t size, bool positive) {
    check_array(a, size);
    for (std::size_t i = 0; i < size; ++i)
        if (positive ? a[i] <= 0.0 : a[i] < 0.0)
            throw std::invalid_argument("invalid physical coefficient");
}

std::size_t check_grid(const GridView& grid) {
    if (grid.nx == std::numeric_limits<std::size_t>::max() ||
        grid.ny == std::numeric_limits<std::size_t>::max() ||
        grid.nz == std::numeric_limits<std::size_t>::max())
        throw std::invalid_argument("invalid grid extent");
    const auto cells = product(product(grid.nx, grid.ny), grid.nz);
    check_coefficient(grid.dx, grid.nx, true);
    check_coefficient(grid.dy, grid.ny, true);
    check_coefficient(grid.dz, grid.nz, true);
    return cells;
}




}  // namespace


namespace {
void check_energy_fluid(const FluidEnergyView& f, const GridView& g, std::size_t cells,
                        bool fluid_equations) {
    check_array(f.h, cells);
    check_array(f.temperature, cells);
    check_coefficient(f.hv, cells, false);
    if (fluid_equations) check_coefficient(f.conductivity, cells, false);
    check_array(f.mass_x, product(product(g.nx + 1, g.ny), g.nz));
    check_array(f.mass_y, product(product(g.nx, g.ny + 1), g.nz));
    check_array(f.mass_z, product(product(g.nx, g.ny), g.nz + 1));
    if (!std::isfinite(f.h_in)) throw std::invalid_argument("nonfinite inlet enthalpy");
}

double inward_boundary_power(const GridView& g, ArrayView<const double> h,
                             const ArrayView<const double> (&mass)[3], double h_in) {
    double q_in = 0.;
    const std::size_t stride[] = {g.ny * g.nz, g.nz, 1};
    const std::size_t extent[] = {g.nx, g.ny, g.nz};
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const auto nx = g.nx + (axis == 0), ny = g.ny + (axis == 1), nz = g.nz + (axis == 2);
        for (std::size_t i = 0; i < nx; ++i)
            for (std::size_t j = 0; j < ny; ++j)
                for (std::size_t k = 0; k < nz; ++k) {
                    const std::size_t coord[] = {i, j, k};
                    const auto c = coord[axis];
                    if (c > 0 && c < extent[axis]) continue;
                    const auto high = (i * g.ny + j) * g.nz + k;
                    const auto low = c > 0 ? high - stride[axis] : 0;
                    const double flow = mass[axis][(i * ny + j) * nz + k];
                    const double upstream = flow >= 0.
                        ? (c > 0 ? h[low] : h_in)
                        : (c < extent[axis] ? h[high] : h_in);
                    const double flux = flow * upstream;
                    if (c == 0) q_in += flux;
                    else q_in -= flux;
                }
    }
    if (!std::isfinite(q_in)) throw std::domain_error("nonfinite boundary enthalpy duty");
    return q_in;
}

}  // namespace


EnergyAudit thermal_energy_audit(const GridView& grid, const FluidEnergyView& a,
                                const FluidEnergyView& b, ArrayView<const double> ts,
                                ArrayView<const double> k_ss, ArrayView<double> ra,
                                ArrayView<double> rb, ArrayView<double> rs,
                                bool fluid_equations) {
    const auto cells = check_grid(grid);
    check_energy_fluid(a, grid, cells, fluid_equations);
    check_energy_fluid(b, grid, cells, fluid_equations);
    check_array(ts, cells);
    check_coefficient(k_ss, cells, false);
    for (const auto r : {ra, rb, rs})
        if (!r.data || r.size != cells)
            throw std::invalid_argument("residual array length does not match grid");
    EnergyAudit result{};
    result.fluid_equations_computed = fluid_equations;
    const detail::EnergyMesh mesh(grid);
    const FluidEnergyView* fluids[]{&a,&b};
    const ArrayView<double> residuals[]{ra,rb};
    double* duties[]{&result.q_a,&result.q_b};
    for(std::size_t side=0;side<2;++side) {
        const auto& fluid=*fluids[side];
        const ArrayView<const double> mass[]{fluid.mass_x,fluid.mass_y,fluid.mass_z};
        *duties[side]=inward_boundary_power(grid,fluid.h,mass,fluid.h_in);
        if(fluid_equations) {
            const detail::EnthalpyAuditPhase phase{fluid};
            for(std::size_t p=0;p<cells;++p)
                residuals[side][p]=detail::fluid_energy_defect_row(mesh,phase,fluid.temperature,ts,p).rhs;
        }
    }
    if (!fluid_equations) {
        const auto nan = std::numeric_limits<double>::quiet_NaN();
        std::fill_n(ra.data,cells,nan);
        std::fill_n(rb.data,cells,nan);
        std::fill_n(result.fluid_abs_sum,2,nan);
        std::fill_n(result.fluid_cell_max,2,nan);
        result.equation_ratio = nan;
    }
    for(std::size_t p=0;p<cells;++p)
        rs[p]=detail::solid_energy_defect_row(mesh,k_ss,a.hv,b.hv,a.temperature,b.temperature,ts,{},p).rhs;
    for (std::size_t p = 0; p < cells; ++p) {
        if (!std::isfinite(rs[p]) || (fluid_equations
            && (!std::isfinite(ra[p]) || !std::isfinite(rb[p]))))
            throw std::domain_error("nonfinite energy residual");
        if (fluid_equations) {
            result.fluid_abs_sum[0] += std::abs(ra[p]);
            result.fluid_abs_sum[1] += std::abs(rb[p]);
            result.fluid_cell_max[0] = std::max(result.fluid_cell_max[0], std::abs(ra[p]));
            result.fluid_cell_max[1] = std::max(result.fluid_cell_max[1], std::abs(rb[p]));
        }
        result.solid_abs_sum += std::abs(rs[p]);
    }
    result.net = result.q_a + result.q_b;
    result.denominator = std::max({std::abs(result.q_a), std::abs(result.q_b), 1.});
    result.coupled_ratio = std::max(std::abs(result.net), result.solid_abs_sum) / result.denominator;
    if (fluid_equations) {
        result.equation_ratio = std::max({std::abs(result.net), result.solid_abs_sum,
            result.fluid_abs_sum[0], result.fluid_abs_sum[1]}) / result.denominator;
        for (const double x : {result.equation_ratio,result.fluid_abs_sum[0],result.fluid_abs_sum[1]})
            if (!std::isfinite(x)) throw std::domain_error("nonfinite fluid energy budget");
    }
    for (const double x : {result.q_a, result.q_b, result.net, result.solid_abs_sum,
            result.denominator, result.coupled_ratio})
        if (!std::isfinite(x)) throw std::domain_error("nonfinite energy budget");
    return result;
}
}  // namespace tpmshx
