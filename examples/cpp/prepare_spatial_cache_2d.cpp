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
struct Cache {
    tpmshx_preparation_sigmoid_lut_view_v6 lut{};
    std::size_t geometry_reads{},geometry_writes{},inlet_reads{},inlet_writes{},lut_reads{};
    bool nominal{},spatial{},narrow{};
};
int TPMSHX_PREPARATION_CALL geometry(void* context,std::uint32_t action,
    const tpmshx_preparation_geometry_key_v9* key,tpmshx_preparation_geometry_cache_v3* value,std::uint32_t* hit) {
    auto& cache=*static_cast<Cache*>(context);
    if (key->topology!=1 || !(key->cell_length_mm>0.) || !(key->wall_thickness_mm>0.)) return 1;
    cache.narrow|=key->cell_kind.precision==32 && key->cell_kind.strong==1;
    if (action) {++cache.geometry_writes;if (!(value->epsilon>0. && value->epsilon<1.)) return 1;}
    else {++cache.geometry_reads;*hit=0;}
    return 0;
}
int TPMSHX_PREPARATION_CALL inlet(void* context,std::uint32_t action,
    const tpmshx_preparation_inlet_key_v9* key,tpmshx_preparation_inlet_cache_v3* value,std::uint32_t* hit) {
    auto& cache=*static_cast<Cache*>(context);
    if (key->geometry.topology!=1 || key->fluid || key->velocity_m_s<=0.) return 1;
    cache.nominal|=key->have_sco2_nu==1;cache.spatial|=key->have_sco2_nu==0;
    if (action) {++cache.inlet_writes;if (!(value->properties.rho>0.) || !value->evidence.range_count) return 1;}
    else {++cache.inlet_reads;*hit=0;}
    return 0;
}
int TPMSHX_PREPARATION_CALL lut(void* context,std::uint32_t action,std::uint32_t topology,
    std::size_t resolution,tpmshx_preparation_sigmoid_lut_view_v6* value,std::uint32_t* hit) {
    auto& cache=*static_cast<Cache*>(context);
    if (action || topology!=1 || resolution!=256 || value->cell_mm.size!=41 || value->wall_mm.size!=31) return 1;
    ++cache.lut_reads;*value=cache.lut;*hit=1;return 0;
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
    value.bounds[0]={lower,64,0};value.bounds[1]={upper,64,0};
    value.bounds[2]={0.,64,0};value.bounds[3]={1.,64,0};
    value.cell_length_mm=cell;value.wall_thickness_mm=.4;
    value.cell_kind={32,1,1};value.wall_kind={64,0,0};return value;
}
void prepared(const tpmshx_preparation_zoned_case_2d_v5& state,
    const tpmshx_preparation_flow_2d_v3& flow,const tpmshx_preparation_array_v1& pore) {
    check(!state.owner && !state.prepared.values.owner && !flow.owner);
    check(pore.size==state.cell_count && state.cell_count==state.prepared.values.nx*state.prepared.values.ny);
    for (std::size_t i=0;i<state.cell_count;++i) {
        check(pore.data[i]>0. && pore.data[i]<.5);
        check(std::isfinite(state.volumetric_transfer[0].data[i]) && state.volumetric_transfer[0].data[i]>0.);
    }
    check(std::abs(flow.speeds[0].value-8.)<1e-12 && std::abs(flow.speeds[1].value-6.)<1e-12);
}
}
int main() {
    try {
        using namespace tpmshx::stages;
        Cache cache;
        tpmshx_preparation_case_callbacks_v9 callbacks{};
        callbacks.values.values.values.abi_version=9;
        callbacks.values.values.values.struct_size=sizeof(callbacks);
        callbacks.values.values.values.context=&cache;
        callbacks.geometry_cache_at=geometry;callbacks.inlet_cache_at=inlet;callbacks.sigmoid_lut_cache=lut;
        PreparationOptions options;options.allow_extrapolation=1;
        GridKinds2D grid;
        std::array<double,2> zone_targets{},sigmoid_targets{};
        auto zones=[&] {
            ZonedFlowInput2Dv9 input;configure(input.values.values.values.values);
            input.model.solid_conductivity_kind={64,0,0};
            std::array<tpmshx_preparation_zone_region_v5,2> regions{{region(0.,.4,7.),region(.4,1.,6.)}};
            input.values.values.regions=regions.data();input.values.values.region_count=regions.size();
            auto capacity=prepare_inlet_mass_capacities(input,grid,options,&callbacks);
            check(capacity.view().owner && !capacity.view().values.owner);
            input.values.values=capacity.view().values.input;input.values.have_explicit_targets=1;
            for (std::size_t i=0;i<2;++i)
                input.values.explicit_targets_kg_s[i]=zone_targets[i]=capacity.view().values.flow.capacities[i].value*(i?6.:8.);
            return resolve_inlet_flow(input,grid,options,&callbacks);
        }();
        ZonedFlowInput2Dv9 zone_input;zone_input.values.values=zones.view().values.input;
        zone_input.model=zones.view().model;zone_input.values.have_explicit_targets=1;
        std::copy(zone_targets.begin(),zone_targets.end(),zone_input.values.explicit_targets_kg_s);
        auto zone_result=prepare_case(zone_input,grid,options,&callbacks);
        check(zone_result.view().owner && !zone_result.view().values.owner);
        prepared(zone_result.view().values.prepared,zone_result.view().values.flow.flow,zone_result.view().design_pore_porosity);
        check(cache.nominal && cache.spatial && cache.narrow && cache.geometry_reads && cache.geometry_writes);
        check(cache.inlet_reads && cache.inlet_writes);

        auto sigmoid=[&] {
            SigmoidFlowInput2Dv9 input;configure(input.values.values.values.values.values);
            input.model.solid_conductivity_kind={64,0,0};input.model.load_default_lut=1;
            auto bounds=region(0.,1.,7.);
            input.values.values.values.regions=&bounds;input.values.values.values.region_count=1;
            std::array<double,36> controls{};
            for (std::size_t i=0;i<18;++i) {controls[2*i]=7.;controls[2*i+1]=.4;}
            input.values.values.controls.decision_mm={controls.data(),controls.size()};
            auto table=build_sigmoid_lut(1,2,2,16);cache.lut=table.view().values;
            auto capacity=prepare_inlet_mass_capacities(input,grid,options,&callbacks);
            input.values.values=capacity.view().values.input;input.values.have_explicit_targets=1;
            for (std::size_t i=0;i<2;++i)
                input.values.explicit_targets_kg_s[i]=sigmoid_targets[i]=capacity.view().values.flow.capacities[i].value*(i?6.:8.);
            return resolve_inlet_flow(input,grid,options,&callbacks);
        }();
        cache.lut={};
        check(cache.lut_reads==2 && sigmoid.view().values.input.lut.porosity.size==4);
        SigmoidFlowInput2Dv9 sigmoid_input;sigmoid_input.values.values=sigmoid.view().values.input;
        sigmoid_input.model=sigmoid.view().model;sigmoid_input.model.load_default_lut=0;
        sigmoid_input.values.have_explicit_targets=1;
        std::copy(sigmoid_targets.begin(),sigmoid_targets.end(),sigmoid_input.values.explicit_targets_kg_s);
        auto sigmoid_result=prepare_case(sigmoid_input,grid,options,&callbacks);
        check(sigmoid_result.view().owner && !sigmoid_result.view().values.owner);
        prepared(sigmoid_result.view().values.prepared.values,sigmoid_result.view().values.flow.flow,
            sigmoid_result.view().design_pore_porosity);
        std::cout<<"Prepared v9 spatial cases with "<<cache.geometry_reads<<" geometry reads, "
                 <<cache.inlet_reads<<" inlet reads and "<<cache.lut_reads<<" LUT reads\n";
        return 0;
    } catch (const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
