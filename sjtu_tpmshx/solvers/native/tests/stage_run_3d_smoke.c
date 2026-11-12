#include <tpmshx/stage_run_3d_c_api.h>
#include <stdio.h>
#include <string.h>

#define REQUIRE(value) do {if(!(value)){fprintf(stderr,"3D C stage check failed at %d: %s\n",__LINE__,error);return 1;}} while(0)
static int TPMSHX_THERMAL_CALL cancel(void* context) {(void)context;return 1;}
int main(void) {
    char error[4096]="unchanged";
    tpmshx_preparation_case_input_3d_v1 input={0};
    tpmshx_preparation_case_options_v1 options={0};
    tpmshx_preparation_case_3d_v1 prepared={0};
    tpmshx_preparation_case_failure_v2 failure={0};
    tpmshx_stage_run_request_3d_v1 request={0};
    tpmshx_stage_run_control_3d_v1 control={0};
    tpmshx_stage_run_result_3d_v1 result={0},before;
    tpmshx_run_state_v1 snapshot={0};
    tpmshx_stage_capture_3d_v1 capture={0};
    tpmshx_stage_output_v1 report={0};
    tpmshx_result_diagnostics_v1 diagnostics={0};uint64_t token=0;
    void* run=NULL;void* restored=NULL;uint32_t phase=0;size_t i;
    REQUIRE(tpmshx_stage_capture_3d_abi_version()==1);
    input.abi_version=1;input.struct_size=sizeof(input);input.max_cells=2000000;
    input.lengths_m[0].value=.182;input.lengths_m[1].value=.042;input.lengths_m[2].value=.031;
    for(i=0;i<3;++i)input.lengths_m[i].precision=64;
    input.counts[0]=6;input.counts[1]=5;input.counts[2]=4;
    input.topology=1;input.cell_length_mm=7.;input.wall_thickness_mm=.6;input.solid_conductivity_W_mK=16.;
    input.kinds.cell_length.precision=input.kinds.wall_thickness.precision=input.kinds.solid_conductivity.precision=64;
    for(i=0;i<2;++i) {
        input.sides[i].port.active=1;input.sides[i].pressure_Pa=200000.;
        input.kinds.sides[i].velocity.precision=input.kinds.sides[i].temperature.precision=input.kinds.sides[i].pressure.precision=64;
    }
    input.sides[0].velocity_m_s=6.;input.sides[0].temperature_K=350.;
    input.sides[1].fluid=1;input.sides[1].velocity_m_s=.02;input.sides[1].temperature_K=320.;input.sides[1].port.direction=3;
    options.abi_version=1;options.struct_size=sizeof(options);options.allow_extrapolation=1;
    prepared.abi_version=1;prepared.struct_size=sizeof(prepared);failure.abi_version=2;failure.struct_size=sizeof(failure);
    REQUIRE(tpmshx_prepare_case_3d_v1(&input,&options,NULL,&prepared,&failure,error,sizeof(error))==0);
    request.abi_version=1;request.struct_size=sizeof(request);
    request.max_iter_simple.present=request.max_outer_ltne.present=1;
    request.max_iter_simple.value=12;request.max_outer_ltne.value=2;
    request.model_h.max_iterations=9;request.model_h.temperature_tolerance=.5;request.model_h.q_relative_tolerance=1e-3;
    control.result_id="plain-C-3d";control.cpu_threads=2;
    result.abi_version=1;result.struct_size=sizeof(result);before=result;
    REQUIRE(tpmshx_run_case_3d_v1(&prepared,NULL,NULL,&request,&control,&result,(char*)&prepared,sizeof(prepared))==1);
    REQUIRE(memcmp(&result,&before,sizeof(result))==0);
    REQUIRE(tpmshx_stage_run_3d_create_v1(&prepared,NULL,NULL,&request,&control,&run,error,sizeof(error))==0);
    REQUIRE(tpmshx_stage_run_3d_take_result_v1(run,&result,error,sizeof(error))!=0);
    REQUIRE(memcmp(&result,&before,sizeof(result))==0);
    REQUIRE(tpmshx_stage_run_3d_advance_step_v1(run,&phase,error,sizeof(error))==0);
    REQUIRE(tpmshx_stage_run_3d_snapshot_v1(run,&snapshot,error,sizeof(error))==0);
    tpmshx_stage_run_3d_release_run_v1(&run);REQUIRE(run==NULL);
    control.cpu_threads=1;
    REQUIRE(tpmshx_stage_run_3d_restore_v1(&prepared,NULL,NULL,&request,&control,
        snapshot.fields,snapshot.count,&restored,error,sizeof(error))==0);
    tpmshx_run_state_release_v1(&snapshot);
    while(phase!=TPMSHX_FULL3D_COMPLETED)REQUIRE(tpmshx_stage_run_3d_advance_step_v1(restored,&phase,error,sizeof(error))==0);
    REQUIRE(tpmshx_stage_run_3d_take_result_v1(restored,&result,error,sizeof(error))==0);
    tpmshx_stage_run_3d_release_run_v1(&restored);
    tpmshx_preparation_case_3d_release_v1(&prepared);
    REQUIRE(result.raw.stop<=1 && result.evidence.dimension==3 && result.evidence.field_count==25);
    REQUIRE(tpmshx_stage_run_3d_get_capture_v1(&result,1,&capture)==0);
    REQUIRE(capture.model_h_cell_count==120 && capture.audit_outlet[0].size==20);
    report.struct_size=sizeof(report);
    REQUIRE(tpmshx_result_stage_query_v2(&result.evaluation,0,NULL,NULL,0,&report,&diagnostics,&token,error,sizeof(error))==0);
    REQUIRE(report.json && report.metric_count==15);
    tpmshx_result_stage_release_v1(&report);tpmshx_stage_run_3d_release_v1(&result);
    REQUIRE(!result.owner);tpmshx_stage_run_3d_release_v1(&result);
    prepared.abi_version=1;prepared.struct_size=sizeof(prepared);
    REQUIRE(tpmshx_prepare_case_3d_v1(&input,&options,NULL,&prepared,&failure,error,sizeof(error))==0);
    request.model_h.max_iterations=0;request.model_h.temperature_tolerance=0.;request.model_h.q_relative_tolerance=0.;
    request.variable_rho_cp.present=request.thermal_iterations.present=1;
    request.variable_rho_cp.value=0;request.thermal_iterations.value=9;
    result.abi_version=1;result.struct_size=sizeof(result);
    REQUIRE(tpmshx_run_case_3d_v1(&prepared,NULL,NULL,&request,&control,&result,error,sizeof(error))==0);
    REQUIRE(result.evaluation.none_count==2);
    report.struct_size=sizeof(report);
    REQUIRE(tpmshx_result_stage_query_v2(&result.evaluation,0,NULL,NULL,0,&report,&diagnostics,&token,error,sizeof(error))==0);
    for(i=0;i<report.metric_count;++i)if(!strcmp(report.metrics[i].name,"T_out_A"))break;
    REQUIRE(i<report.metric_count && !strcmp(report.metrics[i].reason,"missing or incomplete evidence: 'native boundary faces'"));
    tpmshx_result_stage_release_v1(&report);tpmshx_stage_run_3d_release_v1(&result);
    result.abi_version=1;result.struct_size=sizeof(result);control.callbacks.cancel=cancel;
    REQUIRE(tpmshx_run_case_3d_v1(&prepared,NULL,NULL,&request,&control,&result,error,sizeof(error))==0);
    REQUIRE(result.raw.stop==2 && result.evidence.abi_version==0);
    capture.q_net=123.;
    REQUIRE(tpmshx_stage_run_3d_get_capture_v1(&result,0,&capture)==1 && capture.q_net==123.);
    tpmshx_preparation_case_3d_release_v1(&prepared);tpmshx_stage_run_3d_release_v1(&result);
    puts("Plain C 3D prepare/run/restore/evaluate passed");return 0;
}
