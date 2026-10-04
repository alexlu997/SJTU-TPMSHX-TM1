#include "tpmshx/conservative_energy.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <vector>

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

std::size_t check_grid(const GridView& g) {
    if (g.nx == std::numeric_limits<std::size_t>::max() ||
        g.ny == std::numeric_limits<std::size_t>::max() ||
        g.nz == std::numeric_limits<std::size_t>::max())
        throw std::invalid_argument("invalid grid extent");
    const auto cells = product(product(g.nx, g.ny), g.nz);
    check_coefficient(g.dx, g.nx, true);
    check_coefficient(g.dy, g.ny, true);
    check_coefficient(g.dz, g.nz, true);
    return cells;
}

void check_mass(const std::array<ArrayView<const double>, 3>& mass,
                const GridView& g) {
    check_array(mass[0], product(product(g.nx + 1, g.ny), g.nz));
    check_array(mass[1], product(product(g.nx, g.ny + 1), g.nz));
    check_array(mass[2], product(product(g.nx, g.ny), g.nz + 1));
}

void check_fluid(const FluidView& f, const GridView& g, std::size_t cells) {
    check_coefficient(f.dh, cells, false);
    check_coefficient(f.cp, cells, true);
    check_coefficient(f.hv, cells, false);
    check_array(f.t_star, cells);
    check_array(f.h_star, cells);
    check_mass({f.mass_x, f.mass_y, f.mass_z}, g);
    if (!std::isfinite(f.h_in))
        throw std::invalid_argument("nonfinite inlet enthalpy");
}

void update_temperature(double diagonal, double rhs, double omega, double& t) {
    if (!std::isfinite(diagonal) || !std::isfinite(rhs))
        throw std::domain_error("nonfinite conservative temperature row");
    if (diagonal > 1e-30) {
        const double next = (1. - omega) * t + omega * rhs / diagonal;
        if (!std::isfinite(next))
            throw std::domain_error("nonfinite conservative temperature update");
        t = next;
    }
}

void fluid_sweep(const GridView& g, const FluidView& f, ArrayView<double> t,
                 ArrayView<double> ts, double omega,
                 ArrayView<const double> source, bool reverse) {
    const std::size_t stride[]{g.ny * g.nz, g.nz, 1};
    const std::size_t extent[]{g.nx, g.ny, g.nz};
    const ArrayView<const double> width[]{g.dx, g.dy, g.dz};
    const ArrayView<const double> mass[]{f.mass_x, f.mass_y, f.mass_z};
    const auto cells = g.nx * g.ny * g.nz;
    for (std::size_t ordinal = 0; ordinal < cells; ++ordinal) {
        const auto p = reverse ? cells - 1 - ordinal : ordinal;
        const std::size_t i = p / stride[0], j = (p / g.nz) % g.ny, k = p % g.nz;
        const std::size_t coord[]{i, j, k};
        const std::size_t face[]{p, (i * (g.ny + 1) + j) * g.nz + k,
            (i * g.ny + j) * (g.nz + 1) + k};
        const double volume = g.dx[i] * g.dy[j] * g.dz[k];
        const double ki = f.dh[p] * f.cp[p], exchange = f.hv[p] * volume;
        const double intercept = f.h_star[p] - f.cp[p] * f.t_star[p];
        double diagonal = exchange;
        double rhs = exchange * ts[p] + (source.size ? source[p] : 0.);
        for (std::size_t axis = 0; axis < 3; ++axis) {
            const auto c = coord[axis];
            const double area = volume / width[axis][c];
            for (int sign : {-1, 1}) {
                const double outward = sign * mass[axis][face[axis]
                    + (sign > 0 ? stride[axis] : 0)];
                const double leaving = std::max(outward, 0.);
                const double entering = std::max(-outward, 0.);
                diagonal += leaving * f.cp[p];
                rhs -= leaving * intercept;
                if (sign < 0 ? c > 0 : c + 1 < extent[axis]) {
                    const auto q = sign < 0 ? p - stride[axis] : p + stride[axis];
                    const auto neighbor = sign < 0 ? c - 1 : c + 1;
                    const double d = detail::diffusion_conductance(
                        ki, f.dh[q] * f.cp[q], .5 * width[axis][c],
                        .5 * width[axis][neighbor]) * area;
                    diagonal += d;
                    rhs += d * t[q]
                        + entering * (f.h_star[q] + f.cp[q] * (t[q] - f.t_star[q]));
                } else {
                    rhs += entering * f.h_in;
                }
            }
        }
        update_temperature(diagonal, rhs, omega, t[p]);
    }
}

