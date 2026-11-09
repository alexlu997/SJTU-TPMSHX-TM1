#include "tpmshx/simple_pressure.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace tpmshx {
namespace {

std::size_t multiply(std::size_t a, std::size_t b) {
    if (!a || !b || a > std::numeric_limits<std::size_t>::max() / b)
        throw std::invalid_argument("invalid SIMPLE grid extent");
    return a * b;
}

template <typename T>
void extent(ArrayView<T> array, std::size_t size) {
    if (array.size != size || (size != 0 && !array.data))
        throw std::invalid_argument("SIMPLE array extent does not match grid");
}

template <typename T>
void field(ArrayView<T> array, std::size_t size, int sign = 0) {
    extent(array, size);
    for (std::size_t i = 0; i < size; ++i)
        if (!std::isfinite(array[i]) || (sign == 1 && array[i] <= 0.)
                || (sign == 2 && array[i] < 0.))
            throw std::invalid_argument("invalid SIMPLE field value");
}

void mask(ArrayView<const unsigned char> array, std::size_t size) {
    extent(array, size);
    for (std::size_t i = 0; i < size; ++i)
        if (array[i] > 1) throw std::invalid_argument("SIMPLE mask must contain only zero or one");
}

std::size_t check_grid(int dimension, const GridView& g) {
    if ((dimension != 2 && dimension != 3)
            || g.nx == std::numeric_limits<std::size_t>::max()
            || g.ny == std::numeric_limits<std::size_t>::max()
            || g.nz == std::numeric_limits<std::size_t>::max())
        throw std::invalid_argument("invalid SIMPLE dimension or grid");
    const auto cells = multiply(multiply(g.nx, g.ny), g.nz);
    if (cells >= static_cast<std::size_t>(std::numeric_limits<int>::max()))
        throw std::invalid_argument("SIMPLE pressure grid exceeds 32-bit indices");
    field(g.dx, g.nx, 1); field(g.dy, g.ny, 1); field(g.dz, g.nz, 1);
    if (dimension == 2 && (g.nz != 1 || g.dz[0] != 1.))
        throw std::invalid_argument("2D SIMPLE requires nz=1 and unit depth");
    return cells;
}

template <typename T>
void check_faces(int dimension, const GridView& g, SimpleFacesView<T> faces, int sign = 0) {
    field(faces.u, multiply(multiply(g.nx + 1, g.ny), g.nz), sign);
    field(faces.v, multiply(multiply(g.nx, g.ny + 1), g.nz), sign);
    field(faces.w, dimension == 3 ? multiply(multiply(g.nx, g.ny), g.nz + 1) : 0, sign);
}

void check_boundary(int dimension, const GridView& g, const SimpleBoundaryView& b) {
    const auto ports = multiply(g.nx, g.nz);
    field(b.inlet_velocity, ports);
    field(b.inlet_fraction, dimension == 2 ? ports : 0, 2);
    for (std::size_t i = 0; i < b.inlet_fraction.size; ++i)
        if (b.inlet_fraction[i] > 1.) throw std::invalid_argument("inlet fraction exceeds one");
    mask(b.outlet_open, ports);
}

double finite(double value) {
    if (!std::isfinite(value)) throw std::domain_error("nonfinite SIMPLE pressure/continuity arithmetic");
    return value;
}

std::size_t cell(const GridView& g, std::size_t i, std::size_t j, std::size_t k) {
    return (i * g.ny + j) * g.nz + k;
}
std::size_t yface(const GridView& g, std::size_t i, std::size_t j, std::size_t k) {
    return (i * (g.ny + 1) + j) * g.nz + k;
}
std::size_t zface(const GridView& g, std::size_t i, std::size_t j, std::size_t k) {
    return (i * g.ny + j) * (g.nz + 1) + k;
}

// E,W,N,S,T,B; the same arithmetic face interpolation as both Python owners.
std::array<double, 6> densities(const GridView& g, ArrayView<const double> rho_eps,
                                std::size_t i, std::size_t j, std::size_t k) {
    const auto p = cell(g, i, j, k), sx = g.ny * g.nz, sy = g.nz;
    const double center = rho_eps[p];
    return {i + 1 < g.nx ? .5 * (center + rho_eps[p + sx]) : center,
            i > 0 ? .5 * (rho_eps[p - sx] + center) : center,
            j + 1 < g.ny ? .5 * (center + rho_eps[p + sy]) : center,
            j > 0 ? .5 * (rho_eps[p - sy] + center) : center,
            k + 1 < g.nz ? .5 * (center + rho_eps[p + 1]) : center,
            k > 0 ? .5 * (rho_eps[p - 1] + center) : center};
}

std::array<double, 6> face_fluxes(int dimension, const GridView& g,
                                 SimpleFacesView<const double> v,
                                 ArrayView<const double> rho_eps,
                                 std::size_t i, std::size_t j, std::size_t k) {
    const auto rho = densities(g, rho_eps, i, j, k);
    const auto px = cell(g, i, j, k), py = yface(g, i, j, k), pz = zface(g, i, j, k);
    const auto sx = g.ny * g.nz;
    const double ae = g.dy[j] * g.dz[k], an = g.dx[i] * g.dz[k], at = g.dx[i] * g.dy[j];
    std::array<double, 6> flux{
        rho[0] * v.u[px + sx] * ae, rho[1] * v.u[px] * ae,
        rho[2] * v.v[py + g.nz] * an, rho[3] * v.v[py] * an,
        dimension == 3 ? rho[4] * v.w[pz + 1] * at : 0.,
        dimension == 3 ? rho[5] * v.w[pz] * at : 0.};
    for (double value : flux) finite(value);
    return flux;
}

void close_outlet_unchecked(int dimension, const GridView& g,
                            ArrayView<const unsigned char> outlet,
                            SimpleFacesView<double> v,
                            ArrayView<const double> rho, ArrayView<const double> eps) {
    const auto j = g.ny - 1, sx = g.ny * g.nz, sy = g.nz;
    for (std::size_t i = 0; i < g.nx; ++i) {
        for (std::size_t k = 0; k < g.nz; ++k) {
            const auto py = yface(g, i, j, k), px = cell(g, i, j, k);
            if (!outlet[i * g.nz + k]) { v.v[py + sy] = 0.; continue; }
            if (dimension == 2) {
                // Keep the 2D epsilon-ratio algebra and its evaluation order.
                const double rc = rho[px], ec = eps[px];
                const double rs = j > 0 ? .5 * (rho[px - sy] * (eps[px - sy] / ec) + rc) : rc;
                const double rw = i > 0 ? .5 * (rho[px - sx] * (eps[px - sx] / ec) + rc) : rc;
                const double re = i + 1 < g.nx ? .5 * (rc + rho[px + sx] * (eps[px + sx] / ec)) : rc;
                const double lateral = (re * v.u[px + sx] - rw * v.u[px]) * g.dy[j] / g.dx[i];
                v.v[py + sy] = finite((rs * v.v[py] - lateral) / rc);
            } else {
                const auto pz = zface(g, i, j, k);
                const double er = rho[px] * eps[px];
                const double ers = j > 0 ? .5 * std::fma(rho[px - sy], eps[px - sy], er) : er;
                const double erw = i > 0 ? .5 * std::fma(rho[px - sx], eps[px - sx], er) : er;
                const double ere = i + 1 < g.nx ? .5 * std::fma(rho[px + sx], eps[px + sx], er) : er;
                const double erb = k > 0 ? .5 * std::fma(rho[px - 1], eps[px - 1], er) : er;
                const double ert = k + 1 < g.nz ? .5 * std::fma(rho[px + 1], eps[px + 1], er) : er;
                // Match the 3D kernel's fused arithmetic and z-before-x sum.
                const double cross_x = std::fma(-erw, v.u[px], ere * v.u[px + sx])
                    * (-g.dy[j]) / g.dx[i];
                const double cross_z = std::fma(-erb, v.w[pz], ert * v.w[pz + 1])
                    * (-g.dy[j]) / g.dz[k];
                v.v[py + sy] = finite((std::fma(ers, v.v[py], cross_z) + cross_x) / er);
            }
        }
    }
}

void y_boundary_unchecked(int dimension, const GridView& g, const SimpleBoundaryView& b,
                           SimpleFacesView<double> velocity,
                           ArrayView<const double> rho, ArrayView<const double> eps) {
    for (std::size_t i = 0; i < g.nx; ++i)
        for (std::size_t k = 0; k < g.nz; ++k) {
            const auto port = i * g.nz + k;
            velocity.v[yface(g, i, 0, k)] = finite(b.inlet_velocity[port]
                * (dimension == 2 ? b.inlet_fraction[port] : 1.));
        }
    close_outlet_unchecked(dimension, g, b.outlet_open, velocity, rho, eps);
}

}  // namespace

