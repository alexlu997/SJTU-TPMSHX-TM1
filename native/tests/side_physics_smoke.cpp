#include "tpmshx/full_2d.hpp"
#include "tpmshx/full_3d.hpp"

#include <stdexcept>

using namespace tpmshx;

void require(bool value) {
    if(!value) throw std::runtime_error("resolved side physics does not preserve its route");
}

int main() {
    const std::array<Fluid,4> fluids{Fluid::air,Fluid::water,Fluid::sco2,Fluid::co2};
    for(auto a:fluids) for(auto b:fluids) {
        Full2DProblem planar{};planar.sides[0].fluid=a;planar.sides[1].fluid=b;
        planar.thermal_mode=Full2DThermalMode::true_h;
        const auto eos=resolve_full_2d_physics(planar);
        for(std::size_t side=0;side<2;++side) {
            const auto fluid=side?b:a;const auto& selected=eos[side];
            require(selected.transport_fluid==fluid);
            require(selected.energy==EnergyRelation::eos_h_TP);
            require(selected.conductivity==ConductivitySource::local_eos);
            require(selected.local_heat_transfer()==uses_co2_eos(fluid));
            if(!uses_co2_eos(fluid))
                require(selected.heat_transfer==HeatTransferSampling::thermal_mean_at_inlet_pressure);
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
        const auto ordinary=co2?EnergyRelation::eos_h_TP:
            a==Fluid::water && b==Fluid::water?EnergyRelation::capacity_temperature:EnergyRelation::integral_cp_T;
        for(std::size_t side=0;side<2;++side) {
            const auto fluid=side?b:a;const auto& physics=selected[side];
            require(physics.energy==ordinary);
            require(physics.conductivity==(co2?ConductivitySource::local_eos:ConductivitySource::outer_transport));
            require(!physics.local_heat_transfer(false));
            require(physics.local_heat_transfer(true)==uses_co2_eos(fluid));
        }
        if(co2) continue;
        spatial.geometry.asymmetric=true;
        for(const auto& physics:resolve_full_3d_physics(spatial,control))
            require(physics.energy==EnergyRelation::capacity_temperature);
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
