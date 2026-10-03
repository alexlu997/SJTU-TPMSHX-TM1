#include "tpmshx/enthalpy_driver.hpp"
#include "tpmshx/model_coefficients.hpp"

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
    std::vector<double> cp, dh, k, star, table_lower, table_upper;
    bool table_used = false;
    Side(const EnthalpySideView& f, ArrayView<double> enthalpy, ArrayView<double> temperature,
         std::size_t n) : input(f), h(enthalpy), t(temperature), cp(n), dh(n), k(n), star(n) {}

    void invert(EnthalpyEOS& eos, const GridView& grid, bool tables, const std::string& where) {
        bool use_table = tables && !table_lower.empty();
        if (use_table) for (std::size_t p = 0; p < h.size; ++p)
            if (!(h[p] > table_lower[p] && h[p] < table_upper[p])) { use_table = false; break; }
        for (std::size_t p = 0; p < h.size; ++p)
            t[p] = eos.temperature(input.fluid,h[p],input.pressure[p],use_table,location(grid,p,where));
        table_used = table_used || use_table;
    }

    FluidView frozen() const {
        return {view(dh),view(cp),view(t),view(star),input.hv,
                input.mass_x,input.mass_y,input.mass_z,hin,lower,upper};
    }
    FluidEnergyView energy(bool equations) const {
        return {view(h),view(t),input.hv,equations ? view(k) : ArrayView<const double>{},
                input.mass_x,input.mass_y,input.mass_z,hin};
    }
};
}  // namespace

EnthalpyResult solve_enthalpy(const GridView& grid, const EnthalpySideView& a,
                             const EnthalpySideView& b, ArrayView<const double> k_ss,
                             EnthalpyStateView state, const EnthalpyControl& control) {
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