SimplePressureAssembly::SimplePressureAssembly(int dimension, const GridView& g,
                                               ArrayView<const unsigned char> outlet)
    : dimension_(dimension), nx_(g.nx), ny_(g.ny), nz_(g.nz) {
    const auto n = check_grid(dimension, g);
    mask(outlet, multiply(g.nx, g.nz));
    system_.row_offsets.resize(n + 1);
    system_.rhs.resize(n);
    system_.pin_mask.resize(n);
    const auto add = [&](std::size_t value) { system_.columns.push_back(static_cast<int>(value)); };
    for (std::size_t i = 0; i < g.nx; ++i)
        for (std::size_t j = 0; j < g.ny; ++j)
            for (std::size_t k = 0; k < g.nz; ++k) {
                if (system_.columns.size() > static_cast<std::size_t>(std::numeric_limits<int>::max() - 7))
                    throw std::invalid_argument("SIMPLE pressure stencil exceeds 32-bit nnz");
                const auto p = cell(g, i, j, k);
                system_.row_offsets[p] = static_cast<int>(system_.columns.size());
                const bool pin = j + 1 == g.ny && outlet[i * g.nz + k];
                system_.pin_mask[p] = static_cast<unsigned char>(pin);
                // Natural sorted columns: W,S,B,center,T,N,E. Missing stencil
                // slots contribute zero to center in Python and need no entry.
                if (!pin) {
                    if (i > 0) add(p - g.ny * g.nz);
                    if (j > 0) add(p - g.nz);
                    if (dimension == 3 && k > 0) add(p - 1);
                }
                add(p);
                if (!pin) {
                    if (dimension == 3 && k + 1 < g.nz) add(p + 1);
                    if (j + 1 < g.ny) add(p + g.nz);
                    if (i + 1 < g.nx) add(p + g.ny * g.nz);
                }
            }
    system_.row_offsets[n] = static_cast<int>(system_.columns.size());
    system_.values.resize(system_.columns.size());
}

