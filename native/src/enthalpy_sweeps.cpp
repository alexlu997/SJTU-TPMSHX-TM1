#include "tpmshx/enthalpy_sweeps.hpp"

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

void check_fluid(const FluidView& f, const GridView& g, std::size_t cells) {
    check_coefficient(f.dh, cells, false);
    check_coefficient(f.cp, cells, true);
    check_coefficient(f.hv, cells, false);
    check_array(f.t_star, cells);
    check_array(f.h_star, cells);
    check_array(f.mass_x, product(product(g.nx + 1, g.ny), g.nz));
    check_array(f.mass_y, product(product(g.nx, g.ny + 1), g.nz));
    check_array(f.mass_z, product(product(g.nx, g.ny), g.nz + 1));
    if (!std::isfinite(f.h_in) || !std::isfinite(f.h_lo) ||
        !std::isfinite(f.h_hi) || f.h_lo > f.h_hi)
        throw std::invalid_argument("invalid enthalpy boundary or bounds");
}

double harmonic(double a, double b) {
    return a + b <= 0.0 ? 0.0 : 2.0 * a * b / (a + b);
}

std::uint64_t fluid_sweep(const GridView& g, const FluidView& f,
                          ArrayView<double> h, ArrayView<double> ts, double omega) {
    std::uint64_t clips = 0;
    const auto sx = g.ny * g.nz;
    const auto sy = g.nz;
    for (std::size_t i = 0; i < g.nx; ++i) {
        for (std::size_t j = 0; j < g.ny; ++j) {
            for (std::size_t k = 0; k < g.nz; ++k) {
                const auto p = (i * g.ny + j) * g.nz + k;
                const double dxi = g.dx[i], dyj = g.dy[j], dzk = g.dz[k];
                const double ax = dyj * dzk, ay = dxi * dzk, az = dxi * dyj;
                const double vol = dxi * dyj * dzk;
                const double ki = f.dh[p] * f.cp[p];
                const double dw = i > 0 ? harmonic(ki, f.dh[p-sx] * f.cp[p-sx]) * ax
                    / (0.5 * (g.dx[i-1] + dxi)) : 0.0;
                const double de = i+1 < g.nx ? harmonic(ki, f.dh[p+sx] * f.cp[p+sx]) * ax
                    / (0.5 * (g.dx[i+1] + dxi)) : 0.0;
                const double ds = j > 0 ? harmonic(ki, f.dh[p-sy] * f.cp[p-sy]) * ay
                    / (0.5 * (g.dy[j-1] + dyj)) : 0.0;
                const double dn = j+1 < g.ny ? harmonic(ki, f.dh[p+sy] * f.cp[p+sy]) * ay
                    / (0.5 * (g.dy[j+1] + dyj)) : 0.0;
                const double db = k > 0 ? harmonic(ki, f.dh[p-1] * f.cp[p-1]) * az
                    / (0.5 * (g.dz[k-1] + dzk)) : 0.0;
                const double dt = k+1 < g.nz ? harmonic(ki, f.dh[p+1] * f.cp[p+1]) * az
                    / (0.5 * (g.dz[k+1] + dzk)) : 0.0;

                const auto py = (i * (g.ny + 1) + j) * g.nz + k;
                const auto pz = (i * g.ny + j) * (g.nz + 1) + k;
                const double fw = f.mass_x[p], fe = f.mass_x[p+sx];
                const double fs = f.mass_y[py], fn = f.mass_y[py+sy];
                const double fb = f.mass_z[pz], ft = f.mass_z[pz+1];
                const double aw = std::max(fw, 0.0), ae = std::max(-fe, 0.0);
                const double as = std::max(fs, 0.0), an = std::max(-fn, 0.0);
                const double ab = std::max(fb, 0.0), at = std::max(-ft, 0.0);
                const double cpi = std::max(f.cp[p], 1e-30);
                const double offset = f.t_star[p] - f.h_star[p] / cpi;
                const double exchange = f.hv[p] * vol;
                const double ap = (dw + de + ds + dn + db + dt + exchange) / cpi
                    + std::max(-fw, 0.0) + std::max(fe, 0.0)
                    + std::max(-fs, 0.0) + std::max(fn, 0.0)
                    + std::max(-fb, 0.0) + std::max(ft, 0.0);
                double rhs = exchange * (ts[p] - f.t_star[p] + f.h_star[p] / cpi);
                if (i > 0)
                    rhs += aw * h[p-sx] + dw * (f.t_star[p-sx]
                        + (h[p-sx] - f.h_star[p-sx]) / f.cp[p-sx] - offset);
                else if (fw > 0.0) rhs += fw * f.h_in;
                if (i+1 < g.nx)
                    rhs += ae * h[p+sx] + de * (f.t_star[p+sx]
                        + (h[p+sx] - f.h_star[p+sx]) / f.cp[p+sx] - offset);
                else if (fe < 0.0) rhs += -fe * f.h_in;
                if (j > 0)
                    rhs += as * h[p-sy] + ds * (f.t_star[p-sy]
                        + (h[p-sy] - f.h_star[p-sy]) / f.cp[p-sy] - offset);
                else if (fs > 0.0) rhs += fs * f.h_in;
                if (j+1 < g.ny)
                    rhs += an * h[p+sy] + dn * (f.t_star[p+sy]
                        + (h[p+sy] - f.h_star[p+sy]) / f.cp[p+sy] - offset);
                else if (fn < 0.0) rhs += -fn * f.h_in;
                if (k > 0)
                    rhs += ab * h[p-1] + db * (f.t_star[p-1]
                        + (h[p-1] - f.h_star[p-1]) / f.cp[p-1] - offset);
                else if (fb > 0.0) rhs += fb * f.h_in;
                if (k+1 < g.nz)
                    rhs += at * h[p+1] + dt * (f.t_star[p+1]
                        + (h[p+1] - f.h_star[p+1]) / f.cp[p+1] - offset);
                else if (ft < 0.0) rhs += -ft * f.h_in;
                if (!std::isfinite(ap) || !std::isfinite(rhs))
                    throw std::domain_error("nonfinite fluid sweep equation");
                if (ap > 1e-30) {
                    const double update = (1.0 - omega) * h[p] + omega * rhs / ap;
                    if (!std::isfinite(update))
                        throw std::domain_error("nonfinite fluid sweep update");
                    clips += update < f.h_lo || update > f.h_hi;
                    h[p] = std::min(std::max(update, f.h_lo), f.h_hi);
                }
            }
        }
    }
    return clips;
}

