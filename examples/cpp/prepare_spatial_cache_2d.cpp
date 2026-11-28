#include <tpmshx/stages.hpp>
#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>
#include <stdexcept>

namespace {
void check(bool accepted) {
    if (!accepted) throw std::runtime_error("spatial cache contract failed");
}
void configure(tpmshx_preparation_case_input_2d_v1& value) {
    value.length_m=.182;value.height_m=.042;value.requested_nx=12;value.requested_ny=16;
    value.have_physical_depth=1;value.physical_depth_m=.042;
    value.topology=1;value.cell_length_mm=7.;value.wall_thickness_mm=.4;value.solid_conductivity_W_mK=16.;
    for (std::size_t i=0;i<2;++i) {
        auto& side=value.sides[i];side.velocity_m_s=-99.;side.temperature_K=i?300.:400.;
        side.pressure_Pa=200000.;side.port.direction=static_cast<std::int32_t>(i);
    }
}
tpmshx_preparation_zone_region_v5 region(double lower,double upper,double cell) {
    tpmshx_preparation_zone_region_v5 value{};
    value.bounds[0]=lower;value.bounds[1]=upper;
    value.bounds[2]=0.;value.bounds[3]=1.;
    value.cell_length_mm=cell;value.wall_thickness_mm=.4;return value;
}
template<class CaseView> void check_prepared(const CaseView& state) {
    check(state.owner!=nullptr);
    check(state.design_pore_porosity.size==state.cell_count && state.cell_count==state.prepared.nx*state.prepared.ny);
    for (std::size_t i=0;i<state.cell_count;++i) {
        check(state.design_pore_porosity.data[i]>0. && state.design_pore_porosity.data[i]<.5);
        check(std::isfinite(state.volumetric_transfer[0].data[i]) && state.volumetric_transfer[0].data[i]>0.);
    }
    check(std::abs(state.flow.speeds[0]-8.)<1e-12 && std::abs(state.flow.speeds[1]-6.)<1e-12);
}
}
int main() {
    try {
        using namespace tpmshx::stages;
        PreparationOptions options;options.allow_extrapolation=1;
        std::array<double,2> zone_targets{},sigmoid_targets{};
        auto zones=[&] {
            ZonedFlowInput2D input;configure(input.input);
            input.model.solid_conductivity_W_mK=input.input.solid_conductivity_W_mK;
            std::array<tpmshx_preparation_zone_region_v5,2> regions{{region(0.,.4,7.),region(.4,1.,6.)}};
            input.regions=regions.data();input.region_count=regions.size();
            auto capacity=prepare_inlet_mass_capacities(input,options);
            check(capacity.view().owner!=nullptr);
            input.input=capacity.view().flow.input;
            input.regions=capacity.view().regions;input.region_count=capacity.view().region_count;
            input.have_explicit_targets=1;
            for (std::size_t i=0;i<2;++i)
                input.explicit_targets_kg_s[i]=zone_targets[i]=capacity.view().flow.capacities[i]*(i?6.:8.);
            return resolve_inlet_flow(input,options);
        }();
        ZonedFlowInput2D zone_input;
        zone_input.input=zones.view().flow.input;
        zone_input.kind=zones.view().kind;zone_input.axis=zones.view().axis;
        zone_input.regions=zones.view().regions;zone_input.region_count=zones.view().region_count;
        zone_input.model=zones.view().model;zone_input.have_explicit_targets=1;
        std::copy(zone_targets.begin(),zone_targets.end(),zone_input.explicit_targets_kg_s);
        auto zone_result=prepare_case(zone_input,options);
        check_prepared(zone_result.view());
        tpmshx_preparation_cache_info_v1 info{};
        char error[256]{};
        check(!tpmshx_preparation_read_cache_info_v1(TPMSHX_PREPARATION_CACHE_INLET,&info,error,sizeof(error)));
        check(info.currsize && info.misses);

        auto sigmoid=[&] {
            SigmoidFlowInput2D input;configure(input.input);
            input.model.solid_conductivity_W_mK=input.input.solid_conductivity_W_mK;
            input.model.load_default_lut=0;
            auto bounds=region(0.,1.,7.);
            input.regions=&bounds;input.region_count=1;
            std::array<double,36> controls{};
            for (std::size_t i=0;i<18;++i) {controls[2*i]=7.;controls[2*i+1]=.4;}
            input.controls.decision_mm={controls.data(),controls.size()};
            auto table=build_sigmoid_lut(1,2,2,16);
            input.lut={table.view().cell_mm,table.view().wall_mm,table.view().porosity,
                table.view().area_density_per_m,table.view().porosity_fast,table.view().area_fast};
            auto capacity=prepare_inlet_mass_capacities(input,options);
            input.input=capacity.view().flow.input;
            input.regions=capacity.view().regions;input.region_count=capacity.view().region_count;
            input.controls=capacity.view().controls;input.lut=capacity.view().lut;
            input.have_explicit_targets=1;
            for (std::size_t i=0;i<2;++i)
                input.explicit_targets_kg_s[i]=sigmoid_targets[i]=capacity.view().flow.capacities[i]*(i?6.:8.);
            return resolve_inlet_flow(input,options);
        }();
        check(sigmoid.view().lut.porosity.size==4);
        SigmoidFlowInput2D sigmoid_input;
        sigmoid_input.input=sigmoid.view().flow.input;
        sigmoid_input.kind=sigmoid.view().kind;sigmoid_input.axis=sigmoid.view().axis;
        sigmoid_input.regions=sigmoid.view().regions;sigmoid_input.region_count=sigmoid.view().region_count;
        sigmoid_input.controls=sigmoid.view().controls;sigmoid_input.lut=sigmoid.view().lut;
        sigmoid_input.model=sigmoid.view().model;sigmoid_input.model.load_default_lut=0;
        sigmoid_input.have_explicit_targets=1;
        std::copy(sigmoid_targets.begin(),sigmoid_targets.end(),sigmoid_input.explicit_targets_kg_s);
        auto sigmoid_result=prepare_case(sigmoid_input,options);
        check_prepared(sigmoid_result.view());
        std::cout<<"Prepared spatial cases with "<<info.currsize<<" cached inlets\n";
        return 0;
    } catch (const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