const PressureSystem& SimplePressureAssembly::assemble(const GridView& g,
        SimpleFacesView<const double> velocity, SimpleFacesView<const double> d,
        ArrayView<const double> rho_eps) {
    const auto n = check_grid(dimension_, g);
    if (g.nx != nx_ || g.ny != ny_ || g.nz != nz_)
        throw std::invalid_argument("SIMPLE assembly shape differs from cached pattern");
    check_faces(dimension_, g, velocity); check_faces(dimension_, g, d, 2);
    field(rho_eps, n, 1);
    for (std::size_t i = 0; i < g.nx; ++i)
        for (std::size_t j = 0; j < g.ny; ++j)
            for (std::size_t k = 0; k < g.nz; ++k) {
                const auto p = cell(g, i, j, k), py = yface(g, i, j, k), pz = zface(g, i, j, k);
                auto at = static_cast<std::size_t>(system_.row_offsets[p]);
                if (system_.pin_mask[p]) { system_.values[at] = 1.; system_.rhs[p] = 0.; continue; }
                const auto rho = densities(g, rho_eps, i, j, k);
                const double ae = g.dy[j] * g.dz[k], an = g.dx[i] * g.dz[k], az = g.dx[i] * g.dy[j];
                const auto sx = g.ny * g.nz;
                // The original 3D JIT groups rho*area before d, then sums
                // opposite-face pairs. Keep the established 2D order intact.
                const double e = i + 1 < g.nx ? (dimension_ == 3
                    ? (rho[0] * ae) * d.u[p + sx] : rho[0] * d.u[p + sx] * ae) : 0.;
                const double w = i > 0 ? (dimension_ == 3
                    ? (rho[1] * ae) * d.u[p] : rho[1] * d.u[p] * ae) : 0.;
                const double north = j + 1 < g.ny ? (dimension_ == 3
                    ? (rho[2] * an) * d.v[py + g.nz] : rho[2] * d.v[py + g.nz] * an) : 0.;
                const double south = j > 0 ? (dimension_ == 3
                    ? (rho[3] * an) * d.v[py] : rho[3] * d.v[py] * an) : 0.;
                const double top = dimension_ == 3 && k + 1 < g.nz ? (rho[4] * az) * d.w[pz + 1] : 0.;
                const double bottom = dimension_ == 3 && k > 0 ? (rho[5] * az) * d.w[pz] : 0.;
                const double diagonal = finite(dimension_ == 3
                    ? ((e + w) + (north + south)) + (top + bottom)
                    : e + w + north + south + top + bottom);
                const bool degenerate = diagonal < 1e-30;
                const auto put = [&](double value) { system_.values[at++] = degenerate ? 0. : -value; };
                if (i > 0) put(w);
                if (j > 0) put(south);
                if (dimension_ == 3 && k > 0) put(bottom);
                system_.values[at++] = degenerate ? 1. : diagonal;
                if (dimension_ == 3 && k + 1 < g.nz) put(top);
                if (j + 1 < g.ny) put(north);
                if (i + 1 < g.nx) put(e);
                if (dimension_ == 3) {
                    const double fx = std::fma(-rho[1], velocity.u[p], rho[0] * velocity.u[p + sx]);
                    const double fy = std::fma(-rho[3], velocity.v[py], rho[2] * velocity.v[py + g.nz]);
                    const double fz = std::fma(-rho[5], velocity.w[pz], rho[4] * velocity.w[pz + 1]);
                    system_.rhs[p] = degenerate ? 0.
                        : finite(-std::fma(fz, az, std::fma(fy, an, fx * ae)));
                } else {
                    // Retain the absent z-face term's signed-zero rounding.
                    system_.rhs[p] = degenerate ? 0. : finite(-(
                        (rho[0] * velocity.u[p + sx] - rho[1] * velocity.u[p]) * ae
                        + (rho[2] * velocity.v[py + g.nz] - rho[3] * velocity.v[py]) * an + 0.));
                }
            }
    return system_;
}

