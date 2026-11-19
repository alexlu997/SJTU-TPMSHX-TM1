#include "tpmshx/simple_2d_c_api.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { size_t polls, progress; int cancel; } Observer;
static int TPMSHX_THERMAL_CALL cancelled(void* context) {
    Observer* observer = (Observer*)context;
    ++observer->polls;
    return observer->cancel;
}
static void TPMSHX_THERMAL_CALL progressed(void* context, size_t iteration, double residual) {
    Observer* observer = (Observer*)context;
    if (iteration && isfinite(residual)) ++observer->progress;
}

int main(void) {
    const size_t ny = 8, sizes[16] = {8,8,8,8,8,8,16,9,8,8,16,9,8,1,1,2};
    const double width = .02, length = .032, velocity = .005, viscosity = .001;
    double dx[1] = {.02}, dy[8], eps[8], mu[8], me[8], k[8], cf[8] = {0.}, temperature[8];
    double u[16] = {0.}, v[9] = {.005}, p[8] = {0.}, pp[8] = {0.}, du[16] = {0.}, dv[9] = {0.}, rho[8];
    double inlet[1] = {.005}, fraction[1] = {1.}, outlet_u[2] = {1.,1.};
    double* arrays[16] = {eps,mu,me,k,cf,temperature,u,v,p,pp,du,dv,rho,inlet,fraction,outlet_u};
    const uint8_t outlet[1] = {1};
    tpmshx_simple_2d_handle* handle = NULL;
    tpmshx_simple_2d_config_v1 config = {0};
    tpmshx_simple_2d_result_v1 result = {0};
    Observer observer = {0,0,0};
    const tpmshx_simple_callbacks_v1 callbacks = {cancelled,progressed,&observer};
    char error[512];
    size_t i, needed = 0, first_iterations, warm_iterations;
    int status;
    for (i = 0; i < ny; ++i) {
        dy[i] = length / (double)ny; eps[i] = .6; mu[i] = viscosity; me[i] = viscosity/.6;
        k[i] = 1e-7; temperature[i] = 300.; rho[i] = 1000.;
    }
    config.max_iterations = 2000; config.inner_sweeps = 2;
    config.alpha_velocity = .7; config.alpha_pressure = .3; config.alpha_density = .3;
    config.pressure_reference_absolute = 101325.; config.gas_constant = 287.05;
    config.massflux_inlet = config.close_outlet_on_exit = config.have_inlet_density_reference = 1;
    config.reference_inlet_velocity = velocity; config.taper_flux_scale = 1.; config.inlet_density_reference = 1000.;
    config.f2.momentum_tolerance = 1e-9; config.f2.local_mass_tolerance = config.f2.global_mass_tolerance = 1e-10;
    config.f2.backflow_maximum = .01; config.f2.velocity_check_tolerance = 1e-4; config.f2.stall_ratio = 1e-3;
    config.f2.confirmations = 2; config.f2.momentum_interval = 5; config.f2.stall_window = 60;
    if (tpmshx_simple_2d_abi_version() != TPMSHX_SIMPLE_2D_ABI_VERSION) return 1;
    status = tpmshx_simple_2d_create_v1(1,ny,dx,dy,outlet,&handle,error,sizeof(error));
    if (status || !handle) { fprintf(stderr,"create: %s\n",error); return 2; }
    status = tpmshx_simple_2d_solve_v1(handle,arrays,sizes,&config,&callbacks,&result,error,sizeof(error));
    if (status || !result.converged || !result.post_closure_certified || !result.pressure_success
        || result.stop != TPMSHX_SIMPLE_TOL || result.massflux_target != 5.
        || result.momentum.maximum > 1e-9 || result.mass.global_residual > 1e-10
        || observer.polls != result.iterations || !observer.progress || error[0]) return 3;
    first_iterations = result.iterations;
    for (i = 0; i < ny; ++i) {
        const double gradient = (viscosity/1e-7 + 4.*(viscosity/.6)/(width*width))*velocity;
        const double expected = gradient*dy[0]*(double)(ny-1-i);
        if (fabs(p[i]-expected) > 2e-8 || fabs(v[i]-velocity) > 1e-12) return 4;
    }
    if (p[ny-1] != 0. || fabs(v[ny]-velocity) > 1e-12) return 5;
    status = tpmshx_simple_2d_history_v1(handle,0,NULL,0,&needed,error,sizeof(error));
    if (status || needed != first_iterations) return 6;
    {
        double untouched = 123.;
        status = tpmshx_simple_2d_history_v1(handle,0,&untouched,1,&needed,error,sizeof(error));
        if (status != TPMSHX_SIMPLE_INVALID_ARGUMENT || untouched != 123.) return 7;
    }
    status = tpmshx_simple_2d_solve_v1(handle,arrays,sizes,&config,NULL,&result,error,sizeof(error));
    if (status || !result.converged || result.iterations != 21 || result.massflux_target != 5.) return 8;
    warm_iterations = result.iterations;
    status = tpmshx_simple_2d_history_v1(handle,0,NULL,0,&needed,error,sizeof(error));
    if (status || needed != first_iterations+warm_iterations) return 9;
    {
        double* history = (double*)malloc(needed*sizeof(double));
        if (!history) return 10;
        status = tpmshx_simple_2d_history_v1(handle,0,history,needed,&needed,error,sizeof(error));
        for (i = 0; i < needed; ++i) if (!isfinite(history[i])) status = 99;
        free(history);
        if (status) return 11;
    }
    result.iterations = 123; result.stop = 91;
    config.ideal_gas = 2;
    status = tpmshx_simple_2d_solve_v1(handle,arrays,sizes,&config,NULL,&result,error,sizeof(error));
    if (status != TPMSHX_SIMPLE_INVALID_ARGUMENT || result.iterations != 123 || result.stop != 91) return 12;
    config.ideal_gas = 0;
    {
        char short_error[2] = {'x','x'};
        status = tpmshx_simple_2d_solve_v1(handle,NULL,sizes,&config,NULL,&result,short_error,2);
        if (status != TPMSHX_SIMPLE_INVALID_ARGUMENT || short_error[1] != '\0' || result.stop != 91) return 13;
    }
    observer.cancel = 1; observer.polls = 0;
    status = tpmshx_simple_2d_solve_v1(handle,arrays,sizes,&config,&callbacks,&result,error,sizeof(error));
    if (status || result.stop != TPMSHX_SIMPLE_CANCELLED || result.iterations || result.converged || observer.polls != 1) return 14;
    observer.cancel = 0;
    p[0] = NAN;
    status = tpmshx_simple_2d_solve_v1(handle,arrays,sizes,&config,NULL,&result,error,sizeof(error));
    if (status || result.stop != TPMSHX_SIMPLE_NONFINITE || !isnan(p[0]) || result.converged) return 15;
    tpmshx_simple_2d_destroy(handle); tpmshx_simple_2d_destroy(NULL);
    printf("SIMPLE 2D C ABI: analytic Darcy/wall solution, warm/history, errors and cancellation passed\n");
    return 0;
}
