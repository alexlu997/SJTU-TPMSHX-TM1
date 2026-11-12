#include <tpmshx/stages.hpp>
#include <array>
#include <iostream>

int main() {
    try {
        tpmshx::stages::SigmoidInput2D input;
        auto& values=input.values.values.values;
        values.length_m=.06;values.height_m=.03;values.requested_nx=8;values.requested_ny=6;
        values.topology=1;values.cell_length_mm=7.;values.wall_thickness_mm=.4;values.solid_conductivity_W_mK=16.;
        for (std::size_t i=0;i<2;++i) {
            values.sides[i].velocity_m_s=i?6.:8.;values.sides[i].temperature_K=i?300.:450.;
            values.sides[i].pressure_Pa=i?120000.:200000.;values.sides[i].port.direction=i?3:0;
        }
        tpmshx_preparation_zone_region_v5 region{};
        region.bounds[0]=region.bounds[2]={0.,64,0};region.bounds[1]=region.bounds[3]={1.,64,0};
        region.cell_length_mm=7.;region.wall_thickness_mm=.4;region.cell_kind=region.wall_kind={64,0,0};
        input.values.regions=&region;input.values.region_count=1;
        std::array<double,36> decisions;
        for (std::size_t i=0;i<18;++i) {decisions[2*i]=6.+double(i%3)*.5;decisions[2*i+1]=.35+double(i%4)*.05;}
        input.controls.decision_mm={decisions.data(),decisions.size()};
        auto lut=tpmshx::stages::build_sigmoid_lut(values.topology);
        input.lut=lut.view().values;
        tpmshx::stages::PreparationOptions options;options.allow_extrapolation=1;
        auto prepared=tpmshx::stages::prepare_case(input,options);
        const auto& state=prepared.view();const auto& fields=state.values;const auto& base=fields.prepared.values;
        if (!state.owner || fields.owner || base.owner || fields.region_count || fields.kind!=2
            || fields.cell_count!=48 || fields.thermal_porosity.size!=48
            || base.sides[0].row_permeability.size!=base.nx || base.sides[0].permeability.size) return 1;
        auto repeated=tpmshx::stages::prepare_case(input,options);
        const auto& next=repeated.view().values;
        for (std::size_t i=0;i<fields.cell_count;++i)
            if (fields.volumetric_transfer[0].data[i]!=next.volumetric_transfer[0].data[i]) return 1;
        std::cout<<"Prepared native sigmoid with a 41 x 31, N=256 LUT: "<<base.nx<<" x "<<base.ny<<" cells\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