void close_simple_outlet(int dimension, const GridView& g,
                         ArrayView<const unsigned char> outlet, SimpleFacesView<double> velocity,
                         ArrayView<const double> rho, ArrayView<const double> eps) {
    const auto n = check_grid(dimension, g);
    check_faces(dimension, g, velocity); mask(outlet, g.nx * g.nz);
    field(rho, n, 1); field(eps, n, 1);
    close_outlet_unchecked(dimension, g, outlet, velocity, rho, eps);
}

void apply_simple_y_boundary(int dimension, const GridView& g, const SimpleBoundaryView& b,
                             SimpleFacesView<double> velocity,
                             ArrayView<const double> rho, ArrayView<const double> eps) {
    const auto n = check_grid(dimension, g);
    check_faces(dimension, g, velocity); check_boundary(dimension, g, b);
    field(rho, n, 1); field(eps, n, 1);
    y_boundary_unchecked(dimension, g, b, velocity, rho, eps);
}

void correct_simple_pressure(int dimension, const GridView& g, const SimpleBoundaryView& b,
                             ArrayView<double> pressure, ArrayView<const double> correction,
                             SimpleFacesView<double> velocity, SimpleFacesView<const double> d,
                             ArrayView<const double> rho, ArrayView<const double> eps, double alpha_p) {
    const auto n = check_grid(dimension, g);
    check_faces(dimension, g, velocity); check_faces(dimension, g, d, 2);
    check_boundary(dimension, g, b);
    field(pressure, n); field(correction, n); field(rho, n, 1); field(eps, n, 1);
    if (!std::isfinite(alpha_p) || alpha_p < 0. || alpha_p > 1.)
        throw std::invalid_argument("invalid SIMPLE pressure relaxation");
    for (std::size_t i = 0; i < g.nx; ++i)
        for (std::size_t j = 0; j < g.ny; ++j)
            for (std::size_t k = 0; k < g.nz; ++k) {
                if (j + 1 == g.ny && b.outlet_open[i * g.nz + k]) continue;
                const auto p = cell(g, i, j, k);
                pressure[p] = finite(dimension == 3
                    ? std::fma(alpha_p, correction[p], pressure[p])
                    : pressure[p] + alpha_p * correction[p]);
            }
    for (std::size_t i = 1; i < g.nx; ++i)
        for (std::size_t j = 0; j < g.ny; ++j)
            for (std::size_t k = 0; k < g.nz; ++k) {
                const auto p = cell(g, i, j, k);
                const double dp = correction[p - g.ny * g.nz] - correction[p];
                velocity.u[p] = finite(dimension == 3
                    ? std::fma(d.u[p], dp, velocity.u[p]) : velocity.u[p] + d.u[p] * dp);
            }
    for (std::size_t i = 0; i < g.nx; ++i)
        for (std::size_t j = 1; j < g.ny; ++j)
            for (std::size_t k = 0; k < g.nz; ++k) {
                const auto p = cell(g, i, j, k), py = yface(g, i, j, k);
                const double dp = correction[p - g.nz] - correction[p];
                velocity.v[py] = finite(dimension == 3
                    ? std::fma(d.v[py], dp, velocity.v[py]) : velocity.v[py] + d.v[py] * dp);
            }
    if (dimension == 3)
        for (std::size_t i = 0; i < g.nx; ++i)
            for (std::size_t j = 0; j < g.ny; ++j)
                for (std::size_t k = 1; k < g.nz; ++k) {
                    const auto p = cell(g, i, j, k), pz = zface(g, i, j, k);
                    velocity.w[pz] = finite(std::fma(d.w[pz],
                        correction[p - 1] - correction[p], velocity.w[pz]));
                }
    for (std::size_t j = 0; j < g.ny; ++j)
        for (std::size_t k = 0; k < g.nz; ++k)
            velocity.u[cell(g, 0, j, k)] = velocity.u[cell(g, g.nx, j, k)] = 0.;
    if (dimension == 3)
        for (std::size_t i = 0; i < g.nx; ++i)
            for (std::size_t j = 0; j < g.ny; ++j)
                velocity.w[zface(g, i, j, 0)] = velocity.w[zface(g, i, j, g.nz)] = 0.;
    y_boundary_unchecked(dimension, g, b, velocity, rho, eps);
}

