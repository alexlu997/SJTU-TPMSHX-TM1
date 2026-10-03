#include "tpmshx/model_h_c_api.h"
#include <math.h>
#include <stdio.h>

#define CHECK(x) do { if (!(x)) { fprintf(stderr,"model-h C check failed, line %d\n",__LINE__); return 1; } } while (0)
static int TPMSHX_THERMAL_CALL cancel(void* value) { return *(int*)value; }
int main(void) {
    CHECK(tpmshx_model_h_abi_version()==1);
    for (unsigned dimension=2;dimension<=3;++dimension) {
        size_t shape[3]={1,1,dimension==2?1:2};
        const size_t n=shape[2];
        double dx[1]={1},dy[1]={1},dz[2]={1,1};
        double zero[2]={0,0},hv[2]={2,2},mx[4]={0},my[4]={0},mz[3]={0};
        double ta[2]={350,350},tb[2]={300,300},ts[2]={325,325};
        double* arrays[24]={dx,dy,dz,zero,NULL,zero,hv,mx,my,mz,NULL,NULL,NULL,
            zero,hv,mx,my,mz,NULL,NULL,NULL,ta,tb,ts};
        size_t sizes[24]={1,1,n,n,0,n,n,2*n,2*n,dimension==3?n+1:0,0,0,0,
            n,n,2*n,2*n,dimension==3?n+1:0,0,0,0,n,n,n};
        tpmshx_model_h_config_v1 config={0};
        config.dimension=dimension; config.fluid_b=1; config.direction_b=1;
        config.warm_start=1; config.max_iterations=1; config.chunk_iterations=1;
        config.inlet_a=350; config.inlet_b=300; config.q_relative_tolerance=1e-4;
        config.alpha_a=.2; config.alpha_solid=1; config.alpha_b=.2;
        tpmshx_model_h_result_v1 result={0}; char error[512];
        CHECK(!tpmshx_solve_model_h_v1(shape,arrays,sizes,&config,NULL,&result,error,sizeof(error)));
        CHECK(result.dimension==dimension && result.stop==1 && result.iterations==1 && result.audit_available);
        CHECK(fabs(ta[0]-345)<1e-12 && fabs(ts[0]-322.5)<1e-12 && fabs(tb[0]-304.5)<1e-12);
        const tpmshx_model_h_array_v1 residual=dimension==2?result.plane.sides[0].residual:result.volume.sides[0].residual;
        CHECK(residual.size==n && residual.data && isfinite(residual.data[0]));
        const double saved=residual.data[0]; ta[0]=999; hv[0]=999;
        CHECK(residual.data[0]==saved); /* owner does not borrow caller fields */
        tpmshx_model_h_release_v1(&result); CHECK(!result.owner && !result.audit_available);
        tpmshx_model_h_release_v1(&result); /* cleared handle is safe */
        config.fluid_a=99; result.iterations=719; char short_error[1]={'x'};
        CHECK(tpmshx_solve_model_h_v1(shape,arrays,sizes,&config,NULL,&result,short_error,1)==1);
        CHECK(result.iterations==719 && short_error[0]=='\0' && !result.owner);
        config.fluid_a=0; config.warm_start=0; hv[0]=2;
        int should_cancel=1;
        tpmshx_model_h_callbacks_v1 callbacks={cancel,NULL,&should_cancel};
        CHECK(!tpmshx_solve_model_h_v1(shape,arrays,sizes,&config,&callbacks,&result,error,sizeof(error)));
        CHECK(result.stop==2 && !result.audit_available);
        tpmshx_model_h_release_v1(&result); should_cancel=0;
        CHECK(!tpmshx_solve_model_h_v1(shape,arrays,sizes,&config,&callbacks,&result,error,sizeof(error)));
        CHECK(result.stop==1 && result.audit_available);
        tpmshx_model_h_release_v1(&result);
    }
    tpmshx_model_h_release_v1(NULL);
    puts("model-h C ABI: 2D/3D phase schedule, owned views, errors and cancel recovery passed");
    return 0;
}
