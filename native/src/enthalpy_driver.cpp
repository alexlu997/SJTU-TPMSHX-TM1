#include "tpmshx/enthalpy_driver.hpp"
#include "tpmshx/conservative_energy.hpp"
#include "tpmshx/model_coefficients.hpp"

#include "model_h_common.hpp"

#include <CoolProp/Exceptions.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <future>
#include <cmath>
#include <limits>
#include <string>
#include <string_view>
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

std::string location(const GridView& grid, std::size_t p, std::string_view stage) {
    return std::string(stage) + ": index=(" + std::to_string(p/(grid.ny*grid.nz)) + ", "
        + std::to_string((p/grid.nz)%grid.ny) + ", " + std::to_string(p%grid.nz) + ")";
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
        for (std::size_t p = 0; p < h.size; ++p) {
            bool used = use_table;
            t[p] = eos.temperature(input.fluid,h[p],input.pressure[p],used,location(grid,p,where),input.energy);
            table_used = table_used || used;
        }
    }

    double conductivity(EnthalpyEOS& eos, std::size_t p, double evaluated) const {
        if(input.conductivity_source!=ConductivitySource::local_eos)
            return input.effective_conductivity[p];
        const double value=input.energy==EnergyRelation::eos_h_TP ? evaluated
            : eos.conductivity(input.fluid,t[p],input.pressure[p]);
        return input.epsilon[p]*value;
    }
    void transport(EnthalpyEOS& eos, std::size_t p, const EnthalpyProperties& properties) {
        cp[p]=properties.cp;k[p]=conductivity(eos,p,properties.conductivity);
        dh[p]=k[p]/properties.cp;
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

void retain_physical_audit(PhysicalHeatLedger* output, const GridView& grid,
        const Side& a, const Side& b, std::vector<double>& ra,
        std::vector<double>& rb, std::vector<double>& rs, bool second_order) {
    if (!output) return;
    PhysicalHeatLedger ledger;
    ledger.residual={std::move(ra),std::move(rb),std::move(rs)};
    const std::size_t planes[]{grid.ny*grid.nz,grid.ny*grid.nz,
        grid.nx*grid.nz,grid.nx*grid.nz,grid.nx*grid.ny,grid.nx*grid.ny};
    for (std::size_t phase=0;phase<3;++phase) for (std::size_t face=0;face<6;++face) {
        ledger.advective_out[phase][face].assign(planes[face],0.);
        ledger.diffusive_out[phase][face].assign(planes[face],0.);
    }
    const Side* sides[]{&a,&b};
    for (std::size_t side=0;side<2;++side) {
        const auto& f=*sides[side];
        ledger.advective_out[side]=enthalpy_boundary_power(grid,view(f.h),
            {f.input.mass_x,f.input.mass_y,f.input.mass_z},f.hin,second_order);
    }
    *output=std::move(ledger);
}

void check_inflow(const GridView& g, const EnthalpySideView& side) {
    if (side.inlet_direction < -1 || side.inlet_direction > 5)
        throw std::invalid_argument("invalid T energy inlet direction");
    if (side.inlet_direction == -1) return;
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

}  // namespace

struct EnthalpyRun::Impl {
    GridView grid;
    EnthalpySideView a,b;
    ArrayView<const double> k_ss;
    EnthalpyStateView state;
    EnthalpyControl control;
    PhysicalHeatLedger* physical_audit;
    bool temperature,sou,check_energy,equations;
    bool next_temperatures=false,table_ready=false,boundary=true,taken=false;
    std::size_t n=0;
    EnthalpyPhase phase=EnthalpyPhase::active;
    EnthalpyResult result{};
    EnthalpyEOS eos,aa_eos;
    std::optional<Side> side_a,side_b;
    std::vector<double> ra,rb,rs,old_solid,source_a,source_b;
    model_h_common::Anderson aa;

    struct PropertyLane { EnthalpyEOS ordinary,trial; };
    std::vector<std::unique_ptr<PropertyLane>> property_lanes;
    template<class F> bool property_cells(bool trial,F&& cell) {
        const auto lanes=std::min(control.cpu_threads,n);
        std::vector<std::exception_ptr> errors(lanes);
        std::atomic<bool> cancelled{false};
        auto poll=[&] {
            if(control.cancel && control.cancel(control.context)) cancelled.store(true);
        };
        property_lanes.resize(lanes-1);
        for(std::size_t lane=1;lane<lanes;++lane)
            if(!property_lanes[lane-1]) property_lanes[lane-1]=std::make_unique<PropertyLane>();
        auto run=[&](std::size_t lane) {
            try {
                auto& local=lane ? (trial ? property_lanes[lane-1]->trial : property_lanes[lane-1]->ordinary)
                                 : (trial ? aa_eos : eos);
                for(std::size_t p=n*lane/lanes;p<n*(lane+1)/lanes;++p) {
                    if(trial && lane==0 && p%256==0) poll();
                    if(cancelled.load() || !cell(lane,p,local)) break;
                }
            } catch(...) { errors[lane]=std::current_exception(); }
        };
        std::vector<std::future<void>> futures;
        futures.reserve(lanes-1);
        for(std::size_t lane=1;lane<lanes;++lane)
            futures.push_back(std::async(std::launch::async,run,lane));
        run(0);
        for(auto& future:futures) {
            while(future.wait_for(std::chrono::milliseconds(10))!=std::future_status::ready) {
                try { if(trial) poll(); }
                catch(...) { if(!errors[0]) errors[0]=std::current_exception();cancelled.store(true); }
            }
            future.get();
        }
        for(const auto& error:errors) if(error) std::rethrow_exception(error);
        return cancelled.load();
    }

    Impl(const GridView& input_grid,const EnthalpySideView& input_a,const EnthalpySideView& input_b,
        ArrayView<const double> solid_k,EnthalpyStateView fields,const EnthalpyControl& options,
        PhysicalHeatLedger* output)
        :grid(input_grid),a(input_a),b(input_b),k_ss(solid_k),state(fields),control(options),physical_audit(output),
         temperature(control.algorithm!=EnthalpyAlgorithm::legacy_h_fou),
         sou(control.algorithm==EnthalpyAlgorithm::temperature_sou),
         check_energy(control.coupled_energy_tolerance || control.equation_energy_tolerance),
         equations(control.equation_energy_tolerance.has_value()) {
        validate(true);prepare_sides();
        if(temperature)initialize_temperature();else initialize_legacy();
        if(phase==EnthalpyPhase::active) {initialize_update_scale();prepare_scratch();}
    }
    Impl(const GridView& input_grid,const EnthalpySideView& input_a,const EnthalpySideView& input_b,
        ArrayView<const double> solid_k,EnthalpyStateView fields,const EnthalpyControl& options,
        PhysicalHeatLedger* output,const EnthalpyRunState& saved)
        :grid(input_grid),a(input_a),b(input_b),k_ss(solid_k),state(fields),control(options),physical_audit(output),
         temperature(control.algorithm!=EnthalpyAlgorithm::legacy_h_fou),
         sou(control.algorithm==EnthalpyAlgorithm::temperature_sou),
         check_energy(control.coupled_energy_tolerance || control.equation_energy_tolerance),
         equations(control.equation_energy_tolerance.has_value()) {
        validate(false);validate_saved(saved);prepare_sides();prepare_scratch();
        result=saved.result;next_temperatures=saved.next_temperatures;aa.restore(saved.acceleration);
        const std::array<Side*,2> sides{&*side_a,&*side_b};
        for(std::size_t s=0;s<2;++s) {
            auto& side=*sides[s];const auto& from=saved.sides[s];
            side.hin=result.inlet_enthalpy[s];side.lower=from.lower;side.upper=from.upper;
            side.table_lower=from.table_lower;side.table_upper=from.table_upper;
            side.table_used=result.used_bicubic[s];
            if(temperature) { side.cp=from.transport[0];side.dh=from.transport[1];side.k=from.transport[2]; }
        }
        const ArrayView<double> fields_to_restore[]{state.h_a,state.h_b,state.a,state.b,state.solid};
        for(std::size_t i=0;i<5;++i)
            std::copy(saved.fields[i].begin(),saved.fields[i].end(),fields_to_restore[i].data);
    }
    void validate(bool initial) {
        if(!control.cpu_threads)throw std::invalid_argument("CPU thread count must be positive");
        switch(control.algorithm) {
        case EnthalpyAlgorithm::legacy_h_fou:validate_legacy();break;
        case EnthalpyAlgorithm::temperature_fou:
        case EnthalpyAlgorithm::temperature_sou:validate_temperature(initial);break;
        default:throw std::invalid_argument("unknown conservative energy algorithm");
        }
    }
    void validate_temperature(bool initial) {
        if (!control.max_iterations || !std::isfinite(control.omega)
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
        n = product(product(grid.nx,grid.ny),grid.nz);
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
        check(state.a,n,false); check(state.b,n,false); check(state.solid,n,initial && state.warm_solid);
    }
    void validate_legacy() {
        for (const auto limit : {control.coupled_energy_tolerance,control.equation_energy_tolerance})
            if (limit && (!std::isfinite(*limit) || *limit <= 0.))
                throw std::invalid_argument("true-h energy tolerances must be finite and positive");
        eos.validate(a.fluid,a.inlet_temperature,a.inlet_pressure,"enthalpy inlet A");
        eos.validate(b.fluid,b.inlet_temperature,b.inlet_pressure,"enthalpy inlet B");
        if (!control.max_iterations || !std::isfinite(control.omega) || control.omega <= 0.
            || control.omega > 1. || !std::isfinite(control.update_tolerance) || control.update_tolerance <= 0.)
            throw std::invalid_argument("invalid true-h numerical controls");
        const auto maximum = std::numeric_limits<std::size_t>::max();
        if (grid.nx == maximum || grid.ny == maximum || grid.nz == maximum)
            throw std::invalid_argument("invalid true-h grid extent");
        n = product(product(grid.nx,grid.ny),grid.nz);
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
    }
    void prepare_sides() {
        for(const auto* side:{&a,&b}) {
            if(side->energy!=EnergyRelation::eos_h_TP && side->energy!=EnergyRelation::integral_cp_T)
                throw std::invalid_argument("invalid conservative energy relation");
            if(side->energy==EnergyRelation::integral_cp_T)model_h_coefficients(side->fluid);
            if(side->conductivity_source==ConductivitySource::prepared
                || side->conductivity_source==ConductivitySource::outer_transport)
                coefficient(side->effective_conductivity,n,false);
            else if(side->conductivity_source!=ConductivitySource::local_eos
                || side->effective_conductivity.size)
                throw std::invalid_argument("invalid conservative conductivity source");
        }
        side_a.emplace(a,state.h_a,state.a,n,temperature);
        side_b.emplace(b,state.h_b,state.b,n,temperature);
    }
    std::array<double,2> update_scale(const std::array<double,2>& inlet_enthalpy) {
        std::array<double,2> scale;
        if(!control.reference_independent_update) {
            scale.fill(std::max(std::abs(inlet_enthalpy[0]-inlet_enthalpy[1]),1.));
            return scale;
        }
        const double difference=std::abs(a.inlet_temperature-b.inlet_temperature);
        const EnthalpySideView* sides[]{&a,&b};
        for(std::size_t side=0;side<2;++side) {
            const auto& input=*sides[side];
            const auto properties=eos.evaluate(input.fluid,input.inlet_temperature,input.inlet_pressure,input.energy);
            scale[side]=std::max(properties.cp*difference,1.);
            if(!std::isfinite(scale[side]))
                throw std::domain_error("nonfinite enthalpy update scale");
        }
        return scale;
    }
    void initialize_update_scale() {
        result.reference_independent_update=control.reference_independent_update;
        result.enthalpy_update_scale=update_scale(result.inlet_enthalpy);
    }
    void prepare_scratch() {
        ra.resize(check_energy?n:0);rb.resize(check_energy?n:0);rs.resize(check_energy?n:0);
        if(temperature)old_solid.resize(n);
        if(sou) { source_a.resize(n);source_b.resize(n); }
    }
    void initialize_temperature() {
        auto& sa=*side_a;auto& sb=*side_b;
        const std::array<Side*,2> sides{&sa,&sb};
        const std::array<bool,2> warm{state.warm_a,state.warm_b};
        result.algorithm = control.algorithm;
        result.picard_relaxation = sou ? .6 : 1.;
        result.stop = EnthalpyStop::cancelled;
        if (control.cancel && control.cancel(control.context)) { phase=EnthalpyPhase::cancelled;return; }
        for (std::size_t s = 0; s < sides.size(); ++s) {
            auto& side = *sides[s];
            const auto& f = side.input;
            const std::string name = s == 0 ? "A" : "B";
            side.hin = eos.evaluate_state(f.fluid,f.inlet_temperature,f.inlet_pressure,"T energy inlet "+name,f.energy).enthalpy;
            for (std::size_t p = 0; p < n; ++p) {
                const double initial_temperature = warm[s] ? side.t[p] : f.inlet_temperature;
                const auto actual = eos.evaluate_state(f.fluid,initial_temperature,f.pressure[p],
                    location(grid,p,"T energy initial state "+name),f.energy);
                side.t[p] = initial_temperature; side.h[p] = actual.enthalpy;
                side.transport(eos,p,{actual.cp,actual.conductivity});
            }
        }
        result.inlet_enthalpy = {sa.hin,sb.hin};
        if (!state.warm_solid)
            std::fill_n(state.solid.data,n,.5*(a.inlet_temperature+b.inlet_temperature));
    }
    void initialize_legacy() {
        auto& sa=*side_a;auto& sb=*side_b;
        const std::array<Side*,2> sides{&sa,&sb};
        const std::array<bool,2> warm{state.warm_a,state.warm_b};
        const auto& floors = model_coefficients::enthalpy_temperature_lower_bounds;
        const double tlo = std::min(a.inlet_temperature,b.inlet_temperature)-model_coefficients::enthalpy_bracket_margin;
        const double thi = std::max(a.inlet_temperature,b.inlet_temperature)+model_coefficients::enthalpy_bracket_margin;
        for (std::size_t s = 0; s < sides.size(); ++s) {
            auto& side = *sides[s];
            const auto& f = side.input;
            side.hin = eos.bracket_enthalpy(f.fluid,f.inlet_temperature,f.inlet_pressure,f.energy);
            side.lower = eos.bracket_enthalpy(f.fluid,std::max(tlo,floors[static_cast<std::size_t>(f.fluid)]),f.inlet_pressure,f.energy);
            side.upper = eos.bracket_enthalpy(f.fluid,thi,f.inlet_pressure,f.energy);
        }
        // As in the Python driver, actual water/sCO2 warm states precede generic
        // finite-temperature checks and all field enthalpy conversions.
        for (std::size_t s = 0; s < sides.size(); ++s) {
            auto& side = *sides[s];
            const auto& f = side.input;
            const std::string stage = s == 0 ? "enthalpy warm start A" : "enthalpy warm start B";
            if (uses_co2_eos(f.fluid) || (warm[s] && f.fluid == Fluid::water))
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
                side.h[p] = warm[s] ? eos.bracket_enthalpy(f.fluid,side.t[p],f.pressure[p],f.energy) : side.hin;
                side.lower = std::min({side.lower,side.hin,side.h[p]});
                side.upper = std::max({side.upper,side.hin,side.h[p]});
            }
        }
        if (!state.warm_solid)
            std::fill_n(state.solid.data,n,.5*(a.inlet_temperature+b.inlet_temperature));
        result.stop = EnthalpyStop::cancelled;
        result.inlet_enthalpy = {sa.hin,sb.hin};
    }
    void advance_temperature() {
        auto& sa=*side_a;auto& sb=*side_b;
        const std::array<Side*,2> sides{&sa,&sb};
        const auto iteration=result.iterations;
        // Capture before sweeps replace T with an unaudited image.
        const auto reference_audit=result.final_audit;
        const double reference_equation=reference_audit ? reference_audit->equation_ratio : std::numeric_limits<double>::quiet_NaN();
        const double reference_coupled=reference_audit ? reference_audit->coupled_ratio : std::numeric_limits<double>::quiet_NaN();
        const double reference_merit=reference_audit ? std::max(reference_equation / *control.equation_energy_tolerance,reference_coupled / *control.coupled_energy_tolerance) : std::numeric_limits<double>::quiet_NaN();
        if (control.cancel && control.cancel(control.context)) { result.final_audit.reset(); phase=EnthalpyPhase::cancelled;return; }
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
        if (control.cancel && control.cancel(control.context)) { result.final_audit.reset(); phase=EnthalpyPhase::cancelled;return; }
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
                        const auto lanes=std::min(control.cpu_threads,n);
                        std::vector<double> dt(lanes),dh(lanes);
                        std::vector<unsigned char> lane_valid(lanes,1);
                        trial_cancelled=property_cells(true,[&](std::size_t lane,std::size_t p,EnthalpyEOS& local) {
                            const auto where=location(grid,p,s==0 ? "AA candidate A" : "AA candidate B");
                            EnthalpyPTState actual{};
                            try { actual=local.evaluate_state(side.input.fluid,side.t[p],side.input.pressure[p],where,side.input.energy); }
                            catch (const std::invalid_argument&) { lane_valid[lane]=false; }
                            catch (const std::domain_error&) { lane_valid[lane]=false; }
                            catch (const CoolProp::CoolPropBaseError&) { lane_valid[lane]=false; }
                            if(!lane_valid[lane]) return false;
                            side.h[p]=actual.enthalpy;side.transport(local,p,{actual.cp,actual.conductivity});
                            dt[lane]=std::max(dt[lane],std::abs(side.t[p]-sides[s]->temperature_star[p]));
                            dh[lane]=std::max(dh[lane],std::abs(side.h[p]-sides[s]->star[p])/result.enthalpy_update_scale[s]);
                            lane_valid[lane]=std::isfinite(side.k[p]) && std::isfinite(side.dh[p]);
                            return lane_valid[lane]!=0;
                        });
                        for(std::size_t lane=0;lane<lanes;++lane) {
                            trial_dT=std::max(trial_dT,dt[lane]);trial_dh=std::max(trial_dh,dh[lane]);
                            valid=valid && lane_valid[lane];
                        }
                        valid=valid && !trial_cancelled;
                    }
                    for (std::size_t p=0;p<n;++p)
                        trial_dT=std::max(trial_dT,std::abs(candidate[2*n+p]-old_solid[p]));
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
                if (trial_cancelled) { result.final_audit.reset(); phase=EnthalpyPhase::cancelled;return; }
                if (accepted) return;  // Only the untouched ordinary gate below may converge.
            }
        }
        double temperature_update = 0., enthalpy_update = 0.;
        for (std::size_t s = 0; s < sides.size(); ++s) {
            auto& side = *sides[s];
            const auto lanes=std::min(control.cpu_threads,n);
            std::vector<double> dt(lanes),dh(lanes);
            property_cells(false,[&](std::size_t lane,std::size_t p,EnthalpyEOS& local) {
                const auto actual = local.evaluate_state(side.input.fluid,side.t[p],side.input.pressure[p],
                    location(grid,p,s == 0 ? "T energy actual state A" : "T energy actual state B"),side.input.energy);
                dt[lane] = std::max(dt[lane],std::abs(side.t[p]-side.temperature_star[p]));
                side.h[p] = actual.enthalpy;
                side.transport(local,p,{actual.cp,actual.conductivity});
                dh[lane] = std::max(dh[lane],std::abs(side.h[p]-side.star[p])/result.enthalpy_update_scale[s]);
                return true;
            });
            for(std::size_t lane=0;lane<lanes;++lane) {
                temperature_update=std::max(temperature_update,dt[lane]);
                enthalpy_update=std::max(enthalpy_update,dh[lane]);
            }
        }
        for (std::size_t p = 0; p < n; ++p)
            temperature_update = std::max(temperature_update,std::abs(state.solid[p]-old_solid[p]));
        result.temperature_update = temperature_update;
        result.residual = enthalpy_update;
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
            retain_physical_audit(physical_audit,grid,sa,sb,ra,rb,rs,sou);
            phase=EnthalpyPhase::completed;return;
        }
    }
    void finish_temperature() {
        const auto& sa=*side_a;const auto& sb=*side_b;
        result.stop = EnthalpyStop::iteration_limit;
        retain_physical_audit(physical_audit,grid,sa,sb,ra,rb,rs,sou);
        phase=EnthalpyPhase::completed;
    }
    bool tabulated_side(const EnthalpySideView& side) {
        if (side.fluid == Fluid::sco2) return true;
        if (side.fluid != Fluid::co2) return false;
        const auto range = std::minmax_element(side.pressure.data,side.pressure.data+side.pressure.size);
        return eos.bicubic_pressure(*range.first) && eos.bicubic_pressure(*range.second);
    }
    void advance_legacy() {
        auto& sa=*side_a;auto& sb=*side_b;
        const std::array<Side*,2> sides{&sa,&sb};
        const auto iteration=result.iterations;
        if (control.cancel && control.cancel(control.context)) { phase=EnthalpyPhase::cancelled;return; }
        if (iteration == 0) for (auto* side : sides) if (tabulated_side(side->input)) {
            if (!table_ready) { eos.enable_bicubic(control.table_directory);table_ready=true; }
            side->table_lower.assign(n,side->lower); side->table_upper.assign(n,side->upper);
            if (side->input.fluid == Fluid::sco2) for (std::size_t p = 0; p < n; ++p) {
                side->table_lower[p] = eos.bracket_enthalpy(Fluid::sco2,
                    model_coefficients::sco2_temperature_range[0],side->input.pressure[p]);
                side->table_upper[p] = eos.bracket_enthalpy(Fluid::sco2,
                    model_coefficients::sco2_temperature_range[1],side->input.pressure[p]);
            }
        }
        if(!table_ready && !result.heos_polish && (!sa.table_lower.empty() || !sb.table_lower.empty())) {
            eos.enable_bicubic(control.table_directory);table_ready=true;
        }
        if (!next_temperatures) {
            sa.invert(eos,grid,!result.heos_polish,"enthalpy iteration EOS return A");
            sb.invert(eos,grid,!result.heos_polish,"enthalpy iteration EOS return B");
        }
        next_temperatures = false;
        for (auto* side : sides) for (std::size_t p = 0; p < n; ++p) {
            const auto props = eos.evaluate(side->input.fluid,side->t[p],side->input.pressure[p],side->input.energy);
            side->transport(eos,p,props);
            side->star[p] = side->h[p];
        }
        result.last_clips = enthalpy_sweeps(grid,sa.frozen(),sb.frozen(),k_ss,
            {state.h_a,state.h_b,state.solid},control.sweeps,control.omega);
        result.total_clips.a += result.last_clips.a;
        result.total_clips.b += result.last_clips.b;
        result.iterations = iteration+1;
        if (control.cancel && control.cancel(control.context)) { phase=EnthalpyPhase::cancelled;return; }
        double update = 0.;
        for (std::size_t s=0;s<2;++s) for (std::size_t p = 0; p < n; ++p)
            update = std::max(update,std::abs(sides[s]->h[p]-sides[s]->star[p])/result.enthalpy_update_scale[s]);
        result.residual = update;
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
                side->k[p] = side->conductivity(eos,p,side->input.conductivity_source==ConductivitySource::local_eos
                    ? eos.conductivity(side->input.fluid,side->t[p],side->input.pressure[p],side->input.energy) : 0.);
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
        if (converged) { result.stop = EnthalpyStop::converged;finish_legacy(); }
    }
    void finish_legacy() {
        auto& sa=*side_a;auto& sb=*side_b;
        if (!check_energy) {
            sa.invert(eos,grid,false,"enthalpy final EOS return A");
            sb.invert(eos,grid,false,"enthalpy final EOS return B");
            check(state.solid,n);
        }
        if (result.stop != EnthalpyStop::converged)
            result.stop = result.last_clips.a || result.last_clips.b
                ? EnthalpyStop::enthalpy_limited : EnthalpyStop::iteration_limit;
        if (result.final_audit && result.final_audit->fluid_equations_computed)
            retain_physical_audit(physical_audit,grid,sa,sb,ra,rb,rs,false);
        phase=EnthalpyPhase::completed;
    }
    void advance() {
        if(phase==EnthalpyPhase::failed)throw std::logic_error("failed energy run cannot advance");
        if(phase!=EnthalpyPhase::active)return;
        if(!boundary)throw std::logic_error("energy run is already advancing");
        boundary=false;
        try {
            if(temperature)advance_temperature();else advance_legacy();
            if(phase==EnthalpyPhase::active && result.iterations==control.max_iterations) {
                if(temperature)finish_temperature();else finish_legacy();
            }
            boundary=true;
        } catch(...) { phase=EnthalpyPhase::failed;throw; }
    }
    void validate_saved(const EnthalpyRunState& saved) {
        const auto& r=saved.result;
        for(std::size_t i=0;i<5;++i) {
            // A cold H start replaces T at the first inverse step.
            const bool initialized=temperature || r.iterations || i<2 || i==4
                || (i==2?state.warm_a:state.warm_b);
            check(view(saved.fields[i]),n,initialized);
        }
        if(r.algorithm!=control.algorithm || r.reference_independent_update!=control.reference_independent_update
            || r.stop!=EnthalpyStop::cancelled
            || r.iterations>=control.max_iterations || r.last_clips.a>r.total_clips.a || r.last_clips.b>r.total_clips.b
            || !std::isfinite(r.residual) || r.residual<0.
            || r.picard_relaxation!=(sou?.6:1.) || (temperature && (r.heos_polish || saved.next_temperatures))
            || (saved.next_temperatures && (!r.heos_polish || !r.final_audit))
            || r.temperature_update.has_value()!=(temperature && r.iterations!=0)
            || (temperature && r.final_audit.has_value()!=(r.iterations!=0))
            || (r.heos_polish && (!check_energy || !r.final_audit || !r.iterations))
            || (!check_energy && r.final_audit))
            throw std::invalid_argument("invalid saved energy iteration");
        if(r.temperature_update && (!std::isfinite(*r.temperature_update) || *r.temperature_update<0.))
            throw std::invalid_argument("invalid saved energy temperature update");
        if(check_energy) {
            if(!std::isfinite(r.q_a) || !std::isfinite(r.q_b)
                || !std::isfinite(r.energy_imbalance) || r.energy_imbalance<0.)
                throw std::invalid_argument("invalid saved energy power");
        }
        if(r.final_audit) {
            const auto& audit=*r.final_audit;
            if(audit.fluid_equations_computed!=equations || !std::isfinite(audit.q_a)
                || !std::isfinite(audit.q_b) || !std::isfinite(audit.net)
                || !std::isfinite(audit.denominator) || audit.denominator<=0.)
                throw std::invalid_argument("invalid saved energy audit");
            for(double value:{audit.solid_abs_sum,audit.coupled_ratio})
                if(!std::isfinite(value) || value<0.)throw std::invalid_argument("invalid saved energy audit");
            for(double value:{audit.fluid_abs_sum[0],audit.fluid_abs_sum[1],
                    audit.fluid_cell_max[0],audit.fluid_cell_max[1],audit.equation_ratio})
                if(equations ? (!std::isfinite(value) || value<0.) : !std::isnan(value))
                    throw std::invalid_argument("invalid saved energy equation audit");
        }
        for(std::size_t s=0;s<2;++s) {
            const auto& side=saved.sides[s];const auto& input=s==0?a:b;
            if(!std::isfinite(r.enthalpy_update_scale[s]) || r.enthalpy_update_scale[s]<1.
                || !std::isfinite(r.inlet_enthalpy[s]) || !std::isfinite(side.lower) || !std::isfinite(side.upper)
                || side.lower>side.upper || (temperature && r.used_bicubic[s]))
                throw std::invalid_argument("invalid saved energy side state");
            if(temperature) {
                coefficient(view(side.transport[0]),n,true);
                coefficient(view(side.transport[1]),n,false);coefficient(view(side.transport[2]),n,false);
            } else for(const auto& field:side.transport)
                if(!field.empty())throw std::invalid_argument("unexpected saved energy transport state");
            const auto tables=!temperature && r.iterations!=0 && tabulated_side(input);
            if(tables) {
                check(view(side.table_lower),n);check(view(side.table_upper),n);
                for(std::size_t p=0;p<n;++p)if(side.table_lower[p]>=side.table_upper[p])
                    throw std::invalid_argument("invalid saved energy table bounds");
            } else if(!side.table_lower.empty() || !side.table_upper.empty())
                throw std::invalid_argument("unexpected saved energy table bounds");
            if(r.used_bicubic[s] && !tables)throw std::invalid_argument("invalid saved energy table use");
        }
        if(r.enthalpy_update_scale!=update_scale(r.inlet_enthalpy))
            throw std::invalid_argument("saved energy update scale differs from its inlet state");
        const auto& history=saved.acceleration;
        if(history.history_limit!=6 || history.condition_limit!=1e10
            || (!sou && !history.x.empty()) || (sou && (r.iterations==0)!=history.x.empty()))
            throw std::invalid_argument("invalid saved energy acceleration");
        model_h_common::Anderson checked;checked.restore(history);
        if(!checked.x.empty() && static_cast<std::size_t>(checked.x.front().size())!=3*n)
            throw std::invalid_argument("saved energy acceleration extent differs");
    }
    EnthalpyRunState snapshot() const {
        if(phase!=EnthalpyPhase::active || !boundary)
            throw std::logic_error("energy run has no active save boundary");
        EnthalpyRunState saved;
        const ArrayView<double> fields[]{state.h_a,state.h_b,state.a,state.b,state.solid};
        for(std::size_t i=0;i<5;++i)saved.fields[i].assign(fields[i].data,fields[i].data+fields[i].size);
        const Side* sides[]{&*side_a,&*side_b};
        for(std::size_t s=0;s<2;++s) {
            auto& to=saved.sides[s];const auto& from=*sides[s];
            to.lower=from.lower;to.upper=from.upper;
            to.table_lower=from.table_lower;to.table_upper=from.table_upper;
            if(temperature)to.transport={from.cp,from.dh,from.k};
        }
        saved.result=result;saved.acceleration=aa.snapshot();saved.next_temperatures=next_temperatures;
        return saved;
    }
    EnthalpyResult take_result() {
        if(taken || (phase!=EnthalpyPhase::completed && phase!=EnthalpyPhase::cancelled))
            throw std::logic_error("energy result is not available");
        taken=true;return std::move(result);
    }
};

