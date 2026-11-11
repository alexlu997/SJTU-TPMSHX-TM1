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

static int check_v2(void) {
    tpmshx_preparation_case_input_2d_v2 source = {0}, original;
    tpmshx_preparation_case_2d_v2 result = {0}, before;
    tpmshx_preparation_case_failure_v2 failure = {0};
    tpmshx_preparation_case_options_v1 options = {1, sizeof(options), 0, 1, 0.};
    tpmshx_preparation_case_callbacks_v1 callbacks = {1, sizeof(callbacks), cancel_event, NULL};
    const tpmshx_preparation_scalar_kind_v2 weak = {64, 0, 0};
    char version[] = "saved-version", provenance[] = "saved-source", scope[] = "saved-scope";
    char error[4096];
    size_t side, calls = 0;
    source.abi_version = result.abi_version = failure.abi_version = 2;
    source.struct_size = sizeof(source); result.struct_size = sizeof(result); failure.struct_size = sizeof(failure);
    source.values = input();
    source.values.sides[0].fluid = 2; source.values.sides[0].pressure_Pa = 8e6;
    source.values.sides[0].velocity_m_s = .15;
    source.values.sides[1].fluid = 1; source.values.sides[1].velocity_m_s = .02;
    source.kinds.cell_length = source.kinds.wall_thickness = source.kinds.solid_conductivity = weak;
    for (side = 0; side < 2; ++side)
        source.kinds.sides[side].velocity = source.kinds.sides[side].temperature = source.kinds.sides[side].pressure = weak;
    source.sco2_nu.mode = 1;
    source.sco2_nu.have_alpha[0] = source.sco2_nu.have_alpha[1] = 1;
    source.sco2_nu.alpha[0] = 1.13; source.sco2_nu.alpha[1] = 2.27;
    source.sco2_nu.parameter_version.data = version; source.sco2_nu.parameter_version.size = strlen(version);
    source.sco2_nu.source.data = provenance; source.sco2_nu.source.size = strlen(provenance);
    source.sco2_nu.applicability.data = scope; source.sco2_nu.applicability.size = strlen(scope);
    original = source;
    CHECK(tpmshx_preparation_case_abi_version_v2() == 2);
    CHECK(!tpmshx_prepare_case_2d_v2(&source, &options, NULL, &result, &failure, error, sizeof(error)));
    CHECK(result.values.owner && !failure.kind && !error[0]);
    CHECK(!memcmp(&source, &original, sizeof(source)));
    CHECK(result.values.sides[0].inlet.fluid == 2 && result.sco2_nu.alpha[1] == 2.27);
    CHECK(result.values.sides[1].properties.rho > 900. && result.notice_count == 1);
    CHECK(result.sco2_nu.source.data != provenance);
    provenance[0] = 'X';
    CHECK(!memcmp(result.sco2_nu.source.data, "saved-source", strlen("saved-source")));
    before = result;
    CHECK(tpmshx_prepare_case_2d_v2(&source, &options, NULL, &result, &failure, error, sizeof(error)) == 1);
    CHECK(!memcmp(&before, &result, sizeof(result)) && failure.kind == 1);
    tpmshx_preparation_case_2d_release_v2(&result);
    CHECK(!result.values.owner && !result.struct_size && !result.sco2_nu.source.data);
    tpmshx_preparation_case_2d_release_v2(&result);
    tpmshx_preparation_case_2d_release_v2(NULL);
    result.abi_version = 2; result.struct_size = sizeof(result); before = result;
    callbacks.context = &calls;
    CHECK(tpmshx_prepare_case_2d_v2(&source, &options, &callbacks, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_RUNTIME);
    CHECK(calls == 1 && !memcmp(&before, &result, sizeof(result)) && failure.kind == 3);
    source.values.sides[1].temperature_K = 450.;
    CHECK(tpmshx_prepare_case_2d_v2(&source, &options, NULL, &result, &failure, error, sizeof(error)) != 0);
    CHECK(!memcmp(&before, &result, sizeof(result)) && failure.kind == 2 && failure.side == 1 && failure.have_property);
    source = original; source.kinds.cell_length.precision = 8;
    CHECK(tpmshx_prepare_case_2d_v2(&source, &options, NULL, &result, &failure, error, sizeof(error)) == 1);
    CHECK(!memcmp(&before, &result, sizeof(result)) && failure.kind == 1);
    source = original; source.sco2_nu.source.data = NULL;
    CHECK(tpmshx_prepare_case_2d_v2(&source, &options, NULL, &result, &failure, error, sizeof(error)) == 1);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    source = original;
    CHECK(tpmshx_prepare_case_2d_v2(&source, &options, NULL, &result, &failure, (char*)&result, sizeof(result)) == 1);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    CHECK(tpmshx_prepare_case_2d_v2(&source, &options, NULL, &result, NULL, error, sizeof(error)) == 1);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    return 0;
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
    CHECK(!check_v2());
    return 0;
}
