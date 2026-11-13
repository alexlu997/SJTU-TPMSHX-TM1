#include <tpmshx/stages.hpp>
#include <cmath>
#include <iostream>

int main() {
    try {
        tpmshx::stages::FlowInput2D input;
        auto& values=input.values.values;
        values.length_m=1.;values.height_m=2.;values.physical_depth_m=.042;
        values.have_physical_depth=1;values.requested_nx=values.requested_ny=12;
        values.topology=1;values.cell_length_mm=7.;values.wall_thickness_mm=.6;
        values.solid_conductivity_W_mK=16.;
        for (auto& side:values.sides) {
            side.velocity_m_s=5.;side.temperature_K=350.;side.pressure_Pa=101325.;
        }
        values.sides[1].temperature_K=300.;values.sides[1].port.direction=3;
        auto& port=values.sides[0].port;
        port.inlet_center_m=port.outlet_center_m=1.;
        port.inlet_width_m=port.outlet_width_m=.199951171875;
        tpmshx::stages::GridKinds2D grid;
        grid.lengths[0]={8,2,1};grid.lengths[1]={16,2,1};
        grid.ports[0][0]=grid.ports[0][2]={8,2,1};
        grid.ports[0][1]=grid.ports[0][3]={16,1,1};
        tpmshx::stages::PreparationOptions options;options.allow_extrapolation=1;
        auto capacities=tpmshx::stages::prepare_inlet_mass_capacities(input,grid,options);
        input.have_explicit_targets=1;
        for (std::size_t side=0;side<2;++side)
            input.explicit_targets_kg_s[side]=capacities.view().capacities[side].value*5.;
        auto resolved=tpmshx::stages::resolve_inlet_flow(input,grid,options);
        auto prepared=tpmshx::stages::prepare_case(input,grid,options);
        const auto& state=prepared.view().prepared.values;
        if (state.sides[0].inlet_bounds[0]!=.89990234375
            || state.sides[0].inlet_bounds[1]!=1.099609375) return 1;
        for (std::size_t side=0;side<2;++side)
            if (!std::isfinite(resolved.view().speeds[side].value)
                || resolved.view().speeds[side].value!=state.sides[side].inlet.velocity_m_s) return 1;
        std::cout<<"Prepared typed grid: "<<state.nx<<" x "<<state.ny<<" cells\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
