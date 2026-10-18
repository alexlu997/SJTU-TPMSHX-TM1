#include "tpmshx/enthalpy_driver_c_api.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

static int TPMSHX_THERMAL_CALL cancel_first(void* context) {
    size_t* calls = (size_t*)context;
    ++*calls;
    return 1;
}

int main(void) {
    if (tpmshx_energy_algorithm_version_v1(TPMSHX_ENERGY_TEMPERATURE_FOU)!=1
        || tpmshx_energy_algorithm_version_v1(TPMSHX_ENERGY_TEMPERATURE_SOU)!=2
        || tpmshx_energy_algorithm_version_v1(TPMSHX_ENERGY_LEGACY_H_FOU)!=0
        || tpmshx_energy_algorithm_version_v1(UINT32_MAX)!=0) return 9;
    const size_t shape[3] = {8, 1, 1};
    const size_t sizes[21] = {8,1,1,8,8,8,8,9,16,16,8,8,8,9,16,16,8,8,8,8,8};
    double dx[8], dy[1] = {.01}, dz[1] = {.01}, ks[8], pressure[8], eps[8], hv[8];
    double mx_a[9], mx_b[9], yz[16] = {0.}, ha[8], hb[8], ta[8], tb[8], ts[8];
    double* arrays[21] = {dx,dy,dz,ks,pressure,eps,hv,mx_a,yz,yz,
                         pressure,eps,hv,mx_b,yz,yz,ha,hb,ta,tb,ts};
    tpmshx_enthalpy_config_v1 config = {0};
    tpmshx_enthalpy_result_v1 result = {0};
    char error[512];
    size_t i, calls = 0;
    int status;
    for (i = 0; i < 8; ++i) {
        dx[i] = .005; ks[i] = 4.; pressure[i] = 2e5; eps[i] = .3; hv[i] = 1e5;
        ta[i] = NAN; tb[i] = NAN; ts[i] = NAN;
    }
    for (i = 0; i < 9; ++i) { mx_a[i] = .001; mx_b[i] = -.003; }
    config.sides[0].fluid = TPMSHX_ENTHALPY_AIR;
    config.sides[0].inlet_temperature = 370.; config.sides[0].inlet_pressure = 2e5;
    config.sides[1].fluid = TPMSHX_ENTHALPY_WATER;
    config.sides[1].inlet_temperature = 300.; config.sides[1].inlet_pressure = 2e5;
    config.max_iterations = 1000; config.sweeps = 5; config.omega = .6;
    config.update_tolerance = 2e-5;
    config.coupled_gate = config.equation_gate = 1;
    config.coupled_tolerance = config.equation_tolerance = 1e-3;
    if (tpmshx_enthalpy_driver_abi_version() != TPMSHX_ENTHALPY_DRIVER_ABI_VERSION) return 1;
    status = tpmshx_solve_enthalpy_v1(shape,arrays,sizes,&config,NULL,&result,error,sizeof(error));
    if (status || result.stop != TPMSHX_ENTHALPY_CONVERGED || !result.audit_available
        || !result.audit.fluid_equations_computed || result.audit.equation_ratio > 1e-3
        || strcmp(result.coolprop_version,"8.0.0") || error[0]) {
        fprintf(stderr,"true-h C solve failed: status=%d, %s\n",status,error); return 2;
    }
    for (i = 0; i < 8; ++i)
        if (!isfinite(ha[i]) || !isfinite(hb[i]) || !isfinite(ta[i]) || !isfinite(tb[i])
            || !isfinite(ts[i]) || ta[i] < 299. || ta[i] > 371.) return 3;
    printf("enthalpy C ABI ok; iterations=%zu; equation_ratio=%.12g; CoolProp=%s\n",
           result.iterations,result.audit.equation_ratio,result.coolprop_version);


    {
        tpmshx_energy_result_v1 energy = {0};
        for (unsigned mask=0;mask<4;++mask) {
            config.coupled_gate = mask & 1u;
            config.equation_gate = (mask >> 1) & 1u;
            status = tpmshx_solve_enthalpy_v2(shape,arrays,sizes,&config,1e-8,NULL,
                &result,&energy,error,sizeof(error));
            if (status || result.stop != TPMSHX_ENTHALPY_CONVERGED
                || energy.algorithm != TPMSHX_ENERGY_TEMPERATURE_SOU
                || energy.has_temperature_update != 1 || !isfinite(energy.temperature_update)
                || energy.temperature_update > 1e-8 || result.residual > config.update_tolerance
                || result.audit_available != (mask != 0)
                || (mask && result.audit.fluid_equations_computed != config.equation_gate)
                || (config.coupled_gate && result.audit.coupled_ratio > config.coupled_tolerance)
                || (config.equation_gate && result.audit.equation_ratio > config.equation_tolerance)) {
                fprintf(stderr,"T-SOU C gates failed: mask=%u, status=%d, %s\n",mask,status,error);
                return 10;
            }
            if (mask == 1 && (!isnan(result.audit.equation_ratio)
                || !isnan(result.audit.fluid_abs_sum[0]) || !isnan(result.audit.fluid_abs_sum[1]))) return 11;
            for (i = 0; i < 8; ++i)
                if (!isfinite(ha[i]) || !isfinite(hb[i]) || !isfinite(ta[i]) || !isfinite(tb[i])
                    || !isfinite(ts[i]) || ta[i] < 299. || ta[i] > 371.) return 12;
            if (fabs(result.q_a+result.q_b) > 1e-3*fmax(fabs(result.q_a),fabs(result.q_b))) return 13;
        }
        config.coupled_gate = config.equation_gate = 1;
        config.update_tolerance = 1e-13;
        status = tpmshx_solve_enthalpy_v2(shape,arrays,sizes,&config,1e-3,NULL,
            &result,&energy,error,sizeof(error));
        if (status || result.stop != TPMSHX_ENTHALPY_CONVERGED
            || result.residual > config.update_tolerance || energy.temperature_update > 1e-3) return 19;
        config.update_tolerance = 2e-5;
        config.sweeps = 0; config.max_iterations = 2;
        status = tpmshx_solve_enthalpy_v2(shape,arrays,sizes,&config,1e-8,NULL,
            &result,&energy,error,sizeof(error));
        if (status || result.stop != TPMSHX_ENTHALPY_ITERATION_LIMIT || result.iterations != 2
            || energy.has_temperature_update != 1 || energy.temperature_update != 0.
            || result.residual != 0. || !result.audit_available
            || result.audit.equation_ratio <= config.equation_tolerance) return 17;
        for (i=0;i<8;++i)
            if (ta[i] != 370. || tb[i] != 300. || ts[i] != 335.) return 18;
        config.sweeps = 5; config.max_iterations = 1000;
        {
            const double invalid[] = {0.,-1.,NAN};
            for (i=0;i<3;++i) {
                result.stop = 93; energy.algorithm = 97;
                status = tpmshx_solve_enthalpy_v2(shape,arrays,sizes,&config,invalid[i],NULL,
                    &result,&energy,error,sizeof(error));
                if (status != TPMSHX_ENTHALPY_INVALID_ARGUMENT || result.stop != 93 || energy.algorithm != 97) return 14;
            }
            status = tpmshx_solve_enthalpy_v2(shape,arrays,sizes,&config,1e-8,NULL,
                &result,NULL,error,sizeof(error));
            if (status != TPMSHX_ENTHALPY_INVALID_ARGUMENT || result.stop != 93) return 15;
        }
        {
            const tpmshx_enthalpy_callbacks_v1 callbacks = {cancel_first,&calls};
            calls = 0;
            status = tpmshx_solve_enthalpy_v2(shape,arrays,sizes,&config,1e-8,&callbacks,
                &result,&energy,error,sizeof(error));
            if (status || result.stop != TPMSHX_ENTHALPY_CANCELLED || result.audit_available
                || energy.algorithm != TPMSHX_ENERGY_TEMPERATURE_SOU || energy.has_temperature_update || calls != 1) return 16;
            calls = 0;
        }
        printf("T-SOU C ABI optional gates and actual Kelvin evidence ok\n");
    }

    result.stop = 93; result.iterations = 97; result.q_a = 123456.;
    config.warm_a = 2;
    status = tpmshx_solve_enthalpy_v1(shape,arrays,sizes,&config,NULL,&result,error,sizeof(error));
    if (status != TPMSHX_ENTHALPY_INVALID_ARGUMENT || result.stop != 93
        || result.iterations != 97 || result.q_a != 123456.) return 4;
    config.warm_a = 0;
    {
        char short_error[2] = {'x','x'};
        status = tpmshx_solve_enthalpy_v1(NULL,arrays,sizes,&config,NULL,&result,short_error,2);
        if (status != TPMSHX_ENTHALPY_INVALID_ARGUMENT || short_error[1] != '\0') return 5;
    }
    arrays[20] = NULL;
    status = tpmshx_solve_enthalpy_v1(shape,arrays,sizes,&config,NULL,&result,error,sizeof(error));
    if (status != TPMSHX_ENTHALPY_INVALID_ARGUMENT || result.stop != 93) return 6;
    arrays[20] = ts;
    config.sides[1].inlet_temperature = 500.;
    status = tpmshx_solve_enthalpy_v1(shape,arrays,sizes,&config,NULL,&result,error,sizeof(error));
    if (status != TPMSHX_ENTHALPY_WATER_STATE || result.stop != 93
        || !strstr(error,"enthalpy inlet B") || !strstr(error,"P_abs=")) return 7;
    config.sides[1].inlet_temperature = 300.;
    {
        const tpmshx_enthalpy_callbacks_v1 callbacks = {cancel_first,&calls};
        status = tpmshx_solve_enthalpy_v1(shape,arrays,sizes,&config,&callbacks,&result,error,sizeof(error));
        if (status || result.stop != TPMSHX_ENTHALPY_CANCELLED || result.iterations
            || result.audit_available || calls != 1) return 8;
    }
    return 0;
}
