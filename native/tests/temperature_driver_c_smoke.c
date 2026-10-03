#include "tpmshx/temperature_driver_c_api.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

typedef struct { size_t cancel_at,calls,progress,last; } context;
static int TPMSHX_THERMAL_CALL cancel(void* p) {
    context* c=(context*)p; ++c->calls; return c->cancel_at && c->calls>=c->cancel_at;
}
static void TPMSHX_THERMAL_CALL progress(void* p,size_t done,size_t total) {
    context* c=(context*)p; ++c->progress; c->last=done; (void)total;
}
int main(void) {
    double storage[31][64],*arrays[31]; size_t sizes[31],shape[3]={4,3,2};
    tpmshx_temperature_driver_v1* driver=NULL;
    tpmshx_temperature_result_v1 result={0};
    tpmshx_temperature_config_v1 config={0};
    context calls={0};
    tpmshx_temperature_callbacks_v1 callbacks={cancel,progress,&calls};
    char error[256]; size_t p,i,mode;
    if (tpmshx_temperature_driver_abi_version()!=1) return 1;
    if (tpmshx_temperature_driver_create_v1(&driver,error,sizeof(error)) || !driver) return 2;
    for (p=0;p<31;++p) arrays[p]=storage[p];
    config.direction_a=0; config.direction_b=2; config.inlet_a=350; config.inlet_b=300;
    config.max_iterations=8; config.chunk_iterations=4; config.q_relative_tolerance=1e-6;
    for (mode=0;mode<4;++mode) {
        const size_t scheme=mode==3 ? 0 : mode;
        size_t n; shape[2]=scheme==0 ? 1 : 2; n=shape[0]*shape[1]*shape[2];
        memset(storage,0,sizeof(storage)); memset(sizes,0,sizeof(sizes)); memset(&calls,0,sizeof(calls));
        sizes[0]=4; sizes[1]=3; sizes[2]=shape[2];
        for (p=0;p<3;++p) for (i=0;i<sizes[p];++i) storage[p][i]=p==2 && scheme==0 ? 1 : .01;
        sizes[3]=n; for (i=0;i<n;++i) storage[3][i]=5;
        for (p=6;p<=17;p+=11) {
            size_t axis;
            for (i=0;i<n;++i) { storage[p][i]=.2; storage[p+1][i]=10000; storage[p+2][i]=.35; storage[p+3][i]=1200; }
            for (i=0;i<4;++i) sizes[p+i]=n;
            for (axis=0;axis<3;++axis) {
                sizes[p+4+axis]=axis==2 && scheme==0 ? 0 : (scheme==2 ? n/shape[axis]*(shape[axis]+1) : n);
                for (i=0;i<sizes[p+4+axis];++i) storage[p+4+axis][i]=(p==6 ? axis==0 : axis==1) ? .1 : 0;
            }
        }
        if (scheme==2) storage[10][shape[1]*shape[2]]+=.01;
        for (p=28;p<31;++p) { sizes[p]=n; for (i=0;i<n;++i) storage[p][i]=NAN; }
        config.scheme=(uint32_t)scheme; config.conservative=scheme==2; config.second_order_b=scheme!=0;
        config.red_black=mode==3;
        config.alpha_a=.7; config.alpha_solid=scheme==0 ? 1 : .7; config.alpha_b=scheme==0 ? 1 : .7;
        if (tpmshx_solve_temperature_v1(driver,shape,arrays,sizes,&config,&callbacks,&result,error,sizeof(error))) {
            fprintf(stderr,"temperature C smoke: %s\n",error); return 3;
        }
        if (result.scheme!=scheme || result.stop>1 || result.iterations!=8 || calls.progress!=2
            || !isfinite(result.q_b) || !isfinite(storage[28][0])) return 4;
        if (scheme==2 && (!result.fluid[0].available || !result.fluid[1].available
            || result.fluid[0].cell_count!=n || result.projection[0].skipped)) return 5;
        if (scheme==2) {
            const double saved=result.fluid[0].cells[0];
            storage[28][0]=NAN;
            if (result.fluid[0].cells[0]!=saved) return 6;
        }
        tpmshx_temperature_release_v1(&result); tpmshx_temperature_release_v1(&result);
        if (result.owner || result.fluid[0].cells) return 7;
    }
    config.warm_start=2; result.iterations=991;
    if (tpmshx_solve_temperature_v1(driver,shape,arrays,sizes,&config,NULL,&result,error,2)!=1
        || result.iterations!=991 || error[1]!='\0') return 8;
    config.warm_start=0; config.accelerate=1;
    if (tpmshx_solve_temperature_v1(driver,shape,arrays,sizes,&config,NULL,&result,error,sizeof(error))!=1) return 9;
    config.accelerate=0;
    if (tpmshx_solve_temperature_v1(NULL,shape,arrays,sizes,&config,NULL,&result,error,sizeof(error))!=1) return 10;
    memset(&result,0,sizeof(result)); calls.cancel_at=1; calls.calls=0;
    if (tpmshx_solve_temperature_v1(driver,shape,arrays,sizes,&config,&callbacks,&result,error,sizeof(error))
        || result.stop!=2 || result.fluid[0].available || result.fluid[1].available) return 11;
    tpmshx_temperature_release_v1(&result);
    tpmshx_temperature_driver_destroy_v1(driver); tpmshx_temperature_driver_destroy_v1(NULL);
    puts("temperature_c ABI=1 CC2D_serial+RB+CC3D+staggered owned_audit+cancel+errors PASS");
    return 0;
}
