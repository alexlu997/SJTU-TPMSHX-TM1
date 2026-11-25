#include <tpmshx/stage_run_3d_c_api.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#define REQUIRE(value) do {if(!(value)){fprintf(stderr,"3D C stage check failed at %d: %s\n",__LINE__,error);return 1;}} while(0)
static int TPMSHX_THERMAL_CALL cancel(void* context) {(void)context;return 1;}
static tpmshx_full3d_array_v1 field(tpmshx_preparation_array_v1 source) {
    tpmshx_full3d_array_v1 view={source.data,source.size};
    return view;
}

/* Pack the flat saved v3 descriptor from a uniform 3D spatial preparation.
   Uniform geometry uses one area density and one hydraulic diameter. */
static void pack_saved(const tpmshx_preparation_case_3d_v1* p,tpmshx_stage_saved_case_3d_v3* saved,
        tpmshx_full3d_input_v1* raw) {
    size_t i,s;
    memset(saved,0,sizeof(*saved));memset(raw,0,sizeof(*raw));
    raw->area_density.data=&p->geometry.area_density_per_m;raw->area_density.size=1;
    raw->hydraulic_diameter.data=&p->geometry.hydraulic_diameter_m;raw->hydraulic_diameter.size=1;
    raw->epsilon=field(p->total_porosity);raw->epsilon_a=raw->epsilon_b=field(p->side_porosity);
    raw->cell_length=field(p->cell_length);raw->permeability=field(p->permeability);
    raw->forchheimer=field(p->forchheimer);raw->solid_conductivity=field(p->solid_conductivity);
    raw->topology=p->input.topology;raw->solve_b=1;
    raw->reference_hydraulic_diameter=p->geometry.hydraulic_diameter_m;
    raw->reference_cell_length=p->input.cell_length_mm*1e-3;
    saved->abi_version=TPMSHX_STAGE_RUN_3D_SAVED_ABI_VERSION;saved->struct_size=sizeof(*saved);
    saved->input=raw;saved->nominal_cell_length_mm=p->input.cell_length_mm;
    saved->nominal_wall_thickness_mm=p->input.wall_thickness_mm;
    saved->nominal_porosity=p->geometry.epsilon;saved->wall_thickness_m=p->wall_thickness;
    saved->preparation=p->evidence;saved->inlet_recorded=1;
    saved->notices=p->notices;saved->notice_count=p->notice_count;
    static const char* const fluid_names[]={"air","water","sco2","co2"};
    memcpy(saved->models,p->models,sizeof(saved->models));
    for(s=0;s<2;++s) {
        saved->resource_fluids[s].data=fluid_names[p->input.sides[s].fluid];
        saved->resource_fluids[s].size=strlen(saved->resource_fluids[s].data);
    }
    saved->resource_topology.data="Gyroid";saved->resource_topology.size=6;
    saved->sco2_nu=saved->resource_nu[0]=saved->resource_nu[1]=p->input.sco2_nu;
    for(i=0;i<3;++i) {
        raw->widths[i]=field(p->widths[i]);raw->shape[i]=p->widths[i].size;
        saved->lengths_m[i]=p->input.lengths_m[i];
    }
    for(s=0;s<2;++s) {
        tpmshx_full3d_side_v1* side=&raw->sides[s];
        tpmshx_stage_saved_axes_3d_v2* axes=&saved->axes[s];
        axes->port=p->input.sides[s].port;axes->reverse=axes->port.direction%2;
        side->fluid=p->input.sides[s].fluid;side->direction=(uint32_t)axes->port.direction;
        side->inlet_velocity=p->input.sides[s].velocity_m_s;
        side->inlet_pressure=p->input.sides[s].pressure_Pa;side->inlet_temperature=p->input.sides[s].temperature_K;
        side->inlet_opening=field(p->sides[s].inlet_opening);side->outlet_opening=field(p->sides[s].outlet_opening);
        side->permeability_scale=p->sides[s].have_drag_application?p->sides[s].drag_evidence.scale_permeability:1.;
        side->forchheimer_scale=p->sides[s].have_drag_application?p->sides[s].drag_evidence.scale_forchheimer:1.;
        side->sco2_nusselt_multiplier=1.;
        for(i=0;i<4;++i)side->heat_transfer_geometry[i]=1.;
        for(i=0;i<3;++i) {
            const size_t axis=(size_t)p->sides[s].axes[i];
            side->solver_axes[i]=(uint32_t)axis;axes->solver_to_real[axis]=(int32_t)i;
            axes->widths[i]=p->widths[axis];axes->counts[i]=axes->solver_counts[i]=raw->shape[axis];
            axes->lengths[i]=axes->solver_lengths[i]=saved->lengths_m[axis];
        }
    }
}
/* Full-result hosts call v3 directly with the captured input. */
static int query(const tpmshx_stage_input_v3* input,tpmshx_stage_output_v1* report,
        tpmshx_result_diagnostics_v1* diagnostics,uint64_t* token,char* error,size_t capacity) {
    return tpmshx_result_stage_query_v3(input,0,NULL,NULL,0,report,diagnostics,token,error,capacity);
}
static int prepare(const tpmshx_preparation_case_input_3d_v1* input,const tpmshx_preparation_case_options_v1* options,
        tpmshx_preparation_3d_spatial_case_v1* prepared,char* error,size_t capacity) {
    tpmshx_preparation_3d_spatial_input_v1 spatial={0};
    tpmshx_preparation_case_failure_v2 failure={0};
    spatial.abi_version=1;spatial.struct_size=sizeof(spatial);
    spatial.input=*input;
    memset(prepared,0,sizeof(*prepared));prepared->abi_version=1;prepared->struct_size=sizeof(*prepared);
    failure.abi_version=2;failure.struct_size=sizeof(failure);
    return tpmshx_preparation_3d_spatial_prepare_case_v1(&spatial,options,NULL,prepared,&failure,error,capacity);
}

