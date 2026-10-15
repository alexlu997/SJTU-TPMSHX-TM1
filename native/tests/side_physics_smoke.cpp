#include "tpmshx/full_2d.hpp"
#include "tpmshx/full_3d.hpp"

#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>

using namespace tpmshx;

void require_at(bool value,int line) {
    if(!value) throw std::runtime_error("side physics check failed at line "+std::to_string(line));
}
#define require(value) require_at((value),__LINE__)

void energy_model_cases() {
    EnthalpyEOS energy;
    PropertyEvaluator transport;
    for(auto fluid:{Fluid::air,Fluid::water}) {
        const auto model=EnergyRelation::integral_cp_T;
        const std::array<double,6> temperatures=fluid==Fluid::air
            ?std::array<double,6>{225.,250.,300.,500.,1000.,1100.}
            :std::array<double,6>{280.,300.,320.,340.,360.,363.15};
        for(double t:temperatures) {
            const auto reference=energy.evaluate_state(fluid,t,2e6,"model reference",model);
            for(double pressure:{2e5,2e6,8e6}) {
                const auto state=energy.evaluate_state(fluid,t,pressure,"model state",model);
                const auto properties=transport.evaluate(fluid,t,pressure);
                require(state.enthalpy==reference.enthalpy && state.cp==properties.cp
                        && state.conductivity==properties.k);
                bool table_used=false;
                const double restored=energy.temperature(fluid,state.enthalpy,pressure,table_used,"model inverse",model);
                require(std::abs(restored-t)<1e-10 && !table_used);
                const double step=1e-3;
                const double derivative=(energy.bracket_enthalpy(fluid,t+step,pressure,model)
                    -energy.bracket_enthalpy(fluid,t-step,pressure,model))/(2.*step);
                require(std::abs(derivative-state.cp)<1e-7*state.cp);
            }
        }
        // Fused products can leave roundoff at the enthalpy reference.
        require(std::abs(energy.bracket_enthalpy(fluid,300.,2e6,model))<1e-9);
        const auto implicit=energy.evaluate_state(fluid,350.,2e6,"default EOS");
        const auto explicit_eos=energy.evaluate_state(fluid,350.,2e6,"explicit EOS",EnergyRelation::eos_h_TP);
        require(implicit.enthalpy==explicit_eos.enthalpy && implicit.cp==explicit_eos.cp
                && implicit.conductivity==explicit_eos.conductivity);
    }
    bool rejected=false;
    try { energy.evaluate_state(Fluid::water,420.,2e5,"boiling model water",EnergyRelation::integral_cp_T); }
    catch(const WaterStateError&) { rejected=true; }
    require(rejected);
    rejected=false;
    try { energy.evaluate_state(Fluid::co2,350.,8e6,"invalid integral fluid",EnergyRelation::integral_cp_T); }
    catch(const std::invalid_argument&) { rejected=true; }
    require(rejected);
    rejected=false;
    bool table_used=false;
    try { energy.temperature(Fluid::air,std::numeric_limits<double>::infinity(),2e5,table_used,
                             "invalid inverse",EnergyRelation::integral_cp_T); }
    catch(const std::invalid_argument&) { rejected=true; }
    require(rejected);
}

int main() {
    energy_model_cases();
    const std::array<Fluid,4> fluids{Fluid::air,Fluid::water,Fluid::sco2,Fluid::co2};
    for(auto a:fluids) for(auto b:fluids) {
        Full2DProblem planar{};planar.sides[0].fluid=a;planar.sides[1].fluid=b;
        planar.thermal_mode=Full2DThermalMode::true_h;
        const auto eos=resolve_full_2d_physics(planar);
        for(std::size_t side=0;side<2;++side) {
            const auto fluid=side?b:a;const auto& selected=eos[side];
            require(selected.transport_fluid==fluid);
            require(selected.energy==(uses_co2_eos(fluid)?EnergyRelation::eos_h_TP:EnergyRelation::integral_cp_T));
            require(selected.conductivity==(uses_co2_eos(fluid)?ConductivitySource::local_eos:ConductivitySource::prepared));
            require(selected.local_heat_transfer()==uses_co2_eos(fluid));
            if(!uses_co2_eos(fluid))
                require(selected.heat_transfer==HeatTransferSampling::outer_mean_inlet_reference);
        }
        if(!uses_co2_eos(a) && !uses_co2_eos(b))
            for(auto mode:{Full2DThermalMode::model_h,Full2DThermalMode::temperature}) {
                planar.thermal_mode=mode;
                for(const auto& selected:resolve_full_2d_physics(planar)) {
                    require(selected.energy==EnergyRelation::integral_cp_T);
                    require(selected.conductivity==ConductivitySource::prepared);
                    require(selected.heat_transfer==HeatTransferSampling::outer_mean_inlet_reference);
                }
            }

        Full3DInput spatial{};spatial.geometry.grid.nz=2;spatial.a.fluid=a;spatial.b.fluid=b;
        Full3DControl control;
        const bool co2=uses_co2_eos(a)||uses_co2_eos(b);
        const auto selected=resolve_full_3d_physics(spatial,control);
        const auto ordinary=co2?EnergyRelation::eos_h_TP:EnergyRelation::integral_cp_T;
        for(std::size_t side=0;side<2;++side) {
            const auto fluid=side?b:a;const auto& physics=selected[side];
            require(physics.energy==(co2 && !uses_co2_eos(fluid)?EnergyRelation::integral_cp_T:ordinary));
            require(physics.conductivity==(uses_co2_eos(fluid)?ConductivitySource::local_eos:ConductivitySource::outer_transport));
            require(!physics.local_heat_transfer(false));
            require(physics.local_heat_transfer(true)==uses_co2_eos(fluid));
        }
        if(co2) continue;
        spatial.geometry.asymmetric=true;
        for(const auto& physics:resolve_full_3d_physics(spatial,control))
            require(physics.energy==EnergyRelation::integral_cp_T);
        control.conservative=false;
        for(const auto& physics:resolve_full_3d_physics(spatial,control))
            require(physics.energy==EnergyRelation::integral_cp_T);
        control.force_cell_centered=false;
        for(const auto& physics:resolve_full_3d_physics(spatial,control))
            require(physics.energy==EnergyRelation::capacity_temperature);
        spatial.geometry.grid.nz=1;
        for(const auto& physics:resolve_full_3d_physics(spatial,control))
            require(physics.energy==EnergyRelation::integral_cp_T);
    }
    for(auto a:{Fluid::air,Fluid::water,Fluid::sco2}) {
        Full3DInput single{};single.geometry.grid.nz=2;single.a.fluid=a;
        single.b.fluid=Fluid::co2;single.solve_b=false;
        Full3DControl control;control.conservative=false;
        const auto selected=resolve_full_3d_physics(single,control);
        require(selected[0].energy==(a==Fluid::sco2?EnergyRelation::capacity_temperature:EnergyRelation::integral_cp_T));
        require(selected[1].energy==EnergyRelation::prescribed_temperature);
        require(selected[1].conductivity==ConductivitySource::prescribed);
        require(selected[1].heat_transfer==HeatTransferSampling::prescribed);
    }
}
