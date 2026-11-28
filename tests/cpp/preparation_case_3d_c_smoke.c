#include "tpmshx/preparation_case_3d_c_api.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

#define CHECK(test) do { if (!(test)) { fprintf(stderr, "line %d: %s\n%s\n", __LINE__, #test, error); return 1; } } while (0)

/* Each entry point must reject one incompatible record version or size before it writes its result. */
#define REJECT_RECORDS(function,request_type,result_type,base) do { \
    int record_,field_; \
    for (record_=0;record_<6;++record_) for (field_=0;field_<2;++field_) { \
        request_type request_=(base); \
        tpmshx_preparation_case_options_v1 options_={1,sizeof(options_),0,1,0.}; \
        tpmshx_preparation_callbacks_v2 callbacks_={0}; \
        tpmshx_preparation_case_failure_v2 failure_={0}; \
        result_type result_={0},saved_result_; \
        uint32_t* versions_[6]; size_t* sizes_[6]; \
        callbacks_.abi_version=2;callbacks_.struct_size=sizeof(callbacks_); \
        result_.abi_version=1;result_.struct_size=sizeof(result_); \
        failure_.abi_version=2;failure_.struct_size=sizeof(failure_); \
        versions_[0]=&request_.abi_version;sizes_[0]=&request_.struct_size; \
        versions_[1]=&request_.input.abi_version;sizes_[1]=&request_.input.struct_size; \
        versions_[2]=&options_.abi_version;sizes_[2]=&options_.struct_size; \
        versions_[3]=&callbacks_.abi_version;sizes_[3]=&callbacks_.struct_size; \
        versions_[4]=&result_.abi_version;sizes_[4]=&result_.struct_size; \
        versions_[5]=&failure_.abi_version;sizes_[5]=&failure_.struct_size; \
        if (field_) *sizes_[record_]=1; else *versions_[record_]=99; \
        saved_result_=result_;error[0]=0; \
        CHECK(function(&request_,&options_,&callbacks_,&result_,&failure_,error,sizeof(error))!=0); \
        CHECK(error[0] && !memcmp(&result_,&saved_result_,sizeof(result_))); \
    } \
} while (0)

/* A request with an invalid geometry mode or grid rectangle must report an input failure without writing its result. */
#define REJECT_INPUT(function,result_type,request,expected) do { \
    result_type result_={0},saved_result_; \
    result_.abi_version=1;result_.struct_size=sizeof(result_);saved_result_=result_; \
    failure.kind=0;error[0]=0; \
    CHECK(function(&(request),&options,NULL,&result_,&failure,error,sizeof(error))==1); \
    CHECK(failure.kind==1 && error[0] && (!(expected) || strstr(error,(expected))!=NULL)); \
    CHECK(!memcmp(&result_,&saved_result_,sizeof(result_))); \
} while (0)

/* A request with a null cell buffer and positive count fails in the pointer pre-check without touching diagnostics. */
#define REJECT_BUFFER(function,result_type,request) do { \
    result_type result_={0},saved_result_; \
    result_.abi_version=1;result_.struct_size=sizeof(result_);saved_result_=result_; \
    memset(error,17,sizeof(error));memcpy(saved_error,error,sizeof(error));saved_failure=failure; \
    CHECK(function(&(request),&options,NULL,&result_,&failure,error,sizeof(error))==1); \
    CHECK(!memcmp(&result_,&saved_result_,sizeof(result_)) && !memcmp(error,saved_error,sizeof(error))); \
    CHECK(!memcmp(&failure,&saved_failure,sizeof(failure))); \
} while (0)

