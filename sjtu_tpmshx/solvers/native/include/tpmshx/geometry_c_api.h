#ifndef TPMSHX_GEOMETRY_C_API_H
#define TPMSHX_GEOMETRY_C_API_H

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#  if defined(TPMSHX_GEOMETRY_BUILD_SHARED)
#    define TPMSHX_GEOMETRY_API __declspec(dllexport)
#  elif defined(TPMSHX_GEOMETRY_USE_SHARED)
#    define TPMSHX_GEOMETRY_API __declspec(dllimport)
#  else
#    define TPMSHX_GEOMETRY_API
#  endif
#  define TPMSHX_GEOMETRY_CALL __cdecl
#else
#  if defined(__GNUC__) || defined(__clang__)
#    define TPMSHX_GEOMETRY_API __attribute__((visibility("default")))
#  else
#    define TPMSHX_GEOMETRY_API
#  endif
#  define TPMSHX_GEOMETRY_CALL
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define TPMSHX_GEOMETRY_ABI_VERSION 1u

enum tpmshx_geometry_status_v1 {
    TPMSHX_GEOMETRY_OK = 0, TPMSHX_GEOMETRY_INVALID = 1,
    TPMSHX_GEOMETRY_DOMAIN = 2, TPMSHX_GEOMETRY_RUNTIME = 3
};
enum tpmshx_geometry_topology_v1 {
    TPMSHX_GEOMETRY_DIAMOND = 0, TPMSHX_GEOMETRY_GYROID = 1
};
enum tpmshx_geometry_area_method_v1 {
    TPMSHX_GEOMETRY_VOXEL = 0, TPMSHX_GEOMETRY_MARCHING_CUBES = 1
};

typedef struct tpmshx_geometry_index_v1 tpmshx_geometry_index_v1;
typedef struct {
    double lower, upper, comparison_lower, comparison_upper;
    uint32_t lower_precision, upper_precision;
} tpmshx_geometry_levels_v1;
typedef struct {
    double split_a;
    uint32_t has_sides;
    double sides[2][4]; /* A/B rows: voxel A0, MC Dh, reference A0, reference Dh. */
} tpmshx_geometry_prepared_sides_v1;

/* Buffers are borrowed for the call. Lengths count elements, not bytes.
 * Input, output, error and handle slots must not overlap. Output lengths are exact.
 * A zero-length array may be NULL. Other pointers need valid aligned storage.
 * An error buffer is required, including for an empty batch.
 * Failure leaves all output unchanged and writes a bounded NUL-terminated error.
 * Success clears error. No C++ exception crosses this boundary.
 * Destroy each handle once, after its last query. Destroying NULL is valid.
 */
