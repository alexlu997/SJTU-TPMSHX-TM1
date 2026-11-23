#include "tpmshx/preparation_case_3d_c_api.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

#define CHECK(test) do { if (!(test)) { fprintf(stderr, "line %d: %s\n%s\n", __LINE__, #test, error); return 1; } } while (0)

static int TPMSHX_PREPARATION_CALL stop_event(void* context,const tpmshx_preparation_event_v1* event) {
    size_t* count=(size_t*)context;
    if (event) ++*count;
    return 1;
}
int main(void) {
    tpmshx_preparation_case_input_3d_v1 input={0},original;
    tpmshx_preparation_case_failure_v2 failure={0},saved_failure;
    tpmshx_preparation_case_options_v1 options={1,sizeof(options),0,1,0.};
    tpmshx_preparation_case_callbacks_v1 callback={1,sizeof(callback),stop_event,NULL};
    const double dimensions[3]={.182,.042,.031};
    char error[4096]={0},saved_error[4096],source[]="source";
    size_t i,calls=0;
    input.abi_version=1;input.struct_size=sizeof(input);
    failure.abi_version=2;failure.struct_size=sizeof(failure);
    for (i=0;i<3;++i) input.lengths_m[i]=dimensions[i];
    input.counts[0]=6;input.counts[1]=5;input.counts[2]=4;input.max_cells=2000000;
    input.topology=1;input.cell_length_mm=7.;input.wall_thickness_mm=.6;input.solid_conductivity_W_mK=16.;
    for (i=0;i<2;++i) {
        input.sides[i].port.active=1;
        input.sides[i].velocity_m_s=5.;input.sides[i].temperature_K=i?300.:400.;input.sides[i].pressure_Pa=101325.;
    }
    input.sides[1].port.direction=5;input.sides[0].mass_flow_kg_s=123.;
    input.sco2_nu.source.data=source;input.sco2_nu.source.size=strlen(source);original=input;
    CHECK(tpmshx_preparation_host_3d_abi_version_v5()==5);
    {
        /* Uniform preparation uses spatial v4 with geometry_mode 0 and no grid cells. */
        tpmshx_preparation_spatial_input_3d_v4 request={0},saved_request;
        tpmshx_preparation_spatial_flow_3d_v4 flow={0},saved_flow;
        tpmshx_preparation_spatial_case_3d_v4 combined={0},saved_combined;
        request.abi_version=flow.abi_version=combined.abi_version=4;
        request.struct_size=sizeof(request);flow.struct_size=sizeof(flow);combined.struct_size=sizeof(combined);
        request.values.abi_version=2;request.values.struct_size=sizeof(request.values);
        request.values.input=original;
        saved_request=request;
        CHECK(!tpmshx_prepare_flow_case_3d_v4(&request,&options,NULL,&combined,&failure,error,sizeof(error)));
        CHECK(!failure.kind && combined.owner && !combined.prepared.owner && !combined.flow.owner && !combined.cell_count);
        CHECK(!memcmp(&request,&saved_request,sizeof(request)) && !memcmp(&request.values.input,&original,sizeof(original)));
        CHECK(combined.prepared.cell_length.size==120 && combined.prepared.sides[1].inlet_opening.size==30);
        CHECK(combined.prepared.sides[1].axes[6]==1 && isfinite(combined.prepared.solid_conductivity.data[0]));
        CHECK(combined.prepared.geometry.epsilon_a==combined.prepared.side_porosity.data[0]);
        CHECK(combined.split_a==.5 && !combined.have_side_geometry);
        CHECK(!combined.area_density_per_m.size && !combined.hydraulic_diameter_m.size && !combined.thermal_porosity.size);
        CHECK(!combined.prepared.input.sides[0].have_mass_flow);
        CHECK(combined.prepared.input.sco2_nu.source.data!=source);source[0]='X';
        CHECK(!memcmp(combined.prepared.input.sco2_nu.source.data,"source",6));saved_combined=combined;
        CHECK(tpmshx_prepare_flow_case_3d_v4(&request,&options,NULL,&combined,&failure,error,sizeof(error))==1);
        CHECK(!memcmp(&combined,&saved_combined,sizeof(combined)));
        tpmshx_preparation_spatial_case_3d_release_v4(&combined);CHECK(!combined.owner && !combined.struct_size);
        tpmshx_preparation_spatial_case_3d_release_v4(&combined);tpmshx_preparation_spatial_case_3d_release_v4(NULL);
        combined.abi_version=4;combined.struct_size=sizeof(combined);saved_combined=combined;
        request.values.input.sides[0].velocity_m_s=1e-9;callback.context=&calls;
        CHECK(tpmshx_prepare_flow_case_3d_v4(&request,&options,&callback,&combined,&failure,error,sizeof(error))==3);
        CHECK(calls==1 && failure.kind==3 && !memcmp(&saved_combined,&combined,sizeof(combined)));
        request=saved_request;request.values.input.max_cells=119;
        CHECK(tpmshx_prepare_flow_case_3d_v4(&request,&options,NULL,&combined,&failure,error,sizeof(error))==1);
        CHECK(strstr(error,"3D grid 6x5x4 exceeds the 119-cell cap") && !memcmp(&saved_combined,&combined,sizeof(combined)));
        memset(error,17,sizeof(error));memcpy(saved_error,error,sizeof(error));saved_failure=failure;
        CHECK(tpmshx_prepare_flow_case_3d_v4(&request,&options,NULL,&combined,
            (tpmshx_preparation_case_failure_v2*)&combined,error,sizeof(error))==1);
        CHECK(!memcmp(&saved_combined,&combined,sizeof(combined)) && !memcmp(error,saved_error,sizeof(error)));
        CHECK(!memcmp(&failure,&saved_failure,sizeof(failure)));
        request=saved_request;request.values.input.sides[0].velocity_m_s=NAN;request.values.input.sides[1].velocity_m_s=-99.;
        saved_request=request;
        CHECK(!tpmshx_prepare_inlet_mass_capacities_3d_v4(&request,&options,NULL,&flow,&failure,error,sizeof(error)));
        CHECK(flow.owner && !flow.flow.owner && flow.flow.have_capacities && !flow.cell_count);
        CHECK(!memcmp(&request,&saved_request,sizeof(request)));
        CHECK(flow.flow.capacities[0]>0. && flow.flow.capacities[1]>0.);
        request.values.have_explicit_targets=1;
        for (i=0;i<2;++i) {
            request.values.explicit_targets_kg_s[i]=flow.flow.capacities[i]*5.;
            request.values.input.sides[i].have_mass_flow=1;request.values.input.sides[i].mass_flow_kg_s=-1.;
        }
        tpmshx_preparation_spatial_flow_3d_release_v4(&flow);CHECK(!flow.owner && !flow.struct_size);
        flow.abi_version=4;flow.struct_size=sizeof(flow);
        CHECK(!tpmshx_resolve_inlet_flow_3d_v4(&request,&options,NULL,&flow,&failure,error,sizeof(error)));
        CHECK(!tpmshx_prepare_flow_case_3d_v4(&request,&options,NULL,&combined,&failure,error,sizeof(error)));
        CHECK(combined.owner && !combined.flow.owner && !combined.prepared.owner && combined.prepared.cell_length.size==120);
        for (i=0;i<2;++i) {
            CHECK(combined.prepared.input.sides[i].velocity_m_s==flow.flow.speeds[i]);
            CHECK(!combined.prepared.input.sides[i].have_mass_flow && !combined.flow.input.sides[i].have_mass_flow);
        }
        tpmshx_preparation_spatial_case_3d_release_v4(&combined);
        tpmshx_preparation_spatial_flow_3d_release_v4(&flow);tpmshx_preparation_spatial_flow_3d_release_v4(NULL);
        flow.abi_version=4;flow.struct_size=sizeof(flow);saved_flow=flow;
        request=saved_request;request.values.input.lengths_m[0]=-1.;
        CHECK(!tpmshx_resolve_inlet_flow_3d_v4(&request,&options,NULL,&flow,&failure,error,sizeof(error)));
        CHECK(!flow.flow.have_capacities && flow.flow.input.lengths_m[0]==-1.);
        CHECK(isnan(flow.flow.input.sides[0].velocity_m_s) && flow.flow.input.sco2_nu.source.data!=source);
        tpmshx_preparation_spatial_flow_3d_release_v4(&flow);flow=saved_flow;
        request=saved_request;request.values.have_explicit_targets=1;request.values.explicit_targets_kg_s[0]=-1.;
        CHECK(tpmshx_resolve_inlet_flow_3d_v4(&request,&options,NULL,&flow,&failure,error,sizeof(error))==1);
        CHECK(strstr(error,"mass_flow_A_kg_s") && !memcmp(&flow,&saved_flow,sizeof(flow)));
        saved_request=request;saved_failure=failure;
        CHECK(tpmshx_resolve_inlet_flow_3d_v4(&request,&options,NULL,&flow,&failure,
            (char*)&request,sizeof(request))==1);
        CHECK(!memcmp(&request,&saved_request,sizeof(request)) && !memcmp(&failure,&saved_failure,sizeof(failure)));
        CHECK(!memcmp(&flow,&saved_flow,sizeof(flow)));
        combined.abi_version=4;combined.struct_size=sizeof(combined);saved_combined=combined;
        request.values.explicit_targets_kg_s[0]=request.values.explicit_targets_kg_s[1]=1e-15;calls=0;
        CHECK(tpmshx_prepare_flow_case_3d_v4(&request,&options,&callback,&combined,&failure,error,sizeof(error))==3);
        CHECK(calls==1 && failure.kind==3 && !memcmp(&combined,&saved_combined,sizeof(combined)));
    }
    {
        tpmshx_preparation_continuous_input_3d_v3 request={0},saved_request;
        tpmshx_preparation_continuous_flow_3d_v3 flow={0};
        tpmshx_preparation_continuous_case_3d_v3 combined={0},saved_combined;
        double decisions[]={4.5,6.,7.5,5.4,.31,.42,.59,.36},saved_decisions[8];
        request.abi_version=flow.abi_version=combined.abi_version=3;
        request.struct_size=sizeof(request);flow.struct_size=sizeof(flow);combined.struct_size=sizeof(combined);
        request.values.abi_version=2;request.values.struct_size=sizeof(request.values);
        request.values.input=original;request.values.input.geometry_mode=1;
        request.controls.n_ctrl_x=request.controls.n_ctrl_y=2;request.controls.n_ctrl_z=1;
        request.controls.spline_order=1;request.controls.L_bounds_mm[0]=4.;request.controls.L_bounds_mm[1]=8.;
        request.controls.t_bounds_mm[0]=.3;request.controls.t_bounds_mm[1]=.6;
        request.controls.decision_mm.data=decisions;request.controls.decision_mm.size=8;
        memcpy(saved_decisions,decisions,sizeof(decisions));saved_request=request;
        CHECK(tpmshx_preparation_continuous_3d_abi_version_v3()==3);
        CHECK(!tpmshx_prepare_inlet_mass_capacities_3d_v3(&request,&options,NULL,&flow,&failure,error,sizeof(error)));
        CHECK(flow.owner && !flow.flow.owner && flow.flow.have_capacities);
        CHECK(flow.controls.decision_mm.data!=decisions && !memcmp(flow.controls.decision_mm.data,decisions,sizeof(decisions)));
        request.values.have_explicit_targets=1;
        for (i=0;i<2;++i) request.values.explicit_targets_kg_s[i]=flow.flow.capacities[i]*5.;
        tpmshx_preparation_continuous_flow_3d_release_v3(&flow);
        flow.abi_version=3;flow.struct_size=sizeof(flow);
        CHECK(!tpmshx_resolve_inlet_flow_3d_v3(&request,&options,NULL,&flow,&failure,error,sizeof(error)));
        CHECK(!tpmshx_prepare_flow_case_3d_v3(&request,&options,NULL,&combined,&failure,error,sizeof(error)));
        CHECK(combined.owner && !combined.prepared.owner && !combined.flow.owner);
        CHECK(combined.area_density_per_m.size==120 && combined.hydraulic_diameter_m.size==120 && combined.thermal_porosity.size==120);
        CHECK(!memcmp(decisions,saved_decisions,sizeof(decisions)));
        saved_combined=combined;
        CHECK(tpmshx_prepare_flow_case_3d_v3(&request,&options,NULL,&combined,&failure,error,sizeof(error))==1);
        CHECK(!memcmp(&combined,&saved_combined,sizeof(combined)));
        tpmshx_preparation_continuous_case_3d_release_v3(&combined);
        tpmshx_preparation_continuous_case_3d_release_v3(&combined);tpmshx_preparation_continuous_case_3d_release_v3(NULL);
        tpmshx_preparation_continuous_flow_3d_release_v3(&flow);tpmshx_preparation_continuous_flow_3d_release_v3(NULL);
        request=saved_request;request.controls.have_ctrl_z=1;
        combined.abi_version=3;combined.struct_size=sizeof(combined);
        CHECK(!tpmshx_prepare_flow_case_3d_v3(&request,&options,NULL,&combined,&failure,error,sizeof(error)));
        CHECK(combined.controls.have_ctrl_z && combined.controls.n_ctrl_z==1);
        tpmshx_preparation_continuous_case_3d_release_v3(&combined);
        flow.abi_version=3;flow.struct_size=sizeof(flow);
        request.values.input.lengths_m[0]=-1.;request.controls.spline_order=99;
        CHECK(!tpmshx_resolve_inlet_flow_3d_v3(&request,&options,NULL,&flow,&failure,error,sizeof(error)));
        CHECK(!flow.flow.have_capacities && flow.controls.spline_order==99 && flow.flow.input.lengths_m[0]==-1.);
        tpmshx_preparation_continuous_flow_3d_release_v3(&flow);
        request=saved_request;combined.abi_version=3;combined.struct_size=sizeof(combined);saved_combined=combined;
        memset(error,17,sizeof(error));memcpy(saved_error,error,sizeof(error));saved_failure=failure;
        CHECK(tpmshx_prepare_flow_case_3d_v3(&request,&options,NULL,&combined,&failure,(char*)decisions,sizeof(decisions))==1);
        CHECK(!memcmp(decisions,saved_decisions,sizeof(decisions)) && !memcmp(&failure,&saved_failure,sizeof(failure)));
        CHECK(!memcmp(&combined,&saved_combined,sizeof(combined)));
        request.controls.decision_mm.data=(double*)&combined;request.controls.decision_mm.size=1;
        CHECK(tpmshx_prepare_flow_case_3d_v3(&request,&options,NULL,&combined,&failure,error,sizeof(error))==1);
        CHECK(!memcmp(&combined,&saved_combined,sizeof(combined)) && !memcmp(error,saved_error,sizeof(error)));
        CHECK(!memcmp(&failure,&saved_failure,sizeof(failure)));
    }
    {
        tpmshx_preparation_spatial_input_3d_v4 request={0},saved_request;
        tpmshx_preparation_spatial_flow_3d_v4 flow={0};
        tpmshx_preparation_spatial_case_3d_v4 combined={0},saved_combined;
        tpmshx_preparation_grid_cell_3d_v4 cells[2]={
            {{0.,.7,0.,1.},4.5,.31},
            {{.4,1.,.2,.8},7.5,.59}},saved_cells[2];
        request.abi_version=flow.abi_version=combined.abi_version=4;
        request.struct_size=sizeof(request);flow.struct_size=sizeof(flow);combined.struct_size=sizeof(combined);
        request.values.abi_version=2;request.values.struct_size=sizeof(request.values);
        request.values.input=original;request.values.input.geometry_mode=2;request.values.input.delta_levelset=.15;
        request.cells=cells;request.cell_count=2;saved_request=request;memcpy(saved_cells,cells,sizeof(cells));
        CHECK(tpmshx_preparation_spatial_3d_abi_version_v4()==4);
        CHECK(!tpmshx_prepare_inlet_mass_capacities_3d_v4(&request,&options,NULL,&flow,&failure,error,sizeof(error)));
        CHECK(flow.owner && !flow.flow.owner && flow.flow.have_capacities && flow.cell_count==2 && flow.cells!=cells);
        CHECK(!memcmp(&request,&saved_request,sizeof(request)) && !memcmp(cells,saved_cells,sizeof(cells)));
        request.values.have_explicit_targets=1;
        for (i=0;i<2;++i) request.values.explicit_targets_kg_s[i]=flow.flow.capacities[i]*5.;
        tpmshx_preparation_spatial_flow_3d_release_v4(&flow);flow.abi_version=4;flow.struct_size=sizeof(flow);
        CHECK(!tpmshx_resolve_inlet_flow_3d_v4(&request,&options,NULL,&flow,&failure,error,sizeof(error)));
        CHECK(!tpmshx_prepare_flow_case_3d_v4(&request,&options,NULL,&combined,&failure,error,sizeof(error)));
        CHECK(combined.owner && !combined.prepared.owner && !combined.flow.owner && combined.cell_count==2 && combined.cells!=cells);
        CHECK(combined.side_b_porosity.size==120 && combined.area_density_per_m.size==120
            && combined.hydraulic_diameter_m.size==120 && combined.thermal_porosity.size==120 && combined.have_side_geometry);
        CHECK(combined.split_a>0. && combined.split_a<1.);
        for (i=0;i<120;++i) {
            CHECK(combined.prepared.side_porosity.data[i]==combined.prepared.total_porosity.data[i]*combined.split_a);
            CHECK(combined.side_b_porosity.data[i]==combined.prepared.total_porosity.data[i]*(1.-combined.split_a));
        }
        for (i=0;i<2;++i) CHECK(combined.prepared.input.sides[i].velocity_m_s==flow.flow.speeds[i]);
        cells[0].cell_length_mm=8.;
        CHECK(combined.cells[0].cell_length_mm==4.5 && flow.cells[0].cell_length_mm==4.5);
        memcpy(cells,saved_cells,sizeof(cells));saved_combined=combined;
        CHECK(tpmshx_prepare_flow_case_3d_v4(&request,&options,NULL,&combined,&failure,error,sizeof(error))==1);
        CHECK(!memcmp(&combined,&saved_combined,sizeof(combined)));
        tpmshx_preparation_spatial_case_3d_release_v4(&combined);tpmshx_preparation_spatial_case_3d_release_v4(&combined);
        tpmshx_preparation_spatial_flow_3d_release_v4(&flow);tpmshx_preparation_spatial_flow_3d_release_v4(&flow);
        tpmshx_preparation_spatial_case_3d_release_v4(NULL);tpmshx_preparation_spatial_flow_3d_release_v4(NULL);
        request=saved_request;request.values.input.delta_levelset=0.;
        combined.abi_version=4;combined.struct_size=sizeof(combined);
        CHECK(!tpmshx_prepare_flow_case_3d_v4(&request,&options,NULL,&combined,&failure,error,sizeof(error)));
        CHECK(combined.split_a==.5 && !combined.have_side_geometry
            && combined.side_b_porosity.data==combined.prepared.side_porosity.data);
        tpmshx_preparation_spatial_case_3d_release_v4(&combined);
        flow.abi_version=4;flow.struct_size=sizeof(flow);request.values.input.lengths_m[0]=-1.;
        CHECK(!tpmshx_resolve_inlet_flow_3d_v4(&request,&options,NULL,&flow,&failure,error,sizeof(error)));
        CHECK(!flow.flow.have_capacities && flow.flow.input.lengths_m[0]==-1. && flow.cell_count==2 && flow.cells!=cells);
        tpmshx_preparation_spatial_flow_3d_release_v4(&flow);
        request=saved_request;combined.abi_version=4;combined.struct_size=sizeof(combined);saved_combined=combined;
        memset(error,17,sizeof(error));memcpy(saved_error,error,sizeof(error));saved_failure=failure;
        CHECK(tpmshx_prepare_flow_case_3d_v4(&request,&options,NULL,&combined,&failure,(char*)cells,sizeof(cells))==1);
        CHECK(!memcmp(cells,saved_cells,sizeof(cells)) && !memcmp(&failure,&saved_failure,sizeof(failure)));
        CHECK(!memcmp(&combined,&saved_combined,sizeof(combined)));
        request.cells=(const tpmshx_preparation_grid_cell_3d_v4*)&combined;request.cell_count=1;
        CHECK(tpmshx_prepare_flow_case_3d_v4(&request,&options,NULL,&combined,&failure,error,sizeof(error))==1);
        CHECK(!memcmp(&combined,&saved_combined,sizeof(combined)) && !memcmp(error,saved_error,sizeof(error)));
        CHECK(!memcmp(&failure,&saved_failure,sizeof(failure)));
    }
    puts("3D preparation C ownership and failure checks passed");
    return 0;
}