/* A live result owns the view at data. The view must not become a failure or a 1-byte error output. */
#define REJECT_ALIAS(function,request,result,data,bytes) do { \
    static unsigned char outer_[16384],view_[4096]; \
    char text_[16]="unchanged",saved_text_[16]; \
    tpmshx_preparation_case_failure_v2 failure_={0},saved_failure_; \
    const unsigned char* view_data_=(const unsigned char*)(data); \
    size_t view_size_=(bytes),offset_=0; \
    CHECK(view_data_ && view_size_ && view_size_<=sizeof(view_) && sizeof(result)<=sizeof(outer_)); \
    while (offset_+1<view_size_ && !view_data_[offset_]) ++offset_; \
    failure_.abi_version=2;failure_.struct_size=sizeof(failure_);saved_failure_=failure_; \
    memcpy(saved_text_,text_,sizeof(text_));memcpy(outer_,&(result),sizeof(result)); \
    memcpy(view_,view_data_,view_size_); \
    CHECK(function(&(request),NULL,NULL,&(result),(tpmshx_preparation_case_failure_v2*)(void*)view_data_, \
        text_,sizeof(text_))==1); \
    CHECK(!memcmp(outer_,&(result),sizeof(result)) && !memcmp(view_,view_data_,view_size_)); \
    CHECK(!memcmp(text_,saved_text_,sizeof(text_))); \
    CHECK(function(&(request),NULL,NULL,&(result),&failure_,(char*)(void*)(view_data_+offset_),1)==1); \
    CHECK(!memcmp(outer_,&(result),sizeof(result)) && !memcmp(view_,view_data_,view_size_)); \
    CHECK(!memcmp(&failure_,&saved_failure_,sizeof(failure_))); \
} while (0)

