#include "tpmshx/enthalpy_driver.hpp"
#include "tpmshx/conservative_energy.hpp"
#include "tpmshx/model_coefficients.hpp"

#include "model_h_common.hpp"

#include <CoolProp/Exceptions.h>

#include <algorithm>
#include <cmath>
#include <limits>
#include <sstream>
#include <vector>

namespace tpmshx {
namespace {
std::size_t product(std::size_t a, std::size_t b) {
    if (!a || !b || a > std::numeric_limits<std::size_t>::max()/b)
        throw std::invalid_argument("invalid true-h grid extent");
    return a*b;
}

template <typename T> void check(ArrayView<T> field, std::size_t n, bool finite = true) {
    if (!field.data || field.size != n)
        throw std::invalid_argument("true-h array length does not match grid");
    if (finite) for (std::size_t p = 0; p < n; ++p)
        if (!std::isfinite(field[p])) throw std::invalid_argument("nonfinite true-h field");
}
void coefficient(ArrayView<const double> field, std::size_t n, bool positive) {
    check(field,n);
    for (std::size_t p = 0; p < n; ++p)
        if (positive ? field[p] <= 0. : field[p] < 0.)
            throw std::invalid_argument("invalid true-h physical coefficient");
}
ArrayView<const double> view(const std::vector<double>& a) { return {a.data(),a.size()}; }
ArrayView<const double> view(ArrayView<double> a) { return {a.data,a.size}; }
ArrayView<double> output(std::vector<double>& a) { return {a.data(),a.size()}; }

std::string location(const GridView& grid, std::size_t p, const std::string& stage) {
    std::ostringstream text;
    text << stage << ": index=(" << p/(grid.ny*grid.nz) << ", " << (p/grid.nz)%grid.ny
         << ", " << p%grid.nz << ")";
    return text.str();
}

struct Side {
    const EnthalpySideView& input;
    ArrayView<double> h, t;
    double hin = 0., lower = 0., upper = 0.;
    std::vector<double> cp, dh, k, star, temperature_star, table_lower, table_upper;
    bool table_used = false;
    Side(const EnthalpySideView& f, ArrayView<double> enthalpy, ArrayView<double> temperature,
         std::size_t n, bool temperature_variable = false)
        : input(f), h(enthalpy), t(temperature), cp(n), dh(n), k(n), star(n),
          temperature_star(temperature_variable ? n : 0) {}

    void invert(EnthalpyEOS& eos, const GridView& grid, bool tables, const std::string& where) {
        bool use_table = tables && !table_lower.empty();
        if (use_table) for (std::size_t p = 0; p < h.size; ++p)
            if (!(h[p] > table_lower[p] && h[p] < table_upper[p])) { use_table = false; break; }
        for (std::size_t p = 0; p < h.size; ++p)
            t[p] = eos.temperature(input.fluid,h[p],input.pressure[p],use_table,location(grid,p,where));
        table_used = table_used || use_table;
    }

