#include <tpmshx/stages.hpp>
#include <cmath>
#include <iostream>

int main() {
    try {
        tpmshx::stages::SpatialInput3D input;
        auto& flow=input.values;auto& values=flow.input;
        values.lengths_m[0].value=.182;values.lengths_m[1].value=.042;values.lengths_m[2].value=.031;
        values.counts[0]=6;values.counts[1]=5;values.counts[2]=4;
        values.topology=1;values.cell_length_mm=7.;values.wall_thickness_mm=.6;
        values.solid_conductivity_W_mK=16.;values.geometry_mode=2;values.delta_levelset=.15;
        values.sides[0].fluid=0;values.sides[0].velocity_m_s=-99.;
        values.sides[0].temperature_K=350.;values.sides[0].pressure_Pa=200000.;
        values.sides[1].fluid=1;values.sides[1].velocity_m_s=-99.;
        values.sides[1].temperature_K=320.;values.sides[1].pressure_Pa=200000.;
        values.sides[0].port.direction=1;values.sides[1].port.direction=5;
        tpmshx_preparation_grid_cell_3d_v4 cells[]{
            {{{0.,64,0},{.7,64,0},{0.,64,0},{1.,64,0}},4.5,.31},
            {{{.4,64,0},{1.,64,0},{.2,64,0},{.8,64,0}},7.5,.59}};
        input.cells=cells;input.cell_count=2;
        auto capacities=tpmshx::stages::prepare_inlet_mass_capacities(input);
        flow.have_explicit_targets=1;
        flow.explicit_targets_kg_s[0]=capacities.view().flow.capacities[0].value*6.;
        flow.explicit_targets_kg_s[1]=capacities.view().flow.capacities[1].value*.02;
        auto resolved=tpmshx::stages::resolve_inlet_flow(input);
        tpmshx::stages::PreparationOptions options;options.allow_extrapolation=1;
        auto prepared=tpmshx::stages::prepare_case(input,options);
        const auto& state=prepared.view();
        if (!state.flow.have_capacities || state.prepared.owner || state.flow.owner
            || state.cell_count!=2 || state.cells==cells || state.cells[0].cell_length_mm!=4.5
            || state.area_density_per_m.size!=120 || state.hydraulic_diameter_m.size!=120
            || state.thermal_porosity.size!=120 || state.side_b_porosity.size!=120
            || !state.have_side_geometry || !(state.split_a>0. && state.split_a<1.)) return 1;
        for (std::size_t i=0;i<120;++i) {
            const auto total=state.prepared.total_porosity.data[i];
            if (state.prepared.side_porosity.data[i]!=total*state.split_a
                || state.side_b_porosity.data[i]!=total*(1.-state.split_a)) return 1;
        }
        for (std::size_t i=0;i<2;++i) {
            const auto speed=resolved.view().flow.speeds[i].value;
            if (!std::isfinite(speed) || speed<=0. || state.prepared.input.sides[i].velocity_m_s!=speed
                || state.prepared.input.sides[i].have_mass_flow) return 1;
            for (const auto value:state.side_geometry[i]) if (!std::isfinite(value) || value<=0.) return 1;
        }
        cells[0].cell_length_mm=8.;
        if (state.cells[0].cell_length_mm!=4.5 || capacities.view().cells[0].cell_length_mm!=4.5
            || resolved.view().cells[0].cell_length_mm!=4.5) return 1;
        std::cout<<"Prepared asymmetric XY grid zones on 6 x 5 x 4 cells\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
