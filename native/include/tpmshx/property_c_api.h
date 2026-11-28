#ifndef TPMSHX_PROPERTY_C_API_H
#define TPMSHX_PROPERTY_C_API_H

#include "tpmshx/preparation_c_api.h"

#define TPMSHX_PROPERTY_EVENT_COUNT TPMSHX_PREPARATION_FP_EVENT_COUNT

/* Inputs are contiguous float64 buffers after Python shape broadcasting. */
typedef struct {const double* values;size_t count;} tpmshx_property_input_v1;
/* values has count elements. events has at least TPMSHX_PROPERTY_EVENT_COUNT
 * elements; event_count receives the used prefix. Event bits:
 * 0..3=invalid/divide/overflow/underflow, 8..15=operation.
 * Failure preserves values, events and event_count.
 */
typedef struct {
    double* values;size_t count;
    uint32_t* events;size_t event_capacity;size_t* event_count;
} tpmshx_property_output_v1;
typedef struct {const char* data;size_t size;} tpmshx_property_key_v1;
/* SIZE_MAX means that no logical index is available. detail holds a phase
 * code or a melting temperature when the corresponding reason supplies it.
 * Water reason 6 is a policy error; reason 7 is an EOS error.
 */
typedef struct {
    uint32_t reason,input;
    size_t index,first_t_index,first_p_index;
    double temperature,pressure,detail;
    tpmshx_preparation_fp_failure_v1 fp;
} tpmshx_property_failure_v1;

enum tpmshx_preparation_cache_id {
    TPMSHX_PREPARATION_CACHE_GEOMETRY=0, TPMSHX_PREPARATION_CACHE_CO2=1, TPMSHX_PREPARATION_CACHE_SCO2=2
};
typedef struct {size_t hits,misses,maxsize,currsize;} tpmshx_preparation_cache_info_v1;

