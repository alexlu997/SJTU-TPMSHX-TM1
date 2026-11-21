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
    for(n=0;n<TPMSHX_QUICK_VALUE_COUNT;++n) {
        value.values[n].value=numbers[n];value.values[n].precision=64;
    }
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
    size_t widths,properties,pressures;uint32_t stop;void* alias;
    double typed_conductivity,typed_wall;
    uint32_t populated;tpmshx_preparation_geometry_cache_v3 geometry;
    uint32_t use_eos,eos_have[4];double eos_values[4][5];size_t eos_sizes[4];
    size_t eos_lookups,eos_hits,eos_stores,eos_bad_size;void* eos_alias;
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
static int TPMSHX_PREPARATION_CALL observe(void* raw,tpmshx_quick_host_request_v2* request) {
    struct context* state=(struct context*)raw;
    if(request->operation==TPMSHX_QUICK_WIDTH_PACK)++state->widths;
    if(request->operation==TPMSHX_QUICK_GEOMETRY_PACK && state->typed_wall) {
        request->text=text("Gyroid");
        request->scalars[1].value=state->typed_wall;
        request->scalars[1].precision=16;request->scalars[1].strong=1;
        request->scalars[0].strong=1;
    }
    if(request->operation==TPMSHX_QUICK_MATERIAL_PACK && state->typed_conductivity) {
        request->text=text("Gyroid");
        request->scalars[0].value=state->typed_conductivity;
        request->scalars[0].precision=16;request->scalars[0].strong=1;
        request->scalars[2].precision=64;request->scalars[2].strong=1;
    }
    if(request->operation==TPMSHX_QUICK_PROPERTY_RESULT)++state->properties;
    if(request->operation==TPMSHX_QUICK_PRESSURE_RESULT)++state->pressures;
    if(request->operation==TPMSHX_QUICK_PROPERTY_PACK && request->flags[0]==0) {
        if(request->flags[2]!=1 || (request->index==0 && request->text.size))return 1;
        if(request->index==1) {
            const char label[]="air_viscosity";
            if(request->text.size!=sizeof(label)-1 || !request->text.data ||
               memcmp(request->text.data,label,sizeof(label)-1) ||
               request->scalars[0].value!=200. || request->scalars[1].value!=1100.)return 1;
        }
    }
    if(state->alias && request->operation==TPMSHX_QUICK_PROPERTY_PACK) {
        request->property_inputs[0].values=(const double*)state->alias;
        request->property_inputs[0].count=1;
    }
    if(state->use_eos && request->operation==TPMSHX_QUICK_EOS_CACHE_LOOKUP) {
        size_t at=request->flags[0]==3?0:request->index;
        ++state->eos_lookups;
        if(state->eos_have[at]) {
            ++state->eos_hits;request->flags[1]=1;
            request->property_values.data=state->eos_alias?(const double*)state->eos_alias:state->eos_values[at];
            request->property_values.size=state->eos_bad_size?state->eos_bad_size:state->eos_sizes[at];
        }
    }
    if(state->use_eos && request->operation==TPMSHX_QUICK_EOS_CACHE_STORE) {
        size_t at=request->flags[0]==3?0:request->index;
        ++state->eos_stores;state->eos_have[at]=1;state->eos_sizes[at]=request->property_values.size;
        if(request->property_values.size>5)return 1;
        memcpy(state->eos_values[at],request->property_values.data,request->property_values.size*sizeof(double));
    }
    return request->operation==state->stop;
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
    callbacks.context=&state;callbacks.host=observe;
    CHECK(tpmshx_quick_pressure_fractions_v2(&raw,&callbacks,&dp,error,sizeof(error))==0);
    CHECK(state.widths==0 && state.properties==10 && state.pressures==2);
    CHECK(dp.fractions[0].value>0. && dp.fractions[1].value>0.);
    CHECK(tpmshx_prepare_quick_design_v2(&raw,0,&full,error,sizeof(error))==0);
    CHECK(full.owner && full.shape[0]==60 && full.shape[1]==40 && full.shape[2]==1);
    CHECK(full.epsilon.size==2400 && full.solid_conductivity.size==2400);
    CHECK(full.controls.have_q_relative_tolerance && full.controls.have_chunk_iterations);
    CHECK(full.controls.q_relative_tolerance==1e-4 && full.controls.chunk_iterations==100);
    for(n=0;n<2;++n)CHECK(full.fractions[n].value==dp.fractions[n].value);
    CHECK(full.widths[0].size==60 && full.edges[0].size==61 && full.width_precision[0]==64);
    CHECK(full.cell_length_m.value==.007 && full.wall_thickness_m.value==.0005);
    tpmshx_quick_prepared_release_v2(&full);CHECK(!full.owner && !full.epsilon.data);
    tpmshx_quick_prepared_release_v2(&full);

    {
        double conductivity,fraction;
        raw.topology=text("Gyroid");callbacks.geometry_cache=cached_geometry;full=prepared();
        state.typed_conductivity=16.3;state.typed_wall=.5119;
        CHECK(tpmshx_prepare_quick_design_v2(&raw,&callbacks,&full,error,sizeof(error))==0);
        CHECK(state.populated);conductivity=full.solid_conductivity.data[0];fraction=full.fractions[0].value;
        tpmshx_quick_prepared_release_v2(&full);full=prepared();
        state.typed_conductivity=16.296875; /* 16.3 rounded to binary16. */
        CHECK(tpmshx_prepare_quick_design_v2(&raw,&callbacks,&full,error,sizeof(error))==0);
        CHECK(full.solid_conductivity.data[0]==conductivity && full.fractions[0].value==fraction);
        tpmshx_quick_prepared_release_v2(&full);full=prepared();
        state.populated=0;state.typed_wall=.51171875; /* .5119 rounded to binary16. */
        CHECK(tpmshx_prepare_quick_design_v2(&raw,&callbacks,&full,error,sizeof(error))==0);
        CHECK(full.solid_conductivity.data[0]==conductivity && full.fractions[0].value==fraction);
        tpmshx_quick_prepared_release_v2(&full);callbacks.geometry_cache=0;raw=input();
        state.typed_conductivity=0.;state.typed_wall=0.;
    }

    full=prepared();raw.arrangement=text("counter");raw.values[TPMSHX_QUICK_SPAN].precision=32;
    raw.values[TPMSHX_QUICK_SPAN].strong=1;
    CHECK(tpmshx_prepare_quick_design_v2(&raw,0,&full,error,sizeof(error))==0);
    CHECK(full.shape[1]==1 && full.shape[2]==2 && full.width_precision[1]==32);
    CHECK(!full.controls.have_q_relative_tolerance && !full.controls.have_chunk_iterations);
    tpmshx_quick_prepared_release_v2(&full);

    raw=input();raw.arrangement=text("anything");dp=pressure();
    CHECK(tpmshx_quick_pressure_fractions_v2(&raw,0,&dp,error,sizeof(error))==0);
    full=prepared();CHECK(tpmshx_prepare_quick_design_v2(&raw,0,&full,error,sizeof(error))!=0 && !full.owner);
    raw=input();dp=pressure();state.stop=TPMSHX_QUICK_FLOW_PACK;state.pressures=0;
    CHECK(tpmshx_quick_pressure_fractions_v2(&raw,&callbacks,&dp,error,sizeof(error))==TPMSHX_QUICK_HOST_FAILURE);
    CHECK(state.pressures==0 && dp.fractions[0].precision==0);
    state.stop=0;state.alias=&dp;
    CHECK(tpmshx_quick_pressure_fractions_v2(&raw,&callbacks,&dp,error,sizeof(error))!=0);
    CHECK(dp.fractions[0].precision==0);state.alias=0;
    CHECK(tpmshx_quick_pressure_fractions_v2(&raw,0,&dp,(char*)&dp,sizeof(dp))==TPMSHX_PREPARATION_INVALID);
    CHECK(dp.fractions[0].precision==0);

    raw=input();raw.fluids[0]=text("water");raw.values[TPMSHX_QUICK_TEMPERATURE_A].value=350.;
    raw.values[TPMSHX_QUICK_PRESSURE_A].value=10000.;dp=pressure();
    CHECK(tpmshx_quick_pressure_fractions_v2(&raw,0,&dp,error,sizeof(error))==TPMSHX_PREPARATION_WATER_STATE);
    CHECK(dp.fractions[0].precision==0);
    {
        const char* fluids[]={"water","sco2","co2"};size_t fluid;
        for(fluid=0;fluid<3;++fluid) {
            raw=input();raw.fluids[0]=text(fluids[fluid]);dp=pressure();full=prepared();
            if(fluid==0) {
                raw.values[TPMSHX_QUICK_TEMPERATURE_A].value=350.;
                raw.values[TPMSHX_QUICK_PRESSURE_A].value=200000.;
            }
            CHECK(tpmshx_quick_pressure_fractions_v2(&raw,0,&dp,error,sizeof(error))==0);
            CHECK(tpmshx_prepare_quick_design_v2(&raw,0,&full,error,sizeof(error))==0);
            for(n=0;n<2;++n)CHECK(isfinite(dp.fractions[n].value) && dp.fractions[n].value>0. &&
                dp.fractions[n].value==full.fractions[n].value);
            tpmshx_quick_prepared_release_v2(&full);
        }
    }
    {
        const char* fluids[]={"sco2","co2"};size_t fluid;
        for(fluid=0;fluid<2;++fluid) {
            double first;memset(&state,0,sizeof(state));state.use_eos=1;
            raw=input();raw.fluids[0]=text(fluids[fluid]);dp=pressure();full=prepared();
            CHECK(tpmshx_quick_pressure_fractions_v2(&raw,&callbacks,&dp,error,sizeof(error))==0);
            first=dp.fractions[0].value;
            CHECK(state.eos_lookups==4 && state.eos_stores==(fluid?1u:4u) && state.eos_hits==(fluid?3u:0u));
            CHECK(tpmshx_prepare_quick_design_v2(&raw,&callbacks,&full,error,sizeof(error))==0);
            CHECK(full.fractions[0].value==first && state.eos_lookups==8 && state.eos_hits==(fluid?7u:4u));
            tpmshx_quick_prepared_release_v2(&full);
            dp=pressure();state.eos_bad_size=2;
            CHECK(tpmshx_quick_pressure_fractions_v2(&raw,&callbacks,&dp,error,sizeof(error))!=0);
            CHECK(dp.fractions[0].precision==0);state.eos_bad_size=0;state.eos_alias=&dp;
            CHECK(tpmshx_quick_pressure_fractions_v2(&raw,&callbacks,&dp,error,sizeof(error))!=0);
            CHECK(dp.fractions[0].precision==0);state.eos_alias=0;state.stop=TPMSHX_QUICK_EOS_CACHE_LOOKUP;
            CHECK(tpmshx_quick_pressure_fractions_v2(&raw,&callbacks,&dp,error,sizeof(error))==TPMSHX_QUICK_HOST_FAILURE);
            CHECK(dp.fractions[0].precision==0);
        }
    }
    puts("Quick preparation v2: owned fields, typed controls, EOS caches and failure boundaries passed");
    return 0;
}
