#include "tpmshx/preparation_case_3d_c_api.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

#define CHECK(test) do { if (!(test)) { fprintf(stderr, "line %d: %s\n", __LINE__, #test); return 1; } } while (0)

static int TPMSHX_PREPARATION_CALL stop_event(void* context,const tpmshx_preparation_event_v1* event) {
    size_t* count=(size_t*)context;
    if (event) ++*count;
    return 1;
}
int main(void) {
    tpmshx_preparation_case_input_3d_v1 input={0},original;
    tpmshx_preparation_case_3d_v1 output={0},before;
    tpmshx_preparation_case_failure_v2 failure={0},saved_failure;
    tpmshx_preparation_case_options_v1 options={1,sizeof(options),0,1,0.};
    tpmshx_preparation_case_callbacks_v1 callback={1,sizeof(callback),stop_event,NULL};
    const tpmshx_preparation_scalar_kind_v2 weak={64,0,0};
    const tpmshx_grid_scalar_v1 dimensions[3]={{.182,64,0},{.042,64,0},{.031,64,0}};
    char error[4096],saved_error[4096],source[]="source";
    size_t i,calls=0;
    input.abi_version=output.abi_version=1;input.struct_size=sizeof(input);output.struct_size=sizeof(output);
    failure.abi_version=2;failure.struct_size=sizeof(failure);
    for (i=0;i<3;++i) input.lengths_m[i]=dimensions[i];
    input.counts[0]=6;input.counts[1]=5;input.counts[2]=4;input.max_cells=2000000;
    input.topology=1;input.cell_length_mm=7.;input.wall_thickness_mm=.6;input.solid_conductivity_W_mK=16.;
    input.kinds.cell_length=input.kinds.wall_thickness=input.kinds.solid_conductivity=weak;
    for (i=0;i<2;++i) {
        input.sides[i].port.active=1;
        input.kinds.sides[i].velocity=input.kinds.sides[i].temperature=input.kinds.sides[i].pressure=weak;
        input.sides[i].velocity_m_s=5.;input.sides[i].temperature_K=i?300.:400.;input.sides[i].pressure_Pa=101325.;
    }
    input.sides[1].port.direction=5;
    input.sco2_nu.source.data=source;input.sco2_nu.source.size=strlen(source);original=input;
    CHECK(tpmshx_preparation_case_3d_abi_version_v1()==1);
    CHECK(!tpmshx_prepare_case_3d_v1(&input,&options,NULL,&output,&failure,error,sizeof(error)));
    CHECK(!failure.kind && output.owner && !memcmp(&input,&original,sizeof(input)));
    CHECK(output.cell_length.size==120 && output.sides[1].inlet_opening.size==30 && output.sides[1].axes[6]==1);
    CHECK(output.geometry.epsilon_a==output.side_porosity.data[0] && isfinite(output.solid_conductivity.data[0]));
    CHECK(output.input.sco2_nu.source.data!=source);source[0]='X';
    CHECK(!memcmp(output.input.sco2_nu.source.data,"source",6));before=output;
    CHECK(tpmshx_prepare_case_3d_v1(&input,&options,NULL,&output,&failure,error,sizeof(error))==1);
    CHECK(!memcmp(&output,&before,sizeof(output)));
    tpmshx_preparation_case_3d_release_v1(&output);CHECK(!output.owner && !output.struct_size);
    tpmshx_preparation_case_3d_release_v1(&output);tpmshx_preparation_case_3d_release_v1(NULL);
    output.abi_version=1;output.struct_size=sizeof(output);before=output;
    input.sides[0].velocity_m_s=1e-9;callback.context=&calls;
    CHECK(tpmshx_prepare_case_3d_v1(&input,&options,&callback,&output,&failure,error,sizeof(error))==3);
    CHECK(calls==1 && failure.kind==3 && !memcmp(&before,&output,sizeof(output)));
    input=original;input.max_cells=119;
    CHECK(tpmshx_prepare_case_3d_v1(&input,&options,NULL,&output,&failure,error,sizeof(error))==1);
    CHECK(strstr(error,"3D grid 6x5x4 exceeds the 119-cell cap") && !memcmp(&before,&output,sizeof(output)));
    memset(error,17,sizeof(error));memcpy(saved_error,error,sizeof(error));saved_failure=failure;
    CHECK(tpmshx_prepare_case_3d_v1(&input,&options,NULL,&output,
        (tpmshx_preparation_case_failure_v2*)&output,error,sizeof(error))==1);
    CHECK(!memcmp(&before,&output,sizeof(output)) && !memcmp(error,saved_error,sizeof(error)));
    CHECK(!memcmp(&failure,&saved_failure,sizeof(failure)));
    puts("3D preparation C ownership and failure checks passed");
    return 0;
}