#ifdef __cplusplus
extern "C" {
#endif

TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_property_backend_v1(
    char* version,size_t version_capacity,char* revision,size_t revision_capacity,
    char* error,size_t error_capacity);
/* Getter order: air mu/k/rho/cp, then water rho/mu/k/cp. Only air rho reads P.
 * Water cp returns one value, including for an empty temperature array.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_empirical_v1(
    uint32_t getter,tpmshx_property_input_v1 temperature,tpmshx_property_input_v1 pressure,
    tpmshx_property_output_v1 result,tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_water_pt_v1(
    const double* temperature,const double* pressure,size_t count,
    tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_co2_validate_pt_v1(
    const double* temperature,const double* pressure,size_t count,
    tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
/* Scalar geometry returns epsilon, epsilon A, epsilon B, area density (1/m) and diameter (m).
 * On a geometry error, failure.reason is 1=cell, 2=wall, 3=closed pore or 4=degenerate.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_cached_geometry_v1(
    uint32_t topology,double cell_mm,double wall_mm,size_t resolution,double* values,size_t value_count,
    tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_read_cache_info_v1(
    uint32_t id,tpmshx_preparation_cache_info_v1* result,char* error,size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_clear_cache_v1(
    uint32_t id,char* error,size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_cached_sco2_v1(
    tpmshx_property_key_v1 key,double temperature,double pressure,double* result,
    tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
/* Both CO2 queries require a non-null cause_offset. It receives the byte offset of the first
 * cause byte in error, or SIZE_MAX if the buffer contains no cause bytes.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_cached_co2_v1(
    double temperature,double pressure,double* values,size_t value_count,size_t* cause_offset,
    tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
/* Keys: 0=D, 1=V, 2=L, 3=C, 4=H. Values use [key][point] order.
 * An empty key list still checks Phase. Empty CO2 states are rejected.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_co2_pt_v2(
    const double* temperature,const double* pressure,size_t count,
    const uint32_t* keys,size_t key_count,double* values,size_t value_count,size_t* cause_offset,
    tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_sco2_validate_v1(
    const double* temperature,size_t temperature_count,const double* pressure,size_t pressure_count,
    tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
/* Form: 0=string scalar, 1=string field, 2=tuple query. Keys retain the
 * original CoolProp strings. Values use [key][point] order.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_sco2_pt_v1(
    uint32_t form,const tpmshx_property_key_v1* keys,size_t key_count,
    const double* temperature,const double* pressure,size_t count,
    double* values,size_t value_count,tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_sco2_hp_scalar_v1(
    double enthalpy,double pressure,double* temperature,size_t temperature_count,
    tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_sco2_hp_v1(
    const double* enthalpy,const double* pressure,size_t count,double* temperature,size_t temperature_count,
    tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
/* Route: 0=air direct, 1=air vector, 2=water, 3=sCO2, 4=CO2 segment 2.
 * Prepare inputs before the original warning/topology stages. Extrema order:
 * prepared Re min/max, Pr min/max. Unused or empty extrema are NaN.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_nu_inputs_v1(
    uint32_t route,tpmshx_property_input_v1 re,tpmshx_property_input_v1 pr,
    tpmshx_property_input_v1 cell,tpmshx_property_input_v1 diameter,
    tpmshx_property_input_v1 re_floor,tpmshx_property_output_v1 prepared_re,
    double* extrema,size_t extrema_count,tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_nu_v1(
    uint32_t route,uint32_t topology,tpmshx_property_input_v1 re,tpmshx_property_input_v1 pr,
    tpmshx_property_input_v1 cell,tpmshx_property_input_v1 diameter,
    double selected_alpha,tpmshx_property_output_v1 result,
    tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
/* Quantity: 0=Petukhov, 1=Haaland, 2=height ratio, 3=friction gain,
 * 4=extra Nu factor, 5=unit factor. Quantity 5 reads no inputs.
 * Quantities 0 and 4 read first only. Other quantities read both inputs.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_roughness_v1(
    uint32_t quantity,tpmshx_property_input_v1 first,tpmshx_property_input_v1 second,
    tpmshx_property_output_v1 result,tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_reynolds_v1(
    tpmshx_property_input_v1 rho,tpmshx_property_input_v1 speed,
    tpmshx_property_input_v1 diameter,tpmshx_property_input_v1 mu,tpmshx_property_output_v1 result,
    tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_prandtl_v1(
    tpmshx_property_input_v1 mu,tpmshx_property_input_v1 cp,tpmshx_property_input_v1 conductivity,
    tpmshx_property_output_v1 result,tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_surface_transfer_v1(
    tpmshx_property_input_v1 nu,tpmshx_property_input_v1 conductivity,tpmshx_property_input_v1 diameter,
    tpmshx_property_output_v1 result,tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_inlet_re_pr_v1(
    tpmshx_property_input_v1 rho,tpmshx_property_input_v1 mu,tpmshx_property_input_v1 conductivity,
    tpmshx_property_input_v1 cp,tpmshx_property_input_v1 speed,tpmshx_property_input_v1 diameter,
    tpmshx_property_output_v1 re,tpmshx_property_output_v1 pr,
    tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_inlet_transfer_v1(
    tpmshx_property_input_v1 nu,tpmshx_property_input_v1 conductivity,tpmshx_property_input_v1 diameter,
    tpmshx_property_input_v1 area,tpmshx_property_input_v1 epsilon,
    tpmshx_property_output_v1 surface,tpmshx_property_output_v1 volume,tpmshx_property_output_v1 pore,
    tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_volumetric_transfer_v1(
    tpmshx_property_input_v1 surface,tpmshx_property_input_v1 area,tpmshx_property_output_v1 result,
    tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_pore_conductivity_v1(
    tpmshx_property_input_v1 epsilon,tpmshx_property_input_v1 conductivity,tpmshx_property_output_v1 result,
    tpmshx_property_failure_v1* failure,char* error,size_t error_capacity);

#ifdef __cplusplus
}
#endif
#endif
