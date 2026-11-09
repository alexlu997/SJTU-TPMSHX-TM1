#include "tpmshx/solver_c_api.h"
#include "tpmshx/temperature_driver_c_api.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#define REQUIRE(condition) do { if (!(condition)) { \
    fprintf(stderr,"C QD check failed at line %d: %s\n",__LINE__,error); return 1; } } while (0)

static int TPMSHX_THERMAL_CALL cancel_now(void* context) {
    ++*(unsigned*)context;
    return 1;
}
static void TPMSHX_THERMAL_CALL record_progress(void* context, unsigned percent) {
    *(unsigned*)context = percent;
}

int main(void) {
    const size_t shape[3] = {8,3,1}, sizes[9] = {8,3,1,24,24,24,24,24,24};
    double dx[8], dy[3], dz[1] = {.036};
    double eps[24], ea[24], ks[24], ta[24] = {0}, tb[24] = {0}, ts[24] = {0};
    double* arrays[9] = {dx,dy,dz,eps,ea,ks,ta,tb,ts};
    tpmshx_qd_config_v1 config = {0};
    tpmshx_qd_result_v1 result = {0};
    unsigned progress = 0;
    tpmshx_callbacks_v1 callbacks = {NULL,record_progress,&progress};
    char error[160] = {0};
    size_t i;
    for (i=0;i<8;++i) dx[i] = .004;
    for (i=0;i<3;++i) dy[i] = .012;
    for (i=0;i<24;++i) { eps[i]=.6; ea[i]=.3; ks[i]=6.4; }
    config.topology=TPMSHX_DIAMOND; config.arrangement=TPMSHX_CROSS;
    config.property_mode=TPMSHX_MEAN;
    config.length=.032; config.span=.036; config.height=.036;
    config.cell_length=.007; config.area_density=1000.; config.hydraulic_diameter=.002;
    config.sides[0]=(tpmshx_qd_side_v1){TPMSHX_WATER,355.,2e5,.08,.001};
    config.sides[1]=(tpmshx_qd_side_v1){TPMSHX_AIR,300.,2e5,.02,.01};
    config.max_iterations=1000; config.chunk_iterations=100;
    config.q_relative_tolerance=1e-4; config.alpha=.7;
    REQUIRE(tpmshx_solver_abi_version()==TPMSHX_SOLVER_ABI_VERSION);
    {
        const char* expected[3]={"shared_fv_cc2d_tminmod_guarded_line_v1",
            "shared_fv_cc3d_tminmod_guarded_line_v1","shared_fv_staggered_tminmod_picard_v1"};
        for (i=0;i<3;++i) {
            const char* identity=tpmshx_temperature_algorithm_v1((uint32_t)i);
            REQUIRE(identity && strcmp(identity,expected[i])==0);
        }
        REQUIRE(tpmshx_temperature_algorithm_v1(3)==NULL);
        REQUIRE(tpmshx_temperature_algorithm_v1(UINT32_MAX)==NULL);
    }
    REQUIRE(tpmshx_solve_quick_design_v1(shape,arrays,sizes,&config,&callbacks,&result,error,sizeof(error))==TPMSHX_OK);
    REQUIRE(result.completed_passes==2 && result.stop==TPMSHX_CONVERGED && progress==100);
    REQUIRE(result.pressure[0].outlet==199800. && !result.pressure[0].choked);
    for (i=0;i<24;++i)
        REQUIRE(isfinite(ta[i]) && isfinite(tb[i]) && isfinite(ts[i])
            && ta[i]>=299. && ta[i]<=356. && tb[i]>=299. && tb[i]<=356. && ts[i]>=299. && ts[i]<=356.);

    /* Invalid input leaves the result untouched and always bounds its message. */
    result.completed_passes=99;
    config.property_mode=99;
    REQUIRE(tpmshx_solve_quick_design_v1(shape,arrays,sizes,&config,NULL,&result,error,1)==TPMSHX_INVALID_ARGUMENT);
    REQUIRE(error[0]=='\0' && result.completed_passes==99);
    config.property_mode=TPMSHX_MEAN;
    config.sides[0].inlet_temperature=500.;
    REQUIRE(tpmshx_solve_quick_design_v1(shape,arrays,sizes,&config,NULL,&result,error,sizeof(error))==TPMSHX_WATER_INPUT);
    REQUIRE(result.completed_passes==99 && error[0]);
    config.sides[0].inlet_temperature=355.;
    config.warm_start=1; ta[7]=500.;
    REQUIRE(tpmshx_solve_quick_design_v1(shape,arrays,sizes,&config,NULL,&result,error,sizeof(error))==TPMSHX_WATER_FIELD);
    REQUIRE(result.completed_passes==99 && error[0]);
    config.warm_start=0;
    progress=0; callbacks.cancel=cancel_now;
    REQUIRE(tpmshx_solve_quick_design_v1(shape,arrays,sizes,&config,&callbacks,&result,error,sizeof(error))==TPMSHX_OK);
    REQUIRE(result.stop==TPMSHX_CANCELLED && result.completed_passes==0 && progress==1 && !error[0]);
    callbacks.cancel=NULL;
    REQUIRE(tpmshx_solve_quick_design_v1(shape,arrays,sizes,&config,&callbacks,&result,error,sizeof(error))==TPMSHX_OK);
    REQUIRE(result.stop==TPMSHX_CONVERGED && result.completed_passes==2 && progress==100);
    puts("C Quick Design: two property passes, bounded errors, liquid guards, cancellation and recovery passed");
    return 0;
}
