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

static int check_v3(void) {
    tpmshx_preparation_flow_input_2d_v3 source = {0}, original;
    tpmshx_preparation_flow_2d_v3 query = {0}, query_before;
    tpmshx_preparation_flow_case_2d_v3 result = {0}, before;
    tpmshx_preparation_case_failure_v2 failure = {2, sizeof(failure)}, failure_before;
    tpmshx_preparation_case_options_v1 options = {1, sizeof(options), 0, 1, 0.};
    tpmshx_preparation_case_callbacks_v1 callbacks = {1, sizeof(callbacks), cancel_event, NULL};
    const tpmshx_preparation_scalar_kind_v2 weak = {64, 0, 0};
    char provenance[] = "mass-source", error[4096], preserved[sizeof(provenance)];
    size_t i, calls = 0;
    double expected_speeds[2];
    source.abi_version = query.abi_version = result.abi_version = 3;
    source.struct_size = sizeof(source); query.struct_size = sizeof(query); result.struct_size = sizeof(result);
    source.values.abi_version = 2; source.values.struct_size = sizeof(source.values);
    source.values.values = input();
    source.values.values.have_physical_depth = 1; source.values.values.physical_depth_m = .042;
    source.values.values.sides[0].velocity_m_s = -99.; source.values.values.sides[1].velocity_m_s = -88.;
    source.values.values.sides[1].fluid = 1; source.values.values.sides[1].pressure_Pa = 200000.;
    source.values.kinds.cell_length = source.values.kinds.wall_thickness = source.values.kinds.solid_conductivity = weak;
    source.physical_depth_kind = weak;
    for (i = 0; i < 2; ++i) {
        source.target_kinds[i] = weak;
        source.values.kinds.sides[i].velocity = source.values.kinds.sides[i].temperature = source.values.kinds.sides[i].pressure = weak;
    }
    source.values.sco2_nu.source.data = provenance; source.values.sco2_nu.source.size = strlen(provenance);
    original = source;
    CHECK(tpmshx_preparation_case_abi_version_v3() == 3);
    CHECK(!tpmshx_prepare_inlet_mass_capacities_2d_v3(&source, NULL, NULL, &query, &failure, error, sizeof(error)));
    CHECK(query.owner && query.have_capacities && query.capacities[0].value > 0. && query.capacities[1].value > 0.);
    CHECK(!memcmp(&source, &original, sizeof(source)));
    CHECK(query.input.sco2_nu.source.data != provenance);
    source.have_explicit_targets = 1;
    source.explicit_targets_kg_s[0] = query.capacities[0].value * 5.;
    source.explicit_targets_kg_s[1] = query.capacities[1].value * .02;
    for (i = 0; i < 2; ++i) expected_speeds[i] = source.explicit_targets_kg_s[i] / query.capacities[i].value;
    provenance[0] = 'X';
    CHECK(!memcmp(query.input.sco2_nu.source.data, "mass-source", strlen("mass-source")));
    query_before = query;
    CHECK(tpmshx_resolve_inlet_flow_2d_v3(&source, NULL, NULL, &query, &failure, error, sizeof(error)) != 0);
    CHECK(!memcmp(&query_before, &query, sizeof(query)));
    tpmshx_preparation_flow_2d_release_v3(&query);
    query.abi_version = 3; query.struct_size = sizeof(query);
    CHECK(!tpmshx_resolve_inlet_flow_2d_v3(&source, NULL, NULL, &query, &failure, error, sizeof(error)));
    CHECK(query.speeds[0].value == expected_speeds[0] && query.speeds[1].value == expected_speeds[1]);
    CHECK(!query.input.values.sides[0].have_mass_flow && !query.input.values.sides[1].have_mass_flow);
    tpmshx_preparation_flow_2d_release_v3(&query);
    CHECK(!query.owner && !query.struct_size && !query.input.sco2_nu.source.data);
    tpmshx_preparation_flow_2d_release_v3(&query); tpmshx_preparation_flow_2d_release_v3(NULL);
    CHECK(!tpmshx_prepare_flow_case_2d_v3(&source, &options, NULL, &result, &failure, error, sizeof(error)));
    CHECK(result.owner && !result.prepared.values.owner && !result.flow.owner);
    CHECK(result.prepared.values.sides[0].inlet.velocity_m_s == expected_speeds[0]);
    CHECK(result.prepared.values.sides[1].inlet.velocity_m_s == expected_speeds[1]);
    CHECK(result.flow.evidence.event_count == 1);
    before = result;
    CHECK(tpmshx_prepare_flow_case_2d_v3(&source, &options, NULL, &result, &failure, error, sizeof(error)) != 0);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    tpmshx_preparation_flow_case_2d_release_v3(&result);
    CHECK(!result.owner && !result.prepared.values.dx.data);
    tpmshx_preparation_flow_case_2d_release_v3(&result); tpmshx_preparation_flow_case_2d_release_v3(NULL);
    result.abi_version = 3; result.struct_size = sizeof(result); before = result;
    source.target_kinds[0].strong = 3;
    CHECK(tpmshx_prepare_flow_case_2d_v3(&source, &options, NULL, &result, &failure, error, sizeof(error)) == 1);
    CHECK(failure.kind == 1 && !memcmp(&before, &result, sizeof(result)));
    source.target_kinds[0] = weak; source.physical_depth_kind.layout = 3;
    CHECK(tpmshx_prepare_flow_case_2d_v3(&source, &options, NULL, &result, &failure, error, sizeof(error)) == 1);
    CHECK(failure.kind == 1 && !memcmp(&before, &result, sizeof(result)));
    source.physical_depth_kind = weak;
    callbacks.context = &calls;
    CHECK(tpmshx_prepare_flow_case_2d_v3(&source, &options, &callbacks, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_RUNTIME);
    CHECK(calls == 1 && failure.kind == 3 && !memcmp(&before, &result, sizeof(result)));
    CHECK(tpmshx_prepare_flow_case_2d_v3(&source, &options, NULL, &result, &failure, (char*)&result, sizeof(result)) != 0);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    memcpy(preserved, provenance, sizeof(provenance)); failure_before = failure;
    source.values.sco2_nu.parameter_version.data = NULL; source.values.sco2_nu.parameter_version.size = 1;
    CHECK(tpmshx_prepare_flow_case_2d_v3(&source, &options, NULL, &result, &failure, provenance, sizeof(provenance)) != 0);
    CHECK(!memcmp(preserved, provenance, sizeof(provenance)) && !memcmp(&failure_before, &failure, sizeof(failure)));
    CHECK(!memcmp(&before, &result, sizeof(result)));
    return 0;
}

static int check_v4(void) {
    tpmshx_preparation_continuous_input_2d_v4 source = {0};
    tpmshx_preparation_continuous_flow_2d_v4 capacity = {0}, resolved = {0};
    tpmshx_preparation_continuous_case_2d_v4 result = {0}, before;
    tpmshx_preparation_case_failure_v2 failure = {0}, failure_before;
    tpmshx_preparation_case_options_v1 options = {1, sizeof(options), 0, 1, 0.};
    tpmshx_preparation_case_callbacks_v1 callbacks = {1, sizeof(callbacks), cancel_event, NULL};
    tpmshx_preparation_scalar_kind_v2 weak = {64, 0, 0};
    double decisions[] = {4.5, 6., 7.5, 5.4, .31, .42, .59, .36}, saved[8];
    char error[4096];
    size_t i, calls = 0;
    source.abi_version = 4; source.struct_size = sizeof(source);
    source.values.abi_version = 3; source.values.struct_size = sizeof(source.values);
    source.values.values.abi_version = 2; source.values.values.struct_size = sizeof(source.values.values);
    source.values.values.values = input(); source.values.values.values.geometry_mode = 1;
    source.values.values.values.have_physical_depth = 1; source.values.values.values.physical_depth_m = .042;
    source.values.values.kinds.cell_length = source.values.values.kinds.wall_thickness = weak;
    source.values.values.kinds.solid_conductivity = source.values.physical_depth_kind = weak;
    for (i = 0; i < 2; ++i) {
        source.values.values.kinds.sides[i].velocity = source.values.values.kinds.sides[i].temperature = weak;
        source.values.values.kinds.sides[i].pressure = source.values.target_kinds[i] = weak;
        source.values.values.values.sides[i].velocity_m_s = -99.;
    }
    source.controls.n_ctrl_x = source.controls.n_ctrl_y = 2; source.controls.spline_order = 1;
    source.controls.L_bounds_mm[0] = 4.; source.controls.L_bounds_mm[1] = 8.;
    source.controls.t_bounds_mm[0] = .3; source.controls.t_bounds_mm[1] = .6;
    source.controls.decision_mm.data = decisions; source.controls.decision_mm.size = 8;
    capacity.abi_version = resolved.abi_version = result.abi_version = 4;
    capacity.struct_size = sizeof(capacity); resolved.struct_size = sizeof(resolved); result.struct_size = sizeof(result);
    failure.abi_version = 2; failure.struct_size = sizeof(failure);
    CHECK(tpmshx_preparation_case_abi_version_v4() == 4);
    CHECK(!tpmshx_prepare_inlet_mass_capacities_2d_v4(&source, &options, NULL, &capacity, &failure, error, sizeof(error)));
    CHECK(capacity.owner && !capacity.flow.owner && capacity.flow.have_capacities);
    CHECK(capacity.controls.decision_mm.data != decisions && capacity.controls.decision_mm.size == 8);
    source.values.have_explicit_targets = 1;
    for (i = 0; i < 2; ++i) source.values.explicit_targets_kg_s[i] = capacity.flow.capacities[i].value * 6.;
    CHECK(!tpmshx_resolve_inlet_flow_2d_v4(&source, &options, NULL, &resolved, &failure, error, sizeof(error)));
    CHECK(!tpmshx_prepare_flow_case_2d_v4(&source, &options, NULL, &result, &failure, error, sizeof(error)));
    CHECK(result.owner && !result.prepared.values.owner && !result.flow.owner);
    CHECK(result.area_density_per_m.size == result.prepared.values.nx * result.prepared.values.ny);
    CHECK(result.hydraulic_diameter_m.size == result.area_density_per_m.size);
    for (i = 0; i < 2; ++i) {
        CHECK(result.fluid_conductivity[i].size == result.area_density_per_m.size);
        CHECK(result.prepared.values.sides[i].permeability.size == result.area_density_per_m.size);
        CHECK(result.prepared.values.sides[i].inlet.velocity_m_s == resolved.flow.speeds[i].value);
    }
    decisions[0] = -1.;
    CHECK(capacity.controls.decision_mm.data[0] == 4.5 && result.controls.decision_mm.data[0] == 4.5);
    tpmshx_preparation_continuous_flow_2d_release_v4(&capacity);
    tpmshx_preparation_continuous_flow_2d_release_v4(&resolved);
    tpmshx_preparation_continuous_case_2d_release_v4(&result);
    CHECK(!result.owner && !result.prepared.values.cell_length.data);
    tpmshx_preparation_continuous_case_2d_release_v4(&result);
    tpmshx_preparation_continuous_case_2d_release_v4(NULL);
    result.abi_version = 4; result.struct_size = sizeof(result); before = result;
    CHECK(tpmshx_prepare_flow_case_2d_v4(&source, &options, NULL, &result, &failure, error, sizeof(error)) == 1);
    CHECK(failure.kind == 1 && !memcmp(&before, &result, sizeof(result)));
    decisions[0] = 4.5; memcpy(saved, decisions, sizeof(saved)); failure_before = failure;
    CHECK(tpmshx_prepare_flow_case_2d_v4(&source, &options, NULL, &result, &failure, (char*)decisions, sizeof(decisions)) != 0);
    CHECK(!memcmp(saved, decisions, sizeof(saved)) && !memcmp(&before, &result, sizeof(result)));
    CHECK(!memcmp(&failure_before, &failure, sizeof(failure)));
    source.controls.decision_mm.data = (const double*)&result;
    source.controls.decision_mm.size = 1;
    CHECK(tpmshx_prepare_flow_case_2d_v4(&source, &options, NULL, &result, &failure, error, sizeof(error)) != 0);
    CHECK(!memcmp(&before, &result, sizeof(result)) && !memcmp(&failure_before, &failure, sizeof(failure)));
    source.controls.decision_mm.data = NULL;
    CHECK(tpmshx_prepare_flow_case_2d_v4(&source, &options, NULL, &result, &failure, error, sizeof(error)) != 0);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    source.controls.decision_mm.data = decisions; source.controls.decision_mm.size = 8;
    callbacks.context = &calls;
    CHECK(tpmshx_prepare_flow_case_2d_v4(&source, &options, &callbacks, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_RUNTIME);
    CHECK(calls == 1 && failure.kind == 3 && !memcmp(&before, &result, sizeof(result)));
    source.controls.symmetric_y = 2;
    CHECK(tpmshx_prepare_flow_case_2d_v4(&source, &options, NULL, &result, &failure, error, sizeof(error)) == 1);
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
    CHECK(!check_v3());
    return check_v4();
}
