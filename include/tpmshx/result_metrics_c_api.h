#ifndef TPMSHX_RESULT_METRICS_C_API_H
#define TPMSHX_RESULT_METRICS_C_API_H
#include "tpmshx/result_c_api.h"
#ifdef __cplusplus
extern "C" {
#endif

/* Array outputs use caller-owned writable storage described by the output
 * view. The descriptor and its shape are read-only during the call.
 * Double arguments use the Python float rules of result_c_api.h.
 */
#define TPMSHX_METRICS_DIAG tpmshx_result_diagnostics_v1*,char*,size_t
#define TPMSHX_METRICS_DECL(name) TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_##name##_v1
TPMSHX_METRICS_DECL(pressure_ratio)(const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(pressure_face)(const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(capacity_porosity)(const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(capacity_split_field)(const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(capacity_split)(double,uint32_t,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(port_width_valid)(const tpmshx_result_array_v2*,uint32_t*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(port_opening_valid)(const tpmshx_result_array_v2*,uint32_t*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(weighted_mean)(const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(port_weights)(const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(capacity_duty)(const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(outlet_temperature_2d)(const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,uint32_t,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(outlet_temperature_3d)(const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,uint32_t,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(boundary_enthalpy_duty)(const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,double,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(plane_duty)(const tpmshx_result_array_v2*,size_t,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(staggered_power_duty_2d)(const tpmshx_result_array_v2*,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(boundary_mass_2d)(const tpmshx_result_array_v2*,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(boundary_mass_3d)(const tpmshx_result_array_v2*,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(solid_mass_2d)(const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(solid_mass_3d)(const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(outlet_mean)(const tpmshx_result_array_v2*,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(capture_area)(const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(capture_area_weights)(const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(duty_magnitude)(double,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(mass_imbalance)(double,double,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(full_energy_imbalance)(double,double,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(richardson_duty)(double,double,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(pressure_difference)(double,double,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(absolute_outlet_pressure)(double,double,double*,TPMSHX_METRICS_DIAG);
TPMSHX_METRICS_DECL(pressure_difference_field)(const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,const tpmshx_result_array_v2*,TPMSHX_METRICS_DIAG);
#undef TPMSHX_METRICS_DECL
#undef TPMSHX_METRICS_DIAG
#ifdef __cplusplus
}
#endif
#endif
