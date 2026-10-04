#include "tpmshx/conservative_energy.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace tpmshx;
using Values = std::vector<double>;

ArrayView<const double> read(const Values& a) { return {a.data(), a.size()}; }
ArrayView<double> write(Values& a) { return {a.data(), a.size()}; }

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

void close(double actual, double expected, double tolerance, const char* message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw std::runtime_error(std::string(message) + ": actual="
            + std::to_string(actual) + " expected=" + std::to_string(expected));
}

template <typename Exception, typename Function>
void rejects(Function call, const char* message) {
    try { call(); }
    catch (const Exception&) { return; }
    throw std::runtime_error(message);
}

struct Side {
    Values cp, dh, hv, t_star, h, conductivity;
    std::array<Values, 3> mass;
    double h_in = 300000.;
    Side(std::size_t nx, std::size_t ny, std::size_t nz)
        : cp(nx * ny * nz, 1000.), dh(cp.size(), 0.), hv(cp.size(), 0.),
          t_star(cp.size(), 300.), h(cp.size(), 300000.), conductivity(cp.size(), 0.),
          mass{Values((nx + 1) * ny * nz), Values(nx * (ny + 1) * nz),
               Values(nx * ny * (nz + 1))} {}
    FluidView frozen() const {
        return {read(dh), read(cp), read(t_star), read(h), read(hv),
            read(mass[0]), read(mass[1]), read(mass[2]), h_in, 0., 0.};
    }
    FluidEnergyView actual(const Values& t) const {
        return {read(h), read(t), read(hv), read(conductivity),
            read(mass[0]), read(mass[1]), read(mass[2]), h_in};
    }
    std::array<ArrayView<const double>, 3> faces() const {
        return {read(mass[0]), read(mass[1]), read(mass[2])};
    }
};

struct Case {
    std::size_t nx, ny, nz;
    std::array<Values, 3> widths;
    Side a, b;
    Values ks, ta, tb, ts;
    Case(std::size_t x, std::size_t y, std::size_t z)
        : nx(x), ny(y), nz(z), widths{Values(x, 1.), Values(y, 1.), Values(z, 1.)},
          a(x, y, z), b(x, y, z), ks(x * y * z, 0.),
          ta(ks.size(), 340.), tb(ks.size(), 320.), ts(ks.size(), 330.) {}
    GridView grid() const {
        return {nx, ny, nz, read(widths[0]), read(widths[1]), read(widths[2])};
    }
    TemperatureStateView state() { return {write(ta), write(tb), write(ts)}; }
};

void frozen_linear_balance_and_reference_shift() {
    Case c(1, 1, 1);
    c.a.cp[0] = 1100.; c.b.cp[0] = 1800.;
    c.a.hv[0] = 10.; c.b.hv[0] = 20.;
    c.a.t_star[0] = 340.; c.b.t_star[0] = 320.;
    c.a.h[0] = 1100. * 340. + 500.;
    c.b.h[0] = 1800. * 320. - 7000.;
    c.a.h_in = 1100. * 400. + 500.;
    c.b.h_in = 1800. * 300. - 7000.;
    std::fill(c.a.mass[0].begin(), c.a.mass[0].end(), .01);
    std::fill(c.b.mass[0].begin(), c.b.mass[0].end(), -.02);
    const Values source_a{3.}, source_b{-2.};
    const auto original = c;
    conservative_temperature_sweeps(c.grid(), c.a.frozen(), c.b.frozen(),
        read(c.ks), c.state(), 250, .6, read(source_a), read(source_b), .6);
    // Independent 3x3 balance: C_a(Tin_a-Ta)+S_a=E_a(Ta-Ts),
    // C_b(Tin_b-Tb)+S_b=E_b(Tb-Ts), E_a(Ta-Ts)+E_b(Tb-Ts)=0.
    // Eliminate Ta/Tb to obtain two series thermal conductances at Ts.
    const double ca = 11., cb = 36., ea = 10., eb = 20.;
    const double inlet_a = 400. + 3. / ca, inlet_b = 300. - 2. / cb;
    const double ga = ca * ea / (ca + ea), gb = cb * eb / (cb + eb);
    const double expected_s = (ga * inlet_a + gb * inlet_b) / (ga + gb);
    const double expected_a = (ca * inlet_a + ea * expected_s) / (ca + ea);
    const double expected_b = (cb * inlet_b + eb * expected_s) / (cb + eb);
    close(c.ta[0], expected_a, 2e-10, "frozen matrix Ta");
    close(c.tb[0], expected_b, 2e-10, "frozen matrix Tb");
    close(c.ts[0], expected_s, 2e-10, "frozen matrix Ts");
    require(c.a.t_star == original.a.t_star && c.b.t_star == original.b.t_star
        && c.a.h == original.a.h && c.b.h == original.b.h, "frozen state changed");
    Case shifted = original;
    for (Side* f : {&shifted.a, &shifted.b}) {
        f->h[0] += 500000.;
        f->h_in += 500000.;
    }
    conservative_temperature_sweeps(shifted.grid(), shifted.a.frozen(), shifted.b.frozen(),
        read(shifted.ks), shifted.state(), 250, .6, read(source_a), read(source_b), .6);
    close(shifted.ta[0], c.ta[0], 2e-10, "enthalpy reference changed Ta");
    close(shifted.tb[0], c.tb[0], 2e-10, "enthalpy reference changed Tb");
    close(shifted.ts[0], c.ts[0], 2e-10, "enthalpy reference changed Ts");
}

