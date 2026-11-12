#include <tpmshx/stages.hpp>
#include <array>
#include <cmath>
#include <iostream>
#include <string>

namespace {
void configure(tpmshx_preparation_case_input_2d_v1& values) {
    values.length_m=1.;values.height_m=2.;values.requested_nx=values.requested_ny=12;
    values.physical_depth_m=static_cast<float>(.042);values.have_physical_depth=1;
    values.topology=1;values.cell_length_mm=7.;values.wall_thickness_mm=.4;values.solid_conductivity_W_mK=16.;
    for (std::size_t i=0;i<2;++i) {
        auto& side=values.sides[i];side.velocity_m_s=-99.;
        side.temperature_K=i?300.:400.;side.pressure_Pa=200000.;side.port.direction=i?3:0;
        side.have_mass_flow=1;side.mass_flow_kg_s=.9;
    }
    auto& port=values.sides[0].port;
    port.inlet_center_m=port.outlet_center_m=1.;
    port.inlet_width_m=port.outlet_width_m=.199951171875;
}
tpmshx_preparation_zone_region_v5 region(double lower,double upper) {
    tpmshx_preparation_zone_region_v5 value{};
    value.bounds[0]={lower,64,0};value.bounds[1]={upper,64,0};
    value.bounds[2]={0.,64,0};value.bounds[3]={1.,64,0};
    value.cell_length_mm=7.;value.wall_thickness_mm=.4;value.cell_kind=value.wall_kind={64,0,0};
    return value;
}
void check(bool accepted) {
    if (!accepted) throw std::runtime_error("spatial flow contract failed");
}
void check_prepared(const tpmshx_preparation_zoned_case_2d_v5& state,
                    const tpmshx_preparation_flow_2d_v3& flow,
                    const tpmshx_preparation_flow_2d_v3& resolved) {
    const auto& base=state.prepared.values;
    check(!state.owner && !base.owner && !flow.owner && flow.have_capacities);
    check(state.cell_count==base.nx*base.ny && state.thermal_porosity.size==state.cell_count);
    check(base.sides[0].row_permeability.size==base.nx && base.sides[1].row_permeability.size==base.ny);
    check(base.sides[0].inlet_bounds[0]==.89990234375 && base.sides[0].inlet_bounds[1]==1.099609375);
    for (std::size_t cell=0;cell<state.cell_count;++cell) {
        check(state.thermal_porosity.data[cell]>0. && state.thermal_porosity.data[cell]<1.);
        check(std::isfinite(state.area_density_per_m.data[cell]) && state.area_density_per_m.data[cell]>0.);
    }
    for (std::size_t i=0;i<2;++i) {
        check(flow.capacities[i].value==resolved.capacities[i].value);
        check(base.sides[i].inlet.velocity_m_s==resolved.speeds[i].value);
        check(!base.input.sides[i].have_mass_flow && !flow.input.values.sides[i].have_mass_flow);
        check(state.volumetric_transfer[i].size==state.cell_count);
        for (std::size_t row=0;row<base.sides[i].row_permeability.size;++row)
            check(std::isfinite(base.sides[i].row_permeability.data[row]) && base.sides[i].row_permeability.data[row]>0.);
        for (std::size_t cell=0;cell<state.cell_count;++cell)
            check(std::isfinite(state.volumetric_transfer[i].data[cell]) && state.volumetric_transfer[i].data[cell]>0.);
    }
}
}

