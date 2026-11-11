#include "tpmshx/preparation_case_c_api.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

#define CHECK(test) do { if (!(test)) { fprintf(stderr, "line %d: %s\n", __LINE__, #test); return 1; } } while (0)

static tpmshx_preparation_case_input_2d_v1 input(void) {
    tpmshx_preparation_case_input_2d_v1 value = {0};
    size_t side;
    value.abi_version = TPMSHX_PREPARATION_CASE_ABI_VERSION;
    value.struct_size = sizeof(value);
    value.length_m = .182; value.height_m = .042;
    value.requested_nx = 20; value.requested_ny = 40;
    value.topology = 1; value.cell_length_mm = 7.; value.wall_thickness_mm = .6;
    value.solid_conductivity_W_mK = 16.;
    for (side = 0; side < 2; ++side) {
        value.sides[side].velocity_m_s = 5.;
        value.sides[side].temperature_K = side ? 300. : 400.;
        value.sides[side].pressure_Pa = 101325.;
        value.sides[side].port.direction = (int32_t)side;
    }
    return value;
}
static tpmshx_preparation_case_2d_v1 empty_result(void) {
    tpmshx_preparation_case_2d_v1 result = {0};
    result.abi_version = TPMSHX_PREPARATION_CASE_ABI_VERSION;
    result.struct_size = sizeof(result);
    return result;
}
static int TPMSHX_PREPARATION_CALL cancel_event(void* context, const tpmshx_preparation_event_v1* event) {
    size_t* calls = (size_t*)context;
    if (event && event->message.size) ++*calls;
    return 1;
}

int main(void) {
    tpmshx_preparation_case_input_2d_v1 source = input(), original = source;
    tpmshx_preparation_case_2d_v1 result = empty_result(), before;
    tpmshx_preparation_case_options_v1 options = {1, sizeof(options), 0, 0, 0.};
    tpmshx_preparation_case_callbacks_v1 callbacks = {1, sizeof(callbacks), cancel_event, NULL};
    size_t calls = 0;
    char error[2048];
    double first_width;
    CHECK(tpmshx_preparation_case_abi_version_v1() == TPMSHX_PREPARATION_CASE_ABI_VERSION);
    CHECK(!tpmshx_prepare_case_2d_v1(&source, NULL, NULL, &result, error, sizeof(error)));
    CHECK(!error[0] && result.owner && result.nx == 36 && result.ny == 56);
    CHECK(!memcmp(&source, &original, sizeof(source)));
    CHECK(result.dx.size == result.nx && result.dy.size == result.ny);
    CHECK(result.cell_length.size == result.nx * result.ny && result.range_count == 13);
    CHECK(result.sides[0].row_permeability.size == result.nx && result.sides[1].inlet_geometry.size == result.ny);
    CHECK(result.input.sides[0].port.inlet_width_m == 0. && result.sides[0].inlet.port.inlet_width_m == source.height_m);
    CHECK(result.models[0].name.size == 5 && !memcmp(result.models[0].name.data, "fluid", 5));
    CHECK(result.models[2].version.size && result.sides[0].properties.rho > 0.);
    first_width = result.dx.data[0];
    source.length_m = 2.;
    CHECK(result.input.length_m == original.length_m && result.dx.data[0] == first_width);
    before = result;
    CHECK(tpmshx_prepare_case_2d_v1(&original, NULL, NULL, &result, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)) && error[0]);
    tpmshx_preparation_case_2d_release_v1(&result);
    CHECK(!result.owner && !result.dx.data && !result.struct_size);
    tpmshx_preparation_case_2d_release_v1(&result);
    tpmshx_preparation_case_2d_release_v1(NULL);
    result = empty_result(); before = result;
    source = original; source.abi_version = 99;
    CHECK(tpmshx_prepare_case_2d_v1(&source, NULL, NULL, &result, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    source = original; source.sides[0].port.uniform_inlet = 2;
    CHECK(tpmshx_prepare_case_2d_v1(&source, NULL, NULL, &result, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    source = original; source.sides[0].fluid = 1;
    CHECK(tpmshx_prepare_case_2d_v1(&source, NULL, NULL, &result, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    source = original; source.sides[0].port.inlet_width_m = .01;
    CHECK(tpmshx_prepare_case_2d_v1(&source, NULL, NULL, &result, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(strstr(error, "both be positive") && !memcmp(&before, &result, sizeof(result)));
    options.allow_extrapolation = 2;
    CHECK(tpmshx_prepare_case_2d_v1(&original, &options, NULL, &result, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    callbacks.context = &calls;
    CHECK(tpmshx_prepare_case_2d_v1(&original, NULL, &callbacks, &result, error, sizeof(error)) == TPMSHX_PREPARATION_RUNTIME);
    CHECK(calls == 1 && strstr(error, "callback failed") && !memcmp(&before, &result, sizeof(result)));
    CHECK(tpmshx_prepare_case_2d_v1(&original, NULL, NULL, &result, NULL, 0) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    CHECK(tpmshx_prepare_case_2d_v1(&original, NULL, NULL, &result, (char*)&result, sizeof(result)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    return 0;
}