void solid_sweep(const GridView& g, const FluidView& a, const FluidView& b,
                 ArrayView<const double> ks, ThermalStateView state, double omega) {
    const auto ts = state.t_s;
    const auto sx = g.ny * g.nz;
    const auto sy = g.nz;
    for (std::size_t i = 0; i < g.nx; ++i) {
        for (std::size_t j = 0; j < g.ny; ++j) {
            for (std::size_t k = 0; k < g.nz; ++k) {
                const auto p = (i * g.ny + j) * g.nz + k;
                const double dxi = g.dx[i], dyj = g.dy[j], dzk = g.dz[k];
                const double ax = dyj * dzk, ay = dxi * dzk, az = dxi * dyj;
                const double vol = dxi * dyj * dzk;
                const double dw = i > 0 ? harmonic(ks[p], ks[p-sx]) * ax
                    / (0.5 * (g.dx[i-1] + dxi)) : 0.0;
                const double de = i+1 < g.nx ? harmonic(ks[p], ks[p+sx]) * ax
                    / (0.5 * (g.dx[i+1] + dxi)) : 0.0;
                const double ds = j > 0 ? harmonic(ks[p], ks[p-sy]) * ay
                    / (0.5 * (g.dy[j-1] + dyj)) : 0.0;
                const double dn = j+1 < g.ny ? harmonic(ks[p], ks[p+sy]) * ay
                    / (0.5 * (g.dy[j+1] + dyj)) : 0.0;
                const double db = k > 0 ? harmonic(ks[p], ks[p-1]) * az
                    / (0.5 * (g.dz[k-1] + dzk)) : 0.0;
                const double dt = k+1 < g.nz ? harmonic(ks[p], ks[p+1]) * az
                    / (0.5 * (g.dz[k+1] + dzk)) : 0.0;
                const double ta = a.t_star[p]
                    + (state.h_a[p] - a.h_star[p]) / std::max(a.cp[p], 1e-30);
                const double tb = b.t_star[p]
                    + (state.h_b[p] - b.h_star[p]) / std::max(b.cp[p], 1e-30);
                const double ea = a.hv[p] * vol, eb = b.hv[p] * vol;
                const double ap = dw + de + ds + dn + db + dt + ea + eb;
                double rhs = ea * ta + eb * tb;
                if (i > 0) rhs += dw * ts[p-sx];
                if (i+1 < g.nx) rhs += de * ts[p+sx];
                if (j > 0) rhs += ds * ts[p-sy];
                if (j+1 < g.ny) rhs += dn * ts[p+sy];
                if (k > 0) rhs += db * ts[p-1];
                if (k+1 < g.nz) rhs += dt * ts[p+1];
                if (!std::isfinite(ap) || !std::isfinite(rhs))
                    throw std::domain_error("nonfinite solid sweep equation");
                if (ap > 1e-30) {
                    const double update = (1.0 - omega) * ts[p] + omega * rhs / ap;
                    if (!std::isfinite(update))
                        throw std::domain_error("nonfinite solid sweep update");
                    ts[p] = update;
                }
            }
        }
    }
}
}  // namespace

