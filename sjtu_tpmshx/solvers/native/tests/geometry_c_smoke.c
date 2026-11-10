/* Independent C caller for geometry data, ownership and errors. */
#include "tpmshx/geometry_c_api.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(expression) do { \
    if (!(expression)) { \
        fprintf(stderr, "geometry C caller failed at line %d: %s\n", __LINE__, #expression); \
        return 1; \
    } \
} while (0)
#define OK(expression) CHECK((expression) == TPMSHX_GEOMETRY_OK)

static void fill(double* values, size_t count, double value) {
    size_t i;
    for (i = 0; i < count; ++i) values[i] = value;
}

static int all_equal(const double* values, size_t count, double expected) {
    size_t i;
    for (i = 0; i < count; ++i) if (values[i] != expected) return 0;
    return 1;
}

static tpmshx_geometry_levels_v1 levels(double C, double delta) {
    const tpmshx_geometry_levels_v1 result = {delta-C, delta+C, delta-C, delta+C, 64u, 64u};
    return result;
}

int main(void) {
    char error[256] = "not cleared";
    tpmshx_geometry_index_v1 *index = NULL, *other = NULL, *synthetic = NULL, *coarse = NULL;
    const double cells[2] = {7., 8.};
    const double walls[2] = {.4, .3};
    const double ratios[2] = {.4 / 7., .3 / 8.};
    const double cell_bounds[2] = {4., 8.}, wall_bounds[2] = {.3, .6};
    const size_t small_shape[3] = {2, 2, 2}, empty_shape[3] = {0, 2, 2};
    double field[12], raw[4], thresholds[2], minimum[3];
    double original[8] = {0., 1., 1., 1., 1., 1., 1., 2.};
    const double probes[5] = {-1., 0., .5, 1., 2.};
    const int64_t occupied[5] = {0, 1, 1, 7, 8}, faces[5] = {0, 3, 3, 3, 0};
    int64_t counts[15];
    double epsilon[2] = {.7, .4}, material[4], chi[2], split[4], sides[3], scalar;
    double diameter[2], area[2], lut[14];
    double* phi;
    const size_t phi_count = 32u * 32u * 32u;
    size_t i, j;
    int status;
    tpmshx_geometry_prepared_sides_v1 prepared, raw_prepared;
    tpmshx_geometry_levels_v1 offset, reference, empty_levels = levels(1., 0.);

    CHECK(tpmshx_geometry_abi_version_v1() == 1u);
    OK(tpmshx_geometry_index_create_v1(TPMSHX_GEOMETRY_DIAMOND, 32, &index, error, sizeof error));
    CHECK(index != NULL && error[0] == '\0');
    OK(tpmshx_geometry_index_create_v1(TPMSHX_GEOMETRY_DIAMOND, 32, &other, error, sizeof error));
    CHECK(other != NULL && other != index);
    tpmshx_geometry_index_destroy_v1(other);
    other = NULL;
    tpmshx_geometry_index_destroy_v1(NULL);

    OK(tpmshx_geometry_standard_batch_v1(index, TPMSHX_GEOMETRY_DIAMOND,
        cells, walls, 2, 16., 1, .5, field, 12, error, sizeof error));
    for (i = 0; i < 2; ++i) {
        const double* row = field + 6*i;
        CHECK(row[0] > 0. && row[0] < 1.);
        CHECK(row[1] == .5 * row[0] && row[2] == row[1]);
        CHECK(row[3] > 0. && row[4] == 4. * row[1] / row[3]);
        CHECK(row[5] == .5 * (1. - row[0]) * 16.);
    }
    {
        double scalar_fields[5];
        OK(tpmshx_geometry_standard_scalar_v1(index, TPMSHX_GEOMETRY_DIAMOND,
            cells[0], walls[0], 64u, 64u, scalar_fields, 5, error, sizeof error));
        for (i = 0; i < 5; ++i) CHECK(scalar_fields[i] == field[i]);
        fill(scalar_fields, 5, -77.);
        status = tpmshx_geometry_standard_scalar_v1(index, TPMSHX_GEOMETRY_DIAMOND,
            cells[0], walls[0], 99u, 64u, scalar_fields, 5, error, sizeof error);
        CHECK(status == TPMSHX_GEOMETRY_INVALID && all_equal(scalar_fields, 5, -77.));
    }
    OK(tpmshx_geometry_raw_batch_v1(index, TPMSHX_GEOMETRY_DIAMOND,
        cells, walls, 2, raw, 4, error, sizeof error));
    CHECK(raw[0] == field[0] && raw[1] == field[3]);
    OK(tpmshx_geometry_threshold_batch_v1(TPMSHX_GEOMETRY_DIAMOND,
        ratios, 2, 64u, thresholds, 2, error, sizeof error));
    CHECK(thresholds[0] > 0. && thresholds[1] > 0.);
    offset = levels(thresholds[0], .3);
    reference = levels(thresholds[0], 0.);
    OK(tpmshx_geometry_counts_v1(index, thresholds, 2, counts, 6, error, sizeof error));
    CHECK(counts[0] > 0 && counts[1] > 0 && counts[2] == (int64_t)phi_count);

    OK(tpmshx_geometry_index_create_from_phi_v1(small_shape, original, 8,
        &synthetic, error, sizeof error));
    original[0] = 99.; /* The handle must retain its own copy. */
    OK(tpmshx_geometry_counts_v1(synthetic, probes, 5, counts, 15, error, sizeof error));
    for (i = 0; i < 5; ++i) {
        CHECK(counts[3*i] == occupied[i]);
        CHECK(counts[3*i+1] == faces[i]);
        CHECK(counts[3*i+2] == 8);
    }
    original[0] = 0.;

    OK(tpmshx_geometry_index_create_v1(TPMSHX_GEOMETRY_DIAMOND, 1, &coarse, error, sizeof error));
    OK(tpmshx_geometry_raw_batch_v1(coarse, TPMSHX_GEOMETRY_DIAMOND,
        cells, walls, 1, raw, 2, error, sizeof error));
    CHECK(raw[0] == 0. && raw[1] == 0.);
    fill(field, 12, -77.);
    status = tpmshx_geometry_standard_batch_v1(coarse, TPMSHX_GEOMETRY_DIAMOND,
        cells, walls, 1, 16., 0, 0., field, 6, error, sizeof error);
    CHECK(status == TPMSHX_GEOMETRY_INVALID && all_equal(field, 12, -77.));
    tpmshx_geometry_index_destroy_v1(coarse);
    coarse = NULL;

    OK(tpmshx_geometry_chi_batch_v1(TPMSHX_GEOMETRY_GYROID,
        epsilon, 2, 1, .25, chi, 2, error, sizeof error));
    CHECK(chi[0] == .25 && chi[1] == .25);
    OK(tpmshx_geometry_material_batch_v1(TPMSHX_GEOMETRY_GYROID,
        epsilon, 2, 16., 64u, 1, .25, material, 4, error, sizeof error));
    for (i = 0; i < 2; ++i) {
        CHECK(material[2*i] == .25);
        CHECK(material[2*i+1] == .25 * (1. - epsilon[i]) * 16.);
    }
    {
        const double lut_area[2] = {1e-30, 1200.};
        OK(tpmshx_geometry_lut_batch_v1(TPMSHX_GEOMETRY_GYROID,
            epsilon, lut_area, 2, 16., 1, .25, lut, 14, error, sizeof error));
        for (i = 0; i < 2; ++i) {
            const double* row = lut + 7*i;
            CHECK(row[0] == epsilon[i] && row[1] == epsilon[i]/2. && row[2] == row[1]);
            CHECK(row[3] == lut_area[i] && row[4] == 2.*epsilon[i]/(lut_area[i]+1e-30));
            CHECK(row[5] == material[2*i+1] && row[6] == row[4]/2.);
        }
        fill(lut, 14, -77.);
        status = tpmshx_geometry_lut_batch_v1(TPMSHX_GEOMETRY_GYROID,
            epsilon, lut_area, 2, 16., 1, .25, lut, 13, error, sizeof error);
        CHECK(status == TPMSHX_GEOMETRY_INVALID && all_equal(lut, 14, -77.));
    }
    OK(tpmshx_geometry_standard_minimum_v1(index, TPMSHX_GEOMETRY_DIAMOND,
        cell_bounds, wall_bounds, minimum, 3, error, sizeof error));
    CHECK(minimum[0] == 8. && minimum[1] == .3 && minimum[2] > 0.);
    OK(tpmshx_geometry_co2_batch_v1(TPMSHX_GEOMETRY_GYROID,
        cells, walls, 2, 16., 1, .5, field, 12, error, sizeof error));
    CHECK(field[0] > 0. && field[1] == field[0] / 2. && field[3] > 0. && field[4] > 0.);
    OK(tpmshx_geometry_co2_minimum_v1(TPMSHX_GEOMETRY_GYROID,
        cell_bounds, wall_bounds, 0, 0., minimum, 3, error, sizeof error));
    CHECK(minimum[0] >= 4. && minimum[0] <= 8. && minimum[1] >= .3 && minimum[1] <= .6);

    phi = (double*)malloc(phi_count * sizeof(double));
    CHECK(phi != NULL);
    OK(tpmshx_geometry_phi_grid_v1(TPMSHX_GEOMETRY_DIAMOND, 32,
        phi, phi_count, error, sizeof error));
    CHECK(isfinite(phi[0]) && isfinite(phi[phi_count-1]));
    OK(tpmshx_geometry_eps_sides_v1(phi, phi_count, &offset,
        sides, 3, error, sizeof error));
    CHECK(sides[0] > sides[1] && sides[2] == sides[0] + sides[1]);
    {
        const size_t shape[3] = {32, 32, 32};
        OK(tpmshx_geometry_area_sides_v1(shape, phi, phi_count, &offset,
            .007, 32., 1.553, TPMSHX_GEOMETRY_VOXEL, area, 2, error, sizeof error));
        CHECK(area[0] > 0. && area[1] > 0.);
        OK(tpmshx_geometry_dh_sides_v1(shape, phi, phi_count, &offset,
            .007, 32., 1.553, TPMSHX_GEOMETRY_VOXEL, diameter, 2, error, sizeof error));
        CHECK(diameter[0] == 4. * sides[0] / area[0]);
        OK(tpmshx_geometry_wall_thickness_v1(shape, phi, phi_count, &offset,
            .007, 32., 1.553, &scalar, 1, error, sizeof error));
        CHECK(scalar > 0.);
        OK(tpmshx_geometry_prepare_raw_sides_v1(shape, phi, phi_count,
            &offset, &reference, 0u, .007, 32., 1.553, &raw_prepared, error, sizeof error));
        OK(tpmshx_geometry_prepare_from_index_v1(index, TPMSHX_GEOMETRY_DIAMOND,
            7., .4, .3, &prepared, error, sizeof error));
        CHECK(prepared.has_sides == 1u && prepared.split_a > .5);
        CHECK(prepared.split_a == raw_prepared.split_a);
        OK(tpmshx_geometry_split_from_index_v1(index, TPMSHX_GEOMETRY_DIAMOND,
            7., .4, .3, &scalar, 1, error, sizeof error));
        CHECK(scalar == prepared.split_a);
        for (i = 0; i < 2; ++i)
            for (j = 0; j < 4; ++j)
                CHECK(prepared.sides[i][j] == raw_prepared.sides[i][j]);
    }
    free(phi);
    OK(tpmshx_geometry_dh_from_sides_v1(.4, .2, 0., 500.,
        diameter, 2, error, sizeof error));
    CHECK(diameter[0] == 0. && fabs(diameter[1] - .0016) < 1e-18);
    OK(tpmshx_geometry_wall_from_sides_v1(.7, 1000., 2000., &scalar, 1, error, sizeof error));
    CHECK(fabs(scalar - .0002) < 1e-18);
    OK(tpmshx_geometry_split_fields_v1(epsilon, 2, .25, split, 4, error, sizeof error));
    CHECK(split[0] == epsilon[0] * .25 && split[1] == epsilon[0] * .75);
    OK(tpmshx_geometry_prepare_from_index_v1(index, TPMSHX_GEOMETRY_DIAMOND,
        7., .4, 0., &prepared, error, sizeof error));
    CHECK(prepared.split_a == .5 && prepared.has_sides == 0u);

    /* Empty arrays remain legal where the numerical contract permits them. */
    OK(tpmshx_geometry_standard_batch_v1(index, TPMSHX_GEOMETRY_DIAMOND,
        NULL, NULL, 0, 16., 0, 0., NULL, 0, error, sizeof error));
    OK(tpmshx_geometry_raw_batch_v1(index, TPMSHX_GEOMETRY_DIAMOND,
        NULL, NULL, 0, NULL, 0, error, sizeof error));
    OK(tpmshx_geometry_counts_v1(index, NULL, 0, NULL, 0, error, sizeof error));
    OK(tpmshx_geometry_co2_batch_v1(TPMSHX_GEOMETRY_GYROID,
        NULL, NULL, 0, 16., 0, 0., NULL, 0, error, sizeof error));
    OK(tpmshx_geometry_hydraulic_radius_batch_v1(walls, 2, area, 2, error, sizeof error));
    CHECK(area[0] == walls[0]/2. && area[1] == walls[1]/2.);
    OK(tpmshx_geometry_hydraulic_radius_batch_v1(NULL, 0, NULL, 0, error, sizeof error));
    OK(tpmshx_geometry_eps_sides_v1(NULL, 0, &empty_levels, sides, 3, error, sizeof error));
    CHECK(isnan(sides[0]) && isnan(sides[1]) && isnan(sides[2]));
    OK(tpmshx_geometry_prepare_raw_sides_v1(empty_shape, NULL, 0,
        &empty_levels, &empty_levels, 1u, 0., 0., 0., &prepared, error, sizeof error));
    CHECK(prepared.split_a == .5 && prepared.has_sides == 0u);

    /* A late numerical error must not publish any earlier row. */
    {
        const double invalid_cells[2] = {7., 9.};
        fill(field, 12, -77.);
        status = tpmshx_geometry_co2_batch_v1(TPMSHX_GEOMETRY_GYROID,
            invalid_cells, walls, 2, 16., 0, 0., field, 12, error, sizeof error);
        CHECK(status == TPMSHX_GEOMETRY_INVALID && all_equal(field, 12, -77.));
    }
    {
        const double solid_phi[8] = {0., 0., 0., 0., 0., 0., 0., 0.};
        const tpmshx_geometry_levels_v1 solid_levels = levels(1., .2);
        scalar = -77.;
        status = tpmshx_geometry_split_a_v1(solid_phi, 8, &solid_levels, 0u,
            &scalar, 1, error, sizeof error);
        CHECK(status == TPMSHX_GEOMETRY_DOMAIN && scalar == -77.);
    }
    fill(field, 12, -77.);
    status = tpmshx_geometry_standard_batch_v1(index, TPMSHX_GEOMETRY_GYROID,
        cells, walls, 2, 16., 0, 0., field, 12, error, sizeof error);
    CHECK(status == TPMSHX_GEOMETRY_INVALID && all_equal(field, 12, -77.));
    status = tpmshx_geometry_standard_batch_v1(index, TPMSHX_GEOMETRY_DIAMOND,
        cells, walls, 2, 16., 2, 0., field, 12, error, sizeof error);
    CHECK(status == TPMSHX_GEOMETRY_INVALID && all_equal(field, 12, -77.));
    status = tpmshx_geometry_standard_batch_v1(index, TPMSHX_GEOMETRY_DIAMOND,
        cells, walls, 2, 16., 0, 0., field, 11, error, sizeof error);
    CHECK(status == TPMSHX_GEOMETRY_INVALID && all_equal(field, 12, -77.));
    status = tpmshx_geometry_phi_grid_v1(TPMSHX_GEOMETRY_DIAMOND,
        SIZE_MAX, field, 12, error, sizeof error);
    CHECK(status == TPMSHX_GEOMETRY_INVALID && all_equal(field, 12, -77.));
    status = tpmshx_geometry_counts_v1(NULL, thresholds, 2, counts, 6, error, sizeof error);
    CHECK(status == TPMSHX_GEOMETRY_INVALID);
    status = tpmshx_geometry_index_create_from_phi_v1(small_shape, original, 7,
        &other, error, sizeof error);
    CHECK(status == TPMSHX_GEOMETRY_INVALID && other == NULL);

    /* Failure leaves the existing handle slot and short error buffers coherent. */
    {
        char short_error[5] = "xxxx", one_byte[1] = {'x'};
        tpmshx_geometry_index_v1* slot = index;
        status = tpmshx_geometry_index_create_v1(99u, 32, &slot, short_error, sizeof short_error);
        CHECK(status == TPMSHX_GEOMETRY_INVALID && slot == index);
        CHECK(short_error[0] != '\0' && short_error[4] == '\0');
        status = tpmshx_geometry_index_create_v1(99u, 32, &slot, one_byte, sizeof one_byte);
        CHECK(status == TPMSHX_GEOMETRY_INVALID && one_byte[0] == '\0' && slot == index);
        status = tpmshx_geometry_standard_batch_v1(index, TPMSHX_GEOMETRY_DIAMOND,
            cells, walls, 2, 16., 0, 0., field, 12, NULL, 0);
        CHECK(status == TPMSHX_GEOMETRY_INVALID && all_equal(field, 12, -77.));
        status = tpmshx_geometry_standard_batch_v1(index, TPMSHX_GEOMETRY_DIAMOND,
            cells, walls, 2, 16., 0, 0., field, 12, error, 0);
        CHECK(status == TPMSHX_GEOMETRY_INVALID && all_equal(field, 12, -77.));
    }
    tpmshx_geometry_index_destroy_v1(synthetic);
    tpmshx_geometry_index_destroy_v1(index);
    puts("geometry C caller passed");
    return 0;
}
