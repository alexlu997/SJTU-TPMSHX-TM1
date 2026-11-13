#include <tpmshx/stages.hpp>
#include <iostream>

int main() {
    try {
        tpmshx::stages::ZonedInput2D input;
        auto& values=input.values.values;
        values.length_m=.06;values.height_m=.03;values.requested_nx=8;values.requested_ny=6;
        values.topology=1;values.cell_length_mm=7.;values.wall_thickness_mm=.4;values.solid_conductivity_W_mK=16.;
        for (std::size_t i=0;i<2;++i) {
            values.sides[i].velocity_m_s=i?6.:8.;values.sides[i].temperature_K=i?300.:450.;
            values.sides[i].pressure_Pa=i?120000.:200000.;values.sides[i].port.direction=i?3:0;
        }
        tpmshx_preparation_zone_region_v5 regions[2]{};
        const char* names[]{"first","second"};
        for (std::size_t i=0;i<2;++i) {
            regions[i].name={names[i],i?6u:5u};
            for (auto& bound:regions[i].bounds) bound={0.,64,0};
            regions[i].bounds[0].value=i?.41:0.;regions[i].bounds[1].value=i?1.:.41;
            regions[i].cell_length_mm=i?6.:7.;regions[i].wall_thickness_mm=i?.5:.4;
            regions[i].cell_kind=regions[i].wall_kind={64,0,0};
        }
        input.regions=regions;input.region_count=2;
        tpmshx::stages::PreparationOptions options;options.allow_extrapolation=1;
        auto prepared=tpmshx::stages::prepare_case(input,options);
        const auto& state=prepared.view();const auto& base=state.prepared.values;
        if (!state.owner || base.owner || state.region_count!=2 || state.cell_count!=48
            || state.volumetric_transfer[0].size!=state.cell_count
            || base.sides[0].row_permeability.size!=base.nx
            || base.sides[1].row_permeability.size!=base.ny) return 1;
        values.length_m=1.;values.height_m=2.;values.requested_nx=values.requested_ny=12;
        auto& port=values.sides[0].port;
        port.inlet_center_m=port.outlet_center_m=1.;
        port.inlet_width_m=port.outlet_width_m=.199951171875;
        tpmshx::stages::GridKinds2D grid;
        grid.lengths[0]={8,2,1};grid.lengths[1]={16,2,1};
        grid.ports[0][0]=grid.ports[0][2]={8,2,1};
        grid.ports[0][1]=grid.ports[0][3]={16,1,1};
        auto typed=tpmshx::stages::prepare_case(input,grid,options);
        const auto& typed_base=typed.view().prepared.values;
        if (typed_base.sides[0].inlet_bounds[0]!=.89990234375
            || typed_base.sides[0].inlet_bounds[1]!=1.099609375) return 1;
        std::cout<<"Prepared native stripes: "<<base.nx<<" x "<<base.ny<<" cells\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
