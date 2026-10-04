/* Standalone C11 caller: independent full 3D execution and owned audit views. */
#include "tpmshx/full_3d_c_api.h"
#include <math.h>
#include <stdio.h>
#include <string.h>
static int cancelled(void* context) {(void)context;return 1;}
static tpmshx_full3d_array_v1 view(const double* p,size_t n) {
    tpmshx_full3d_array_v1 v={p,n};return v;
}
int main(void) {
    const double width[2]={.01,.01},opening[4]={1.,1.,1.,1.};
    double eps[8],half[8],k[8],cf[8],ks[8],length[8],area[8],diameter[8];
    for(size_t i=0;i<8;++i) {eps[i]=.6;half[i]=.3;k[i]=1e-8;cf[i]=40.;ks[i]=8.;length[i]=.007;area[i]=500.;diameter[i]=.003;}
    tpmshx_full3d_input_v1 in={0};in.shape[0]=in.shape[1]=in.shape[2]=2;
    for(size_t d=0;d<3;++d)in.widths[d]=view(width,2);
    in.epsilon=view(eps,8);in.epsilon_a=in.epsilon_b=view(half,8);in.permeability=view(k,8);in.forchheimer=view(cf,8);
    in.solid_conductivity=view(ks,8);in.cell_length=view(length,8);in.area_density=view(area,8);in.hydraulic_diameter=view(diameter,8);
    in.reference_cell_length=.007;in.reference_hydraulic_diameter=.003;in.topology=1;in.solve_b=1;
    for(size_t s=0;s<2;++s) {
        tpmshx_full3d_side_v1* a=&in.sides[s];a->fluid=0;a->direction=s?3:2;
        a->solver_axes[0]=0;a->solver_axes[1]=1;a->solver_axes[2]=2;
        a->inlet_temperature=s?300.:500.;a->inlet_pressure=200000.;a->inlet_velocity=1.;
        a->inlet_rectangle[1]=a->inlet_rectangle[3]=a->outlet_rectangle[1]=a->outlet_rectangle[3]=.02;
        a->inlet_opening=a->outlet_opening=view(opening,4);
        a->permeability_scale=a->forchheimer_scale=a->sco2_nusselt_multiplier=1.;
        for(size_t d=0;d<4;++d)a->heat_transfer_geometry[d]=1.;
    }
    tpmshx_full3d_control_v1 c={0};c.max_outer=12;c.initial_simple_iterations=c.warm_simple_iterations=2000;c.thermal_iterations=1000;
    c.outer_temperature_tolerance=.5;c.thermal_relaxation=.7;
    c.pressure_shooting=c.variable_rho_cp=c.conservative=c.strict_mass_balance=c.force_cell_centered=1;
    c.coarse_iterations=200;c.anderson_history=c.anderson_patience=3;c.anderson_trust=5.;c.roughness_height=1e-4;
    c.simple.max_iterations=2000;c.simple.inner_sweeps=1;c.simple.pressure_rebuild_every=100;
    c.simple.alpha_velocity=.5;c.simple.alpha_pressure=.2;c.simple.alpha_density=.3;c.simple.gas_constant=287.05;c.simple.pressure_diagonal_drift=.05;
    c.simple.ideal_gas=c.simple.massflux_inlet=c.simple.adaptive_pressure_tolerance=1;
    c.simple.convergence=(tpmshx_simple_f2_v1){1e-4,1e-6,1e-6,.01,1e-4,1e-3,2,5,60};
    c.enthalpy_iterations=1500;c.enthalpy_sweeps=25;c.enthalpy_omega=.6;c.enthalpy_update_tolerance=1e-3;
    tpmshx_full3d_result_v1 r={0};char error[1024];
    const tpmshx_energy_options_v1 energy={TPMSHX_ENERGY_LEGACY_H_FOU,1e-8};
    if(tpmshx_full_3d_abi_version()!=1 || tpmshx_solve_full_3d_v2(&in,&c,&energy,NULL,&r,error,sizeof error)) {
        fprintf(stderr,"full 3D call failed: %s\n",error);return 1;
    }
    if(!r.converged || !r.owner || !r.has_model_h || r.model_h.owner || r.outer_count<2) {
        fprintf(stderr,"full 3D gates/owner failed: stop=%u simple=%u thermal=%u outer=%u\n",r.stop,r.simple_ok,r.thermal_ok,r.outer_ok);return 2;
    }
    for(size_t f=0;f<3;++f)for(size_t p=0;p<r.temperature[f].size;++p)if(!isfinite(r.temperature[f].data[p]) || r.temperature[f].data[p]<300. || r.temperature[f].data[p]>500.) {
        fprintf(stderr,"temperature envelope mismatch f=%zu p=%zu value=%.17g\n",f,p,r.temperature[f].data[p]);return 3;
    }
    if(!(r.duty[0]>0.) || r.flow[0].last.stop!=TPMSHX_SIMPLE_TOL || !r.model_h.volume.boundary_complete)return 4;
    tpmshx_full3d_bootstrap_trace_v1 trace={0};
    if(tpmshx_full_3d_get_bootstrap_trace_v1(&r,0,&trace) || !trace.available || trace.selected
       || strcmp(trace.policy,"explicit_off") || strcmp(trace.decision,"disabled")
       || trace.level_count || trace.started_cap_sum || trace.total_charged_iterations || r.flow[0].bootstrap.available)return 9;
    trace.selected=99;
    if(tpmshx_full_3d_get_bootstrap_trace_v1(&r,2,&trace)!=1 || trace.selected!=99)return 10;
    /* The additive entry uses the original owner and has no candidate
       evidence when the selected energy algorithm is legacy. */
    tpmshx_full3d_energy_evidence_v1 evidence={0};
    if(tpmshx_full_3d_get_energy_evidence_v1(&r,&evidence) || evidence.available
       || evidence.energy.algorithm!=TPMSHX_ENERGY_LEGACY_H_FOU || evidence.energy.has_temperature_update
       || evidence.outer_count!=r.outer_count)return 14;
    for(size_t i=0;i<evidence.outer_count;++i)
        if(evidence.outer[i].algorithm!=TPMSHX_ENERGY_LEGACY_H_FOU || evidence.outer[i].has_temperature_update)return 14;
    /* Input changes cannot mutate owned result views. */
    eps[0]=.55;if(r.flow[0].epsilon.data[0]!=.6)return 5;eps[0]=.6;
    tpmshx_full_3d_release_v1(&r);tpmshx_full_3d_release_v1(&r);if(r.owner)return 6;
    if(tpmshx_full_3d_get_bootstrap_trace_v1(&r,0,&trace)!=1 || trace.selected!=99)return 11;
    evidence.available=99;
    if(tpmshx_full_3d_get_energy_evidence_v1(&r,&evidence)!=1 || evidence.available!=99)return 15;
    tpmshx_full3d_callbacks_v1 cb={cancelled,NULL,NULL,NULL};
    const tpmshx_energy_options_v1 invalid_energy[]={{3,1e-8},{0,0.},{0,NAN}};
    r.stop=99;
    for(size_t i=0;i<4;++i) {
        error[0]='\0';
        const tpmshx_energy_options_v1* options=i<3?&invalid_energy[i]:NULL;
        if(tpmshx_solve_full_3d_v2(&in,&c,options,&cb,&r,error,sizeof error)!=1
           || r.stop!=99 || r.owner || !error[0])return 16;
        if(tpmshx_full_3d_get_energy_evidence_v1(&r,&evidence)!=1 || evidence.available!=99)return 16;
    }
    c.coarse_bootstrap=1;
    if(tpmshx_solve_full_3d_v1(&in,&c,&cb,&r,error,sizeof error) || r.stop!=2 || r.converged)return 7;
    if(tpmshx_full_3d_get_bootstrap_trace_v1(&r,0,&trace) || !trace.selected || strcmp(trace.decision,"cancelled")
       || trace.level_count || trace.started_cap_sum || trace.total_charged_iterations)return 12;
    tpmshx_full_3d_release_v1(&r);
    in.epsilon.size=7;r.stop=99;
    if(tpmshx_solve_full_3d_v1(&in,&c,NULL,&r,error,sizeof error)!=1 || r.stop!=99 || !error[0])return 8;
    if(r.owner || tpmshx_full_3d_get_bootstrap_trace_v1(&r,0,&trace)!=1)return 13;
    puts("{\"status\":\"passed\",\"abi\":1,\"full3d_owned\":true,\"energy_entry_query\":true,\"cancel\":true,\"error_untouched\":true}");return 0;
}