int main() {
    try {
        using namespace tpmshx::stages;
        GridKinds2D grid;grid.lengths[0]={8,2,1};grid.lengths[1]={16,2,1};
        grid.ports[0][0]=grid.ports[0][2]={8,2,1};
        grid.ports[0][1]=grid.ports[0][3]={16,1,1};
        PreparationOptions options;options.allow_extrapolation=1;
        std::array<double,2> zone_targets{},sigmoid_targets{};
        auto zones=[&] {
            ZonedFlowInput2D input;configure(input.values.values.values);
            input.physical_depth_kind={32,1,1};
            char name[]="first";
            std::array<tpmshx_preparation_zone_region_v5,2> regions{{region(0.,.41),region(.41,1.)}};
            regions[0].name={name,5};regions[1].cell_length_mm=6.;regions[1].wall_thickness_mm=.5;
            input.values.regions=regions.data();input.values.region_count=regions.size();
            auto capacity=prepare_inlet_mass_capacities(input,grid,options);
            check(capacity.view().input.regions!=regions.data() && capacity.view().flow.have_capacities);
            name[0]='X';regions[0].cell_length_mm=-1.;
            const auto copied=capacity.view().input.regions[0];
            check(std::string(copied.name.data,copied.name.size)=="first" && copied.cell_length_mm==7.);
            input.values=capacity.view().input;input.have_explicit_targets=1;
            for (std::size_t i=0;i<2;++i)
                input.explicit_targets_kg_s[i]=zone_targets[i]=capacity.view().flow.capacities[i].value*(i?6.:8.);
            return resolve_inlet_flow(input,grid,options);
        }();
        ZonedFlowInput2D zone_input;zone_input.values=zones.view().input;
        zone_input.physical_depth_kind={32,1,1};zone_input.have_explicit_targets=1;
        std::copy(zone_targets.begin(),zone_targets.end(),zone_input.explicit_targets_kg_s);
        auto zone_prepared=prepare_case(zone_input,grid,options);
        check(zone_prepared.view().owner && !zone_prepared.view().flow.owner && zone_prepared.view().prepared.region_count==2);
        check_prepared(zone_prepared.view().prepared,zone_prepared.view().flow.flow,zones.view().flow);

        auto sigmoid=[&] {
            SigmoidFlowInput2D input;configure(input.values.values.values.values);
            input.physical_depth_kind={32,1,1};
            auto bounds=region(0.,1.);char name[]="grid";bounds.name={name,4};
            input.values.values.regions=&bounds;input.values.values.region_count=1;
            std::array<double,36> decisions{};
            for (std::size_t i=0;i<18;++i) {decisions[2*i]=7.;decisions[2*i+1]=.4;}
            input.values.controls.decision_mm={decisions.data(),decisions.size()};
            auto lut=build_sigmoid_lut(1,2,2,16);input.values.lut=lut.view().values;
            auto capacity=prepare_inlet_mass_capacities(input,grid,options);
            check(capacity.view().input.controls.decision_mm.data!=decisions.data());
            check(capacity.view().input.lut.porosity.data!=lut.view().values.porosity.data);
            decisions[0]=-1.;name[0]='X';
            check(capacity.view().input.controls.decision_mm.data[0]==7.);
            const auto copied=capacity.view().input.values.regions[0].name;
            check(std::string(copied.data,copied.size)=="grid");
            input.values=capacity.view().input;input.have_explicit_targets=1;
            for (std::size_t i=0;i<2;++i)
                input.explicit_targets_kg_s[i]=sigmoid_targets[i]=capacity.view().flow.capacities[i].value*(i?6.:8.);
            return resolve_inlet_flow(input,grid,options);
        }();
        SigmoidFlowInput2D sigmoid_input;sigmoid_input.values=sigmoid.view().input;
        sigmoid_input.physical_depth_kind={32,1,1};sigmoid_input.have_explicit_targets=1;
        std::copy(sigmoid_targets.begin(),sigmoid_targets.end(),sigmoid_input.explicit_targets_kg_s);
        auto sigmoid_prepared=prepare_case(sigmoid_input,grid,options);
        const auto& state=sigmoid_prepared.view();
        check(state.owner && !state.prepared.owner && !state.flow.owner && state.prepared.values.kind==2);
        check_prepared(state.prepared.values,state.flow.flow,sigmoid.view().flow);
        std::cout<<"Prepared spatial fixed flow: "<<state.prepared.values.cell_count
                 <<" cells; stripe capacity "<<zones.view().flow.capacities[0].value
                 <<", sigmoid capacity "<<sigmoid.view().flow.capacities[0].value
                 <<" kg s^-1 per m s^-1; speeds "<<sigmoid.view().flow.speeds[0].value
                 <<" and "<<sigmoid.view().flow.speeds[1].value<<" m/s\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
