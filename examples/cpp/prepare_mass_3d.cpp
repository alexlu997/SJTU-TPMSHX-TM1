#include <tpmshx/stages.hpp>
#include <cmath>
#include <iostream>

int main() {
    try {
        tpmshx::stages::FlowInput3D input;
        auto& values=input.input;
        values.lengths_m[0].value=.182;values.lengths_m[1].value=.042;values.lengths_m[2].value=.031;
        values.counts[0]=6;values.counts[1]=5;values.counts[2]=4;
        values.topology=1;values.cell_length_mm=7.;values.wall_thickness_mm=.6;
        values.solid_conductivity_W_mK=16.;
        values.sides[0].fluid=3;values.sides[0].velocity_m_s=-99.;
        values.sides[0].temperature_K=400.;values.sides[0].pressure_Pa=8e6;
        values.sides[1].fluid=1;values.sides[1].velocity_m_s=-99.;
        values.sides[1].temperature_K=320.;values.sides[1].pressure_Pa=200000.;
        values.sides[0].port.direction=1;values.sides[1].port.direction=5;
        auto capacities=tpmshx::stages::prepare_inlet_mass_capacities(input);
        input.have_explicit_targets=1;
        input.explicit_targets_kg_s[0]=capacities.view().capacities[0].value*.15;
        input.explicit_targets_kg_s[1]=capacities.view().capacities[1].value*.02;
        auto resolved=tpmshx::stages::resolve_inlet_flow(input);
        tpmshx::stages::PreparationOptions options;options.allow_extrapolation=1;
        auto prepared=tpmshx::stages::prepare_case(input,options);
        const auto& state=prepared.view();
        if (!state.flow.have_capacities || state.prepared.owner || state.flow.owner
            || state.prepared.cell_length.size!=120 || !state.prepared.sides[1].axes[6]) return 1;
        for (std::size_t i=0;i<2;++i) {
            const auto speed=resolved.view().speeds[i].value;
            if (!std::isfinite(speed) || speed<=0. || state.prepared.input.sides[i].velocity_m_s!=speed
                || state.prepared.input.sides[i].have_mass_flow) return 1;
        }
        std::cout<<"Prepared 3D CO2/water total flows at "<<resolved.view().speeds[0].value
                 <<" and "<<resolved.view().speeds[1].value<<" m/s\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