TPMSHX_GEOMETRY_API uint32_t TPMSHX_GEOMETRY_CALL tpmshx_geometry_abi_version_v1(void);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_index_create_v1(
    uint32_t topology, size_t N, tpmshx_geometry_index_v1** result, char* error, size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_index_create_from_phi_v1(
    const size_t shape[3], const double* phi, size_t phi_count,
    tpmshx_geometry_index_v1** result, char* error, size_t error_capacity);
TPMSHX_GEOMETRY_API void TPMSHX_GEOMETRY_CALL tpmshx_geometry_index_destroy_v1(
    tpmshx_geometry_index_v1* index);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_phi_grid_v1(
    uint32_t topology, size_t N, double* result, size_t result_count, char* error, size_t error_capacity);
/* ratio_precision (16, 32, 64) sets ratio and first-product precision.
 * The squared-ratio term and output use double.
 */
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_threshold_batch_v1(
    uint32_t topology, const double* wall_over_cell, size_t count, uint32_t ratio_precision,
    double* result, size_t result_count, char* error, size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_hydraulic_radius_batch_v1(
    const double* diameter, size_t count,
    double* result, size_t result_count, char* error, size_t error_capacity);
/* Counts rows contain occupied, faces, voxels as int64. Thresholds are inclusive. */
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_counts_v1(
    const tpmshx_geometry_index_v1* index, const double* thresholds, size_t count,
    int64_t* result, size_t result_count, char* error, size_t error_capacity);
/* Standard/CO2 rows contain epsilon, epsilon_A, epsilon_B, A0, Dh, Kss.
 * Cell and wall inputs use mm; A0 uses 1/m; Dh uses m; Kss uses W/(m K).
 * has_override is 0 or 1. No environment value is read here.
 */
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_standard_batch_v1(
    const tpmshx_geometry_index_v1* index, uint32_t topology,
    const double* cells_mm, const double* walls_mm, size_t count,
    double conductivity, uint32_t has_override, double override_value,
    double* result, size_t result_count, char* error, size_t error_capacity);
/* Scalar rows contain epsilon, epsilon_A, epsilon_B, A0, Dh.
 * cell_precision sets L/1000 and L_m/N precision.
 * ratio_precision sets t/L and its first coefficient product precision.
 * Both precisions are 16, 32 or 64. Powers and outputs use double.
 */
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_standard_scalar_v1(
    const tpmshx_geometry_index_v1* index, uint32_t topology, double cell_mm, double wall_mm,
    uint32_t cell_precision, uint32_t ratio_precision,
    double* result, size_t result_count, char* error, size_t error_capacity);
/* Raw rows contain epsilon, A0. Zero area and degenerate porosity remain valid. */
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_raw_batch_v1(
    const tpmshx_geometry_index_v1* index, uint32_t topology,
    const double* cells_mm, const double* walls_mm, size_t count,
    double* result, size_t result_count, char* error, size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_chi_batch_v1(
    uint32_t topology, const double* epsilon, size_t count,
    uint32_t has_override, double override_value, double* result, size_t result_count,
    char* error, size_t error_capacity);
/* Material rows contain chi_s, Kss for an existing porosity field.
 * chi*(1-epsilon) first uses double.
 * product_precision (16, 32, 64) sets final multiplication precision.
 * Outputs use double storage.
 */
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_material_batch_v1(
    uint32_t topology, const double* epsilon, size_t count, double conductivity, uint32_t product_precision,
    uint32_t has_override, double override_value, double* result, size_t result_count,
    char* error, size_t error_capacity);
/* LUT rows add hydraulic radius after the six standard geometry columns.
 * This route retains the existing denominator regularization and extrapolation.
 */
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_lut_batch_v1(
    uint32_t topology, const double* epsilon, const double* area_density, size_t count,
    double conductivity, uint32_t has_override, double override_value,
    double* result, size_t result_count, char* error, size_t error_capacity);
/* Minimum results contain L_mm, t_mm, epsilon. */
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_standard_minimum_v1(
    const tpmshx_geometry_index_v1* index, uint32_t topology,
    const double cell_bounds_mm[2], const double wall_bounds_mm[2],
    double* result, size_t result_count, char* error, size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_co2_batch_v1(
    uint32_t topology, const double* cells_mm, const double* walls_mm, size_t count,
    double conductivity, uint32_t has_override, double override_value,
    double* result, size_t result_count, char* error, size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_co2_minimum_v1(
    uint32_t topology, const double cell_bounds_mm[2], const double wall_bounds_mm[2],
    uint32_t has_override, double override_value,
    double* result, size_t result_count, char* error, size_t error_capacity);

/* Raw asym helpers receive phi as float64, independent double N, and metre length.
 * Levels retain scalar arithmetic, array comparison bounds, and scalar precision.
 * Precision is 16, 32 or 64 bits. zero_delta is 0 or 1.
 * They use the explicit area correction from the shared model resource.
 * Scalar results have one element; side results have two; porosity has A,B,total.
 */
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_eps_sides_v1(
    const double* phi, size_t phi_count, const tpmshx_geometry_levels_v1* levels,
    double* result, size_t result_count, char* error, size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_area_sides_v1(
    const size_t shape[3], const double* phi, size_t phi_count,
    const tpmshx_geometry_levels_v1* levels,
    double length_m, double N, double area_correction, uint32_t method,
    double* result, size_t result_count, char* error, size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_dh_sides_v1(
    const size_t shape[3], const double* phi, size_t phi_count,
    const tpmshx_geometry_levels_v1* levels,
    double length_m, double N, double area_correction, uint32_t method,
    double* result, size_t result_count, char* error, size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_dh_from_sides_v1(
    double epsilon_a, double epsilon_b, double area_a, double area_b,
    double* result, size_t result_count, char* error, size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_wall_thickness_v1(
    const size_t shape[3], const double* phi, size_t phi_count,
    const tpmshx_geometry_levels_v1* levels, double length_m, double N, double area_correction,
    double* result, size_t result_count, char* error, size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_wall_from_sides_v1(
    double epsilon_total, double area_a, double area_b,
    double* result, size_t result_count, char* error, size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_split_a_v1(
    const double* phi, size_t phi_count, const tpmshx_geometry_levels_v1* levels, uint32_t zero_delta,
    double* result, size_t result_count, char* error, size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_split_fields_v1(
    const double* epsilon_total, size_t count, double fraction_a,
    double* result, size_t result_count, char* error, size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_prepare_raw_sides_v1(
    const size_t shape[3], const double* phi, size_t phi_count,
    const tpmshx_geometry_levels_v1* levels, const tpmshx_geometry_levels_v1* reference_levels,
    uint32_t zero_delta, double length_m, double N, double area_correction,
    tpmshx_geometry_prepared_sides_v1* result, char* error, size_t error_capacity);
/* Formal preparation uses generated calibration and the index resolution. */
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_prepare_from_index_v1(
    const tpmshx_geometry_index_v1* index, uint32_t topology,
    double cell_mm, double wall_mm, double delta,
    tpmshx_geometry_prepared_sides_v1* result, char* error, size_t error_capacity);
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_split_from_index_v1(
    const tpmshx_geometry_index_v1* index, uint32_t topology,
    double cell_mm, double wall_mm, double delta,
    double* result, size_t result_count, char* error, size_t error_capacity);

#ifdef __cplusplus
}
#endif
#endif