ClipCounts enthalpy_sweeps(const GridView& grid, const FluidView& a,
                          const FluidView& b, ArrayView<const double> k_ss,
                          ThermalStateView state, std::size_t n_sweeps,
                          double omega) {
    const auto cells = check_grid(grid);
    check_array(state.h_a, cells);
    check_array(state.h_b, cells);
    check_array(state.t_s, cells);
    check_coefficient(k_ss, cells, false);
    check_fluid(a, grid, cells);
    check_fluid(b, grid, cells);
    if (!std::isfinite(omega) || omega <= 0.0 || omega > 1.0)
        throw std::invalid_argument("omega must be in (0, 1]");
    ClipCounts clips{0, 0};
    for (std::size_t sweep = 0; sweep < n_sweeps; ++sweep) {
        clips.a += fluid_sweep(grid, a, state.h_a, state.t_s, omega);
        clips.b += fluid_sweep(grid, b, state.h_b, state.t_s, omega);
        solid_sweep(grid, a, b, k_ss, state, omega);
    }
    return clips;
}

namespace {
void check_energy_fluid(const FluidEnergyView& f, const GridView& g, std::size_t cells) {
    check_array(f.h, cells);
    check_array(f.temperature, cells);
    check_coefficient(f.hv, cells, false);
    check_coefficient(f.conductivity, cells, false);
    check_array(f.mass_x, product(product(g.nx + 1, g.ny), g.nz));
    check_array(f.mass_y, product(product(g.nx, g.ny + 1), g.nz));
    check_array(f.mass_z, product(product(g.nx, g.ny), g.nz + 1));
    if (!std::isfinite(f.h_in)) throw std::invalid_argument("nonfinite inlet enthalpy");
}

// Each internal Fourier face is shared by two cells, with opposite signs.
void conduction_source(const GridView& g, ArrayView<const double> t,
                       ArrayView<const double> conductivity, ArrayView<double> r) {
    const std::size_t stride[] = {g.ny * g.nz, g.nz, 1};
    const std::size_t extent[] = {g.nx, g.ny, g.nz};
    const ArrayView<const double> width[] = {g.dx, g.dy, g.dz};
    for (std::size_t i = 0; i < g.nx; ++i)
        for (std::size_t j = 0; j < g.ny; ++j)
            for (std::size_t k = 0; k < g.nz; ++k) {
                const auto p = (i * g.ny + j) * g.nz + k;
                const std::size_t coord[] = {i, j, k};
                const double volume = g.dx[i] * g.dy[j] * g.dz[k];
                for (std::size_t axis = 0; axis < 3; ++axis) {
                    const auto c = coord[axis];
                    if (c + 1 == extent[axis]) continue;
                    const auto q = p + stride[axis];
                    const double flux = harmonic(conductivity[p], conductivity[q])
                        * (volume / width[axis][c])
                        / (0.5 * (width[axis][c] + width[axis][c+1])) * (t[q] - t[p]);
                    r[p] += flux;
                    r[q] -= flux;
                }
            }
}

double fluid_residual(const GridView& g, const FluidEnergyView& f,
                      ArrayView<const double> ts, ArrayView<double> r) {
    for (std::size_t i = 0; i < g.nx; ++i)
        for (std::size_t j = 0; j < g.ny; ++j)
            for (std::size_t k = 0; k < g.nz; ++k) {
                const auto p = (i * g.ny + j) * g.nz + k;
                r[p] = f.hv[p] * (ts[p] - f.temperature[p]) * g.dx[i] * g.dy[j] * g.dz[k];
            }
    conduction_source(g, f.temperature, f.conductivity, r);
    double q_in = 0.;
    const ArrayView<const double> mass[] = {f.mass_x, f.mass_y, f.mass_z};
    const std::size_t stride[] = {g.ny * g.nz, g.nz, 1};
    const std::size_t extent[] = {g.nx, g.ny, g.nz};
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const auto nx = g.nx + (axis == 0), ny = g.ny + (axis == 1), nz = g.nz + (axis == 2);
        for (std::size_t i = 0; i < nx; ++i)
            for (std::size_t j = 0; j < ny; ++j)
                for (std::size_t k = 0; k < nz; ++k) {
                    const std::size_t coord[] = {i, j, k};
                    const auto c = coord[axis];
                    const auto high = (i * g.ny + j) * g.nz + k;
                    const auto low = c > 0 ? high - stride[axis] : 0;
                    const double flow = mass[axis][(i * ny + j) * nz + k];
                    const double upstream = flow >= 0.
                        ? (c > 0 ? f.h[low] : f.h_in)
                        : (c < extent[axis] ? f.h[high] : f.h_in);
                    const double flux = flow * upstream;
                    if (c > 0) r[low] -= flux;
                    else q_in += flux;
                    if (c < extent[axis]) r[high] += flux;
                    else q_in -= flux;
                }
    }
    return q_in;
}
}  // namespace