void sou_linear_patch_six_directions() {
    for (std::size_t axis = 0; axis < 3; ++axis)
        for (const int sign : {-1, 1}) {
            Case c(axis == 0 ? 4 : 1, axis == 1 ? 4 : 1, axis == 2 ? 4 : 1);
            c.widths[axis] = {.1, .2, .3, .4};
            std::fill(c.a.mass[axis].begin(), c.a.mass[axis].end(), sign * 2.);
            std::fill(c.b.mass[axis].begin(), c.b.mass[axis].end(), sign * 2.);
            double x = 0.;
            for (std::size_t p = 0; p < 4; ++p) {
                const double center = x + .5 * c.widths[axis][p];
                c.a.h[p] = 1000. + 50. * center;
                c.b.h[p] = 2000. - 50. * center;
                x += c.widths[axis][p];
            }
            c.a.h_in = sign > 0 ? 1000. : 1050.;
            c.b.h_in = sign > 0 ? 2000. : 1950.;
            Values correction(4), ra(4), rb(4), rs(4);
            const double boundary = enthalpy_sou_correction(c.grid(), read(c.a.h),
                c.a.faces(), c.a.h_in, write(correction));
            const double expected_boundary = sign > 0 ? -20. : 5.;
            close(boundary, expected_boundary, 1e-11, "outflow SOU correction");
            close(std::accumulate(correction.begin(), correction.end(), 0.),
                boundary, 1e-11, "SOU source must telescope to boundary");
            const auto audit = thermal_energy_audit_sou(c.grid(), c.a.actual(c.ta),
                c.b.actual(c.tb), read(c.ts), read(c.ks), write(ra), write(rb), write(rs));
            close(audit.q_a, -sign * 100., 1e-10, "SOU exact linear outlet duty A");
            close(audit.q_b, sign * 100., 1e-10, "SOU exact linear outlet duty B");
            close(audit.net, 0., 1e-10, "SOU boundary cancellation");
            close(audit.denominator, 100., 1e-10, "SOU denominator uses corrected duty");
            close(audit.coupled_ratio, 0., 1e-12, "SOU coupled ratio");
            close(audit.equation_ratio, 1., 1e-12, "SOU equation ratio");
            require(audit.fluid_equations_computed, "SOU full fluid audit absent");
            for (std::size_t p = 0; p < 4; ++p) {
                close(ra[p], -sign * 100. * c.widths[axis][p], 1e-10, "SOU exact divergence A");
                close(rb[p], sign * 100. * c.widths[axis][p], 1e-10, "SOU exact divergence B");
                close(rs[p], 0., 1e-12, "SOU solid residual");
            }
            for (int side = 0; side < 2; ++side) {
                close(audit.fluid_abs_sum[side], 100., 1e-10, "SOU absolute residual sum");
                close(audit.fluid_cell_max[side], 40., 1e-10, "SOU cell maximum");
            }
            for (Side* f : {&c.a, &c.b}) {
                for (auto& h : f->h) h += 1000000.;
                f->h_in += 1000000.;
            }
            Values shifted_correction(4);
            close(enthalpy_sou_correction(c.grid(), read(c.a.h), c.a.faces(),
                c.a.h_in, write(shifted_correction)), boundary, 1e-8, "SOU reference boundary");
            for (std::size_t p = 0; p < 4; ++p)
                close(shifted_correction[p], correction[p], 1e-8, "SOU reference source");
            const auto shifted = thermal_energy_audit_sou(c.grid(), c.a.actual(c.ta),
                c.b.actual(c.tb), read(c.ts), read(c.ks), write(ra), write(rb), write(rs));
            close(shifted.q_a, audit.q_a, 1e-8, "SOU reference audit A");
            close(shifted.q_b, audit.q_b, 1e-8, "SOU reference audit B");
            close(shifted.equation_ratio, audit.equation_ratio, 1e-10, "SOU reference ratio");
        }
}