    FluidView frozen() const {
        return {view(dh),view(cp),temperature_star.empty() ? view(t) : view(temperature_star),view(star),input.hv,
                input.mass_x,input.mass_y,input.mass_z,hin,lower,upper};
    }
    FluidEnergyView energy(bool equations) const {
        return {view(h),view(t),input.hv,equations ? view(k) : ArrayView<const double>{},
                input.mass_x,input.mass_y,input.mass_z,hin};
    }
};

void check_inflow(const GridView& g, const EnthalpySideView& side) {
    if (side.inlet_direction < 0 || side.inlet_direction > 5)
        throw std::invalid_argument("T energy requires an explicit inlet direction");
    const std::size_t extent[]{g.nx,g.ny,g.nz}, stride[]{g.ny*g.nz,g.nz,1};
    const ArrayView<const double> mass[]{side.mass_x,side.mass_y,side.mass_z};
    for (std::size_t i = 0; i < g.nx; ++i)
        for (std::size_t j = 0; j < g.ny; ++j)
            for (std::size_t k = 0; k < g.nz; ++k) {
                const std::size_t coord[]{i,j,k};
                const std::size_t face[]{(i*g.ny+j)*g.nz+k,
                    (i*(g.ny+1)+j)*g.nz+k,(i*g.ny+j)*(g.nz+1)+k};
                for (std::size_t axis = 0; axis < 3; ++axis) {
                    const int low = static_cast<int>(2*axis), high = low+1;
                    if ((coord[axis] == 0 && mass[axis][face[axis]] > 0.
                         && side.inlet_direction != low)
                        || (coord[axis]+1 == extent[axis] && mass[axis][face[axis]+stride[axis]] < 0.
                            && side.inlet_direction != high))
                        throw std::invalid_argument("T energy has exterior inflow without a defined inlet state");
                }
            }
}

EnthalpyResult solve_temperature_energy(const GridView& grid, const EnthalpySideView& a,
                                       const EnthalpySideView& b, ArrayView<const double> k_ss,
                                       EnthalpyStateView state, const EnthalpyControl& control) {
    if (!control.max_iterations || !control.sweeps || !std::isfinite(control.omega)
        || control.omega <= 0. || control.omega > 1.
        || !std::isfinite(control.temperature_update_tolerance) || control.temperature_update_tolerance <= 0.)
        throw std::invalid_argument("invalid T energy numerical controls");
    if (control.require_enthalpy_update_on_temperature
        && (!std::isfinite(control.update_tolerance) || control.update_tolerance <= 0.))
        throw std::invalid_argument("T energy h-update tolerance must be finite and positive");
    for (const auto limit : {control.coupled_energy_tolerance,control.equation_energy_tolerance})
        if (!limit || !std::isfinite(*limit) || *limit <= 0.)
            throw std::invalid_argument("T energy requires positive coupled and equation tolerances");
    const auto maximum = std::numeric_limits<std::size_t>::max();
    if (grid.nx == maximum || grid.ny == maximum || grid.nz == maximum)
        throw std::invalid_argument("invalid T energy grid extent");
    const auto n = product(product(grid.nx,grid.ny),grid.nz);
    coefficient(grid.dx,grid.nx,true); coefficient(grid.dy,grid.ny,true); coefficient(grid.dz,grid.nz,true);
    coefficient(k_ss,n,false);
    for (const auto* f : {&a,&b}) {
        check(f->pressure,n,false);
        coefficient(f->epsilon,n,false); coefficient(f->hv,n,false);
        check(f->mass_x,product(product(grid.nx+1,grid.ny),grid.nz));
        check(f->mass_y,product(product(grid.nx,grid.ny+1),grid.nz));
        check(f->mass_z,product(product(grid.nx,grid.ny),grid.nz+1));
        check_inflow(grid,*f);
    }
    check(state.h_a,n,false); check(state.h_b,n,false);
    // Actual PT validation owns each fluid's error category and cell context.
    check(state.a,n,false); check(state.b,n,false); check(state.solid,n,state.warm_solid);
    EnthalpyEOS eos;
    Side sa(a,state.h_a,state.a,n,true), sb(b,state.h_b,state.b,n,true);
    const std::array<Side*,2> sides{&sa,&sb};
    const std::array<bool,2> warm{state.warm_a,state.warm_b};
    const bool sou = control.algorithm == EnthalpyAlgorithm::temperature_sou;
    EnthalpyResult result{};
    result.algorithm = control.algorithm;
    result.picard_relaxation = sou ? .6 : 1.;
    result.stop = EnthalpyStop::cancelled;
    if (control.cancel && control.cancel(control.context)) return result;
    for (std::size_t s = 0; s < sides.size(); ++s) {
        auto& side = *sides[s];
        const auto& f = side.input;
        const std::string name = s == 0 ? "A" : "B";
        side.hin = eos.evaluate_state(f.fluid,f.inlet_temperature,f.inlet_pressure,"T energy inlet "+name).enthalpy;
        for (std::size_t p = 0; p < n; ++p) {
            const double temperature = warm[s] ? side.t[p] : f.inlet_temperature;
            const auto actual = eos.evaluate_state(f.fluid,temperature,f.pressure[p],
                location(grid,p,"T energy initial state "+name));
            side.t[p] = temperature; side.h[p] = actual.enthalpy; side.cp[p] = actual.cp;
            side.k[p] = f.epsilon[p]*actual.conductivity;
            side.dh[p] = side.k[p]/actual.cp;
        }
    }
    result.inlet_enthalpy = {sa.hin,sb.hin};
    if (!state.warm_solid)
        std::fill_n(state.solid.data,n,.5*(a.inlet_temperature+b.inlet_temperature));
    std::vector<double> ra(n), rb(n), rs(n), old_solid(n), source_a(sou ? n : 0), source_b(sou ? n : 0);
    model_h_common::Anderson aa;
    EnthalpyEOS aa_eos;  // Candidate PT state cannot disturb the ordinary EOS.
    for (std::size_t iteration = 0; iteration < control.max_iterations; ++iteration) {
        // Capture before sweeps replace T with an unaudited image.
        const auto reference_audit=result.final_audit;
        const double reference_equation=reference_audit ? reference_audit->equation_ratio : std::numeric_limits<double>::quiet_NaN();
        const double reference_coupled=reference_audit ? reference_audit->coupled_ratio : std::numeric_limits<double>::quiet_NaN();
        const double reference_merit=reference_audit ? std::max(reference_equation / *control.equation_energy_tolerance,reference_coupled / *control.coupled_energy_tolerance) : std::numeric_limits<double>::quiet_NaN();
        if (control.cancel && control.cancel(control.context)) { result.final_audit.reset(); return result; }
        for (auto* side : sides) {
            std::copy_n(side->h.data,n,side->star.begin());
            std::copy_n(side->t.data,n,side->temperature_star.begin());
        }
        std::copy_n(state.solid.data,n,old_solid.begin());
        if (sou) {
            enthalpy_sou_correction(grid,view(sa.h),{a.mass_x,a.mass_y,a.mass_z},sa.hin,output(source_a));
            enthalpy_sou_correction(grid,view(sb.h),{b.mass_x,b.mass_y,b.mass_z},sb.hin,output(source_b));
        }
        conservative_temperature_sweeps(grid,sa.frozen(),sb.frozen(),k_ss,
            {state.a,state.b,state.solid},control.sweeps,control.omega,view(source_a),view(source_b),
            sou ? 1. : control.omega);
        if (sou) {
            // Underrelaxed rows can still form an oscillatory deferred-source
            // Picard block on graded meshes. Dampen the coupled increment,
            // preserving its fixed point; EOS and the audit see this actual T.
            for (auto* side : sides)
                for (std::size_t p = 0; p < n; ++p)
                    side->t[p] = side->temperature_star[p] + result.picard_relaxation
                        * (side->t[p] - side->temperature_star[p]);
            for (std::size_t p = 0; p < n; ++p)
                state.solid[p] = old_solid[p] + result.picard_relaxation * (state.solid[p] - old_solid[p]);
        }
        result.iterations = iteration+1;
        if (control.cancel && control.cancel(control.context)) { result.final_audit.reset(); return result; }
        // First/small-update/final blocks keep the complete ordinary path.
        if (sou && result.iterations<control.max_iterations) {
            Eigen::VectorXd aa_previous(3*n),aa_image(3*n),candidate;
            double pre_dT=0.;
            for (std::size_t p=0;p<n;++p) {
                aa_previous[p]=sa.temperature_star[p]; aa_image[p]=sa.t[p];
                aa_previous[n+p]=sb.temperature_star[p]; aa_image[n+p]=sb.t[p];
                aa_previous[2*n+p]=old_solid[p]; aa_image[2*n+p]=state.solid[p];
                pre_dT=std::max({pre_dT,std::abs(sa.t[p]-sa.temperature_star[p]),
                    std::abs(sb.t[p]-sb.temperature_star[p]),std::abs(state.solid[p]-old_solid[p])});
            }
            const bool finite_image=aa_image.allFinite();
            // The forced first ordinary block still supplies the first (x,G(x)).
            if (finite_image) aa.push(std::move(aa_previous),aa_image);
            if (reference_audit && finite_image && std::isfinite(pre_dT)
                && pre_dT>control.temperature_update_tolerance && aa.x.size()>=2 && std::isfinite(reference_merit)) {
                bool valid=aa.candidate(aa_image,candidate),accepted=false,trial_cancelled=false;
                if (valid) {
                    std::vector<double> ha(n),hb(n),cra(n),crb(n),crs(n);
                    Side ca(a,output(ha),{candidate.data(),n},n),cb(b,output(hb),{candidate.data()+n,n},n);
                    ca.hin=sa.hin; cb.hin=sb.hin;
                    const std::array<Side*,2> trial_sides{&ca,&cb};
                    double trial_dT=0.,trial_dh=0.;
                    for (std::size_t s=0;s<2 && valid;++s) {
                        auto& side=*trial_sides[s];
                        for (std::size_t p=0;p<n && valid;++p) {
                            if (p%256==0 && control.cancel && control.cancel(control.context)) {
                                trial_cancelled=true; valid=false; break;
                            }
                            const auto where=location(grid,p,s==0 ? "AA candidate A" : "AA candidate B");
                            EnthalpyPTState actual{};
                            try { actual=aa_eos.evaluate_state(side.input.fluid,side.t[p],side.input.pressure[p],where); }
                            catch (const std::invalid_argument&) { valid=false; }
                            catch (const std::domain_error&) { valid=false; }
                            catch (const CoolProp::CoolPropBaseError&) { valid=false; }
                            if (!valid) break;
                            side.h[p]=actual.enthalpy; side.cp[p]=actual.cp;
                            side.k[p]=side.input.epsilon[p]*actual.conductivity; side.dh[p]=side.k[p]/actual.cp;
                            trial_dT=std::max(trial_dT,std::abs(side.t[p]-sides[s]->temperature_star[p]));
                            trial_dh=std::max(trial_dh,std::abs(side.h[p]-sides[s]->star[p]));
                            if (!std::isfinite(side.k[p]) || !std::isfinite(side.dh[p])) valid=false;
                        }
                    }
                    for (std::size_t p=0;p<n;++p)
                        trial_dT=std::max(trial_dT,std::abs(candidate[2*n+p]-old_solid[p]));
                    trial_dh/=std::max(std::abs(sa.hin-sb.hin),1.);
                    if (!std::isfinite(trial_dT) || !std::isfinite(trial_dh)) valid=false;
                    EnergyAudit trial_audit{};
                    if (valid) {
                        try { trial_audit=thermal_energy_audit_sou(grid,ca.energy(true),cb.energy(true),
                            {candidate.data()+2*n,n},k_ss,output(cra),output(crb),output(crs)); }
                        catch (const std::domain_error&) { valid=false; }
                    }
                    if (control.cancel && control.cancel(control.context)) { trial_cancelled=true; valid=false; }
                    const double merit=valid ? std::max(trial_audit.equation_ratio / *control.equation_energy_tolerance,trial_audit.coupled_ratio / *control.coupled_energy_tolerance) : std::numeric_limits<double>::quiet_NaN();
                    if (valid && !std::isfinite(merit)) valid=false;
                    if (valid && merit<reference_merit) {
                        for (std::size_t s=0;s<2;++s) {
                            auto& to=*sides[s]; auto& from=*trial_sides[s];
                            std::copy_n(from.t.data,n,to.t.data); std::copy_n(from.h.data,n,to.h.data);
                            to.cp.swap(from.cp); to.k.swap(from.k); to.dh.swap(from.dh);
                        }
                        std::copy_n(candidate.data()+2*n,n,state.solid.data);
                        ra.swap(cra); rb.swap(crb); rs.swap(crs);
                        result.temperature_update=trial_dT; result.residual=trial_dh;
                        result.final_audit=trial_audit; result.q_a=trial_audit.q_a; result.q_b=trial_audit.q_b;
                        result.energy_imbalance=std::abs(trial_audit.net)/std::max({std::abs(trial_audit.q_a),std::abs(trial_audit.q_b),1e-30});
                        accepted=true;
                    }
                }
                // A rejected algebra/PT/audit trial must not hide cancellation
                // behind the additional ordinary EOS pass that now follows it.
                if (!accepted && !trial_cancelled && control.cancel && control.cancel(control.context))
                    trial_cancelled=true;
                if (trial_cancelled) { result.final_audit.reset(); return result; }
                if (accepted) continue;  // Only the untouched ordinary gate below may converge.
            }
        }
        double temperature_update = 0., enthalpy_update = 0.;
        for (std::size_t s = 0; s < sides.size(); ++s) {
            auto& side = *sides[s];
            for (std::size_t p = 0; p < n; ++p) {
                const auto actual = eos.evaluate_state(side.input.fluid,side.t[p],side.input.pressure[p],
                    location(grid,p,s == 0 ? "T energy actual state A" : "T energy actual state B"));
                temperature_update = std::max(temperature_update,std::abs(side.t[p]-side.temperature_star[p]));
                side.h[p] = actual.enthalpy; side.cp[p] = actual.cp;
                side.k[p] = side.input.epsilon[p]*actual.conductivity;
                side.dh[p] = side.k[p]/actual.cp;
                enthalpy_update = std::max(enthalpy_update,std::abs(side.h[p]-side.star[p]));
            }
        }
        for (std::size_t p = 0; p < n; ++p)
            temperature_update = std::max(temperature_update,std::abs(state.solid[p]-old_solid[p]));
        result.temperature_update = temperature_update;
        result.residual = enthalpy_update/std::max(std::abs(sa.hin-sb.hin),1.);
        if (!std::isfinite(temperature_update) || !std::isfinite(result.residual))
            throw std::domain_error("nonfinite actual T energy update");
        result.final_audit = sou
            ? thermal_energy_audit_sou(grid,sa.energy(true),sb.energy(true),view(state.solid),k_ss,output(ra),output(rb),output(rs))
            : thermal_energy_audit(grid,sa.energy(true),sb.energy(true),view(state.solid),k_ss,output(ra),output(rb),output(rs),true);
        const auto& audit = *result.final_audit;
        result.q_a = audit.q_a; result.q_b = audit.q_b;
        result.energy_imbalance = std::abs(audit.net)/std::max({std::abs(audit.q_a),std::abs(audit.q_b),1e-30});
        if (temperature_update <= control.temperature_update_tolerance
            && (!control.require_enthalpy_update_on_temperature || result.residual <= control.update_tolerance)
            && audit.coupled_ratio <= *control.coupled_energy_tolerance
            && audit.equation_ratio <= *control.equation_energy_tolerance) {
            result.stop = EnthalpyStop::converged;
            return result;
        }
    }
    result.stop = EnthalpyStop::iteration_limit;
    return result;
}
}  // namespace

EnthalpyResult solve_enthalpy(const GridView& grid, const EnthalpySideView& a,
                             const EnthalpySideView& b, ArrayView<const double> k_ss,
                             EnthalpyStateView state, const EnthalpyControl& control) {
    switch (control.algorithm) {
        case EnthalpyAlgorithm::temperature_fou:
        case EnthalpyAlgorithm::temperature_sou:
            return solve_temperature_energy(grid,a,b,k_ss,state,control);
        case EnthalpyAlgorithm::legacy_h_fou: break;
        default: throw std::invalid_argument("unknown conservative energy algorithm");
    }
    for (const auto limit : {control.coupled_energy_tolerance,control.equation_energy_tolerance})
        if (limit && (!std::isfinite(*limit) || *limit <= 0.))
            throw std::invalid_argument("true-h energy tolerances must be finite and positive");
    EnthalpyEOS eos;
    eos.validate(a.fluid,a.inlet_temperature,a.inlet_pressure,"enthalpy inlet A");
    eos.validate(b.fluid,b.inlet_temperature,b.inlet_pressure,"enthalpy inlet B");
    if (!control.max_iterations || !std::isfinite(control.omega) || control.omega <= 0.
        || control.omega > 1. || !std::isfinite(control.update_tolerance) || control.update_tolerance <= 0.)
        throw std::invalid_argument("invalid true-h numerical controls");
    const auto maximum = std::numeric_limits<std::size_t>::max();
    if (grid.nx == maximum || grid.ny == maximum || grid.nz == maximum)
        throw std::invalid_argument("invalid true-h grid extent");
    const auto n = product(product(grid.nx,grid.ny),grid.nz);
    coefficient(grid.dx,grid.nx,true);
    coefficient(grid.dy,grid.ny,true);
    coefficient(grid.dz,grid.nz,true);
    coefficient(k_ss,n,false);
    for (const auto* f : {&a,&b}) {
        // The actual inlet/warm/inverse EOS stage validates P and preserves
        // water-specific error classification, including nonfinite local P.
        check(f->pressure,n,false);
        coefficient(f->epsilon,n,false);
        coefficient(f->hv,n,false);
        check(f->mass_x,product(product(grid.nx+1,grid.ny),grid.nz));
        check(f->mass_y,product(product(grid.nx,grid.ny+1),grid.nz));
        check(f->mass_z,product(product(grid.nx,grid.ny),grid.nz+1));
    }
    check(state.h_a,n,false); check(state.h_b,n,false);
    check(state.a,n,false); check(state.b,n,false); check(state.solid,n,false);
    Side sa(a,state.h_a,state.a,n), sb(b,state.h_b,state.b,n);
    const std::array<Side*,2> sides{&sa,&sb};
    const std::array<bool,2> warm{state.warm_a,state.warm_b};
    const auto& floors = model_coefficients::enthalpy_temperature_lower_bounds;
    const double tlo = std::min(a.inlet_temperature,b.inlet_temperature)-model_coefficients::enthalpy_bracket_margin;
    const double thi = std::max(a.inlet_temperature,b.inlet_temperature)+model_coefficients::enthalpy_bracket_margin;
    for (std::size_t s = 0; s < sides.size(); ++s) {
        auto& side = *sides[s];
        const auto& f = side.input;
        side.hin = eos.bracket_enthalpy(f.fluid,f.inlet_temperature,f.inlet_pressure);
        side.lower = eos.bracket_enthalpy(f.fluid,std::max(tlo,floors[static_cast<std::size_t>(f.fluid)]),f.inlet_pressure);
        side.upper = eos.bracket_enthalpy(f.fluid,thi,f.inlet_pressure);
    }
    // As in the Python driver, actual water/sCO2 warm states precede generic
    // finite-temperature checks and all field enthalpy conversions.
    for (std::size_t s = 0; s < sides.size(); ++s) {
        auto& side = *sides[s];
        const auto& f = side.input;
        const std::string stage = s == 0 ? "enthalpy warm start A" : "enthalpy warm start B";
        if (f.fluid == Fluid::sco2 || (warm[s] && f.fluid == Fluid::water))
            for (std::size_t p = 0; p < n; ++p)
                eos.validate(f.fluid,warm[s] ? side.t[p] : f.inlet_temperature,f.pressure[p],location(grid,p,stage));
    }
    if (state.warm_a) check(state.a,n);
    if (state.warm_b) check(state.b,n);
    if (state.warm_solid) check(state.solid,n);
    for (std::size_t s = 0; s < sides.size(); ++s) {
        auto& side = *sides[s];
        const auto& f = side.input;
        for (std::size_t p = 0; p < n; ++p) {
            side.h[p] = warm[s] ? eos.bracket_enthalpy(f.fluid,side.t[p],f.pressure[p]) : side.hin;
            side.lower = std::min({side.lower,side.hin,side.h[p]});
            side.upper = std::max({side.upper,side.hin,side.h[p]});
        }
    }
    if (!state.warm_solid)
        std::fill_n(state.solid.data,n,.5*(a.inlet_temperature+b.inlet_temperature));
    EnthalpyResult result{};
    result.stop = EnthalpyStop::cancelled;
    result.inlet_enthalpy = {sa.hin,sb.hin};
    const bool check_energy = control.coupled_energy_tolerance || control.equation_energy_tolerance;
    const bool equations = control.equation_energy_tolerance.has_value();
    bool next_temperatures = false;
    std::vector<double> ra(check_energy ? n : 0), rb(check_energy ? n : 0), rs(check_energy ? n : 0);
    for (std::size_t iteration = 0; iteration < control.max_iterations; ++iteration) {
        if (control.cancel && control.cancel(control.context)) return result;
        if (iteration == 0 && (a.fluid == Fluid::sco2 || b.fluid == Fluid::sco2)) {
            eos.enable_bicubic(control.table_directory);
            for (auto* side : sides) if (side->input.fluid == Fluid::sco2) {
                side->table_lower.resize(n); side->table_upper.resize(n);
                for (std::size_t p = 0; p < n; ++p) {
                    side->table_lower[p] = eos.bracket_enthalpy(Fluid::sco2,
                        model_coefficients::sco2_temperature_range[0],side->input.pressure[p]);
                    side->table_upper[p] = eos.bracket_enthalpy(Fluid::sco2,
                        model_coefficients::sco2_temperature_range[1],side->input.pressure[p]);
                }
            }
        }
        if (!next_temperatures) {
            sa.invert(eos,grid,!result.heos_polish,"enthalpy iteration EOS return A");
            sb.invert(eos,grid,!result.heos_polish,"enthalpy iteration EOS return B");
        }
        next_temperatures = false;
        for (auto* side : sides) for (std::size_t p = 0; p < n; ++p) {
            const auto props = eos.evaluate(side->input.fluid,side->t[p],side->input.pressure[p]);
            side->cp[p] = props.cp;
            side->dh[p] = side->input.epsilon[p]*props.conductivity/std::max(props.cp,1e-30);
            side->star[p] = side->h[p];
        }
        result.last_clips = enthalpy_sweeps(grid,sa.frozen(),sb.frozen(),k_ss,
            {state.h_a,state.h_b,state.solid},control.sweeps,control.omega);
        result.total_clips.a += result.last_clips.a;
        result.total_clips.b += result.last_clips.b;
        result.iterations = iteration+1;
        if (control.cancel && control.cancel(control.context)) return result;
        double update = 0.;
        for (const auto* side : sides) for (std::size_t p = 0; p < n; ++p)
            update = std::max(update,std::abs(side->h[p]-side->star[p]));
        result.residual = update/std::max(std::abs(sa.hin-sb.hin),1.);
        result.q_a = boundary_enthalpy_duty(grid,view(sa.h),a.mass_x,a.mass_y,a.mass_z,sa.hin);
        result.q_b = boundary_enthalpy_duty(grid,view(sb.h),b.mass_x,b.mass_y,b.mass_z,sb.hin);
        result.energy_imbalance = std::abs(result.q_a+result.q_b)
            /std::max({std::abs(result.q_a),std::abs(result.q_b),1e-30});
        if (check_energy) for (const double value : {result.residual,result.q_a,result.q_b,result.energy_imbalance})
            if (!std::isfinite(value)) throw std::domain_error("nonfinite coupled energy convergence");
        bool converged = result.residual < control.update_tolerance && result.energy_imbalance < .05
            && !result.last_clips.a && !result.last_clips.b;
        if (check_energy && (converged || result.iterations == control.max_iterations)) {
            sa.invert(eos,grid,false,"enthalpy final EOS return A");
            sb.invert(eos,grid,false,"enthalpy final EOS return B");
            if (equations) for (auto* side : sides) for (std::size_t p = 0; p < n; ++p)
                side->k[p] = side->input.epsilon[p]
                    *eos.conductivity(side->input.fluid,side->t[p],side->input.pressure[p]);
            result.final_audit = thermal_energy_audit(grid,sa.energy(equations),sb.energy(equations),
                view(state.solid),k_ss,output(ra),output(rb),output(rs),equations);
            if (control.coupled_energy_tolerance)
                converged = converged && result.final_audit->coupled_ratio <= *control.coupled_energy_tolerance;
            if (control.equation_energy_tolerance)
                converged = converged && result.final_audit->equation_ratio <= *control.equation_energy_tolerance;
            if (!converged && result.iterations < control.max_iterations) {
                next_temperatures = true;
                result.heos_polish = true;
            }
        }
        result.used_bicubic = {sa.table_used,sb.table_used};
        if (converged) { result.stop = EnthalpyStop::converged; break; }
    }
    if (!check_energy) {
        sa.invert(eos,grid,false,"enthalpy final EOS return A");
        sb.invert(eos,grid,false,"enthalpy final EOS return B");
        check(state.solid,n);
    }
    if (result.stop != EnthalpyStop::converged)
        result.stop = result.last_clips.a || result.last_clips.b
            ? EnthalpyStop::enthalpy_limited : EnthalpyStop::iteration_limit;
    return result;
}
}  // namespace tpmshx