EnergyAudit thermal_energy_audit(const GridView& grid, const FluidEnergyView& a,
                                const FluidEnergyView& b, ArrayView<const double> ts,
                                ArrayView<const double> k_ss, ArrayView<double> ra,
                                ArrayView<double> rb, ArrayView<double> rs) {
    const auto cells = check_grid(grid);
    check_energy_fluid(a, grid, cells);
    check_energy_fluid(b, grid, cells);
    check_array(ts, cells);
    check_coefficient(k_ss, cells, false);
    for (const auto r : {ra, rb, rs})
        if (!r.data || r.size != cells)
            throw std::invalid_argument("residual array length does not match grid");
    EnergyAudit result{};
    result.q_a = fluid_residual(grid, a, ts, ra);
    result.q_b = fluid_residual(grid, b, ts, rb);
    for (std::size_t i = 0; i < grid.nx; ++i)
        for (std::size_t j = 0; j < grid.ny; ++j)
            for (std::size_t k = 0; k < grid.nz; ++k) {
                const auto p = (i * grid.ny + j) * grid.nz + k;
                rs[p] = (a.hv[p] * (a.temperature[p] - ts[p])
                       + b.hv[p] * (b.temperature[p] - ts[p]))
                       * grid.dx[i] * grid.dy[j] * grid.dz[k];
            }
    conduction_source(grid, ts, k_ss, rs);
    for (std::size_t p = 0; p < cells; ++p) {
        if (!std::isfinite(ra[p]) || !std::isfinite(rb[p]) || !std::isfinite(rs[p]))
            throw std::domain_error("nonfinite energy residual");
        result.fluid_abs_sum[0] += std::abs(ra[p]);
        result.fluid_abs_sum[1] += std::abs(rb[p]);
        result.fluid_cell_max[0] = std::max(result.fluid_cell_max[0], std::abs(ra[p]));
        result.fluid_cell_max[1] = std::max(result.fluid_cell_max[1], std::abs(rb[p]));
        result.solid_abs_sum += std::abs(rs[p]);
    }
    result.net = result.q_a + result.q_b;
    result.denominator = std::max({std::abs(result.q_a), std::abs(result.q_b), 1.});
    result.coupled_ratio = std::max(std::abs(result.net), result.solid_abs_sum) / result.denominator;
    result.equation_ratio = std::max({std::abs(result.net), result.solid_abs_sum,
        result.fluid_abs_sum[0], result.fluid_abs_sum[1]}) / result.denominator;
    for (const double x : {result.q_a, result.q_b, result.net, result.solid_abs_sum,
            result.denominator, result.coupled_ratio, result.equation_ratio,
            result.fluid_abs_sum[0], result.fluid_abs_sum[1]})
        if (!std::isfinite(x)) throw std::domain_error("nonfinite energy budget");
    return result;
}
}  // namespace tpmshx