void isothermal_pressure_offsets_do_not_conduct() {
    Case c(3, 1, 1);
    c.widths[0] = {.2, .3, .5};
    for (Values* t : {&c.ta, &c.tb, &c.ts}) std::fill(t->begin(), t->end(), 300.);
    c.ks = {2., 4., 3.};
    for (Side* f : {&c.a, &c.b}) {
        f->cp = {1000., 1200., 800.};
        f->conductivity = {1., 4., 2.};
        f->h = {310000., 365000., 242000.};
        for (std::size_t p = 0; p < 3; ++p) f->dh[p] = f->conductivity[p] / f->cp[p];
    }
    conservative_temperature_sweeps(c.grid(), c.a.frozen(), c.b.frozen(),
        read(c.ks), c.state(), 5, .6, {}, {}, .6);
    for (const Values* t : {&c.ta, &c.tb, &c.ts})
        for (const double value : *t) close(value, 300., 1e-10, "isothermal false conduction");
    Values ra(3), rb(3), rs(3);
    const auto audit = thermal_energy_audit_sou(c.grid(), c.a.actual(c.ta),
        c.b.actual(c.tb), read(c.ts), read(c.ks), write(ra), write(rb), write(rs));
    close(audit.equation_ratio, 0., 1e-10, "pressure offsets created energy residual");
}

void sou_extremum_has_no_outward_extrapolation() {
    // Isolate a face leaving a strict interior maximum in either direction.
    // Opposed one-sided slopes must not produce an extrapolated overshoot.
    for (const int sign : {-1, 1}) {
        Case c(3, 1, 1);
        c.a.h = {0., 1., 0.};
        c.a.h_in = 0.;
        c.a.mass[0][sign > 0 ? 2 : 1] = sign;
        Values correction(3);
        close(enthalpy_sou_correction(c.grid(), read(c.a.h), c.a.faces(),
            c.a.h_in, write(correction)), 0., 0., "interior face changed boundary");
        for (const double value : correction)
            close(value, 0., 0., "minmod extrapolated an interior extremum");
    }
}

void invalid_inputs_and_overflow() {
    Case c(1, 1, 1);
    const auto original = c;
    auto call = [&] {
        conservative_temperature_sweeps(c.grid(), c.a.frozen(), c.b.frozen(),
            read(c.ks), c.state(), 2, .6, {}, {}, .6);
    };
    c.b.cp[0] = 0.;
    rejects<std::invalid_argument>(call, "nonpositive cp accepted");
    require(c.ta == original.ta && c.tb == original.tb && c.ts == original.ts,
        "invalid coefficient mutated state");
    c = original;
    rejects<std::invalid_argument>([&] {
        conservative_temperature_sweeps(c.grid(), c.a.frozen(), c.b.frozen(),
            read(c.ks), c.state(), 1, .6, {}, {}, 0.);
    }, "invalid solid omega accepted");
    require(c.ta == original.ta && c.tb == original.tb && c.ts == original.ts,
        "invalid relaxation mutated state");
    c.a.hv[0] = std::numeric_limits<double>::max();
    rejects<std::domain_error>(call, "finite-input row overflow accepted");
    c = original;
    c.a.hv[0] = 1e-29;
    const Values large_source{1e308};
    rejects<std::domain_error>([&] {
        conservative_temperature_sweeps(c.grid(), c.a.frozen(), c.b.frozen(),
            read(c.ks), c.state(), 1, 1., read(large_source), {}, 1.);
    }, "finite-row update overflow accepted");
    Case line(2, 1, 1);
    Values correction(2, 123.);
    line.a.mass[0][0] = std::numeric_limits<double>::quiet_NaN();
    rejects<std::invalid_argument>([&] {
        enthalpy_sou_correction(line.grid(), read(line.a.h), line.a.faces(),
            line.a.h_in, write(correction));
    }, "nonfinite SOU face accepted");
    require(correction == Values(2, 123.), "invalid SOU input mutated output");
    line.a.mass[0][0] = 0.;
    line.a.h = {-1e308, 1e308};
    rejects<std::domain_error>([&] {
        enthalpy_sou_correction(line.grid(), read(line.a.h), line.a.faces(),
            line.a.h_in, write(correction));
    }, "SOU slope overflow accepted");
}

}  // namespace

int main() {
    try {
        frozen_linear_balance_and_reference_shift();
        sou_linear_patch_six_directions();
        isothermal_pressure_offsets_do_not_conduct();
        sou_extremum_has_no_outward_extrapolation();
        invalid_inputs_and_overflow();
        std::cout << "conservative energy smoke passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
