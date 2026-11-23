#include "tpmshx/result_checks_c_api.h"
#include "tpmshx/result_balance_c_api.h"
#include "tpmshx/result_metrics_c_api.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define REQUIRE(test) do {if (!(test)) {fprintf(stderr,"result C caller failed: line %d\n",__LINE__);return 1;}} while (0)

int main(void) {
    char error[256];
    double data[2]={1.5,2.5};
    const size_t shape[1]={2};
    tpmshx_result_array_v2 input={data,1,shape};
    tpmshx_result_diagnostics_v1 diagnostics;
    tpmshx_result_array_check_values_v1 output={91,92};
    REQUIRE(tpmshx_result_abi_version_v1()==TPMSHX_RESULT_ABI_VERSION);
    REQUIRE(tpmshx_result_abi_version_v1()==3);
    REQUIRE(tpmshx_result_array_checks_v1(input,&output,&diagnostics,error,sizeof(error))==0);
    REQUIRE(output.all_finite==1 && output.all_zero==0 && diagnostics.event_count==0);
    input.data=NULL;
    output.all_finite=91;output.all_zero=92;
    REQUIRE(tpmshx_result_array_checks_v1(input,&output,&diagnostics,error,sizeof(error))==TPMSHX_RESULT_INVALID);
    REQUIRE(output.all_finite==91 && output.all_zero==92);
    input.data=data;
    REQUIRE(tpmshx_result_array_checks_v1(input,&output,&diagnostics,(char*)data,sizeof(data))==TPMSHX_RESULT_INVALID);
    REQUIRE(data[0]==1.5 && data[1]==2.5);
    REQUIRE(output.all_finite==91 && output.all_zero==92);
    REQUIRE(tpmshx_result_array_checks_v1(input,NULL,&diagnostics,error,sizeof(error))==TPMSHX_RESULT_INVALID);
    {
        union {tpmshx_result_diagnostics_v1 diagnostics;tpmshx_result_array_check_values_v1 output;} alias;
        memset(&alias,0x5a,sizeof(alias));
        REQUIRE(tpmshx_result_array_checks_v1(input,&alias.output,&alias.diagnostics,error,sizeof(error))==TPMSHX_RESULT_INVALID);
        REQUIRE(alias.output.all_finite==UINT32_C(0x5a5a5a5a));
    }
    {
        double residual[3]={-2.,3.,4.};
        const size_t count[1]={3};
        tpmshx_result_array_v2 view={residual,1,count};
        tpmshx_result_norm_values_v1 norms;
        REQUIRE(tpmshx_result_balance_norms_v1(&view,&norms,&diagnostics,error,sizeof(error))==0);
        REQUIRE(norms.signed_sum==5. && norms.l1==9. && norms.cell_max==4. && norms.cell_count==3);
    }
    {
        double dx[2]={1.,2.},dy[2]={3.,4.},area=-91.;
        tpmshx_result_array_v2 x={dx,1,shape};
        tpmshx_result_array_v2 y={dy,1,shape};
        REQUIRE(tpmshx_result_capture_area_v1(&x,&y,&area,&diagnostics,error,sizeof(error))==0);
        REQUIRE(area==21. && diagnostics.event_count==0);
        area=-91.;
        REQUIRE(tpmshx_result_mach_from_sound_v1(1.,0.,&area,&diagnostics,error,sizeof(error))==TPMSHX_RESULT_NUMERIC);
        REQUIRE(area==-91. && diagnostics.python_cause==TPMSHX_RESULT_ZERO_DIVISION && error[0]);
    }
    puts("PASS: independent result C caller and atomic malformed-buffer checks");
    return 0;
}