SimpleMassAudit simple_mass_audit(int dimension, const GridView& g,
                                 SimpleFacesView<const double> velocity,
                                 ArrayView<const double> rho_eps,
                                 ArrayView<const unsigned char> excluded) {
    const auto n = check_grid(dimension, g);
    check_faces(dimension, g, velocity); field(rho_eps, n, 1); mask(excluded, n);
    SimpleMassAudit result{};
    for (std::size_t i = 0; i < g.nx; ++i)
        for (std::size_t j = 0; j < g.ny; ++j)
            for (std::size_t k = 0; k < g.nz; ++k) {
                if (excluded[cell(g, i, j, k)]) continue;
                const auto f = face_fluxes(dimension, g, velocity, rho_eps, i, j, k);
                const double net = finite((f[0] - f[1]) + (f[2] - f[3]) + (f[4] - f[5]));
                const double through = finite(std::abs(f[0]) + std::abs(f[1]) + std::abs(f[2])
                    + std::abs(f[3]) + std::abs(f[4]) + std::abs(f[5]));
                if (through <= 0.) continue;
                ++result.counted_cells;
                result.local_residual = std::max(result.local_residual, std::abs(net) / through);
            }
    double positive = 0., negative = 0.;
    for (std::size_t i = 0; i < g.nx; ++i)
        for (std::size_t k = 0; k < g.nz; ++k) {
            const double area = g.dx[i] * g.dz[k];
            const double in = finite(rho_eps[cell(g, i, 0, k)] * velocity.v[yface(g, i, 0, k)] * area);
            const double out = finite(rho_eps[cell(g, i, g.ny - 1, k)] * velocity.v[yface(g, i, g.ny, k)] * area);
            result.mass_in += in; result.mass_out += out;
            if (out >= 0.) positive += out; else negative -= out;
        }
    finite(result.mass_in); finite(result.mass_out);
    const double total = finite(positive + negative);
    result.backflow_fraction = total > 0. ? negative / total : 0.;
    result.global_residual = std::abs(result.mass_in) > 1e-14
        ? finite(std::abs(result.mass_out - result.mass_in) / std::abs(result.mass_in)) : 0.;
    return result;
}

