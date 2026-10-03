#include "tpmshx/simple_3d_c_api.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int calls;
static int TPMSHX_THERMAL_CALL cancel(void* context) {
    (void)context;return ++calls>=3;
}
static size_t progress_calls;
static void TPMSHX_THERMAL_CALL progress(void* context,size_t iteration,double residual) {
    (void)context;if(iteration&&isfinite(residual))++progress_calls;
}
#define CHECK(c) do { if(!(c)) { fprintf(stderr,"line %d: %s\n",__LINE__,#c);goto failed; } } while(0)
int main(void) {
    const size_t nx=4,ny=5,nz=3,n=60,nu=75,nv=72,nw=80;
    double dx[4]={.009,.009,.009,.009},dy[5]={.016,.016,.016,.016,.016},dz[3]={.008,.008,.008};
    uint8_t open[12];memset(open,1,sizeof open);
    size_t sizes[21]={n,n,n,n,n,n,nu,nv,nw,n,n,nu,nv,nw,n,12,15,16,nu,nv,nw};
    double* a[21]={0};size_t i,j,needed=0;char error[512]={0};tpmshx_simple_3d_handle* handle=NULL;
    tpmshx_simple_3d_result_v1 result,untouched;
    tpmshx_simple_3d_config_v1 config={0};
    tpmshx_simple_callbacks_v1 callbacks={0};
    CHECK(tpmshx_simple_3d_abi_version()==1);
    for(i=0;i<21;++i) { a[i]=(double*)calloc(sizes[i],sizeof(double));CHECK(a[i]!=NULL); }
    for(i=0;i<n;++i) { a[0][i]=.6;a[1][i]=1.8e-5;a[2][i]=3e-5;a[3][i]=1e-7;a[4][i]=35.;a[5][i]=300.;a[14][i]=1.2; }
    for(i=0;i<nv;++i)a[7][i]=.7;
    for(i=0;i<12;++i)a[15][i]=.7;
    for(i=16;i<18;++i)for(j=0;j<sizes[i];++j)a[i][j]=1.;
    config.max_iterations=600;config.inner_sweeps=1;config.pressure_rebuild_every=100;
    config.alpha_velocity=.5;config.alpha_pressure=.2;config.alpha_density=.3;
    config.pressure_reference_absolute=101325.;config.gas_constant=287.05;config.pressure_diagonal_drift=.05;
    config.ideal_gas=1;config.massflux_inlet=1;config.adaptive_pressure_tolerance=1;config.track_momentum=1;
    config.convergence.momentum_tolerance=1e-4;config.convergence.local_mass_tolerance=1e-6;config.convergence.global_mass_tolerance=1e-6;
    config.convergence.backflow_maximum=.01;config.convergence.velocity_check_tolerance=1e-4;config.convergence.stall_ratio=1e-3;
    config.convergence.confirmations=2;config.convergence.momentum_interval=5;config.convergence.stall_window=60;
    callbacks.progress=progress;
    CHECK(tpmshx_simple_3d_create_v1(nx,ny,nz,dx,dy,dz,open,&handle,error,sizeof error)==TPMSHX_SIMPLE_OK);
    CHECK(tpmshx_simple_3d_solve_v1(handle,a,sizes,&config,&callbacks,&result,error,sizeof error)==TPMSHX_SIMPLE_OK);
    CHECK(result.stop==TPMSHX_SIMPLE_TOL&&result.converged&&result.post_closure_certified&&result.mass_faces_available);
    CHECK(result.mass.counted_cells==n&&progress_calls>0);
    CHECK(result.pressure.success&&result.pressure.pin_max_abs<=1e-10);
    for(i=18;i<21;++i)for(j=0;j<sizes[i];++j)CHECK(isfinite(a[i][j]));
    CHECK(tpmshx_simple_3d_history_v1(handle,4,NULL,0,&needed,error,sizeof error)==TPMSHX_SIMPLE_OK&&needed==12);
    for(i=0;i<n;++i)a[5][i]+=1.;
    CHECK(tpmshx_simple_3d_solve_v1(handle,a,sizes,&config,&callbacks,&result,error,sizeof error)==TPMSHX_SIMPLE_OK&&result.converged);
    memset(&result,0x5a,sizeof result);memcpy(&untouched,&result,sizeof result);
    config.ideal_gas=2;
    CHECK(tpmshx_simple_3d_solve_v1(handle,a,sizes,&config,NULL,&result,error,sizeof error)==TPMSHX_SIMPLE_INVALID_ARGUMENT);
    CHECK(memcmp(&result,&untouched,sizeof result)==0&&error[0]);config.ideal_gas=1;
    callbacks.cancel=cancel;
    for(i=18;i<21;++i)for(j=0;j<sizes[i];++j)a[i][j]=-999.;
    CHECK(tpmshx_simple_3d_solve_v1(handle,a,sizes,&config,&callbacks,&result,error,sizeof error)==TPMSHX_SIMPLE_OK);
    CHECK(result.stop==TPMSHX_SIMPLE_CANCELLED&&!result.converged&&!result.mass_faces_available&&result.iterations==1&&calls==3);
    for(i=18;i<21;++i)for(j=0;j<sizes[i];++j)CHECK(a[i][j]==-999.);
    tpmshx_simple_3d_destroy(handle);for(i=0;i<21;++i)free(a[i]);
    puts("3D public C ABI cold/warm/raw-mass/error/cancel passed");return 0;
failed:
    fprintf(stderr,"native error: %s\n",error);
    tpmshx_simple_3d_destroy(handle);for(i=0;i<21;++i)free(a[i]);return 1;
}
