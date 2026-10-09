#include "tpmshx/conservative_energy.hpp"
#include "../src/temperature_faces.hpp"

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
            const auto powers=enthalpy_boundary_power(c.grid(),read(c.a.h),c.a.faces(),c.a.h_in,true);
            const auto fou=enthalpy_boundary_power(c.grid(),read(c.a.h),c.a.faces(),c.a.h_in,false);
            double sou_q=0.,fou_q=0.;
            for(std::size_t face=0;face<6;++face) {
                const std::size_t expected_size=face/2==axis?1:4;
                require(powers[face].size()==expected_size,"boundary power plane shape");
                sou_q-=std::accumulate(powers[face].begin(),powers[face].end(),0.);
                fou_q-=std::accumulate(fou[face].begin(),fou[face].end(),0.);
                if(face/2!=axis)
                    for(double value:powers[face]) close(value,0.,0.,"closed face power");
            }
            close(powers[2*axis][0],-sign*2000.,1e-10,"physical low-face outward power");
            close(powers[2*axis+1][0],sign*2100.,1e-10,"physical high-face outward power");
            close(sou_q,-sign*100.,1e-10,"linear boundary power duty");
            close(sou_q-fou_q,boundary,1e-10,"boundary power reuses SOU correction");
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

void temperature_sou_internal_endpoint_face_accuracy() {
    // This is fixed-capacity temperature reconstruction, distinct from the
    // enthalpy SOU inlet/outlet powers checked above. Expected face values
    // come only from analytic T(x) at cumulative physical face coordinates.
    // Dyadic data make the affine identities and local h^2 errors exact.
    constexpr std::size_t cells=4;
    const std::array<double,cells> widths{.125,.375,.25,.5};
    for(std::size_t axis=0;axis<3;++axis) for(int sign:{-1,1}) {
        try {
            Case c(axis==0?cells:1,axis==1?cells:1,axis==2?cells:1);
            std::copy(widths.begin(),widths.end(),c.widths[axis].begin());
            const auto grid=c.grid();
            const detail::EnergyMesh mesh(grid);
            // Reuse Side's face-array shapes, with C in W/K for this test.
            auto capacity=c.a.mass,offset=c.a.mass;
            const double C=sign*2.;
            std::fill(capacity[axis].begin(),capacity[axis].end(),C);
            const std::array<ArrayView<const double>,3> input{
                read(capacity[0]),read(capacity[1]),read(capacity[2])};
            const std::array<ArrayView<double>,3> output{
                write(offset[0]),write(offset[1]),write(offset[2])};
            std::array<double,cells+1> edges{};
            for(std::size_t p=0;p<cells;++p) edges[p+1]=edges[p]+widths[p];
            for(double slope:{-16.,16.}) {
                for(std::size_t p=0;p<cells;++p)
                    c.ta[p]=300.+slope*.5*(edges[p]+edges[p+1]);
                detail::temperature_face_offsets(mesh,input,read(c.ta),output);
                for(std::size_t face=1;face<cells;++face) {
                    const auto donor=sign>0?face-1:face;
                    const double expected=C*(300.+slope*edges[face]);
                    close(C*c.ta[donor]+offset[axis][face],expected,0.,
                        "nonuniform affine internal temperature face power");
                    if((sign>0&&face==1)||(sign<0&&face==cells-1))
                        require(expected!=C*c.ta[donor],
                            "affine endpoint fixture does not distinguish zero correction");
                }
                for(std::size_t a=0;a<3;++a)
                    for(std::size_t face=0;face<offset[a].size();++face)
                        if(a!=axis||face==0||face==cells)
                            close(offset[a][face],0.,0.,
                                "exterior or untransported temperature correction");
            }
            // T(x)=300+16x+x^2 is smooth and monotone on each homothetic
            // patch. Halving ALL widths must quarter the endpoint face error.
            // This is local face-reconstruction order, not a fixed-domain
            // mesh-convergence claim for the coupled finite-volume solver.
            const auto quadratic=[](double x) { return 300.+16.*x+x*x; };
            std::array<double,3> error{};
            for(std::size_t level=0;level<error.size();++level) {
                const double scale=std::ldexp(1.,-static_cast<int>(level));
                for(std::size_t p=0;p<cells;++p) {
                    c.widths[axis][p]=scale*widths[p];
                    edges[p+1]=edges[p]+c.widths[axis][p];
                    c.ta[p]=quadratic(.5*(edges[p]+edges[p+1]));
                }
                detail::temperature_face_offsets(mesh,input,read(c.ta),output);
                const std::size_t face=sign>0?1:cells-1,donor=sign>0?0:cells-1;
                error[level]=std::abs(C*c.ta[donor]+offset[axis][face]
                    -C*quadratic(edges[face]));
                require(error[level]>0.,"quadratic face fixture has no measurable truncation error");
            }
            close(error[0],4.*error[1],0.,"temperature endpoint face error is not locally second order");
            close(error[1],4.*error[2],0.,"temperature endpoint face refinement lost local second order");
        } catch(const std::exception& error) {
            throw std::runtime_error("temperature SOU internal endpoint axis="+std::to_string(axis)
                +" sign="+std::to_string(sign)+": "+error.what());
        }
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

void prepared_capacity_sources_and_reservoir() {
    const Values dx{1.,2.}, transverse{1.}, zero(2,0.), cx(3,2.), no_x(3,0.), no_yz(4,0.);
    const Values ha{2.,3.},hb{5.,7.},sa{4.,6.},sb{9.,11.},ss{8.,10.},fixed_b{300.,310.};
    const GridView grid{2,1,1,read(dx),read(transverse),read(transverse)};
    EnergyPhase a{read(zero),read(ha),read(sa),
        {{read(cx),read(no_yz),read(no_yz)},{}},{0,360.,{},{},{}},false};
    const EnergyPhase b{read(zero),read(hb),read(sb),
        {{read(no_x),read(no_yz),read(no_yz)},{}},{1,300.,{},{},{}},false};
    Values ta{350.,340.},tb=fixed_b,ts{330.,320.};
    const TemperatureStateView state{write(ta),write(tb),write(ts)};
    const auto ledger=energy_physical_audit(grid,a,b,read(zero),state,read(ss),read(fixed_b));
    require(ledger.boundary_complete && !ledger.solved[1] && ledger.residual[1].empty()
        && std::isnan(ledger.source_integral[1]),"prescribed reservoir has a solved B equation");
    close(ledger.residual[0][0],-16.,1e-12,"first cell capacity/source balance");
    close(ledger.residual[0][1],-88.,1e-12,"second cell capacity/source balance");
    close(ledger.residual[2][0],-102.,1e-12,"first solid exchange balance");
    close(ledger.residual[2][1],0.,1e-12,"second solid exchange balance");
    close(ledger.advective_out[0][0][0],-720.,1e-12,"capacity inlet power");
    close(ledger.advective_out[0][1][0],680.,1e-12,"capacity outlet power");
    close(ledger.source_integral[0],16.,1e-12,"physical fluid source volume");
    close(ledger.source_integral[2],28.,1e-12,"physical solid source volume");
    close(ledger.prescribed_b_power,-290.,1e-12,"external reservoir power");
    close(energy_balance_error(ledger),206.,1e-12,"shared actual-state balance reduction");

    const Values numerical{8.,-12.};
    tb={322.,333.};
    energy_temperature_sweeps(grid,a,b,read(zero),state,0,1.,read(ss),read(fixed_b),read(numerical));
    require(tb==Values({322.,333.}),"zero sweeps applied prescribed state");
    energy_temperature_sweeps(grid,a,b,read(zero),state,1,1.,read(ss),read(fixed_b),read(numerical));
    require(tb==fixed_b,"positive sweep did not pin prescribed B");
    close(ta[0],348.,1e-12,"numerical source is not once in W/cell");
    close(ta[1],327.,1e-12,"internal capacity is not shared with opposite signs");
    close(ts[0],2204./7.,1e-12,"first solid physical source and exchange");
    close(ts[1],6322./20.,1e-12,"second solid physical source and exchange");
    const auto actual=energy_physical_audit(grid,a,b,read(zero),state,read(ss),read(fixed_b));
    close(actual.residual[0][0],2*(360.-ta[0])+2*(ts[0]-ta[0])+4.,1e-12,
        "numerical source leaked into actual physical ledger");
    const auto before_a=ta,before_b=tb,before_s=ts;
    a.inlet.direction=1; // Positive x- transport now has no declared inlet state.
    const auto incomplete=energy_physical_audit(grid,a,b,read(zero),state,read(ss),read(fixed_b));
    require(!incomplete.boundary_complete,"unknown inward boundary claimed complete");
    rejects<std::invalid_argument>([&] {
        energy_temperature_sweeps(grid,a,b,read(zero),state,1,1.,read(ss),read(fixed_b));
    },"unknown inward boundary accepted by solve");
    require(ta==before_a && tb==before_b && ts==before_s,"invalid inlet mutated state");
}

void diffusion_line_and_compensated_equilibrium() {
    const Values dx{.3,.7}, transverse{.4}, zero(2,0.), one(2,1.);
    const Values cx(3,0.), cy(4,0.), cz(4,0.), conductivity{.2,.3};
    const GridView grid{2,1,1,read(dx),read(transverse),read(transverse)};
    const detail::EnergyMesh mesh(grid);
    EnergyPhase phase{read(conductivity),read(one),{},
        {{read(cx),read(cy),read(cz)},{}},{0,330.,{},{},{}},false};
    const Values bath{330.,300.};
    Values temperature{345.,315.};
    detail::EnergyLineScratch scratch(2);
    detail::fluid_energy_line(mesh,phase,write(temperature),read(bath),0,0,1.,scratch);
    // Independent two-cell conductance system with adiabatic exterior faces.
    const double conductance=.16/(.3/(2*.2)+.7/(2*.3));
    const double h0=.3*.16,h1=.7*.16,d0=h0+conductance,d1=h1+conductance;
    const double determinant=d0*d1-conductance*conductance;
    close(temperature[0],(h0*bath[0]*d1+conductance*h1*bath[1])/determinant,
        2e-12,"nonuniform diffusion line first cell");
    close(temperature[1],(h1*bath[1]*d0+conductance*h0*bath[0])/determinant,
        2e-12,"nonuniform diffusion line second cell");

    phase.K=read(zero);
    for(double target:{273.15,330.,480.125}) for(double direction:{-1.,1.}) {
        const double start=std::nextafter(target,target+direction);
        Values t(2,start),ts(2,start),reference(2,start),equilibrium(2,target),carry(2,0.),solid_carry(2,0.);
        for(int sweep=0;sweep<32;++sweep) {
            const double change=detail::fluid_energy_line(mesh,phase,write(t),read(equilibrium),0,0,.2,scratch,{},write(carry));
            detail::fluid_energy_line(mesh,phase,write(reference),read(equilibrium),0,0,.2,scratch);
            detail::solid_energy_line(mesh,read(zero),read(one),read(one),read(equilibrium),
                read(equilibrium),write(ts),{},0,0,.2,scratch,write(solid_carry));
            if(sweep==0) require(change>0. && t==Values(2,start),
                "sub-ulp live line update incorrectly reports zero");
        }
        require(t==equilibrium && ts==equilibrium,"compensated line misses exact equilibrium");
        require(reference==Values(2,start),"uncompensated control no longer reproduces stagnation");
    }
    const Values initial{329.,331.};
    for(std::size_t extent:{1U,2U}) {
        Values t=initial,carry{.125,std::numeric_limits<double>::quiet_NaN()};
        rejects<std::exception>([&] {
            detail::fluid_energy_line(mesh,phase,write(t),read(bath),0,0,.2,scratch,{},
                {carry.data(),extent});
        },"invalid compensation accepted");
        require(t==initial && carry[0]==.125 && std::isnan(carry[1]),
            "failed line changed temperature or compensation");
    }
}

void inlet_fourier_flux_six_directions() {
    struct Configuration {
        const char* name;
        std::size_t cells;
        double h1, kp, kn, q0, q1, opening;
    };
    const std::array<Configuration,10> configurations{{
        {"constant",2,.375,.5,2.,0.,0.,1.},
        {"constant-K uniform affine",2,.125,.5,.5,2.,0.,1.},
        {"constant-K nonuniform quadratic",2,.375,.5,.5,2.,3.,1.},
        {"layered-K constant flux",2,.375,.5,2.,2.,0.,1.},
        {"layered-K linear flux",2,.375,.5,2.,2.,3.,1.},
        {"partial opening linear flux",2,.375,.5,2.,2.,3.,.25},
        {"closed opening",2,.375,.5,2.,2.,3.,0.},
        {"zero boundary conductivity",2,.375,0.,2.,2.,3.,1.},
        {"zero neighbor conductivity",2,.375,.5,0.,2.,0.,1.},
        {"singleton",1,.375,.5,2.,2.,0.,1.}
    }};
    const auto check=[](double actual,double expected,const char* message) {
        close(actual,expected,5e-12+2e-12*std::abs(expected),message);
    };
    for(int direction=0;direction<6;++direction) for(const auto& configuration:configurations) {
        try {
            const std::size_t axis=direction/2,n=configuration.cells;
            const int sign=direction%2 ? 1:-1; // Outward normal; s increases inward.
            const std::size_t p=sign>0 ? n-1:0,q=n==1 ? p:1-p;
            Case c(axis==0 ? n:1,axis==1 ? n:1,axis==2 ? n:1);
            constexpr double h0=.125,tin=300.,area=.125;
            for(std::size_t j=0;j<3;++j) if(j!=axis)
                c.widths[j][0]=j==(axis+1)%3 ? .5:.25;
            c.widths[axis][p]=h0;
            c.a.conductivity[p]=configuration.kp;
            if(n>1) {
                c.widths[axis][q]=configuration.h1;
                c.a.conductivity[q]=configuration.kn;
            }
            const Values profile{tin},opening{configuration.opening};
            // A deliberately different scalar checks that the true face profile is used.
            const TemperatureBoundary inlet{direction,123.,read(profile),read(opening),{}};
            const EnergyPhase a{read(c.a.conductivity),read(c.a.hv),{},
                {c.a.faces(),{}},inlet,true,true};
            const EnergyPhase b{read(c.b.conductivity),read(c.b.hv),{},
                {c.b.faces(),{}},{direction^1,tin,{},{},{}},false};
            const PhysicalEnergyPhase physical_a{read(c.a.conductivity),read(c.a.hv),{},
                c.a.faces(),c.a.faces(),inlet,true,true};
            const PhysicalEnergyPhase physical_b{read(c.b.conductivity),read(c.b.hv),{},
                c.b.faces(),c.b.faces(),{direction^1,tin,{},{},{}},false};

            // Independent continuum construction: T(s)=Tin-q0*R(s)-q1*M(s),
            // R=int(1/K ds), M=int(s/K ds), with Kp on [0,h0], then Kn.
            // No production inlet/diffusion helper is used for these expectations.
            double gb=0.,gn=0.,internal=0.;
            const double open_area=area*configuration.opening;
            if(configuration.kp==0.) {
                c.ta[p]=267.;c.ta[q]=331.;
            } else {
                const double center=h0/2.,rp=center/configuration.kp;
                const double mp=center*center/(2.*configuration.kp);
                c.ta[p]=tin-configuration.q0*rp-configuration.q1*mp;
                gb=open_area/rp;
                if(n>1&&configuration.kn>0.) {
                    const double next_center=h0+configuration.h1/2.;
                    const double rn=h0/configuration.kp+(next_center-h0)/configuration.kn;
                    const double mn=h0*h0/(2.*configuration.kp)
                        +(next_center*next_center-h0*h0)/(2.*configuration.kn);
                    c.ta[q]=tin-configuration.q0*rn-configuration.q1*mn;
                    const double determinant=rp*mn-rn*mp;
                    gb=open_area*(mn-mp)/determinant;
                    gn=open_area*mp/determinant;
                    internal=area/(h0/(2.*configuration.kp)
                        +configuration.h1/(2.*configuration.kn));
                } else if(n>1) c.ta[q]=617.; // This isolated temperature must not enter Qin.
            }
            const double expected_out=configuration.kp==0. ? 0.:-open_area*configuration.q0;
            require(gb>=0.&&gn>=0.,"independent Fourier coefficients are negative");
            const auto initial=c.ta;
            const auto grid=c.grid();
            const detail::EnergyMesh mesh(grid);
            Values expected_residual(n,0.);
            for(std::size_t cell=0;cell<n;++cell) {
                const auto other=n==1 ? cell:1-cell;
                const double boundary=cell==p ? gb:0.;
                const double neighbor=n==1 ? 0.:internal+(cell==p ? gn:0.);
                const double expected_diagonal=boundary+neighbor;
                const double expected_rhs=boundary*tin+neighbor*c.ta[other];
                expected_residual[cell]=(cell==p ? -expected_out:0.)
                    +internal*(c.ta[other]-c.ta[cell]);
                const auto absolute=detail::fluid_energy_row(mesh,a,read(c.ta),read(c.ts),cell);
                const auto defect=detail::fluid_energy_defect_row(mesh,a,read(c.ta),read(c.ts),cell);
                const auto diffusion=detail::energy_diffusion(mesh,a,cell);
                const auto reused=detail::fluid_energy_defect_row(mesh,a,read(c.ta),read(c.ts),cell,0.,&diffusion);
                const detail::PointEnergyCoefficients coefficients{absolute.diagonal,absolute.neighbor};
                const auto cached=detail::fluid_energy_row(mesh,a,read(c.ta),read(c.ts),cell,coefficients);
                check(absolute.diagonal,expected_diagonal,"independent Fourier row diagonal");
                check(absolute.rhs,expected_rhs,"independent Fourier absolute RHS");
                check(absolute.local_rhs,boundary*tin,"Fourier local RHS contains a neighbor");
                check(defect.rhs,expected_residual[cell],"independent physical Fourier defect");
                check(defect.rhs,absolute.rhs-absolute.diagonal*c.ta[cell],"absolute/defect mismatch");
                check(defect.diagonal,absolute.diagonal,"defect diagonal differs");
                check(defect.local_rhs,0.,"defect has an absolute local RHS");
                check(reused.rhs,expected_residual[cell],"fixed diffusion changed physical Fourier defect");
                check(reused.diagonal,expected_diagonal,"fixed diffusion changed Fourier diagonal");
                check(cached.diagonal,absolute.diagonal,"cached Fourier diagonal differs");
                check(cached.rhs,absolute.rhs,"cached Fourier RHS counts neighbor twice");
                check(cached.local_rhs,absolute.local_rhs,"cached local RHS differs");
                for(std::size_t face=0;face<6;++face) {
                    const double expected=n>1&&face==2*axis+(other>cell) ? neighbor:0.;
                    check(absolute.neighbor[face],expected,"independent inward neighbor coefficient");
                    check(defect.neighbor[face],expected,"defect inward neighbor coefficient");
                    check(reused.neighbor[face],expected,"fixed diffusion changed inward neighbor coefficient");
                    check(cached.neighbor[face],expected,"cached inward neighbor coefficient");
                }
                check(absolute.diagonal-std::accumulate(absolute.neighbor.begin(),absolute.neighbor.end(),0.),
                    boundary,"independent boundary Gb from row");
                if(n>1) check(absolute.neighbor[2*axis+(other>cell)]-internal,cell==p ? gn:0.,
                    "independent boundary Gn from row");
            }
            const auto prepared=energy_physical_audit(grid,a,b,read(c.ks),c.state());
            const auto physical=energy_physical_audit(grid,physical_a,physical_b,read(c.ks),c.state());
            double residual_sum=0.,boundary_sum=0.,expected_l1=0.;
            for(double value:expected_residual) expected_l1+=std::abs(value);
            require(prepared.boundary_complete&&physical.boundary_complete,
                "declared Fourier boundary is incomplete");
            for(std::size_t phase=0;phase<3;++phase) {
                check(prepared.source_integral[phase],0.,"unexpected prepared Fourier source");
                check(physical.source_integral[phase],0.,"unexpected actual Fourier source");
                for(std::size_t cell=0;cell<n;++cell) {
                    const double expected=phase==0 ? expected_residual[cell]:0.;
                    check(prepared.residual[phase][cell],expected,"prepared Fourier ledger residual");
                    check(physical.residual[phase][cell],expected,"actual Fourier ledger residual");
                    residual_sum+=prepared.residual[phase][cell];
                }
                for(std::size_t face=0;face<6;++face)
                    for(std::size_t patch=0;patch<prepared.diffusive_out[phase][face].size();++patch) {
                        const double expected=phase==0&&face==static_cast<std::size_t>(direction)
                            ? expected_out:0.;
                        check(prepared.diffusive_out[phase][face][patch],expected,"prepared six-face Fourier power");
                        check(physical.diffusive_out[phase][face][patch],expected,"actual six-face Fourier power");
                        check(prepared.advective_out[phase][face][patch],0.,"unexpected prepared advection");
                        check(physical.advective_out[phase][face][patch],0.,"unexpected actual advection");
                        boundary_sum+=prepared.diffusive_out[phase][face][patch];
                    }
            }
            check(prepared.prescribed_b_power,0.,"unexpected prepared reservoir power");
            check(physical.prescribed_b_power,0.,"unexpected actual reservoir power");
            check(boundary_sum,expected_out,"global Fourier boundary power");
            check(residual_sum,-boundary_sum,"Fourier residual does not telescope to boundary");
            const double expected_error=std::max(expected_l1,std::abs(expected_out));
            check(energy_balance_error(prepared),expected_error,"full Fourier reduction differs");
            const auto scalar=energy_balance_audit(grid,a,b,read(c.ks),c.state());
            require(scalar.boundary_complete,"scalar Fourier boundary is incomplete");
            check(scalar.error,expected_error,"scalar Fourier reduction differs");

            if(configuration.kp==configuration.kn&&configuration.q1!=0.) {
                auto legacy=a;legacy.second_order_inlet_conduction=false;
                const auto old=energy_physical_audit(grid,legacy,b,read(c.ks),c.state());
                const double old_expected=-open_area*(configuration.q0+configuration.q1*h0/4.);
                const double old_power=old.diffusive_out[0][direction][0];
                check(old_power,old_expected,"legacy half-cell arithmetic changed");
                require(std::abs(old_power-expected_out)>5e-12+2e-12*std::abs(expected_out),
                    "quadratic counterexample no longer exposes half-cell boundary error");
            }
            require(c.ta==initial,"Fourier operator audits mutated temperature");
        } catch(const std::exception& error) {
            throw std::runtime_error("Fourier direction="+std::to_string(direction)
                +" case="+configuration.name+": "+error.what());
        }
    }
}

void fixed_diffusion_keeps_transport_and_state_live() {
    for(int direction=0;direction<6;++direction) for(bool second_order:{false,true}) {
        Case c(3,2,2);
        c.widths={Values{.2,.5,.3},Values{.1,.4},Values{.3,.7}};
        for(std::size_t p=0;p<c.ta.size();++p) {
            c.a.conductivity[p]=.1*(p+1);c.ks[p]=.3*(p+1);
        }
        const auto grid=c.grid();const detail::EnergyMesh mesh(grid);
        Values source(c.ta.size(),7.);
        const EnergyPhase phase{read(c.a.conductivity),read(c.a.hv),read(source),
            {c.a.faces(),c.b.faces()},{direction,360.,{},{},{}},true,second_order};
        std::vector<detail::EnergyDiffusion> fluid,solid;
        for(std::size_t p=0;p<c.ta.size();++p) {
            fluid.push_back(detail::energy_diffusion(mesh,phase,p));
            solid.push_back(detail::energy_diffusion(mesh,read(c.ks),p));
        }
        for(int step=0;step<3;++step) {
            for(std::size_t axis=0;axis<3;++axis) for(std::size_t f=0;f<c.a.mass[axis].size();++f) {
                c.a.mass[axis][f]=.01*(step+1)*(static_cast<double>(f%3)-1.);
                c.b.mass[axis][f]=.03*(step+2)*(f+1);
            }
            for(std::size_t p=0;p<c.ta.size();++p) {
                c.ta[p]+=step+p;c.ts[p]-=.1*(step+p);c.tb[p]+=.2*step;
                c.a.hv[p]=.4*(step+p);c.b.hv[p]=.2*(step+1);source[p]+=step;
                const auto a=detail::fluid_energy_defect_row(mesh,phase,read(c.ta),read(c.ts),p,3.);
                const auto b=detail::fluid_energy_defect_row(mesh,phase,read(c.ta),read(c.ts),p,3.,&fluid[p]);
                require(a.diagonal==b.diagonal&&a.rhs==b.rhs&&a.neighbor==b.neighbor,
                    "fixed fluid diffusion froze live transport, sources or state");
                const auto s=detail::solid_energy_defect_row(mesh,read(c.ks),read(c.a.hv),read(c.b.hv),
                    read(c.ta),read(c.tb),read(c.ts),read(source),p);
                const auto r=detail::solid_energy_defect_row(mesh,read(c.ks),read(c.a.hv),read(c.b.hv),
                    read(c.ta),read(c.tb),read(c.ts),read(source),p,&solid[p]);
                require(s.diagonal==r.diagonal&&s.rhs==r.rhs&&s.neighbor==r.neighbor,
                    "fixed solid diffusion froze exchange, sources or state");
            }
        }
    }
}

}  // namespace

int main() {
    try {
        frozen_linear_balance_and_reference_shift();
        sou_linear_patch_six_directions();
        temperature_sou_internal_endpoint_face_accuracy();
        isothermal_pressure_offsets_do_not_conduct();
        sou_extremum_has_no_outward_extrapolation();
        invalid_inputs_and_overflow();
        prepared_capacity_sources_and_reservoir();
        diffusion_line_and_compensated_equilibrium();
        inlet_fourier_flux_six_directions();
        fixed_diffusion_keeps_transport_and_state_live();
        std::cout << "conservative energy smoke passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