void solid_sweep(const GridView& g, const FluidView& a, const FluidView& b,
                 ArrayView<const double> ks, TemperatureStateView state,
                 double omega, bool reverse) {
    const std::size_t stride[]{g.ny * g.nz, g.nz, 1}, extent[]{g.nx, g.ny, g.nz};
    const ArrayView<const double> width[]{g.dx, g.dy, g.dz};
    const auto cells = g.nx * g.ny * g.nz;
    for (std::size_t ordinal = 0; ordinal < cells; ++ordinal) {
        const auto p = reverse ? cells - 1 - ordinal : ordinal;
        const std::size_t i = p / stride[0], j = (p / g.nz) % g.ny, k = p % g.nz;
        const std::size_t coord[]{i, j, k};
        const double volume = g.dx[i] * g.dy[j] * g.dz[k];
        const double ea = a.hv[p] * volume, eb = b.hv[p] * volume;
        double diagonal = ea + eb, rhs = ea * state.a[p] + eb * state.b[p];
        for (std::size_t axis = 0; axis < 3; ++axis) {
            const auto c = coord[axis];
            for (int sign : {-1, 1}) {
                if (sign < 0 ? c == 0 : c + 1 == extent[axis]) continue;
                const auto q = sign < 0 ? p - stride[axis] : p + stride[axis];
                const auto neighbor = sign < 0 ? c - 1 : c + 1;
                const double d = detail::diffusion_conductance(ks[p], ks[q],
                    .5 * width[axis][c], .5 * width[axis][neighbor])
                    * (volume / width[axis][c]);
                diagonal += d;
                rhs += d * state.solid[q];
            }
        }
        update_temperature(diagonal, rhs, omega, state.solid[p]);
    }
}

double slope(double difference, double distance) {
    const double value = difference / distance;
    if (!std::isfinite(distance) || !std::isfinite(value))
        throw std::domain_error("nonfinite enthalpy reconstruction slope");
    return value;
}

double minmod(double a, double b) {
    if ((a > 0. && b > 0.) || (a < 0. && b < 0.))
        return std::copysign(std::min(std::abs(a), std::abs(b)), a);
    return 0.;
}

std::array<std::vector<double>, 3> enthalpy_gradients(
    const GridView& g, ArrayView<const double> h,
    const std::array<ArrayView<const double>, 3>& mass, double h_in) {
    const auto cells = g.nx * g.ny * g.nz;
    const std::size_t stride[]{g.ny * g.nz, g.nz, 1}, extent[]{g.nx, g.ny, g.nz};
    const ArrayView<const double> width[]{g.dx, g.dy, g.dz};
    std::array<std::vector<double>, 3> gradient{
        std::vector<double>(cells), std::vector<double>(cells), std::vector<double>(cells)};
    for (std::size_t i = 0; i < g.nx; ++i)
        for (std::size_t j = 0; j < g.ny; ++j)
            for (std::size_t k = 0; k < g.nz; ++k) {
                const auto p = (i * g.ny + j) * g.nz + k;
                const std::size_t coord[]{i, j, k};
                const std::size_t face[]{p, (i * (g.ny + 1) + j) * g.nz + k,
                    (i * g.ny + j) * (g.nz + 1) + k};
                for (std::size_t axis = 0; axis < 3; ++axis) {
                    if (extent[axis] == 1) continue;
                    const auto c = coord[axis];
                    const double d = width[axis][c];
                    bool have_left = false, have_right = false;
                    double left = 0., right = 0.;
                    if (c > 0) {
                        left = slope(h[p] - h[p - stride[axis]], .5 * (d + width[axis][c - 1]));
                        have_left = true;
                    } else if (mass[axis][face[axis]] > 0.) {
                        left = slope(h[p] - h_in, .5 * d);
                        have_left = true;
                    }
                    if (c + 1 < extent[axis]) {
                        right = slope(h[p + stride[axis]] - h[p], .5 * (d + width[axis][c + 1]));
                        have_right = true;
                    } else if (mass[axis][face[axis] + stride[axis]] < 0.) {
                        right = slope(h_in - h[p], .5 * d);
                        have_right = true;
                    }
                    gradient[axis][p] = have_left && have_right ? minmod(left, right)
                        : (have_left ? left : have_right ? right : 0.);
                }
            }
    return gradient;
}

}  // namespace

