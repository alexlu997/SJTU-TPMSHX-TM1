#include <tpmshx/stages.hpp>
#include <cmath>
#include <iostream>

int main() {
    try {
        tpmshx::stages::ContinuousInput3D input;
        auto& flow=input.values;auto& values=flow.input;
        values.lengths_m[0].value=.182;values.lengths_m[1].value=.042;values.lengths_m[2].value=.031;
        values.counts[0]=6;values.counts[1]=5;values.counts[2]=4;
        values.topology=1;values.cell_length_mm=7.;values.wall_thickness_mm=.6;
        values.solid_conductivity_W_mK=16.;
        values.sides[0].fluid=0;values.sides[0].velocity_m_s=-99.;
        values.sides[0].temperature_K=350.;values.sides[0].pressure_Pa=200000.;
        values.sides[1].fluid=1;values.sides[1].velocity_m_s=-99.;
        values.sides[1].temperature_K=320.;values.sides[1].pressure_Pa=200000.;
        values.sides[0].port.direction=1;values.sides[1].port.direction=5;
        const double xy[]{4.5,6.,7.5,5.4,.31,.42,.59,.36};
        const double xyz[]{4.5,5.,6.,6.5,7.5,7.,5.4,5.8,.31,.32,.42,.45,.59,.56,.36,.38};
        tpmshx::stages::PreparationOptions options;options.allow_extrapolation=1;
        for (unsigned dimension=2;dimension<=3;++dimension) {
            input.controls={2,2,dimension==3?2u:1u,dimension==3?1u:0u,1,0,
                {4.,8.},{.3,.6},{dimension==3?xyz:xy,dimension==3?16u:8u}};
            auto capacities=tpmshx::stages::prepare_inlet_mass_capacities(input);
            flow.have_explicit_targets=1;
            flow.explicit_targets_kg_s[0]=capacities.view().flow.capacities[0].value*6.;
            flow.explicit_targets_kg_s[1]=capacities.view().flow.capacities[1].value*.02;
            auto resolved=tpmshx::stages::resolve_inlet_flow(input);
            auto prepared=tpmshx::stages::prepare_case(input,options);
            const auto& state=prepared.view();
            if (!state.flow.have_capacities || state.prepared.owner || state.flow.owner
                || state.area_density_per_m.size!=120 || state.hydraulic_diameter_m.size!=120
                || state.thermal_porosity.size!=120 || state.controls.decision_mm.data==input.controls.decision_mm.data) return 1;
            for (std::size_t i=0;i<2;++i) {
                const auto speed=resolved.view().flow.speeds[i].value;
                if (!std::isfinite(speed) || speed<=0. || state.prepared.input.sides[i].velocity_m_s!=speed
                    || state.prepared.input.sides[i].have_mass_flow) return 1;
            }
            std::cout<<"Prepared continuous "<<dimension<<"-axis controls on 6 x 5 x 4 cells\n";
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