EnthalpyRun::EnthalpyRun(const GridView& grid,const EnthalpySideView& a,const EnthalpySideView& b,
        ArrayView<const double> k_ss,EnthalpyStateView state,const EnthalpyControl& control,
        PhysicalHeatLedger* physical_audit)
    :impl_(std::make_unique<Impl>(grid,a,b,k_ss,state,control,physical_audit)) {}
EnthalpyRun::EnthalpyRun(const GridView& grid,const EnthalpySideView& a,const EnthalpySideView& b,
        ArrayView<const double> k_ss,EnthalpyStateView state,const EnthalpyControl& control,
        const EnthalpyRunState& saved,PhysicalHeatLedger* physical_audit)
    :impl_(std::make_unique<Impl>(grid,a,b,k_ss,state,control,physical_audit,saved)) {}
EnthalpyRun::~EnthalpyRun()=default;
EnthalpyPhase EnthalpyRun::advance() { impl_->advance();return impl_->phase; }
EnthalpyPhase EnthalpyRun::phase() const { return impl_->phase; }
EnthalpyRunState EnthalpyRun::snapshot() const { return impl_->snapshot(); }
EnthalpyResult EnthalpyRun::take_result() { return impl_->take_result(); }

EnthalpyResult solve_enthalpy(const GridView& grid,const EnthalpySideView& a,
                             const EnthalpySideView& b,ArrayView<const double> k_ss,
                             EnthalpyStateView state,const EnthalpyControl& control,
                             PhysicalHeatLedger* physical_audit) {
    EnthalpyRun run(grid,a,b,k_ss,state,control,physical_audit);
    while(run.phase()==EnthalpyPhase::active)run.advance();
    return run.take_result();
}
}  // namespace tpmshx