int main(void) {
    char error[4096]="unchanged";
    tpmshx_preparation_case_input_3d_v1 input={0};
    tpmshx_preparation_case_options_v1 options={0};
    tpmshx_preparation_3d_spatial_case_v1 prepared={0};
    tpmshx_stage_saved_case_3d_v3 saved;tpmshx_full3d_input_v1 raw;
    tpmshx_stage_run_request_3d_v1 request={0};
    tpmshx_stage_run_control_3d_v1 control={0};
    tpmshx_stage_run_result_3d_v1 result={0},before;
    tpmshx_run_state_v1 snapshot={0};
    tpmshx_stage_capture_3d_v1 capture={0};
    tpmshx_stage_output_v1 report={0};
    tpmshx_result_diagnostics_v1 diagnostics={0};uint64_t token=0;
    void* run=NULL;void* restored=NULL;uint32_t phase=0,restored_phase=0;size_t i;
    REQUIRE(tpmshx_stage_run_3d_abi_version()==TPMSHX_STAGE_RUN_3D_SAVED_ABI_VERSION);
    REQUIRE(tpmshx_stage_capture_3d_abi_version()==2);
    input.abi_version=1;input.struct_size=sizeof(input);input.max_cells=2000000;
    input.lengths_m[0]=.182;input.lengths_m[1]=.042;input.lengths_m[2]=.031;
    input.counts[0]=6;input.counts[1]=5;input.counts[2]=4;
    input.topology=1;input.cell_length_mm=7.;input.wall_thickness_mm=.6;input.solid_conductivity_W_mK=16.;
    for(i=0;i<2;++i) {
        input.sides[i].port.active=1;input.sides[i].pressure_Pa=200000.;
    }
    input.sides[0].velocity_m_s=6.;input.sides[0].temperature_K=350.;
    input.sides[1].fluid=1;input.sides[1].velocity_m_s=.02;input.sides[1].temperature_K=320.;input.sides[1].port.direction=3;
    options.abi_version=1;options.struct_size=sizeof(options);options.allow_extrapolation=1;
    REQUIRE(prepare(&input,&options,&prepared,error,sizeof(error))==0);
    REQUIRE(prepared.prepared.cell_length.size==120 && !prepared.cell_count);
    pack_saved(&prepared.prepared,&saved,&raw);
    request.abi_version=1;request.struct_size=sizeof(request);
    request.max_iter_simple.present=request.max_outer_ltne.present=1;
    request.max_iter_simple.value=12;request.max_outer_ltne.value=2;
    request.model_h.max_iterations=9;request.model_h.temperature_tolerance=.5;request.model_h.q_relative_tolerance=1e-3;
    control.result_id="plain-C-3d";control.cpu_threads=12;
    REQUIRE(tpmshx_stage_run_3d_create_saved_v3(&saved,&request,&control,&run,(char*)&saved,sizeof(saved))==1);
    REQUIRE(!run && saved.abi_version==3);
    result.abi_version=1;result.struct_size=sizeof(result);before=result;
    REQUIRE(tpmshx_run_saved_case_3d_v3(&saved,&request,&control,&result,(char*)&saved,sizeof(saved))==1);
    REQUIRE(memcmp(&result,&before,sizeof(result))==0);
    REQUIRE(tpmshx_stage_run_3d_create_saved_v3(&saved,&request,&control,&run,error,sizeof(error))==0);
    REQUIRE(tpmshx_stage_run_3d_take_result_v1(run,&result,error,sizeof(error))!=0);
    REQUIRE(memcmp(&result,&before,sizeof(result))==0);
    REQUIRE(tpmshx_stage_run_3d_advance_step_v1(run,&phase,error,sizeof(error))==0);
    REQUIRE(tpmshx_stage_run_3d_snapshot_v1(run,&snapshot,error,sizeof(error))==0);
    tpmshx_stage_run_3d_release_run_v1(&run);REQUIRE(run==NULL);
    control.cpu_threads=9;
    REQUIRE(tpmshx_stage_run_3d_restore_saved_v3(&saved,&request,&control,
        snapshot.fields,snapshot.count,&restored,error,sizeof(error))==0);
    REQUIRE(tpmshx_stage_run_3d_phase_v1(restored,&restored_phase)==0 && restored_phase==phase);
    tpmshx_run_state_release_v1(&snapshot);
    REQUIRE(tpmshx_stage_run_3d_finish_v1(restored,error,sizeof(error))==0);
    REQUIRE(tpmshx_stage_run_3d_phase_v1(restored,&phase)==0 && phase==TPMSHX_FULL3D_COMPLETED);
    REQUIRE(tpmshx_stage_run_3d_take_result_v1(restored,&result,error,sizeof(error))==0);
    tpmshx_stage_run_3d_release_run_v1(&restored);
    control.cpu_threads=1;
    tpmshx_preparation_3d_spatial_case_release_v1(&prepared);
    REQUIRE(result.raw.stop<=1 && result.evidence.dimension==3 && result.evidence.field_count==25);
    REQUIRE(tpmshx_stage_run_3d_get_capture_v1(&result,1,&capture)==0);
    const tpmshx_stage_run_records_v1* records=tpmshx_stage_run_3d_records_v1(&result);
    REQUIRE(records && records->sampling.count && records->sampling.records);
    const tpmshx_stage_run_3d_execution_v1* executed=tpmshx_stage_run_3d_execution_view_v1(&result);
    REQUIRE(executed && executed->execution.records==records && executed->settings.outer_count==result.raw.outer_count
        && executed->execution.acceleration);
    const size_t last_main=executed->execution.last_main_model_h;
    REQUIRE(last_main<executed->execution.model_h.count && !executed->execution.model_h.records[last_main].refined);
    REQUIRE(records->base_drag[0].minimum>0. && records->base_drag[0].minimum==records->base_drag[0].maximum);
    REQUIRE(records->applied_drag[0][0].minimum==result.raw.flow[0].permeability.data[0]);
    REQUIRE(records->transient_count+records->final_count==result.raw.simple_failure_count);
    REQUIRE(capture.model_h_cell_count==120 && capture.audit_outlet[0].size==20);
    /* Raw evidence queries borrow the stage result and keep their argument contract. */
    tpmshx_full3d_bootstrap_trace_v1 trace={0};tpmshx_property_sampling_v1 sampling={0};
    tpmshx_model_h_iteration_records_v1 calls={0};tpmshx_range_observations_view_v1 ranges={0};
    tpmshx_energy_update_scale_v1 scale_ev={0};tpmshx_full3d_energy_effective_settings_v1 settings_ev={0};
    tpmshx_full3d_energy_evidence_v1 energy_ev={0};tpmshx_model_enthalpy_evidence_v1 model_h_ev={0};
    tpmshx_physical_heat_ledger_v1 ledger_ev={0};tpmshx_model_h_acceleration_v1 accel_ev={0};
    REQUIRE(tpmshx_full_3d_abi_version()==2);
    REQUIRE(tpmshx_full_3d_get_property_sampling_v1(&result.raw,&sampling)==0
        && sampling.count==records->sampling.count);
    REQUIRE(tpmshx_full_3d_get_model_h_iterations_v1(&result.raw,&calls)==0
        && calls.count==executed->execution.model_h.count && calls.count>0);
    REQUIRE(tpmshx_full_3d_get_model_h_acceleration_v1(&result.raw,0,&accel_ev)==0);
    REQUIRE(tpmshx_full_3d_get_bootstrap_trace_v1(&result.raw,0,&trace)==0);
    REQUIRE(tpmshx_full_3d_get_last_closure_ranges_v1(&result.raw,&ranges)==0 && ranges.size>0);
    REQUIRE(tpmshx_full_3d_get_energy_update_scale_v1(&result.raw,&scale_ev)==0 && !scale_ev.available);
    REQUIRE(tpmshx_full_3d_get_energy_effective_settings_v1(&result.raw,&settings_ev)==0 && !settings_ev.resolved.available);
    REQUIRE(tpmshx_full_3d_get_energy_evidence_v1(&result.raw,&energy_ev)==0 && !energy_ev.available);
    REQUIRE(tpmshx_full_3d_get_model_enthalpy_evidence_v1(&result.raw,&model_h_ev)==0);
    REQUIRE(tpmshx_full_3d_get_physical_heat_ledger_v1(&result.raw,&ledger_ev)==0 && ledger_ev.available);
    trace.selected=99;sampling.count=123;ranges.size=123;calls.count=123;accel_ev.history_limit=123;
    scale_ev.available=99;settings_ev.outer_count=123;energy_ev.outer_count=123;
    model_h_ev.available=99;ledger_ev.available=99;
    REQUIRE(tpmshx_full_3d_get_bootstrap_trace_v1(&result.raw,2,&trace)==1 && trace.selected==99);
    REQUIRE(tpmshx_full_3d_get_model_h_acceleration_v1(&result.raw,calls.count+999,&accel_ev)==1 && accel_ev.history_limit==123);
    REQUIRE(tpmshx_full_3d_get_bootstrap_trace_v1(NULL,0,&trace)==1 && trace.selected==99);
    REQUIRE(tpmshx_full_3d_get_property_sampling_v1(NULL,&sampling)==1 && sampling.count==123);
    REQUIRE(tpmshx_full_3d_get_model_h_iterations_v1(NULL,&calls)==1 && calls.count==123);
    REQUIRE(tpmshx_full_3d_get_model_h_acceleration_v1(NULL,0,&accel_ev)==1 && accel_ev.history_limit==123);
    REQUIRE(tpmshx_full_3d_get_last_closure_ranges_v1(NULL,&ranges)==1 && ranges.size==123);
    REQUIRE(tpmshx_full_3d_get_energy_update_scale_v1(NULL,&scale_ev)==1 && scale_ev.available==99);
    REQUIRE(tpmshx_full_3d_get_energy_effective_settings_v1(NULL,&settings_ev)==1 && settings_ev.outer_count==123);
    REQUIRE(tpmshx_full_3d_get_energy_evidence_v1(NULL,&energy_ev)==1 && energy_ev.outer_count==123);
    REQUIRE(tpmshx_full_3d_get_model_enthalpy_evidence_v1(NULL,&model_h_ev)==1 && model_h_ev.available==99);
    REQUIRE(tpmshx_full_3d_get_physical_heat_ledger_v1(NULL,&ledger_ev)==1 && ledger_ev.available==99);
    REQUIRE(tpmshx_full_3d_get_bootstrap_trace_v1(&result.raw,0,NULL)==1);
    REQUIRE(tpmshx_full_3d_get_property_sampling_v1(&result.raw,NULL)==1);
    REQUIRE(tpmshx_full_3d_get_model_h_iterations_v1(&result.raw,NULL)==1);
    REQUIRE(tpmshx_full_3d_get_model_h_acceleration_v1(&result.raw,0,NULL)==1);
    REQUIRE(tpmshx_full_3d_get_last_closure_ranges_v1(&result.raw,NULL)==1);
    REQUIRE(tpmshx_full_3d_get_energy_update_scale_v1(&result.raw,NULL)==1);
    REQUIRE(tpmshx_full_3d_get_energy_effective_settings_v1(&result.raw,NULL)==1);
    REQUIRE(tpmshx_full_3d_get_energy_evidence_v1(&result.raw,NULL)==1);
    REQUIRE(tpmshx_full_3d_get_model_enthalpy_evidence_v1(&result.raw,NULL)==1);
    REQUIRE(tpmshx_full_3d_get_physical_heat_ledger_v1(&result.raw,NULL)==1);
    report.struct_size=sizeof(report);
    REQUIRE(query(&result.evaluation,&report,&diagnostics,&token,error,sizeof(error))==0);
    REQUIRE(report.json && report.metric_count==15);
    tpmshx_result_stage_release_v1(&report);tpmshx_stage_run_3d_release_v1(&result);
    REQUIRE(!result.owner);tpmshx_stage_run_3d_release_v1(&result);
    REQUIRE(tpmshx_full_3d_get_bootstrap_trace_v1(&result.raw,0,&trace)==1 && trace.selected==99);
    REQUIRE(tpmshx_full_3d_get_property_sampling_v1(&result.raw,&sampling)==1 && sampling.count==123);
    REQUIRE(tpmshx_full_3d_get_model_h_iterations_v1(&result.raw,&calls)==1 && calls.count==123);
    REQUIRE(tpmshx_full_3d_get_model_h_acceleration_v1(&result.raw,0,&accel_ev)==1 && accel_ev.history_limit==123);
    REQUIRE(tpmshx_full_3d_get_last_closure_ranges_v1(&result.raw,&ranges)==1 && ranges.size==123);
    REQUIRE(tpmshx_full_3d_get_energy_update_scale_v1(&result.raw,&scale_ev)==1 && scale_ev.available==99);
    REQUIRE(tpmshx_full_3d_get_energy_effective_settings_v1(&result.raw,&settings_ev)==1 && settings_ev.outer_count==123);
    REQUIRE(tpmshx_full_3d_get_energy_evidence_v1(&result.raw,&energy_ev)==1 && energy_ev.outer_count==123);
    REQUIRE(tpmshx_full_3d_get_model_enthalpy_evidence_v1(&result.raw,&model_h_ev)==1 && model_h_ev.available==99);
    REQUIRE(tpmshx_full_3d_get_physical_heat_ledger_v1(&result.raw,&ledger_ev)==1 && ledger_ev.available==99);
    REQUIRE(prepare(&input,&options,&prepared,error,sizeof(error))==0);
    pack_saved(&prepared.prepared,&saved,&raw);
    request.model_h.max_iterations=0;request.model_h.temperature_tolerance=0.;request.model_h.q_relative_tolerance=0.;
    request.variable_rho_cp.present=request.thermal_iterations.present=1;
    request.variable_rho_cp.value=0;request.thermal_iterations.value=9;
    result.abi_version=1;result.struct_size=sizeof(result);
    REQUIRE(tpmshx_run_saved_case_3d_v3(&saved,&request,&control,&result,error,sizeof(error))==0);
    REQUIRE(result.evaluation.none_count==2);
    report.struct_size=sizeof(report);
    REQUIRE(query(&result.evaluation,&report,&diagnostics,&token,error,sizeof(error))==0);
    for(i=0;i<report.metric_count;++i)if(!strcmp(report.metrics[i].name,"T_out_A"))break;
    REQUIRE(i<report.metric_count && !strcmp(report.metrics[i].reason,"missing or incomplete evidence: 'native boundary faces'"));
    tpmshx_result_stage_release_v1(&report);tpmshx_stage_run_3d_release_v1(&result);
    result.abi_version=1;result.struct_size=sizeof(result);control.callbacks.cancel=cancel;
    /* Explicit strict EOS controls must reject non-EOS routes before cancellation. */
    request.require_enthalpy_update_on_temperature=1;before=result;
    REQUIRE(tpmshx_run_saved_case_3d_v3(&saved,&request,&control,&result,error,sizeof(error))==1);
    REQUIRE(memcmp(&result,&before,sizeof(result))==0 && error[0]!='\0');
    request.require_enthalpy_update_on_temperature=0;
    REQUIRE(tpmshx_run_saved_case_3d_v3(&saved,&request,&control,&result,error,sizeof(error))==0);
    REQUIRE(result.raw.stop==2 && result.evidence.abi_version==0);
    REQUIRE(tpmshx_stage_run_3d_records_v1(&result)==NULL);
    REQUIRE(tpmshx_stage_run_3d_execution_view_v1(&result)==NULL);
    capture.q_net=123.;
    REQUIRE(tpmshx_stage_run_3d_get_capture_v1(&result,0,&capture)==1 && capture.q_net==123.);
    tpmshx_preparation_3d_spatial_case_release_v1(&prepared);tpmshx_stage_run_3d_release_v1(&result);
    /* Validate 3D strict EOS energy options and bounds on the stage request boundary. */
    input.counts[0]=input.counts[1]=input.counts[2]=2;
    for(i=0;i<2;++i) {
        input.sides[i].fluid=2;input.sides[i].pressure_Pa=8e6;
        input.sides[i].velocity_m_s=.4;input.sides[i].temperature_K=i?310.:340.;
    }
    REQUIRE(prepare(&input,&options,&prepared,error,sizeof(error))==0);
    pack_saved(&prepared.prepared,&saved,&raw);
    memset(&request,0,sizeof(request));request.abi_version=1;request.struct_size=sizeof(request);
    request.max_outer_ltne.present=request.envelope_mode.present=1;
    request.max_outer_ltne.value=1;request.envelope_mode.value=1;
    {
        const tpmshx_energy_options_v1 invalid_energy[]={
            {0,1e-8},{1,1e-8},{3,1e-8},{TPMSHX_ENERGY_TEMPERATURE_SOU,0.},{TPMSHX_ENERGY_TEMPERATURE_SOU,(double)NAN}};
        tpmshx_energy_options_v1 valid_energy={TPMSHX_ENERGY_TEMPERATURE_SOU,1e-8};
        memset(&result,0,sizeof(result));result.abi_version=1;result.struct_size=sizeof(result);before=result;
        raw.solve_b=0;request.energy=&valid_energy;request.require_enthalpy_update_on_temperature=1;
        REQUIRE(tpmshx_run_saved_case_3d_v3(&saved,&request,&control,&result,error,sizeof(error))==1
            && memcmp(&result,&before,sizeof(result))==0);
        raw.solve_b=1;
        for(i=0;i<sizeof(invalid_energy)/sizeof(invalid_energy[0]);++i) {
            error[0]='\0';request.energy=&invalid_energy[i];
            REQUIRE(tpmshx_run_saved_case_3d_v3(&saved,&request,&control,&result,error,sizeof(error))==1
                && memcmp(&result,&before,sizeof(result))==0 && error[0]!='\0');
        }
        request.energy=&valid_energy;
        request.energy_coupled_tolerance.present=1;request.energy_coupled_tolerance.value=0.;error[0]='\0';
        REQUIRE(tpmshx_run_saved_case_3d_v3(&saved,&request,&control,&result,error,sizeof(error))==1 && !result.owner && error[0]!='\0');
        request.energy_coupled_tolerance.value=(double)NAN;error[0]='\0';
        REQUIRE(tpmshx_run_saved_case_3d_v3(&saved,&request,&control,&result,error,sizeof(error))==1 && !result.owner && error[0]!='\0');
        request.energy_coupled_tolerance.value=1e-5;
        request.energy_equation_tolerance.present=1;request.energy_equation_tolerance.value=0.;error[0]='\0';
        REQUIRE(tpmshx_run_saved_case_3d_v3(&saved,&request,&control,&result,error,sizeof(error))==1 && !result.owner && error[0]!='\0');
        request.energy_equation_tolerance.value=(double)INFINITY;error[0]='\0';
        REQUIRE(tpmshx_run_saved_case_3d_v3(&saved,&request,&control,&result,error,sizeof(error))==1 && !result.owner && error[0]!='\0');
        request.energy_equation_tolerance.value=1e-5;
        request.require_enthalpy_update_on_temperature=2;error[0]='\0';
        REQUIRE(tpmshx_run_saved_case_3d_v3(&saved,&request,&control,&result,error,sizeof(error))==1 && !result.owner && error[0]!='\0');
        request.require_enthalpy_update_on_temperature=1;
        request.energy_update_tolerance.present=1;request.energy_update_tolerance.value=(double)NAN;error[0]='\0';
        REQUIRE(tpmshx_run_saved_case_3d_v3(&saved,&request,&control,&result,error,sizeof(error))==1 && !result.owner && error[0]!='\0');
        request.energy_update_tolerance.value=1e-6;
        request.energy_iterations.present=1;request.energy_iterations.value=0;error[0]='\0';
        REQUIRE(tpmshx_run_saved_case_3d_v3(&saved,&request,&control,&result,error,sizeof(error))==1 && !result.owner && error[0]!='\0');
        request.energy_iterations.value=1000;
        REQUIRE(tpmshx_run_saved_case_3d_v3(&saved,&request,&control,&result,error,sizeof(error))==0
            && result.raw.stop==2 && result.owner && !result.raw.converged);
        REQUIRE(tpmshx_full_3d_get_energy_effective_settings_v1(&result.raw,&settings_ev)==0
            && !settings_ev.resolved.available && !settings_ev.last.available && !settings_ev.outer_count);
        tpmshx_stage_run_3d_release_v1(&result);
    }
    tpmshx_preparation_3d_spatial_case_release_v1(&prepared);
    puts("Plain C 3D prepare/run/restore/evaluate passed");return 0;
}