void conservative_temperature_sweeps(
    const GridView& g, const FluidView& a, const FluidView& b,
    ArrayView<const double> k_ss, TemperatureStateView state,
    std::size_t sweeps, double omega, ArrayView<const double> source_a,
    ArrayView<const double> source_b, double solid_omega) {
    const auto cells = check_grid(g);
    check_fluid(a, g, cells);
    check_fluid(b, g, cells);
    check_coefficient(k_ss, cells, false);
    for (const auto t : {state.a, state.b, state.solid}) check_array(t, cells);
    for (const auto source : {source_a, source_b})
        if (source.size) check_array(source, cells);
    for (const double relaxation : {omega, solid_omega})
        if (!std::isfinite(relaxation) || relaxation <= 0. || relaxation > 1.)
            throw std::invalid_argument("fluid and solid omega must be in (0, 1]");
    for (std::size_t sweep = 0; sweep < sweeps; ++sweep) {
        const bool reverse = sweep % 2 != 0;
        fluid_sweep(g, a, state.a, state.solid, omega, source_a, reverse);
        fluid_sweep(g, b, state.b, state.solid, omega, source_b, reverse);
        solid_sweep(g, a, b, k_ss, state, solid_omega, reverse);
    }
}

double enthalpy_sou_correction(
    const GridView& g, ArrayView<const double> h,
    const std::array<ArrayView<const double>, 3>& mass, double h_in,
    ArrayView<double> correction) {
    const auto cells = check_grid(g);
    check_array(h, cells);
    check_mass(mass, g);
    if (!std::isfinite(h_in)) throw std::invalid_argument("nonfinite inlet enthalpy");
    if (!correction.data || correction.size != cells)
        throw std::invalid_argument("correction array length does not match grid");
    const std::size_t stride[]{g.ny * g.nz, g.nz, 1}, extent[]{g.nx, g.ny, g.nz};
    const ArrayView<const double> width[]{g.dx, g.dy, g.dz};
    const auto gradient = enthalpy_gradients(g, h, mass, h_in);
    std::fill_n(correction.data, cells, 0.);
    double boundary = 0.;
    for (std::size_t i = 0; i < g.nx; ++i)
        for (std::size_t j = 0; j < g.ny; ++j)
            for (std::size_t k = 0; k < g.nz; ++k) {
                const auto p = (i * g.ny + j) * g.nz + k;
                const std::size_t coord[]{i, j, k};
                const std::size_t face[]{p, (i * (g.ny + 1) + j) * g.nz + k,
                    (i * g.ny + j) * (g.nz + 1) + k};
                for (std::size_t axis = 0; axis < 3; ++axis) {
                    const auto c = coord[axis];
                    if (c + 1 < extent[axis]) {
                        const auto q = p + stride[axis];
                        const double m = mass[axis][face[axis] + stride[axis]];
                        const double flux = m * (m >= 0.
                            ? gradient[axis][p] * .5 * width[axis][c]
                            : -gradient[axis][q] * .5 * width[axis][c + 1]);
                        correction[p] -= flux;
                        correction[q] += flux;
                    }
                    if (c == 0 && mass[axis][face[axis]] < 0.) {
                        const double change = mass[axis][face[axis]]
                            * (-.5 * width[axis][c] * gradient[axis][p]);
                        correction[p] += change;
                        boundary += change;
                    }
                    if (c + 1 == extent[axis] && mass[axis][face[axis] + stride[axis]] > 0.) {
                        const double change = -mass[axis][face[axis] + stride[axis]]
                            * (.5 * width[axis][c] * gradient[axis][p]);
                        correction[p] += change;
                        boundary += change;
                    }
                }
            }
    if (!std::isfinite(boundary))
        throw std::domain_error("nonfinite SOU boundary correction");
    for (std::size_t p = 0; p < cells; ++p)
        if (!std::isfinite(correction[p]))
            throw std::domain_error("nonfinite SOU cell correction");
    return boundary;
}

