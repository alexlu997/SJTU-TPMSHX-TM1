#include "tpmshx/quick_design_stage_c_api.h"
#include <fenv.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static tpmshx_preparation_text_v1 text(const char* value) {
    tpmshx_preparation_text_v1 output={value,strlen(value)};return output;
}
static tpmshx_quick_input_v2 input(void) {
    tpmshx_quick_input_v2 value={0};size_t n;
    const double numbers[]={7.,.5,.084,.025,.07,16.,1e-5,.03,.02,480.,320.,9e6,9e6};
    value.abi_version=2;value.struct_size=sizeof(value);
    for(n=0;n<TPMSHX_QUICK_VALUE_COUNT;++n)value.values[n]=numbers[n];
    value.topology=text("Diamond");value.arrangement=text("cross");value.property_mode=text("const");
    value.fluids[0]=text("air");value.fluids[1]=text("air");value.have_height=1;
    return value;
}
static tpmshx_quick_prepared_v2 prepared(void) {
    tpmshx_quick_prepared_v2 value={0};value.abi_version=2;value.struct_size=sizeof(value);return value;
}
static tpmshx_quick_pressure_v2 pressure(void) {
    tpmshx_quick_pressure_v2 value={0};value.abi_version=2;value.struct_size=sizeof(value);return value;
}
struct context {
    uint32_t stop;
    uint32_t populated;tpmshx_preparation_geometry_cache_v3 geometry;
    uint32_t eos_have[4];double eos_values[4][5];size_t eos_sizes[4];
    size_t eos_lookups,eos_hits,eos_stores,eos_bad_size;
};
static int TPMSHX_PREPARATION_CALL cached_geometry(void* raw,uint32_t action,
    tpmshx_preparation_geometry_cache_v3* value,uint32_t* hit) {
    struct context* state=(struct context*)raw;
    if(action==0) {
        *hit=state->populated;
        if(*hit)*value=state->geometry;
    } else {state->geometry=*value;state->populated=1;*hit=0;}
    return 0;
}
static int TPMSHX_PREPARATION_CALL cached_eos(void* raw,uint32_t action,uint32_t fluid,uint32_t index,
    double temperature,double pressure,double* values,size_t capacity,size_t* count,uint32_t* hit) {
    struct context* state=(struct context*)raw;
    const size_t at=fluid==3?0:index;
    (void)temperature;(void)pressure;
    if(state->stop)return 1;
    if(action==0) {
        ++state->eos_lookups;*hit=state->eos_have[at];
        if(*hit) {
            ++state->eos_hits;*count=state->eos_bad_size?state->eos_bad_size:state->eos_sizes[at];
            if(state->eos_sizes[at]>capacity)return 1;
            memcpy(values,state->eos_values[at],state->eos_sizes[at]*sizeof(double));
        }
        return 0;
    }
    ++state->eos_stores;state->eos_have[at]=1;state->eos_sizes[at]=*count;
    if(*count>5)return 1;
    memcpy(state->eos_values[at],values,*count*sizeof(double));
    return 0;
}
#define CHECK(test) do {if(!(test)){fprintf(stderr,"Quick prepare check failed at line %d\n",__LINE__);return 1;}} while(0)
int main(void) {
    tpmshx_quick_input_v2 raw=input();tpmshx_quick_prepared_v2 full=prepared();
    tpmshx_quick_pressure_v2 dp=pressure();char error[4096]={0};size_t n;
    struct context state={0};
    {
        double values[]={1.,0.,4.,1.};
        const uint64_t signaling_nan=UINT64_C(0x7ff0000000000001);
        const tpmshx_preparation_array_v1 input_values={values,4};
        tpmshx_preparation_range_sample_v1 sample={0};
        const tpmshx_preparation_array_v1 alias={&sample.minimum,1};
        memcpy(&values[1],&signaling_nan,sizeof(signaling_nan));
        CHECK(feclearexcept(FE_ALL_EXCEPT)==0);
        CHECK(tpmshx_preparation_collect_range_v1(input_values,2.,3.,&sample,error,sizeof(error))==0);
        CHECK(!fetestexcept(FE_INVALID) && sample.have_finite && sample.nonfinite==1);
        CHECK(sample.minimum==1. && sample.minimum_index==0 && sample.maximum==4. && sample.maximum_index==2);
        CHECK(sample.low==2 && sample.high==1 && sample.size==4);
        CHECK(tpmshx_preparation_collect_range_v1(alias,2.,3.,&sample,error,sizeof(error))==TPMSHX_PREPARATION_INVALID);
        CHECK(sample.minimum==1. && sample.size==4);
    }
    tpmshx_quick_callbacks_v2 callbacks={0};callbacks.abi_version=2;callbacks.struct_size=sizeof(callbacks);
    callbacks.context=&state;
    CHECK(tpmshx_quick_pressure_fractions_v2(&raw,&callbacks,&dp,error,sizeof(error))==0);
    CHECK(dp.fractions[0]>0. && dp.fractions[1]>0. && dp.range_count==6);
    CHECK(!strcmp(dp.ranges[0].label,"air_viscosity") && dp.ranges[0].side==0);
    CHECK(dp.ranges[0].bounds[0]==200. && dp.ranges[0].bounds[1]==1100. && dp.ranges[0].temperature_K==480.);
    CHECK(dp.ranges[3].side==1 && dp.ranges[3].temperature_K==320.);
    for(n=0;n<4;++n)CHECK(dp.floating_events[n]==0);
    CHECK(tpmshx_prepare_quick_design_v2(&raw,0,&full,error,sizeof(error))==0);
    CHECK(full.owner && full.shape[0]==60 && full.shape[1]==40 && full.shape[2]==1);
    CHECK(full.epsilon.size==2400 && full.solid_conductivity.size==2400);
    CHECK(full.controls.have_q_relative_tolerance && full.controls.have_chunk_iterations);
    CHECK(full.controls.q_relative_tolerance==1e-4 && full.controls.chunk_iterations==100);
    for(n=0;n<2;++n)CHECK(full.fractions[n]==dp.fractions[n]);
    CHECK(full.widths[0].size==60 && full.edges[0].size==61 && full.range_count==6);
    CHECK(full.cell_length_m==.007 && full.wall_thickness_m==.0005);
    tpmshx_quick_prepared_release_v2(&full);CHECK(!full.owner && !full.epsilon.data);
    tpmshx_quick_prepared_release_v2(&full);

    {
        double conductivity,fraction;
        raw.topology=text("Gyroid");callbacks.geometry_cache=cached_geometry;full=prepared();
        CHECK(tpmshx_prepare_quick_design_v2(&raw,&callbacks,&full,error,sizeof(error))==0);
        CHECK(state.populated);conductivity=full.solid_conductivity.data[0];fraction=full.fractions[0];
        tpmshx_quick_prepared_release_v2(&full);full=prepared();
        CHECK(tpmshx_prepare_quick_design_v2(&raw,&callbacks,&full,error,sizeof(error))==0);
        CHECK(full.solid_conductivity.data[0]==conductivity && full.fractions[0]==fraction);
        tpmshx_quick_prepared_release_v2(&full);callbacks.geometry_cache=0;raw=input();state.populated=0;
    }

    full=prepared();raw.arrangement=text("counter");
    CHECK(tpmshx_prepare_quick_design_v2(&raw,0,&full,error,sizeof(error))==0);
    CHECK(full.shape[1]==1 && full.shape[2]==2);
    CHECK(!full.controls.have_q_relative_tolerance && !full.controls.have_chunk_iterations);
    tpmshx_quick_prepared_release_v2(&full);

    raw=input();raw.arrangement=text("anything");dp=pressure();
    CHECK(tpmshx_quick_pressure_fractions_v2(&raw,0,&dp,error,sizeof(error))==0);
    full=prepared();CHECK(tpmshx_prepare_quick_design_v2(&raw,0,&full,error,sizeof(error))!=0 && !full.owner);
    raw=input();raw.values[TPMSHX_QUICK_SPAN]=NAN;full=prepared();
    CHECK(tpmshx_prepare_quick_design_v2(&raw,0,&full,error,sizeof(error))==TPMSHX_PREPARATION_INVALID && !full.owner);
    raw=input();dp=pressure();
    CHECK(tpmshx_quick_pressure_fractions_v2(&raw,0,&dp,(char*)&dp,sizeof(dp))==TPMSHX_PREPARATION_INVALID);
    CHECK(dp.fractions[0]==0. && !dp.range_count);

    raw=input();raw.fluids[0]=text("water");raw.values[TPMSHX_QUICK_TEMPERATURE_A]=350.;
    raw.values[TPMSHX_QUICK_PRESSURE_A]=10000.;dp=pressure();
    CHECK(tpmshx_quick_pressure_fractions_v2(&raw,0,&dp,error,sizeof(error))==TPMSHX_PREPARATION_WATER_STATE);
    CHECK(dp.fractions[0]==0. && strstr(error,"quick-design properties: water index=(), T=350 K"));
    {
        const char* fluids[]={"water","sco2","co2"};size_t fluid;
        for(fluid=0;fluid<3;++fluid) {
            raw=input();raw.fluids[0]=text(fluids[fluid]);dp=pressure();full=prepared();
            if(fluid==0) {
                raw.values[TPMSHX_QUICK_TEMPERATURE_A]=350.;
                raw.values[TPMSHX_QUICK_PRESSURE_A]=200000.;
            }
            CHECK(tpmshx_quick_pressure_fractions_v2(&raw,0,&dp,error,sizeof(error))==0);
            CHECK(tpmshx_prepare_quick_design_v2(&raw,0,&full,error,sizeof(error))==0);
            for(n=0;n<2;++n)CHECK(isfinite(dp.fractions[n]) && dp.fractions[n]>0. &&
                dp.fractions[n]==full.fractions[n]);
            tpmshx_quick_prepared_release_v2(&full);
        }
    }
    {
        const char* fluids[]={"sco2","co2"};size_t fluid;
        callbacks.eos_cache=cached_eos;
        for(fluid=0;fluid<2;++fluid) {
            double first;memset(&state,0,sizeof(state));
            raw=input();raw.fluids[0]=text(fluids[fluid]);dp=pressure();full=prepared();
            CHECK(tpmshx_quick_pressure_fractions_v2(&raw,&callbacks,&dp,error,sizeof(error))==0);
            first=dp.fractions[0];CHECK(dp.range_count==3 && dp.ranges[0].side==1);
            CHECK(state.eos_lookups==4 && state.eos_stores==(fluid?1u:4u) && state.eos_hits==(fluid?3u:0u));
            CHECK(tpmshx_prepare_quick_design_v2(&raw,&callbacks,&full,error,sizeof(error))==0);
            CHECK(full.fractions[0]==first && state.eos_lookups==8 && state.eos_hits==(fluid?7u:4u));
            tpmshx_quick_prepared_release_v2(&full);
            dp=pressure();state.eos_bad_size=2;
            CHECK(tpmshx_quick_pressure_fractions_v2(&raw,&callbacks,&dp,error,sizeof(error))!=0);
            CHECK(dp.fractions[0]==0.);state.eos_bad_size=0;state.stop=1;
            CHECK(tpmshx_quick_pressure_fractions_v2(&raw,&callbacks,&dp,error,sizeof(error))==TPMSHX_QUICK_HOST_FAILURE);
            CHECK(dp.fractions[0]==0.);
        }
    }
    puts("Quick preparation v2: owned fields, controls, ranges, EOS caches and failure boundaries passed");
    return 0;
}
