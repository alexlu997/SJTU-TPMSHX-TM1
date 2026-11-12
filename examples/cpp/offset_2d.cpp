#include <tpmshx/stages.hpp>
#include <array>
#include <iostream>

namespace {
void configure(tpmshx_preparation_case_input_2d_v1& values) {
    values.length_m=.06;values.height_m=.03;values.requested_nx=8;values.requested_ny=6;
    values.topology=1;values.cell_length_mm=7.;values.wall_thickness_mm=.4;
    values.solid_conductivity_W_mK=16.;values.delta_levelset=.1;
    for (std::size_t side=0;side<2;++side) {
        values.sides[side].velocity_m_s=side?6.:8.;
        values.sides[side].temperature_K=side?300.:450.;
        values.sides[side].pressure_Pa=side?120000.:200000.;
        values.sides[side].port.direction=side?3:0;
    }
}
tpmshx_preparation_zone_region_v5 region(double x0,double x1,double y0,double y1,double cell,double wall) {
    tpmshx_preparation_zone_region_v5 value{};
    value.bounds[0]={x0,64,0};value.bounds[1]={x1,64,0};
    value.bounds[2]={y0,64,0};value.bounds[3]={y1,64,0};
    value.cell_length_mm=cell;value.wall_thickness_mm=wall;
    value.cell_kind=value.wall_kind={64,0,0};return value;
}
template<class Input> void execute(const Input& input,const char* name) {
    using namespace tpmshx::stages;
    PreparationOptions options;options.allow_extrapolation=1;
    RunControl control;control.result_id=name;control.cpu_threads=2;
    auto prepared=prepare_offset_case(input,{},options);
    if (!prepared.view().thermal.have_side_geometry)
        throw std::runtime_error("offset thermal sides are missing");
    auto result=run_case(prepared,control);
    auto performance=evaluate(result);
    std::cout<<name<<": "<<performance.view().json<<'\n';
    if (!result.view().raw.converged) throw std::runtime_error("offset run did not converge");
}
}

int main() {
    using namespace tpmshx::stages;
    try {
        FlowInput2D uniform;configure(uniform.values.values);
        execute(uniform,"native-offset-uniform");

        ZonedFlowInput2Dv9 zoned;configure(zoned.values.values.values.values);
        std::array<tpmshx_preparation_zone_region_v5,2> stripes{{
            region(0.,.4,0.,1.,7.,.4),region(.4,1.,0.,1.,6.,.5)}};
        zoned.values.values.regions=stripes.data();zoned.values.values.region_count=stripes.size();
        execute(zoned,"native-offset-stripes");

        std::array<tpmshx_preparation_zone_region_v5,4> cells{{
            region(0.,.4,0.,.5,7.,.4),region(.4,1.,0.,.5,6.,.5),
            region(0.,.4,.5,1.,6.5,.45),region(.4,1.,.5,1.,7.5,.35)}};
        zoned.values.values.kind=1;
        zoned.values.values.regions=cells.data();zoned.values.values.region_count=cells.size();
        execute(zoned,"native-offset-grid");

        SigmoidFlowInput2Dv9 sigmoid;configure(sigmoid.values.values.values.values.values);
        auto bounds=region(0.,1.,0.,1.,7.,.4);
        sigmoid.values.values.values.regions=&bounds;sigmoid.values.values.values.region_count=1;
        std::array<double,36> decisions{};
        for (std::size_t i=0;i<18;++i) {decisions[2*i]=6.+double(i%3)*.5;decisions[2*i+1]=.35+double(i%4)*.05;}
        sigmoid.values.values.controls.decision_mm={decisions.data(),decisions.size()};
        // A small native LUT keeps this SDK smoke test short.
        auto lut=build_sigmoid_lut(1,2,2,16);
        sigmoid.values.values.lut=lut.view().values;
        execute(sigmoid,"native-offset-sigmoid");
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