std::array<std::vector<double>, 6> enthalpy_boundary_power(
    const GridView& g, ArrayView<const double> h,
    const std::array<ArrayView<const double>, 3>& mass, double h_in,
    bool second_order) {
    const auto cells = check_grid(g);
    check_array(h, cells);
    check_mass(mass, g);
    if (!std::isfinite(h_in)) throw std::invalid_argument("nonfinite inlet enthalpy");
    std::array<std::vector<double>, 3> gradient;
    if (second_order) gradient = enthalpy_gradients(g, h, mass, h_in);
    const std::size_t stride[]{g.ny * g.nz, g.nz, 1}, extent[]{g.nx, g.ny, g.nz};
    const ArrayView<const double> width[]{g.dx, g.dy, g.dz};
    std::array<std::vector<double>, 6> result;
    for (std::size_t axis = 0; axis < 3; ++axis)
        for (const int sign : {-1, 1}) {
            auto& plane = result[2 * axis + (sign > 0)];
            plane.reserve(cells / extent[axis]);
            for (std::size_t i = 0; i < g.nx; ++i)
                for (std::size_t j = 0; j < g.ny; ++j)
                    for (std::size_t k = 0; k < g.nz; ++k) {
                        const std::size_t coord[]{i, j, k};
                        const auto c = coord[axis];
                        if (c != (sign > 0 ? extent[axis] - 1 : 0)) continue;
                        const auto p = (i * g.ny + j) * g.nz + k;
                        const std::size_t face[]{p, (i * (g.ny + 1) + j) * g.nz + k,
                            (i * g.ny + j) * (g.nz + 1) + k};
                        const double outward = sign * mass[axis][face[axis]
                            + (sign > 0 ? stride[axis] : 0)];
                        double face_h = h_in;
                        if (outward > 0.) {
                            face_h = h[p];
                            if (second_order) face_h += sign * .5 * width[axis][c] * gradient[axis][p];
                        }
                        const double power = outward == 0. ? 0. : outward * face_h;
                        if (!std::isfinite(power)) throw std::domain_error("nonfinite boundary enthalpy power");
                        plane.push_back(power);
                    }
        }
    return result;
}

EnergyAudit thermal_energy_audit_sou(
    const GridView& g, const FluidEnergyView& a, const FluidEnergyView& b,
    ArrayView<const double> ts, ArrayView<const double> k_ss,
    ArrayView<double> ra, ArrayView<double> rb, ArrayView<double> rs) {
    auto result = thermal_energy_audit(g, a, b, ts, k_ss, ra, rb, rs);
    const auto cells = ra.size;
    std::vector<double> correction(cells);
    const FluidEnergyView fluids[]{a, b};
    const ArrayView<double> residuals[]{ra, rb};
    double* duties[]{&result.q_a, &result.q_b};
    for (std::size_t side = 0; side < 2; ++side) {
        const auto& f = fluids[side];
        *duties[side] += enthalpy_sou_correction(g, f.h,
            {f.mass_x, f.mass_y, f.mass_z}, f.h_in, {correction.data(), cells});
        result.fluid_abs_sum[side] = result.fluid_cell_max[side] = 0.;
        for (std::size_t p = 0; p < cells; ++p) {
            residuals[side][p] += correction[p];
            if (!std::isfinite(residuals[side][p]))
                throw std::domain_error("nonfinite SOU energy residual");
            result.fluid_abs_sum[side] += std::abs(residuals[side][p]);
            result.fluid_cell_max[side] = std::max(result.fluid_cell_max[side],
                std::abs(residuals[side][p]));
        }
    }
    result.net = result.q_a + result.q_b;
    result.denominator = std::max({std::abs(result.q_a), std::abs(result.q_b), 1.});
    result.coupled_ratio = std::max(std::abs(result.net), result.solid_abs_sum) / result.denominator;
    result.equation_ratio = std::max({std::abs(result.net), result.solid_abs_sum,
        result.fluid_abs_sum[0], result.fluid_abs_sum[1]}) / result.denominator;
    for (const double value : {result.q_a, result.q_b, result.net,
            result.denominator, result.coupled_ratio, result.equation_ratio,
            result.fluid_abs_sum[0], result.fluid_abs_sum[1]})
        if (!std::isfinite(value)) throw std::domain_error("nonfinite SOU energy budget");
    return result;
}

}  // namespace tpmshx
