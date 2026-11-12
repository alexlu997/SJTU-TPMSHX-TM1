#include <tpmshx/stages.hpp>
#include <cmath>
#include <iostream>

int main() {
    try {
        tpmshx::stages::FlowInput2D input;
        auto& values=input.values.values;
        values.length_m=.182;values.height_m=.042;values.physical_depth_m=.042;
        values.have_physical_depth=1;values.requested_nx=6;values.requested_ny=8;
        values.topology=1;values.cell_length_mm=7.;values.wall_thickness_mm=.6;
        values.solid_conductivity_W_mK=16.;
        values.sides[0].fluid=0;values.sides[0].velocity_m_s=-99.;
        values.sides[0].temperature_K=350.;values.sides[0].pressure_Pa=200000.;
        values.sides[1].fluid=1;values.sides[1].velocity_m_s=-99.;
        values.sides[1].temperature_K=320.;values.sides[1].pressure_Pa=200000.;
        values.sides[1].port.direction=3;
        auto capacities=tpmshx::stages::prepare_inlet_mass_capacities(input);
        input.have_explicit_targets=1;
        input.explicit_targets_kg_s[0]=capacities.view().capacities[0].value*6.;
        input.explicit_targets_kg_s[1]=capacities.view().capacities[1].value*.02;
        auto resolved=tpmshx::stages::resolve_inlet_flow(input);
        tpmshx::stages::PreparationOptions options;options.allow_extrapolation=1;
        auto prepared=tpmshx::stages::prepare_case(input,options);
        const auto& state=prepared.view();
        for (std::size_t i=0;i<2;++i) {
            const auto speed=resolved.view().speeds[i].value;
            if (!std::isfinite(speed) || speed<=0.
                || state.prepared.values.sides[i].inlet.velocity_m_s!=speed
                || state.prepared.values.input.sides[i].have_mass_flow) return 1;
        }
        if (!state.flow.have_capacities || state.prepared.values.owner || state.flow.owner) return 1;
        std::cout<<"Prepared fixed mass flow: "<<state.prepared.values.nx<<" x "
                 <<state.prepared.values.ny<<" cells, speeds "<<resolved.view().speeds[0].value
                 <<" and "<<resolved.view().speeds[1].value<<" m/s\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
