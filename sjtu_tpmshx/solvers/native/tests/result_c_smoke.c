#include "tpmshx/result_checks_c_api.h"
#include "tpmshx/result_balance_c_api.h"
#include "tpmshx/result_metrics_c_api.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define REQUIRE(test) do {if (!(test)) {fprintf(stderr,"result C caller failed: line %d\n",__LINE__);return 1;}} while (0)

int main(void) {
    char error[256];
    uint64_t data[2]={UINT64_C(9007199254740993),UINT64_MAX};
    const size_t shape[1]={2};
    const ptrdiff_t strides[1]={8};
    tpmshx_result_array_v1 input={data,sizeof(data),0,TPMSHX_RESULT_U64,TPMSHX_RESULT_NUMPY_ARRAY,
        TPMSHX_RESULT_NATIVE_ENDIAN,0,1,shape,strides};
    tpmshx_result_diagnostics_v1 diagnostics;
    tpmshx_result_array_check_values_v1 output={91,92};
    tpmshx_result_platform_v1 format;
    REQUIRE(tpmshx_result_abi_version_v1()==2);
    REQUIRE(tpmshx_result_platform_info_v1(&format,error,sizeof(error))==0);
    REQUIRE(format.long_double_size==sizeof(long double));
    REQUIRE(tpmshx_result_array_checks_v1(input,&output,&diagnostics,error,sizeof(error))==0);
    REQUIRE(output.all_finite==1 && output.all_zero==0 && diagnostics.event_count==0);
    input.bytes=sizeof(uint64_t);
    output.all_finite=91;output.all_zero=92;
    REQUIRE(tpmshx_result_array_checks_v1(input,&output,&diagnostics,error,sizeof(error))==TPMSHX_RESULT_INVALID);
    REQUIRE(output.all_finite==91 && output.all_zero==92);
    input.bytes=sizeof(data);
    REQUIRE(tpmshx_result_array_checks_v1(input,&output,&diagnostics,(char*)data,sizeof(data))==TPMSHX_RESULT_INVALID);
    REQUIRE(data[0]==UINT64_C(9007199254740993) && data[1]==UINT64_MAX);
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
        tpmshx_result_array_v1 view={residual,sizeof(residual),0,TPMSHX_RESULT_F64,
            TPMSHX_RESULT_NUMPY_ARRAY,TPMSHX_RESULT_NATIVE_ENDIAN,0,1,count,strides};
        tpmshx_result_norm_values_v1 norms;
        REQUIRE(tpmshx_result_balance_norms_v1(&view,&norms,&diagnostics,error,sizeof(error))==0);
        REQUIRE(norms.signed_sum==5. && norms.l1==9. && norms.cell_max==4. && norms.cell_count==3);
    }
    {
        double dx[2]={1.,2.},dy[2]={3.,4.},area=-91.;
        tpmshx_result_array_v1 x={dx,sizeof(dx),0,TPMSHX_RESULT_F64,
            TPMSHX_RESULT_NUMPY_ARRAY,TPMSHX_RESULT_NATIVE_ENDIAN,0,1,shape,strides};
        tpmshx_result_array_v1 y=x;
        y.data=dy;
        REQUIRE(tpmshx_result_capture_area_v1(&x,&y,&area,&diagnostics,error,sizeof(error))==0);
        REQUIRE(area==21. && diagnostics.event_count==0);
        area=-91.;
        REQUIRE(tpmshx_result_mach_from_sound_v1(1.,0.,&area,&diagnostics,error,sizeof(error))==TPMSHX_RESULT_NUMERIC);
        REQUIRE(area==-91. && diagnostics.python_cause==TPMSHX_RESULT_ZERO_DIVISION && error[0]);
    }
    puts("PASS: independent result C caller and atomic malformed-buffer checks");
    return 0;
}
