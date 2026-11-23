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
static int TPMSHX_PREPARATION_CALL dummy_host(void* context,uint32_t stage,uint32_t side) {
    (void)context;(void)stage;(void)side;return 0;
}
static int TPMSHX_PREPARATION_CALL dummy_geom(void* context,uint32_t action,
    tpmshx_preparation_geometry_cache_v3* value,uint32_t* hit) {
    (void)context;(void)action;(void)value;*hit=0;return 0;
}
static int TPMSHX_PREPARATION_CALL dummy_lut(void* context,uint32_t action,uint32_t topology,
    size_t resolution,tpmshx_preparation_sigmoid_lut_view_v6* value,uint32_t* hit) {
    (void)context;(void)action;(void)topology;(void)resolution;(void)value;*hit=0;return 0;
}
int main(void) {
    tpmshx_preparation_case_input_3d_v1 input={0},original;
    tpmshx_preparation_case_failure_v2 failure={0},saved_failure;
    tpmshx_preparation_case_options_v1 options={1,sizeof(options),0,1,0.};
    tpmshx_preparation_callbacks_v1 callback={1,sizeof(callback),NULL,0,stop_event};
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
    CHECK(tpmshx_preparation_abi_version_v1()==TPMSHX_PREPARATION_ABI_VERSION);
    {
        /* Uniform 3D preparation uses spatial v1 with geometry_mode 0 and no grid cells. */
        tpmshx_preparation_3d_spatial_input_v1 request={0},saved_request;
        tpmshx_preparation_3d_spatial_flow_v1 flow={0},saved_flow;
        tpmshx_preparation_3d_spatial_case_v1 combined={0},saved_combined;
        request.abi_version=flow.abi_version=combined.abi_version=1;
        request.struct_size=sizeof(request);flow.struct_size=sizeof(flow);combined.struct_size=sizeof(combined);
        request.input=original;
        saved_request=request;
        CHECK(!tpmshx_preparation_3d_spatial_prepare_case_v1(&request,&options,NULL,&combined,&failure,error,sizeof(error)));
        CHECK(!failure.kind && combined.owner && !combined.cell_count);
        CHECK(!memcmp(&request,&saved_request,sizeof(request)) && !memcmp(&request.input,&original,sizeof(original)));
        CHECK(combined.prepared.cell_length.size==120 && combined.prepared.sides[1].inlet_opening.size==30);
        CHECK(combined.prepared.sides[1].axes[6]==1 && isfinite(combined.prepared.solid_conductivity.data[0]));
        CHECK(combined.prepared.geometry.epsilon_a==combined.prepared.side_porosity.data[0]);
        CHECK(combined.split_a==.5 && !combined.have_side_geometry);
        CHECK(!combined.area_density_per_m.size && !combined.hydraulic_diameter_m.size && !combined.thermal_porosity.size);
        CHECK(!combined.prepared.input.sides[0].have_mass_flow);
        CHECK(combined.prepared.input.sco2_nu.source.data!=source);source[0]='X';
        CHECK(!memcmp(combined.prepared.input.sco2_nu.source.data,"source",6));saved_combined=combined;
        CHECK(tpmshx_preparation_3d_spatial_prepare_case_v1(&request,&options,NULL,&combined,&failure,error,sizeof(error))==1);
        CHECK(!memcmp(&combined,&saved_combined,sizeof(combined)));
        tpmshx_preparation_3d_spatial_case_release_v1(&combined);CHECK(!combined.owner && !combined.struct_size);
        tpmshx_preparation_3d_spatial_case_release_v1(&combined);tpmshx_preparation_3d_spatial_case_release_v1(NULL);
        combined.abi_version=1;combined.struct_size=sizeof(combined);saved_combined=combined;
        /* 3D rejects untyped cache hooks, sigmoid_lut_cache, and validate_grid_stage != 0. */
        {
            tpmshx_preparation_callbacks_v1 bad={1,sizeof(bad)};
            bad.geometry_cache=dummy_geom;
            CHECK(tpmshx_preparation_3d_spatial_prepare_case_v1(&request,&options,&bad,&combined,&failure,error,sizeof(error))==1);
            CHECK(!memcmp(&saved_combined,&combined,sizeof(combined)));
            bad.geometry_cache=NULL;bad.sigmoid_lut_cache=dummy_lut;
            CHECK(tpmshx_preparation_3d_spatial_prepare_case_v1(&request,&options,&bad,&combined,&failure,error,sizeof(error))==1);
            CHECK(!memcmp(&saved_combined,&combined,sizeof(combined)));
            bad.sigmoid_lut_cache=NULL;bad.validate_grid_stage=1;bad.validate_host_input=dummy_host;
            CHECK(tpmshx_preparation_3d_spatial_prepare_case_v1(&request,&options,&bad,&combined,&failure,error,sizeof(error))==1);
            CHECK(!memcmp(&saved_combined,&combined,sizeof(combined)));
        }
        request.input.sides[0].velocity_m_s=1e-9;callback.context=&calls;
        CHECK(tpmshx_preparation_3d_spatial_prepare_case_v1(&request,&options,&callback,&combined,&failure,error,sizeof(error))==3);
        CHECK(calls==1 && failure.kind==3 && !memcmp(&saved_combined,&combined,sizeof(combined)));
        request=saved_request;request.input.max_cells=119;
        CHECK(tpmshx_preparation_3d_spatial_prepare_case_v1(&request,&options,NULL,&combined,&failure,error,sizeof(error))==1);
        CHECK(strstr(error,"3D grid 6x5x4 exceeds the 119-cell cap") && !memcmp(&saved_combined,&combined,sizeof(combined)));
        memset(error,17,sizeof(error));memcpy(saved_error,error,sizeof(error));saved_failure=failure;
        CHECK(tpmshx_preparation_3d_spatial_prepare_case_v1(&request,&options,NULL,&combined,
            (tpmshx_preparation_case_failure_v2*)&combined,error,sizeof(error))==1);
        CHECK(!memcmp(&saved_combined,&combined,sizeof(combined)) && !memcmp(error,saved_error,sizeof(error)));
        CHECK(!memcmp(&failure,&saved_failure,sizeof(failure)));
        request=saved_request;request.input.sides[0].velocity_m_s=NAN;request.input.sides[1].velocity_m_s=-99.;
        saved_request=request;
        CHECK(!tpmshx_preparation_3d_spatial_capacities_v1(&request,&options,NULL,&flow,&failure,error,sizeof(error)));
        CHECK(flow.owner && flow.flow.have_capacities && !flow.cell_count);
        CHECK(!memcmp(&request,&saved_request,sizeof(request)));
        CHECK(flow.flow.capacities[0]>0. && flow.flow.capacities[1]>0.);
        request.have_explicit_targets=1;
        for (i=0;i<2;++i) {
            request.explicit_targets_kg_s[i]=flow.flow.capacities[i]*5.;
            request.input.sides[i].have_mass_flow=1;request.input.sides[i].mass_flow_kg_s=-1.;
        }
        tpmshx_preparation_3d_spatial_flow_release_v1(&flow);CHECK(!flow.owner && !flow.struct_size);
        flow.abi_version=1;flow.struct_size=sizeof(flow);
        CHECK(!tpmshx_preparation_3d_spatial_resolve_flow_v1(&request,&options,NULL,&flow,&failure,error,sizeof(error)));
        CHECK(!tpmshx_preparation_3d_spatial_prepare_case_v1(&request,&options,NULL,&combined,&failure,error,sizeof(error)));
        CHECK(combined.owner && combined.prepared.cell_length.size==120);
        for (i=0;i<2;++i) {
            CHECK(combined.prepared.input.sides[i].velocity_m_s==flow.flow.speeds[i]);
            CHECK(!combined.prepared.input.sides[i].have_mass_flow && !combined.flow.input.sides[i].have_mass_flow);
        }
        tpmshx_preparation_3d_spatial_case_release_v1(&combined);
        tpmshx_preparation_3d_spatial_flow_release_v1(&flow);tpmshx_preparation_3d_spatial_flow_release_v1(NULL);
        flow.abi_version=1;flow.struct_size=sizeof(flow);saved_flow=flow;
        request=saved_request;request.input.lengths_m[0]=-1.;
        CHECK(!tpmshx_preparation_3d_spatial_resolve_flow_v1(&request,&options,NULL,&flow,&failure,error,sizeof(error)));
        CHECK(!flow.flow.have_capacities && flow.flow.input.lengths_m[0]==-1.);
        CHECK(isnan(flow.flow.input.sides[0].velocity_m_s) && flow.flow.input.sco2_nu.source.data!=source);
        tpmshx_preparation_3d_spatial_flow_release_v1(&flow);flow=saved_flow;
        request=saved_request;request.have_explicit_targets=1;request.explicit_targets_kg_s[0]=-1.;
        CHECK(tpmshx_preparation_3d_spatial_resolve_flow_v1(&request,&options,NULL,&flow,&failure,error,sizeof(error))==1);
        CHECK(strstr(error,"mass_flow_A_kg_s") && !memcmp(&flow,&saved_flow,sizeof(flow)));
        saved_request=request;saved_failure=failure;
        CHECK(tpmshx_preparation_3d_spatial_resolve_flow_v1(&request,&options,NULL,&flow,&failure,
            (char*)&request,sizeof(request))==1);
        CHECK(!memcmp(&request,&saved_request,sizeof(request)) && !memcmp(&failure,&saved_failure,sizeof(failure)));
        CHECK(!memcmp(&flow,&saved_flow,sizeof(flow)));
        combined.abi_version=1;combined.struct_size=sizeof(combined);saved_combined=combined;
        request.explicit_targets_kg_s[0]=request.explicit_targets_kg_s[1]=1e-15;calls=0;
        CHECK(tpmshx_preparation_3d_spatial_prepare_case_v1(&request,&options,&callback,&combined,&failure,error,sizeof(error))==3);
        CHECK(calls==1 && failure.kind==3 && !memcmp(&combined,&saved_combined,sizeof(combined)));
    }
    {
        tpmshx_preparation_3d_continuous_input_v1 request={0},saved_request;
        tpmshx_preparation_3d_continuous_flow_v1 flow={0};
        tpmshx_preparation_3d_continuous_case_v1 combined={0},saved_combined;
        double decisions[]={4.5,6.,7.5,5.4,.31,.42,.59,.36},saved_decisions[8];
        request.abi_version=flow.abi_version=combined.abi_version=1;
        request.struct_size=sizeof(request);flow.struct_size=sizeof(flow);combined.struct_size=sizeof(combined);
        request.input=original;request.input.geometry_mode=1;
        request.controls.n_ctrl_x=request.controls.n_ctrl_y=2;request.controls.n_ctrl_z=1;
        request.controls.spline_order=1;request.controls.L_bounds_mm[0]=4.;request.controls.L_bounds_mm[1]=8.;
        request.controls.t_bounds_mm[0]=.3;request.controls.t_bounds_mm[1]=.6;
        request.controls.decision_mm.data=decisions;request.controls.decision_mm.size=8;
        memcpy(saved_decisions,decisions,sizeof(decisions));saved_request=request;
        CHECK(!tpmshx_preparation_3d_continuous_capacities_v1(&request,&options,NULL,&flow,&failure,error,sizeof(error)));
        CHECK(flow.owner && flow.flow.have_capacities);
        CHECK(flow.controls.decision_mm.data!=decisions && !memcmp(flow.controls.decision_mm.data,decisions,sizeof(decisions)));
        request.have_explicit_targets=1;
        for (i=0;i<2;++i) request.explicit_targets_kg_s[i]=flow.flow.capacities[i]*5.;
        tpmshx_preparation_3d_continuous_flow_release_v1(&flow);
        flow.abi_version=1;flow.struct_size=sizeof(flow);
        CHECK(!tpmshx_preparation_3d_continuous_resolve_flow_v1(&request,&options,NULL,&flow,&failure,error,sizeof(error)));
        CHECK(!tpmshx_preparation_3d_continuous_prepare_case_v1(&request,&options,NULL,&combined,&failure,error,sizeof(error)));
        CHECK(combined.owner);
        CHECK(combined.area_density_per_m.size==120 && combined.hydraulic_diameter_m.size==120 && combined.thermal_porosity.size==120);
        CHECK(!memcmp(decisions,saved_decisions,sizeof(decisions)));
        saved_combined=combined;
        CHECK(tpmshx_preparation_3d_continuous_prepare_case_v1(&request,&options,NULL,&combined,&failure,error,sizeof(error))==1);
        CHECK(!memcmp(&combined,&saved_combined,sizeof(combined)));
        tpmshx_preparation_3d_continuous_case_release_v1(&combined);
        tpmshx_preparation_3d_continuous_case_release_v1(&combined);tpmshx_preparation_3d_continuous_case_release_v1(NULL);
        tpmshx_preparation_3d_continuous_flow_release_v1(&flow);tpmshx_preparation_3d_continuous_flow_release_v1(NULL);
        request=saved_request;request.controls.have_ctrl_z=1;
        combined.abi_version=1;combined.struct_size=sizeof(combined);
        CHECK(!tpmshx_preparation_3d_continuous_prepare_case_v1(&request,&options,NULL,&combined,&failure,error,sizeof(error)));
        CHECK(combined.controls.have_ctrl_z && combined.controls.n_ctrl_z==1);
        tpmshx_preparation_3d_continuous_case_release_v1(&combined);
        flow.abi_version=1;flow.struct_size=sizeof(flow);
        request.input.lengths_m[0]=-1.;request.controls.spline_order=99;
        CHECK(!tpmshx_preparation_3d_continuous_resolve_flow_v1(&request,&options,NULL,&flow,&failure,error,sizeof(error)));
        CHECK(!flow.flow.have_capacities && flow.controls.spline_order==99 && flow.flow.input.lengths_m[0]==-1.);
        tpmshx_preparation_3d_continuous_flow_release_v1(&flow);
        request=saved_request;combined.abi_version=1;combined.struct_size=sizeof(combined);saved_combined=combined;
        memset(error,17,sizeof(error));memcpy(saved_error,error,sizeof(error));saved_failure=failure;
        CHECK(tpmshx_preparation_3d_continuous_prepare_case_v1(&request,&options,NULL,&combined,&failure,(char*)decisions,sizeof(decisions))==1);
        CHECK(!memcmp(decisions,saved_decisions,sizeof(decisions)) && !memcmp(&failure,&saved_failure,sizeof(failure)));
        CHECK(!memcmp(&combined,&saved_combined,sizeof(combined)));
        request.controls.decision_mm.data=(double*)&combined;request.controls.decision_mm.size=1;
        CHECK(tpmshx_preparation_3d_continuous_prepare_case_v1(&request,&options,NULL,&combined,&failure,error,sizeof(error))==1);
        CHECK(!memcmp(&combined,&saved_combined,sizeof(combined)) && !memcmp(error,saved_error,sizeof(error)));
        CHECK(!memcmp(&failure,&saved_failure,sizeof(failure)));
    }
    {
        tpmshx_preparation_3d_spatial_input_v1 request={0},saved_request;
        tpmshx_preparation_3d_spatial_flow_v1 flow={0};
        tpmshx_preparation_3d_spatial_case_v1 combined={0},saved_combined;
        tpmshx_preparation_grid_cell_3d_v4 cells[2]={
            {{0.,.7,0.,1.},4.5,.31},
            {{.4,1.,.2,.8},7.5,.59}},saved_cells[2];
        request.abi_version=flow.abi_version=combined.abi_version=1;
        request.struct_size=sizeof(request);flow.struct_size=sizeof(flow);combined.struct_size=sizeof(combined);
        request.input=original;request.input.geometry_mode=2;request.input.delta_levelset=.15;
        request.cells=cells;request.cell_count=2;saved_request=request;memcpy(saved_cells,cells,sizeof(cells));
        CHECK(!tpmshx_preparation_3d_spatial_capacities_v1(&request,&options,NULL,&flow,&failure,error,sizeof(error)));
        CHECK(flow.owner && flow.flow.have_capacities && flow.cell_count==2 && flow.cells!=cells);
        CHECK(!memcmp(&request,&saved_request,sizeof(request)) && !memcmp(cells,saved_cells,sizeof(cells)));
        request.have_explicit_targets=1;
        for (i=0;i<2;++i) request.explicit_targets_kg_s[i]=flow.flow.capacities[i]*5.;
        tpmshx_preparation_3d_spatial_flow_release_v1(&flow);flow.abi_version=1;flow.struct_size=sizeof(flow);
        CHECK(!tpmshx_preparation_3d_spatial_resolve_flow_v1(&request,&options,NULL,&flow,&failure,error,sizeof(error)));
        CHECK(!tpmshx_preparation_3d_spatial_prepare_case_v1(&request,&options,NULL,&combined,&failure,error,sizeof(error)));
        CHECK(combined.owner && combined.cell_count==2 && combined.cells!=cells);
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
        CHECK(tpmshx_preparation_3d_spatial_prepare_case_v1(&request,&options,NULL,&combined,&failure,error,sizeof(error))==1);
        CHECK(!memcmp(&combined,&saved_combined,sizeof(combined)));
        tpmshx_preparation_3d_spatial_case_release_v1(&combined);tpmshx_preparation_3d_spatial_case_release_v1(&combined);
        tpmshx_preparation_3d_spatial_flow_release_v1(&flow);tpmshx_preparation_3d_spatial_flow_release_v1(&flow);
        tpmshx_preparation_3d_spatial_case_release_v1(NULL);tpmshx_preparation_3d_spatial_flow_release_v1(NULL);
        request=saved_request;request.input.delta_levelset=0.;
        combined.abi_version=1;combined.struct_size=sizeof(combined);
        CHECK(!tpmshx_preparation_3d_spatial_prepare_case_v1(&request,&options,NULL,&combined,&failure,error,sizeof(error)));
        CHECK(combined.split_a==.5 && !combined.have_side_geometry
            && combined.side_b_porosity.data==combined.prepared.side_porosity.data);
        tpmshx_preparation_3d_spatial_case_release_v1(&combined);
        flow.abi_version=1;flow.struct_size=sizeof(flow);request.input.lengths_m[0]=-1.;
        CHECK(!tpmshx_preparation_3d_spatial_resolve_flow_v1(&request,&options,NULL,&flow,&failure,error,sizeof(error)));
        CHECK(!flow.flow.have_capacities && flow.flow.input.lengths_m[0]==-1. && flow.cell_count==2 && flow.cells!=cells);
        tpmshx_preparation_3d_spatial_flow_release_v1(&flow);
        request=saved_request;combined.abi_version=1;combined.struct_size=sizeof(combined);saved_combined=combined;
        memset(error,17,sizeof(error));memcpy(saved_error,error,sizeof(error));saved_failure=failure;
        CHECK(tpmshx_preparation_3d_spatial_prepare_case_v1(&request,&options,NULL,&combined,&failure,(char*)cells,sizeof(cells))==1);
        CHECK(!memcmp(cells,saved_cells,sizeof(cells)) && !memcmp(&failure,&saved_failure,sizeof(failure)));
        CHECK(!memcmp(&combined,&saved_combined,sizeof(combined)));
        request.cells=(const tpmshx_preparation_grid_cell_3d_v4*)&combined;request.cell_count=1;
        CHECK(tpmshx_preparation_3d_spatial_prepare_case_v1(&request,&options,NULL,&combined,&failure,error,sizeof(error))==1);
        CHECK(!memcmp(&combined,&saved_combined,sizeof(combined)) && !memcmp(error,saved_error,sizeof(error)));
        CHECK(!memcmp(&failure,&saved_failure,sizeof(failure)));
    }
    puts("3D preparation C ownership and failure checks passed");
    return 0;
}