SimpleLegacyMass simple_legacy_mass_residual(int dimension, const GridView& g,
        SimpleFacesView<const double> velocity, ArrayView<const double> rho_eps) {
    const auto n = check_grid(dimension, g);
    check_faces(dimension, g, velocity); field(rho_eps, n, 1);
    double inlet = 0.;
    for (std::size_t i = 0; i < g.nx; ++i)
        for (std::size_t k = 0; k < g.nz; ++k)
            inlet += rho_eps[cell(g, i, 0, k)] * std::abs(velocity.v[yface(g, i, 0, k)]) * g.dx[i] * g.dz[k];
    finite(inlet);
    SimpleLegacyMass result{0., 1.};
    if (dimension == 2) {
        if (inlet < 1e-30) return result;
        for (std::size_t j = 1; j <= g.ny; ++j) {
            double plane = 0.;
            for (std::size_t i = 0; i < g.nx; ++i) {
                const double rho = j < g.ny
                    ? .5 * (rho_eps[cell(g, i, j - 1, 0)] + rho_eps[cell(g, i, j, 0)])
                    : rho_eps[cell(g, i, g.ny - 1, 0)];
                plane += rho * velocity.v[yface(g, i, j, 0)] * g.dx[i];
            }
            result.residual = std::max(result.residual, finite(std::abs(plane - inlet) / inlet));
        }
    } else {
        result.reference = inlet > 1e-12 ? inlet : 1.;
        for (std::size_t i = 0; i < g.nx; ++i)
            for (std::size_t j = 0; j < g.ny; ++j)
                for (std::size_t k = 0; k < g.nz; ++k) {
                    const auto r = densities(g, rho_eps, i, j, k);
                    const auto p = cell(g, i, j, k), py = yface(g, i, j, k), pz = zface(g, i, j, k);
                    const double div = finite(
                        (r[0] * velocity.u[p + g.ny * g.nz] - r[1] * velocity.u[p]) * g.dy[j] * g.dz[k]
                        + (r[2] * velocity.v[py + g.nz] - r[3] * velocity.v[py]) * g.dx[i] * g.dz[k]
                        + (r[4] * velocity.w[pz + 1] - r[5] * velocity.w[pz]) * g.dx[i] * g.dy[j]);
                    result.residual = std::max(result.residual, std::abs(div));
                }
        result.residual = finite(result.residual / result.reference);
    }
    return result;
}

void simple_face_mass_flux(int dimension, const GridView& g,
                           SimpleFacesView<const double> velocity,
                           ArrayView<const double> rho_eps, SimpleFacesView<double> mass) {
    const auto n = check_grid(dimension, g);
    check_faces(dimension, g, velocity); field(rho_eps, n, 1);
    extent(mass.u, velocity.u.size); extent(mass.v, velocity.v.size); extent(mass.w, velocity.w.size);
    for (std::size_t i = 0; i <= g.nx; ++i)
        for (std::size_t j = 0; j < g.ny; ++j)
            for (std::size_t k = 0; k < g.nz; ++k) {
                const double rho = i == 0 ? rho_eps[cell(g, 0, j, k)]
                    : (i == g.nx ? rho_eps[cell(g, i - 1, j, k)]
                       : .5 * (rho_eps[cell(g, i - 1, j, k)] + rho_eps[cell(g, i, j, k)]));
                const auto p = cell(g, i, j, k);
                // The 3D thermal owner multiplies the two widths in separate
                // NumPy operations; preserve that rounding at this handoff.
                mass.u[p] = finite(dimension == 3
                    ? ((rho * velocity.u[p]) * g.dy[j]) * g.dz[k]
                    : rho * velocity.u[p] * (g.dy[j] * g.dz[k]));
            }
    for (std::size_t i = 0; i < g.nx; ++i)
        for (std::size_t j = 0; j <= g.ny; ++j)
            for (std::size_t k = 0; k < g.nz; ++k) {
                const double rho = j == 0 ? rho_eps[cell(g, i, 0, k)]
                    : (j == g.ny ? rho_eps[cell(g, i, j - 1, k)]
                       : .5 * (rho_eps[cell(g, i, j - 1, k)] + rho_eps[cell(g, i, j, k)]));
                const auto p = yface(g, i, j, k);
                mass.v[p] = finite(dimension == 3
                    ? ((rho * velocity.v[p]) * g.dx[i]) * g.dz[k]
                    : rho * velocity.v[p] * (g.dx[i] * g.dz[k]));
            }
    if (dimension == 3)
        for (std::size_t i = 0; i < g.nx; ++i)
            for (std::size_t j = 0; j < g.ny; ++j)
                for (std::size_t k = 0; k <= g.nz; ++k) {
                    const double rho = k == 0 ? rho_eps[cell(g, i, j, 0)]
                        : (k == g.nz ? rho_eps[cell(g, i, j, k - 1)]
                           : .5 * (rho_eps[cell(g, i, j, k - 1)] + rho_eps[cell(g, i, j, k)]));
                    const auto p = zface(g, i, j, k);
                    mass.w[p] = finite(((rho * velocity.w[p]) * g.dx[i]) * g.dy[j]);
                }
}

}  // namespace tpmshx
