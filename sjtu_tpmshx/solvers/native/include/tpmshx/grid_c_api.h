#ifndef TPMSHX_GRID_C_API_H
#define TPMSHX_GRID_C_API_H
#include "tpmshx/geometry_c_api.h"
#ifdef __cplusplus
extern "C" {
#endif
/* strong=0: Python float, precision=64. strong=1: NumPy float, precision=16/32/64.
 * strong=2: NumPy integer, precision=8/16/32/64, for mixed floating arithmetic.
 * Integer values use double transport; this is not a modular integer engine.
 */
typedef struct {double value;uint32_t precision,strong;} tpmshx_grid_scalar_v1;
typedef struct {
    int32_t direction;
    uint32_t active;
    tpmshx_grid_scalar_v1 values[2][4];
    uint32_t present[2][4]; /* center, width, second center, second width. */
} tpmshx_grid_port_v1;
typedef struct {size_t layers,minimum;double first,growth;} tpmshx_grid_wall_spec_v1;
/* Buffers are borrowed. Counts use elements. Outputs do not overlap inputs.
 * Output extents are exact, except edge capacity. Failure leaves outputs unchanged.
 * These calls use the geometry status and error-buffer contract.
 */
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_uniform_v1(
 size_t count,tpmshx_grid_scalar_v1 length,double* result,size_t result_count,char* error,size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_aligned_filter_v1(
 tpmshx_grid_scalar_v1 length,const tpmshx_grid_scalar_v1* points,size_t count,
 uint8_t* result,size_t result_count,char* error,size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_aligned_v1(
 size_t count,const tpmshx_grid_scalar_v1* bounds,size_t bounds_count,
 double* result,size_t result_count,char* error,size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_wall_v1(
 tpmshx_grid_scalar_v1 length,size_t bulk,size_t layers,tpmshx_grid_scalar_v1 first,tpmshx_grid_scalar_v1 growth,
 double* result,size_t result_count,char* error,size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_port_edges_v1(
 const tpmshx_grid_scalar_v1* lengths,size_t dimensions,const tpmshx_grid_port_v1* ports,size_t ports_count,size_t axis,
 tpmshx_grid_scalar_v1* result,size_t capacity,size_t* result_count,char* error,size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_breaks_2d_v1(
 const tpmshx_grid_scalar_v1* lengths,const tpmshx_grid_port_v1* ports,size_t ports_count,size_t axis,
 tpmshx_grid_scalar_v1* result,size_t capacity,size_t* result_count,char* error,size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_wall_spec_v1(
 size_t dimensions,size_t knots,tpmshx_grid_wall_spec_v1* result,char* error,size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_port_wall_axis_v1(
 size_t dimensions,size_t axis,size_t count,const tpmshx_grid_scalar_v1* bounds,size_t bounds_count,
 const tpmshx_grid_scalar_v1* bulk_bounds,size_t bulk_bounds_count,
 double* result,size_t result_count,char* error,size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_suggest_v1(
 const tpmshx_grid_scalar_v1* lengths,tpmshx_grid_scalar_v1 diameter,size_t budget,const size_t* minimum,
 size_t* result,size_t result_count,char* error,size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_axis_map_v1(
 int32_t direction,int32_t* result,size_t result_count,char* error,size_t error_capacity);
/* Integral double results retain the original Python arbitrary-size integer conversion. */
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_adaptive_v1(
 const tpmshx_grid_scalar_v1* lengths,tpmshx_grid_scalar_v1 diameter,tpmshx_grid_scalar_v1 alpha,
 double* result,size_t result_count,char* error,size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_rectangles_v1(
 const tpmshx_grid_port_v1* port,tpmshx_grid_scalar_v1 cross2_length,
 tpmshx_grid_scalar_v1* result,size_t result_count,char* error,size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_overlap_v1(
 const double* widths,size_t count,uint32_t width_precision,tpmshx_grid_scalar_v1 lower,tpmshx_grid_scalar_v1 upper,
 uint32_t staggered,double* result,size_t result_count,char* error,size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_fractions_v1(
 const double* widths,size_t count,uint32_t width_precision,tpmshx_grid_scalar_v1 lower,tpmshx_grid_scalar_v1 upper,
 uint32_t uniform,double* raw,double* profile,size_t result_count,char* error,size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_partial_v1(
 const tpmshx_grid_port_v1* port,const double* cross1,size_t count1,uint32_t precision1,
 const double* cross2,size_t count2,uint32_t precision2,uint32_t has_cross2,size_t n_cross2,
 double* inlet,double* outlet,size_t result_count,char* error,size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_continuous_centres_v1(
 size_t count,tpmshx_grid_scalar_v1 length,const double* widths,size_t widths_count,uint32_t has_widths,
 double* result,size_t result_count,char* error,size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_grid_sigmoid_centres_v1(
 size_t count,tpmshx_grid_scalar_v1 length,const double* widths,size_t widths_count,uint32_t has_widths,uint32_t width_precision,
 double* result,size_t result_count,uint32_t* output_precision,char* error,size_t error_capacity);
#ifdef __cplusplus
}
#endif
#endif