static int TPMSHX_PREPARATION_CALL stop_event(void* context,const tpmshx_preparation_event_v1* event) {
    size_t* count=(size_t*)context;
    if (event) ++*count;
    return 1;
}
static int TPMSHX_PREPARATION_CALL dummy_host(void* context,uint32_t stage,uint32_t side) {
    (void)context;(void)stage;(void)side;return 0;
}
static int TPMSHX_PREPARATION_CALL dummy_inlet(void* context,uint32_t action,uint32_t side,
    const tpmshx_preparation_inlet_2d_v1* input,tpmshx_preparation_inlet_cache_v3* value,uint32_t* hit) {
    (void)side; (void)input;
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
    tpmshx_preparation_callbacks_v2 callback={2,sizeof(callback),NULL,0,stop_event};
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
            tpmshx_preparation_callbacks_v2 bad={2,sizeof(bad)};
            bad.inlet_cache=dummy_inlet;
            CHECK(tpmshx_preparation_3d_spatial_prepare_case_v1(&request,&options,&bad,&combined,&failure,error,sizeof(error))==1);
            CHECK(!memcmp(&saved_combined,&combined,sizeof(combined)));
            bad.inlet_cache=NULL;bad.sigmoid_lut_cache=dummy_lut;
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
    {
        /* Record versions, geometry transport, grid rectangles, out-of-range evidence, and aliases on 3D entries. */
        tpmshx_preparation_3d_spatial_input_v1 uniform={0},grid,bad_spatial,cold_spatial;
        tpmshx_preparation_3d_continuous_input_v1 continuous={0},experimental,bad_continuous,cold_continuous;
        tpmshx_preparation_3d_spatial_flow_v1 spatial_flow={0},saved_spatial_flow;
        tpmshx_preparation_3d_spatial_case_v1 spatial_case={0};
        tpmshx_preparation_3d_continuous_flow_v1 continuous_flow={0},saved_continuous_flow;
        tpmshx_preparation_3d_continuous_case_v1 continuous_case={0},drag_case={0};
        tpmshx_preparation_grid_cell_3d_v4 cells[2]={{{0.,.7,0.,1.},4.5,.31},{{.4,1.,.2,.8},7.5,.59}},bad_cells[2];
        double decisions[]={4.5,6.,7.5,5.4,.31,.42,.59,.36};
        char nu_source[]="source";
        uniform.abi_version=continuous.abi_version=1;
        uniform.struct_size=sizeof(uniform);continuous.struct_size=sizeof(continuous);
        uniform.input=original;uniform.input.sco2_nu.source.data=nu_source;
        uniform.have_explicit_targets=1;uniform.explicit_targets_kg_s[0]=.003;uniform.explicit_targets_kg_s[1]=.03;
        grid=uniform;grid.input.geometry_mode=2;grid.input.delta_levelset=.12;grid.cells=cells;grid.cell_count=2;
        continuous.input=uniform.input;continuous.input.geometry_mode=1;
        continuous.have_explicit_targets=1;continuous.explicit_targets_kg_s[0]=.003;continuous.explicit_targets_kg_s[1]=.03;
        continuous.controls.n_ctrl_x=continuous.controls.n_ctrl_y=2;continuous.controls.n_ctrl_z=1;
        continuous.controls.spline_order=1;continuous.controls.L_bounds_mm[0]=4.;continuous.controls.L_bounds_mm[1]=8.;
        continuous.controls.t_bounds_mm[0]=.3;continuous.controls.t_bounds_mm[1]=.6;
        continuous.controls.decision_mm.data=decisions;continuous.controls.decision_mm.size=8;

        REJECT_RECORDS(tpmshx_preparation_3d_spatial_capacities_v1,tpmshx_preparation_3d_spatial_input_v1,
            tpmshx_preparation_3d_spatial_flow_v1,uniform);
        REJECT_RECORDS(tpmshx_preparation_3d_spatial_resolve_flow_v1,tpmshx_preparation_3d_spatial_input_v1,
            tpmshx_preparation_3d_spatial_flow_v1,uniform);
        REJECT_RECORDS(tpmshx_preparation_3d_spatial_prepare_case_v1,tpmshx_preparation_3d_spatial_input_v1,
            tpmshx_preparation_3d_spatial_case_v1,uniform);
        REJECT_RECORDS(tpmshx_preparation_3d_continuous_capacities_v1,tpmshx_preparation_3d_continuous_input_v1,
            tpmshx_preparation_3d_continuous_flow_v1,continuous);
        REJECT_RECORDS(tpmshx_preparation_3d_continuous_resolve_flow_v1,tpmshx_preparation_3d_continuous_input_v1,
            tpmshx_preparation_3d_continuous_flow_v1,continuous);
        REJECT_RECORDS(tpmshx_preparation_3d_continuous_prepare_case_v1,tpmshx_preparation_3d_continuous_input_v1,
            tpmshx_preparation_3d_continuous_case_v1,continuous);

        /* Spatial input rejects continuous mode, uniform cells, missing cells, empty grid cells, and bad bounds. */
        for (i=0;i<2;++i) {
            bad_spatial=i==0?uniform:grid;
            bad_spatial.input.geometry_mode=i==0?1u:0u;
            REJECT_INPUT(tpmshx_preparation_3d_spatial_capacities_v1,tpmshx_preparation_3d_spatial_flow_v1,bad_spatial,NULL);
            REJECT_INPUT(tpmshx_preparation_3d_spatial_resolve_flow_v1,tpmshx_preparation_3d_spatial_flow_v1,bad_spatial,NULL);
            REJECT_INPUT(tpmshx_preparation_3d_spatial_prepare_case_v1,tpmshx_preparation_3d_spatial_case_v1,bad_spatial,NULL);
        }
        bad_spatial=grid;bad_spatial.cells=NULL;
        REJECT_BUFFER(tpmshx_preparation_3d_spatial_capacities_v1,tpmshx_preparation_3d_spatial_flow_v1,bad_spatial);
        REJECT_BUFFER(tpmshx_preparation_3d_spatial_resolve_flow_v1,tpmshx_preparation_3d_spatial_flow_v1,bad_spatial);
        REJECT_BUFFER(tpmshx_preparation_3d_spatial_prepare_case_v1,tpmshx_preparation_3d_spatial_case_v1,bad_spatial);
        bad_spatial=grid;bad_spatial.cells=NULL;bad_spatial.cell_count=0;
        REJECT_INPUT(tpmshx_preparation_3d_spatial_capacities_v1,tpmshx_preparation_3d_spatial_flow_v1,bad_spatial,"non-empty grid cells");
        REJECT_INPUT(tpmshx_preparation_3d_spatial_resolve_flow_v1,tpmshx_preparation_3d_spatial_flow_v1,bad_spatial,"non-empty grid cells");
        REJECT_INPUT(tpmshx_preparation_3d_spatial_prepare_case_v1,tpmshx_preparation_3d_spatial_case_v1,bad_spatial,"non-empty grid cells");
        memcpy(bad_cells,cells,sizeof(cells));bad_cells[0].bounds[1]=-1.;
        bad_spatial=grid;bad_spatial.cells=bad_cells;
        REJECT_INPUT(tpmshx_preparation_3d_spatial_capacities_v1,tpmshx_preparation_3d_spatial_flow_v1,bad_spatial,"Zone grid cell 1: x");
        REJECT_INPUT(tpmshx_preparation_3d_spatial_resolve_flow_v1,tpmshx_preparation_3d_spatial_flow_v1,bad_spatial,"Zone grid cell 1: x");
        REJECT_INPUT(tpmshx_preparation_3d_spatial_prepare_case_v1,tpmshx_preparation_3d_spatial_case_v1,bad_spatial,"Zone grid cell 1: x");

        /* Continuous input rejects the uniform and grid modes. */
        for (i=0;i<2;++i) {
            bad_continuous=continuous;bad_continuous.input.geometry_mode=i?2u:0u;
            REJECT_INPUT(tpmshx_preparation_3d_continuous_capacities_v1,tpmshx_preparation_3d_continuous_flow_v1,bad_continuous,NULL);
            REJECT_INPUT(tpmshx_preparation_3d_continuous_resolve_flow_v1,tpmshx_preparation_3d_continuous_flow_v1,bad_continuous,NULL);
            REJECT_INPUT(tpmshx_preparation_3d_continuous_prepare_case_v1,tpmshx_preparation_3d_continuous_case_v1,bad_continuous,NULL);
        }

        /* Capacity and resolve queries emit out-of-range evidence and warnings when inlet states extrapolate. */
        cold_spatial=uniform;cold_spatial.input.sides[0].temperature_K=190.;
        spatial_flow.abi_version=1;spatial_flow.struct_size=sizeof(spatial_flow);
        CHECK(!tpmshx_preparation_3d_spatial_capacities_v1(&cold_spatial,&options,NULL,&spatial_flow,&failure,error,sizeof(error)));
        CHECK(spatial_flow.flow.evidence.range_count>0 && spatial_flow.flow.evidence.warning_count>0);
        tpmshx_preparation_3d_spatial_flow_release_v1(&spatial_flow);
        cold_continuous=continuous;cold_continuous.input.sides[0].temperature_K=190.;
        continuous_flow.abi_version=1;continuous_flow.struct_size=sizeof(continuous_flow);
        CHECK(!tpmshx_preparation_3d_continuous_resolve_flow_v1(&cold_continuous,&options,NULL,&continuous_flow,&failure,error,sizeof(error)));
        CHECK(continuous_flow.flow.evidence.range_count>0 && continuous_flow.flow.evidence.warning_count>0);
        tpmshx_preparation_3d_continuous_flow_release_v1(&continuous_flow);

        spatial_flow.abi_version=spatial_case.abi_version=continuous_flow.abi_version=continuous_case.abi_version=1;
        spatial_flow.struct_size=sizeof(spatial_flow);spatial_case.struct_size=sizeof(spatial_case);
        continuous_flow.struct_size=sizeof(continuous_flow);continuous_case.struct_size=sizeof(continuous_case);
        drag_case=continuous_case;
        CHECK(!tpmshx_preparation_3d_spatial_resolve_flow_v1(&grid,&options,NULL,&spatial_flow,&failure,error,sizeof(error)));
        CHECK(spatial_flow.flow.evidence.range_count>0);
        saved_spatial_flow=spatial_flow;
        CHECK(tpmshx_preparation_3d_spatial_capacities_v1(&grid,&options,NULL,&spatial_flow,&failure,error,sizeof(error))==1);
        CHECK(strstr(error,"release") && !memcmp(&spatial_flow,&saved_spatial_flow,sizeof(spatial_flow)));
        CHECK(tpmshx_preparation_3d_spatial_resolve_flow_v1(&grid,&options,NULL,&spatial_flow,&failure,error,sizeof(error))==1);
        CHECK(strstr(error,"release") && !memcmp(&spatial_flow,&saved_spatial_flow,sizeof(spatial_flow)));
        REJECT_ALIAS(tpmshx_preparation_3d_spatial_resolve_flow_v1,grid,spatial_flow,
            spatial_flow.cells,spatial_flow.cell_count*sizeof(*spatial_flow.cells));
        REJECT_ALIAS(tpmshx_preparation_3d_spatial_resolve_flow_v1,grid,spatial_flow,
            spatial_flow.flow.evidence.ranges,spatial_flow.flow.evidence.range_count*sizeof(*spatial_flow.flow.evidence.ranges));
        REJECT_ALIAS(tpmshx_preparation_3d_spatial_resolve_flow_v1,grid,spatial_flow,
            spatial_flow.flow.input.sco2_nu.source.data,spatial_flow.flow.input.sco2_nu.source.size);
        spatial_flow.struct_size=0;
        REJECT_ALIAS(tpmshx_preparation_3d_spatial_resolve_flow_v1,grid,spatial_flow,
            spatial_flow.flow.evidence.ranges,spatial_flow.flow.evidence.range_count*sizeof(*spatial_flow.flow.evidence.ranges));
        spatial_flow.struct_size=sizeof(spatial_flow);
        grid.input.abi_version=0;
        REJECT_ALIAS(tpmshx_preparation_3d_spatial_resolve_flow_v1,grid,spatial_flow,
            spatial_flow.flow.evidence.ranges,spatial_flow.flow.evidence.range_count*sizeof(*spatial_flow.flow.evidence.ranges));
        grid.input.abi_version=1;
        tpmshx_preparation_3d_spatial_flow_release_v1(&spatial_flow);
        CHECK(!tpmshx_preparation_3d_spatial_prepare_case_v1(&grid,&options,NULL,&spatial_case,&failure,error,sizeof(error)));
        CHECK(spatial_case.have_side_geometry && spatial_case.side_b_porosity.data!=spatial_case.prepared.side_porosity.data);
        REJECT_ALIAS(tpmshx_preparation_3d_spatial_prepare_case_v1,grid,spatial_case,
            spatial_case.prepared.permeability.data,spatial_case.prepared.permeability.size*sizeof(double));
        REJECT_ALIAS(tpmshx_preparation_3d_spatial_prepare_case_v1,grid,spatial_case,
            spatial_case.cells,spatial_case.cell_count*sizeof(*spatial_case.cells));
        REJECT_ALIAS(tpmshx_preparation_3d_spatial_prepare_case_v1,grid,spatial_case,
            spatial_case.side_b_porosity.data,spatial_case.side_b_porosity.size*sizeof(double));
        REJECT_ALIAS(tpmshx_preparation_3d_spatial_prepare_case_v1,grid,spatial_case,
            spatial_case.area_density_per_m.data,spatial_case.area_density_per_m.size*sizeof(double));
        REJECT_ALIAS(tpmshx_preparation_3d_spatial_prepare_case_v1,grid,spatial_case,
            spatial_case.flow.input.sco2_nu.source.data,spatial_case.flow.input.sco2_nu.source.size);
        tpmshx_preparation_3d_spatial_case_release_v1(&spatial_case);

        CHECK(!tpmshx_preparation_3d_continuous_resolve_flow_v1(&continuous,&options,NULL,&continuous_flow,&failure,error,sizeof(error)));
        CHECK(continuous_flow.flow.evidence.range_count>0);
        saved_continuous_flow=continuous_flow;
        CHECK(tpmshx_preparation_3d_continuous_capacities_v1(&continuous,&options,NULL,&continuous_flow,&failure,error,sizeof(error))==1);
        CHECK(strstr(error,"release") && !memcmp(&continuous_flow,&saved_continuous_flow,sizeof(continuous_flow)));
        CHECK(tpmshx_preparation_3d_continuous_resolve_flow_v1(&continuous,&options,NULL,&continuous_flow,&failure,error,sizeof(error))==1);
        CHECK(strstr(error,"release") && !memcmp(&continuous_flow,&saved_continuous_flow,sizeof(continuous_flow)));
        REJECT_ALIAS(tpmshx_preparation_3d_continuous_resolve_flow_v1,continuous,continuous_flow,
            continuous_flow.controls.decision_mm.data,continuous_flow.controls.decision_mm.size*sizeof(double));
        REJECT_ALIAS(tpmshx_preparation_3d_continuous_resolve_flow_v1,continuous,continuous_flow,
            continuous_flow.flow.evidence.ranges,continuous_flow.flow.evidence.range_count*sizeof(*continuous_flow.flow.evidence.ranges));
        continuous_flow.struct_size=0;
        REJECT_ALIAS(tpmshx_preparation_3d_continuous_resolve_flow_v1,continuous,continuous_flow,
            continuous_flow.flow.evidence.ranges,continuous_flow.flow.evidence.range_count*sizeof(*continuous_flow.flow.evidence.ranges));
        continuous_flow.struct_size=sizeof(continuous_flow);
        tpmshx_preparation_3d_continuous_flow_release_v1(&continuous_flow);
        CHECK(!tpmshx_preparation_3d_continuous_prepare_case_v1(&continuous,&options,NULL,&continuous_case,&failure,error,sizeof(error)));
        REJECT_ALIAS(tpmshx_preparation_3d_continuous_prepare_case_v1,continuous,continuous_case,
            continuous_case.prepared.permeability.data,continuous_case.prepared.permeability.size*sizeof(double));
        REJECT_ALIAS(tpmshx_preparation_3d_continuous_prepare_case_v1,continuous,continuous_case,
            continuous_case.area_density_per_m.data,continuous_case.area_density_per_m.size*sizeof(double));
        REJECT_ALIAS(tpmshx_preparation_3d_continuous_prepare_case_v1,continuous,continuous_case,
            continuous_case.controls.decision_mm.data,continuous_case.controls.decision_mm.size*sizeof(double));
        REJECT_ALIAS(tpmshx_preparation_3d_continuous_prepare_case_v1,continuous,continuous_case,
            continuous_case.flow.input.sco2_nu.source.data,continuous_case.flow.input.sco2_nu.source.size);
        tpmshx_preparation_3d_continuous_case_release_v1(&continuous_case);

        /* The experimental air-water campaign domain gives each side owned drag provenance text. */
        experimental=continuous;experimental.have_explicit_targets=0;
        experimental.input.lengths_m[0]=.182;experimental.input.lengths_m[1]=experimental.input.lengths_m[2]=.042;
        experimental.input.df_mode=1;experimental.input.sides[1].fluid=1;
        experimental.input.sides[0].temperature_K=350.;experimental.input.sides[0].pressure_Pa=200000.;
        experimental.input.sides[0].velocity_m_s=14.;
        experimental.input.sides[1].temperature_K=320.;experimental.input.sides[1].pressure_Pa=200000.;
        experimental.input.sides[1].velocity_m_s=.12;
        CHECK(!tpmshx_preparation_3d_continuous_prepare_case_v1(&experimental,&options,NULL,&drag_case,&failure,error,sizeof(error)));
        CHECK(drag_case.drag[0].transfer_policy.size && drag_case.drag[1].transfer_policy.size);
        REJECT_ALIAS(tpmshx_preparation_3d_continuous_prepare_case_v1,experimental,drag_case,
            drag_case.drag[0].transfer_policy.data,drag_case.drag[0].transfer_policy.size);
        tpmshx_preparation_3d_continuous_case_release_v1(&drag_case);
    }
    puts("3D preparation C ownership and failure checks passed");
    return 0;
}
