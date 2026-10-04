#include "tpmshx/full_2d_c_api.h"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>
#include <math.h>
#include <stdio.h>

static int cancelled(void* context) { (void)context; return 1; }
static void expect_invalid_port(const size_t* shape,const double* const* arrays,const size_t* sizes,
                               const tpmshx_full_2d_config_v2* config) {
    tpmshx_full_2d_result_v2 result={0}; result.iterations=123;
    tpmshx_full_2d_callbacks_v2 callbacks={cancelled,NULL,NULL,NULL};
    char error[256]={0};
    const int status=tpmshx_solve_full_2d_v2(shape,arrays,sizes,config,&callbacks,&result,error,sizeof(error));
    if(status==0) tpmshx_full_2d_release_v2(&result);
    assert(status==1 && result.iterations==123 && result.owner==NULL && error[0]);
}
int main(void) {
    const size_t shape[2]={2,2};
    double widths[2]={.005,.005},depth=1.,k[4]={.21,.21,.21,.21},ks[4]={4.8,4.8,4.8,4.8};
    double eps[4]={.7,.7,.7,.7},a0[4]={100.,100.,100.,100.},dh[4]={.003,.003,.003,.003};
    double length[4]={.007,.007,.007,.007},row_k[2]={1e-5,1e-5},row_cf[2]={0.,0.};
    double nu_ratio[4]={3./7.,3./7.,3./7.,3./7.};
    double opening[2]={1.,1.},out_u[3]={1.,1.,1.};
    const double* arrays[29]={widths,widths,&depth,k,k,ks,eps,a0,dh,length,
        row_k,row_cf,NULL,NULL,opening,opening,opening,opening,out_u,
        row_k,row_cf,NULL,NULL,opening,opening,opening,opening,out_u,nu_ratio};
    const size_t sizes[29]={2,2,1,4,4,4,4,4,4,4,2,2,0,0,2,2,2,2,3,2,2,0,0,2,2,2,2,3,4};
    tpmshx_full_2d_config_v2 config={0};
    config.topology=1; config.thermal_mode=1; config.split_a=.5;
    config.reference_cell_length=.007; config.reference_porosity=.7; config.sco2_nu_multiplier=1.;
    config.simple_iterations=1000; config.simple_sweeps=2; config.outer_iterations=4;
    config.thermal_iterations=2000; config.thermal_chunk=500;
    config.alpha_velocity=.7; config.alpha_pressure=.3; config.alpha_density=.5; config.gas_constant=287.05;
    config.massflux_inlet=1; config.close_outlet_on_exit=1;
    config.f2=(tpmshx_simple_f2_v1){1e-4,1e-6,1e-6,.01,1e-3,.995,2,20,200};
    config.outer_temperature_tolerance=1.; config.outer_density_tolerance=.01; config.outer_relaxation=.7;
    config.thermal_q_tolerance=.001; config.enthalpy_update_tolerance=.1; config.envelope_mode="raise";
    for (size_t side=0;side<2;++side) {
        config.sides[side].fluid=1; config.sides[side].direction=(uint32_t)(2+side);
        config.sides[side].uniform_inlet=1; config.sides[side].inlet_temperature=300.;
        config.sides[side].inlet_pressure=2e6; config.sides[side].inlet_velocity=.01;
        config.sides[side].initial_viscosity=.000854; config.sides[side].seed_permeability=1e-5;
        config.sides[side].inlet_hi=.01; config.sides[side].outlet_hi=.01;
    }
    tpmshx_full_2d_result_v2 result={0}; char error[1024];
    const tpmshx_energy_options_v1 energy={TPMSHX_ENERGY_LEGACY_H_FOU,1e-8};
    tpmshx_full_2d_energy_evidence_v1 evidence={0};
    assert(tpmshx_full_2d_abi_version()==2);
    /* ABI 2 requires the original prepared Nu ratio, without reconstructing
       it from rounded SI geometry or accepting absent/nonfinite inputs. */
    arrays[28]=NULL; expect_invalid_port(shape,arrays,sizes,&config);
    arrays[28]=nu_ratio; nu_ratio[0]=NAN;
    expect_invalid_port(shape,arrays,sizes,&config); nu_ratio[0]=3./7.;
    /* Direct C callers must not combine one coarse boundary with unrelated
       port bounds used by Richardson. Every supplied fraction is in [0,1],
       so these exercise consistency, not the existing range checks. */
    double wrong_opening[3]={.9,1.,1.};
    for(size_t side=0;side<2;++side) {
        for(size_t field=14+9*side;field<19+9*side;++field) {
            const double* saved=arrays[field]; arrays[field]=wrong_opening;
            expect_invalid_port(shape,arrays,sizes,&config); arrays[field]=saved;
        }
        double* bounds[2]={&config.sides[side].inlet_hi,&config.sides[side].outlet_hi};
        for(size_t end=0;end<2;++end) {
            const double saved=*bounds[end]; *bounds[end]=.005;
            expect_invalid_port(shape,arrays,sizes,&config); *bounds[end]=saved;
            *bounds[end]=NAN;
            expect_invalid_port(shape,arrays,sizes,&config); *bounds[end]=saved;
        }
    }
    /* The inlet profile also depends on uniform_inlet. A geometrically valid
       half-width uniform profile must not be accepted as the tapered one. */
    double half_opening[2]={0.,1.};
    arrays[14]=arrays[16]=half_opening; config.sides[0].inlet_lo=.005;
    config.sides[0].uniform_inlet=0;
    expect_invalid_port(shape,arrays,sizes,&config);
    arrays[14]=arrays[16]=opening; config.sides[0].inlet_lo=0.; config.sides[0].uniform_inlet=1;
    int status=tpmshx_solve_full_2d_v2(shape,arrays,sizes,&config,NULL,&result,error,sizeof(error));
    if(status) {fprintf(stderr,"%s\n",error);return 1;}
    /* Equal inlet/initial temperatures are the independent zero-duty solution
       on both main and refined grids, without an EOS or Python oracle. */
    assert(result.converged && result.have_fine && result.fine_extrapolated);
    assert(fabs(result.q_total)<1e-7 && fabs(result.q_solid)<1e-7);
    for(size_t stage=0;stage<2;++stage) {
        const tpmshx_full_2d_thermal_v2* t=stage?&result.fine:&result.main;
        for(size_t phase=0;phase<3;++phase) for(size_t i=0;i<t->temperature[phase].size;++i)
            assert(fabs(t->temperature[phase].data[i]-300.)<1e-9);
        assert(t->model_h.audit_available && t->model_h.plane.passed && t->model_h.owner==NULL);
    }
    const double saved=result.main.dx.data[0]; widths[0]=.123;
    assert(result.main.dx.data[0]==saved); widths[0]=saved;
    tpmshx_full_2d_release_v2(&result); assert(result.owner==NULL);
    tpmshx_full_2d_release_v2(&result);
    /* A complete nonzero heat-exchange solve must also finish independently
       of Python, including the refined final certificate. */
    config.sides[0].inlet_temperature=350.; config.outer_iterations=12;
    status=tpmshx_solve_full_2d_v3(shape,arrays,sizes,&config,&energy,NULL,&result,error,sizeof(error));
    if(status) {fprintf(stderr,"%s\n",error);return 1;}
    assert(result.converged && result.have_fine && result.fine_extrapolated);
    assert(isfinite(result.q_total) && result.q_total>0.);
    for(size_t stage=0;stage<2;++stage) {
        const tpmshx_full_2d_thermal_v2* t=stage?&result.fine:&result.main;
        for(size_t phase=0;phase<3;++phase) for(size_t i=0;i<t->temperature[phase].size;++i) {
            const double value=t->temperature[phase].data[i];
            assert(isfinite(value) && value>=300.-1e-9 && value<=350.+1e-9);
        }
        assert(t->model_h.plane.passed);
    }
    /* The additive entry preserves legacy results and exposes no candidate
       arrays; its query borrows the same owner released by the ABI 2 call. */
    assert(result.owner && tpmshx_full_2d_get_energy_evidence_v1(&result,&evidence)==0);
    assert(!evidence.main.available && !evidence.fine.available);
    assert(evidence.main.energy.algorithm==TPMSHX_ENERGY_LEGACY_H_FOU && !evidence.main.energy.has_temperature_update);
    assert(evidence.fine.energy.algorithm==TPMSHX_ENERGY_LEGACY_H_FOU && !evidence.fine.energy.has_temperature_update);
    assert(evidence.outer_count==result.outer_history_count);
    for(size_t i=0;i<evidence.outer_count;++i)
        assert(evidence.outer[i].algorithm==TPMSHX_ENERGY_LEGACY_H_FOU && !evidence.outer[i].has_temperature_update);
    tpmshx_full_2d_release_v2(&result);
    evidence.main.available=123;
    assert(tpmshx_full_2d_get_energy_evidence_v1(&result,&evidence)==1 && evidence.main.available==123);
    tpmshx_full_2d_callbacks_v2 cb={cancelled,NULL,NULL,NULL};
    const tpmshx_energy_options_v1 invalid_energy[]={{3,1e-8},{0,0.},{0,NAN}};
    result.iterations=123;
    for(size_t i=0;i<4;++i) {
        error[0]='\0';
        const tpmshx_energy_options_v1* options=i<3?&invalid_energy[i]:NULL;
        assert(tpmshx_solve_full_2d_v3(shape,arrays,sizes,&config,options,&cb,&result,error,sizeof(error))==1);
        assert(result.iterations==123 && result.owner==NULL && error[0]);
        assert(tpmshx_full_2d_get_energy_evidence_v1(&result,&evidence)==1 && evidence.main.available==123);
    }
    assert(tpmshx_solve_full_2d_v2(shape,arrays,sizes,&config,&cb,&result,error,sizeof(error))==0);
    assert(result.cancelled && !result.converged); tpmshx_full_2d_release_v2(&result);
    config.split_a=0.; result.iterations=123; char short_error[1]={'x'};
    assert(tpmshx_solve_full_2d_v2(shape,arrays,sizes,&config,NULL,&result,short_error,1)==1);
    assert(result.iterations==123 && short_error[0]=='\0');
    puts("full2D C ABI: port consistency, zero/nonzero duty with refinement, owned views, energy entry/query, cancellation and bounded errors passed");
    return 0;
}
