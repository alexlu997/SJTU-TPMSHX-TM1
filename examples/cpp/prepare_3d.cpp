#include <tpmshx/stages.hpp>
#include <cmath>
#include <iostream>

int main() {
    try {
        tpmshx::stages::CaseInput3D input;
        input.lengths_m[0].value=.182;input.lengths_m[1].value=.042;input.lengths_m[2].value=.031;
        input.counts[0]=6;input.counts[1]=5;input.counts[2]=4;
        input.topology=1;input.cell_length_mm=7.;input.wall_thickness_mm=.6;
        input.solid_conductivity_W_mK=16.;
        input.sides[0].fluid=3;input.sides[0].velocity_m_s=.15;
        input.sides[0].temperature_K=400.;input.sides[0].pressure_Pa=8e6;
        input.sides[1].fluid=1;input.sides[1].velocity_m_s=.02;
        input.sides[1].temperature_K=320.;input.sides[1].pressure_Pa=200000.;
        input.sides[1].port.direction=5;
        tpmshx::stages::PreparationOptions options;options.allow_extrapolation=1;
        auto prepared=tpmshx::stages::prepare_case(input,options);
        const auto& state=prepared.view();
        if (state.cell_length.size!=120 || state.widths[0].size!=6 || state.widths[1].size!=5
            || state.widths[2].size!=4 || state.sides[1].inlet_opening.size!=30
            || state.sides[1].axes[1]!=2 || !state.sides[1].axes[6]
            || !state.co2.active || !state.co2.sides[0] || state.co2.sides[1]
            || !state.sides[0].have_drag_application || state.sides[1].have_drag_application
            || state.sides[0].drag_evidence.scale_forchheimer!=2.5
            || !std::isfinite(state.permeability.data[0]) || state.sides[1].rho<900.) return 1;
        std::cout<<"Prepared 3D CO2/water: "<<state.widths[0].size<<" x "<<state.widths[1].size
                 <<" x "<<state.widths[2].size<<" cells\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
