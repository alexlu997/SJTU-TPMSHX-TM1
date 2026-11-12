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

typedef struct {
    uint32_t stage[8], side[8];
    size_t count, cancel_at;
} host_checks;
static int TPMSHX_PREPARATION_CALL check_host_input(void* context, uint32_t stage, uint32_t side) {
    host_checks* checks = (host_checks*)context;
    if (checks->count < 8) {
        checks->stage[checks->count] = stage; checks->side[checks->count] = side;
    }
    ++checks->count;
    return checks->count == checks->cancel_at;
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


typedef struct {
    tpmshx_preparation_inlet_cache_v3 value;
    tpmshx_preparation_range_v1 ranges[64];
    tpmshx_preparation_text_v1 sources[64][8], warnings[64];
    size_t shapes[64][2], used;
    uint32_t bounds[64];
    char text[32768];
    int valid;
} saved_cache;
typedef struct {
    tpmshx_preparation_geometry_cache_v3 geometry;
    saved_cache sides[2];
    size_t geometry_reads, geometry_writes, inlet_reads, inlet_writes;
    size_t live_ranges, cached_ranges, notices;
    int cancel_observation, invalid_observation;
    int geometry_valid, mode, cancel, publish_only;
    void* alias;
    tpmshx_preparation_range_v1 range;
    tpmshx_preparation_text_v1 source, warning;
    tpmshx_preparation_event_v1 event;
    size_t shape;
    uint32_t bounds;
} cache_checks;
static int copy_cache_text(saved_cache* target, tpmshx_preparation_text_v1* output, tpmshx_preparation_text_v1 input) {
    if (input.size > sizeof(target->text) - target->used) return 1;
    output->data = target->text + target->used; output->size = input.size;
    if (input.size) memcpy(target->text + target->used, input.data, input.size);
    target->used += input.size; return 0;
}
static int save_cache(saved_cache* target, const tpmshx_preparation_inlet_cache_v3* input) {
    size_t i, j;
    target->used = 0; target->value = *input;
    if (input->evidence.range_count > 64 || input->evidence.warning_count > 64 || input->evidence.event_count) return 1;
    target->value.evidence.ranges = target->ranges; target->value.evidence.range_bounds_list = target->bounds;
    target->value.evidence.warnings = target->warnings;
    for (i = 0; i < input->evidence.range_count; ++i) {
        const tpmshx_preparation_range_v1* from = &input->evidence.ranges[i];
        tpmshx_preparation_range_v1* to = &target->ranges[i];
        if (from->source_count > 8 || from->rank > 2) return 1;
        *to = *from; to->source = target->sources[i]; to->shape = target->shapes[i];
        target->bounds[i] = input->evidence.range_bounds_list[i];
        for (j = 0; j < from->rank; ++j) target->shapes[i][j] = from->shape[j];
        for (j = 0; j < from->source_count; ++j)
            if (copy_cache_text(target, &target->sources[i][j], from->source[j])) return 1;
        if (copy_cache_text(target, &to->side, from->side) || copy_cache_text(target, &to->stage, from->stage)
            || copy_cache_text(target, &to->layout, from->layout) || copy_cache_text(target, &to->label, from->label)
            || copy_cache_text(target, &to->quantity, from->quantity) || copy_cache_text(target, &to->unit, from->unit)) return 1;
    }
    for (i = 0; i < input->evidence.warning_count; ++i)
        if (copy_cache_text(target, &target->warnings[i], input->evidence.warnings[i])) return 1;
    target->valid = 1; return 0;
}
static int TPMSHX_PREPARATION_CALL cache_geometry(void* context, uint32_t action,
    tpmshx_preparation_geometry_cache_v3* value, uint32_t* hit) {
    cache_checks* checks = (cache_checks*)context;
    if (action) { ++checks->geometry_writes; checks->geometry = *value; checks->geometry_valid = 1; }
    else { ++checks->geometry_reads; *hit = (uint32_t)checks->geometry_valid; if (*hit) *value = checks->geometry; }
    return 0;
}
static int TPMSHX_PREPARATION_CALL cache_inlet(void* context, uint32_t action, uint32_t side,
    const tpmshx_preparation_inlet_2d_v1* inlet, tpmshx_preparation_scalar_kind_v2 speed,
    tpmshx_preparation_inlet_cache_v3* value, uint32_t* hit) {
    cache_checks* checks = (cache_checks*)context;
    (void)inlet; (void)speed;
    if (checks->mode && (!checks->publish_only || action)) {
        tpmshx_preparation_flow_evidence_v3* evidence = &value->evidence;
        const tpmshx_preparation_text_v1 text = {"cache", 5};
        *value = checks->sides[side].value;
        memset(evidence, 0, sizeof(*evidence)); memset(&checks->range, 0, sizeof(checks->range));
        checks->source = checks->warning = text; checks->shape = 1; checks->bounds = 0;
        checks->range.source = &checks->source; checks->range.source_count = 1;
        checks->range.shape = &checks->shape; checks->range.rank = 1;
        checks->range.side = checks->range.stage = checks->range.layout = text;
        checks->range.label = checks->range.quantity = checks->range.unit = text;
        evidence->ranges = &checks->range; evidence->range_count = 1; evidence->range_bounds_list = &checks->bounds;
        evidence->warnings = &checks->warning; evidence->warning_count = 1;
        checks->event.kind = 1; checks->event.logger = checks->event.message = text;
        *hit = 0;
        switch (checks->mode) {
        case 1: evidence->ranges = (const tpmshx_preparation_range_v1*)checks->alias; break;
        case 2: evidence->range_bounds_list = (const uint32_t*)checks->alias; break;
        case 3: evidence->warnings = (const tpmshx_preparation_text_v1*)checks->alias; break;
        case 4: checks->range.source = (const tpmshx_preparation_text_v1*)checks->alias; break;
        case 5: checks->source.data = (const char*)checks->alias; checks->source.size = 1; break;
        case 6: checks->range.shape = (const size_t*)checks->alias; break;
        case 7: checks->range.side.data = (const char*)checks->alias; checks->range.side.size = 1; break;
        case 8: checks->range.stage.data = (const char*)checks->alias; checks->range.stage.size = 1; break;
        case 9: checks->range.layout.data = (const char*)checks->alias; checks->range.layout.size = 1; break;
        case 10: checks->range.label.data = (const char*)checks->alias; checks->range.label.size = 1; break;
        case 11: checks->range.quantity.data = (const char*)checks->alias; checks->range.quantity.size = 1; break;
        case 12: checks->range.unit.data = (const char*)checks->alias; checks->range.unit.size = 1; break;
        case 13: checks->warning.data = (const char*)checks->alias; checks->warning.size = 1; break;
        case 14: evidence->events = (const tpmshx_preparation_event_v1*)checks->alias; evidence->event_count = 1; break;
        case 15: evidence->events = &checks->event; evidence->event_count = 1; checks->event.logger.data = (const char*)checks->alias; checks->event.logger.size = 1; break;
        case 16: evidence->events = &checks->event; evidence->event_count = 1; checks->event.message.data = (const char*)checks->alias; checks->event.message.size = 1; break;
        case 17: evidence->ranges = NULL; break;
        case 18: evidence->range_count = (size_t)-1; break;
        case 19: checks->range.source = NULL; break;
        case 20: checks->source.data = NULL; break;
        case 21: checks->range.shape = NULL; break;
        case 22: evidence->ranges = (const tpmshx_preparation_range_v1*)((char*)&checks->range + 1); break;
        case 23: *hit = 2; break;
        case 24: *hit = 1; value->kinds[0].layout = 9; break;
        case 25: *hit = 1; checks->range.sample.have_finite = 2; break;
        case 26: *hit = 1; checks->range.sample.have_finite = 1; break;
        case 27: *hit = 1; evidence->events = &checks->event; evidence->event_count = 1; break;
        }
        return checks->cancel;
    }
    if (action) { ++checks->inlet_writes; return save_cache(&checks->sides[side], value); }
    ++checks->inlet_reads; *hit = checks->publish_only ? 0u : (uint32_t)checks->sides[side].valid;
    if (*hit) *value = checks->sides[side].value;
    return 0;
}
static int TPMSHX_PREPARATION_CALL observe_range(void* context, uint32_t cached,
    const tpmshx_preparation_range_v1* value, uint32_t bounds_list, uint32_t have_scalar, double scalar) {
    cache_checks* checks = (cache_checks*)context;
    if (!value || !value->source_count || !value->label.size || cached > 1 || bounds_list > 1
        || have_scalar > 1 || (have_scalar && !isfinite(scalar))) checks->invalid_observation = 1;
    if (cached) ++checks->cached_ranges; else ++checks->live_ranges;
    return checks->cancel_observation == 1;
}
static int TPMSHX_PREPARATION_CALL observe_notice(void* context, uint32_t kind, uint32_t side,
    double value, tpmshx_preparation_text_v1 message) {
    cache_checks* checks = (cache_checks*)context;
    if (kind > 1 || side > 1 || !isfinite(value) || (kind == 1 && !message.size)) checks->invalid_observation = 1;
    ++checks->notices;
    return checks->cancel_observation == 2;
}
static int check_cache_v3(const tpmshx_preparation_flow_input_2d_v3* source) {
    cache_checks checks = {0};
    tpmshx_preparation_case_callbacks_v3 callbacks = {{{3, sizeof(callbacks), NULL, &checks}, NULL}, cache_geometry, cache_inlet, observe_range, observe_notice}, callbacks_before;
    tpmshx_preparation_flow_case_2d_v3 result = {3, sizeof(result)}, before;
    tpmshx_preparation_case_failure_v2 failure = {2, sizeof(failure)}, failure_before;
    tpmshx_preparation_case_options_v1 options = {1, sizeof(options), 0, 1, 0.};
    union { double align; char data[4096]; } error, saved_error;
    double rho[2], kss; size_t counts[4], side, target; int mode, cancel, publish, status;
    CHECK(!tpmshx_prepare_flow_case_2d_v3(source, &options, &callbacks.values.values, &result, &failure, error.data, sizeof(error.data)));
    CHECK(checks.geometry_writes == 1 && checks.inlet_writes == 2 && result.owner);
    CHECK(checks.live_ranges && checks.notices && !checks.invalid_observation);
    for (side = 0; side < 2; ++side) rho[side] = result.prepared.values.sides[side].properties.rho;
    kss = result.prepared.values.uniform_solid_conductivity;
    counts[0] = checks.geometry_reads; counts[1] = checks.geometry_writes;
    counts[2] = checks.inlet_reads; counts[3] = checks.inlet_writes;
    tpmshx_preparation_flow_case_2d_release_v3(&result); result.abi_version = 3; result.struct_size = sizeof(result);
    CHECK(!tpmshx_prepare_flow_case_2d_v3(source, &options, &callbacks.values.values, &result, &failure, error.data, sizeof(error.data)));
    CHECK(checks.geometry_reads > counts[0] && checks.geometry_writes == counts[1]);
    CHECK(checks.inlet_reads == counts[2] + 2 && checks.inlet_writes == counts[3]);
    CHECK(checks.cached_ranges && !checks.invalid_observation);
    for (side = 0; side < 2; ++side) CHECK(result.prepared.values.sides[side].properties.rho == rho[side]);
    CHECK(result.prepared.values.uniform_solid_conductivity == kss);
    tpmshx_preparation_flow_case_2d_release_v3(&result); result.abi_version = 3; result.struct_size = sizeof(result); before = result;
    for (mode = 1; mode <= 22; ++mode) for (target = 0; target < 3; ++target)
        for (cancel = 0; cancel < 2; ++cancel) for (publish = 0; publish < 2; ++publish) {
            checks.mode = mode; checks.cancel = cancel; checks.publish_only = publish;
            checks.alias = target == 0 ? (void*)&result : target == 1 ? (void*)&failure : (void*)error.data;
            memset(error.data, 'Q', sizeof(error.data)); saved_error = error; failure_before = failure;
            status = tpmshx_prepare_flow_case_2d_v3(source, &options, &callbacks.values.values, &result, &failure, error.data, sizeof(error.data));
            CHECK(status == TPMSHX_PREPARATION_INVALID);
            CHECK(!memcmp(&result, &before, sizeof(result)) && !memcmp(&failure, &failure_before, sizeof(failure)));
            CHECK(!memcmp(&error, &saved_error, sizeof(error)));
        }
    checks.publish_only = 0; checks.cancel = 0;
    for (mode = 23; mode <= 27; ++mode) {
        checks.mode = mode;
        CHECK(tpmshx_prepare_flow_case_2d_v3(source, &options, &callbacks.values.values, &result, &failure, error.data, sizeof(error.data)) == TPMSHX_PREPARATION_INVALID);
        CHECK(failure.kind == 1 && error.data[0] && !memcmp(&result, &before, sizeof(result)));
    }
    checks.mode = 28; checks.cancel = 1;
    CHECK(tpmshx_prepare_flow_case_2d_v3(source, &options, &callbacks.values.values, &result, &failure, error.data, sizeof(error.data)) == TPMSHX_PREPARATION_RUNTIME);
    CHECK(failure.kind == 3 && error.data[0] && !memcmp(&result, &before, sizeof(result)));
    callbacks_before = callbacks; failure_before = failure;
    CHECK(tpmshx_prepare_flow_case_2d_v3(source, &options, &callbacks.values.values, &result, &failure,
        (char*)&callbacks.observe_notice, sizeof(callbacks.observe_notice)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&callbacks, &callbacks_before, sizeof(callbacks)) && !memcmp(&failure, &failure_before, sizeof(failure)));
    memset(error.data, 'Q', sizeof(error.data)); saved_error = error;
    CHECK(tpmshx_prepare_flow_case_2d_v3(source, &options,
        (const tpmshx_preparation_case_callbacks_v1*)((const char*)&callbacks + 1), &result, &failure, error.data, sizeof(error.data)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&error, &saved_error, sizeof(error)) && !memcmp(&failure, &failure_before, sizeof(failure)));
    callbacks.geometry_cache = NULL; callbacks.inlet_cache = NULL;
    for (mode = 1; mode <= 2; ++mode) {
        size_t ranges = checks.live_ranges, notices = checks.notices;
        checks.cancel_observation = mode;
        CHECK(tpmshx_prepare_flow_case_2d_v3(source, &options, &callbacks.values.values,
            &result, &failure, error.data, sizeof(error.data)) == TPMSHX_PREPARATION_RUNTIME);
        CHECK(failure.kind == 3 && error.data[0] && !memcmp(&result, &before, sizeof(result)));
        CHECK(mode == 1 ? checks.live_ranges == ranges + 1 : checks.notices == notices + 1);
    }
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
    {
        host_checks checks = {0};
        tpmshx_preparation_case_callbacks_v2 host = {{2, sizeof(host), NULL, &checks}, check_host_input};
        tpmshx_preparation_case_callbacks_v2 host_before;
        CHECK(!tpmshx_prepare_flow_case_2d_v3(&source, &options, &host.values, &result, &failure, error, sizeof(error)));
        CHECK(checks.count == 5 && checks.stage[0] == 1 && checks.stage[1] == 0 && checks.stage[2] == 1);
        CHECK(checks.stage[3] == 2 && checks.side[3] == 0 && checks.stage[4] == 2 && checks.side[4] == 1);
        tpmshx_preparation_flow_case_2d_release_v3(&result);
        result.abi_version = 3; result.struct_size = sizeof(result); before = result;
        checks.count = 0; checks.cancel_at = 4;
        CHECK(tpmshx_prepare_flow_case_2d_v3(&source, &options, &host.values, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_RUNTIME);
        CHECK(checks.count == 4 && failure.kind == 3 && !memcmp(&before, &result, sizeof(result)));
        checks.count = 0; checks.cancel_at = 0; host_before = host; failure_before = failure;
        CHECK(tpmshx_prepare_flow_case_2d_v3(&source, &options, &host.values, &result, &failure,
            (char*)&host.validate_host_input, sizeof(host.validate_host_input)) == TPMSHX_PREPARATION_INVALID);
        CHECK(!checks.count && !memcmp(&host, &host_before, sizeof(host)) && !memcmp(&failure, &failure_before, sizeof(failure)));
        --host.values.struct_size;
        CHECK(tpmshx_prepare_flow_case_2d_v3(&source, &options, &host.values, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
        CHECK(!checks.count && !memcmp(&before, &result, sizeof(result)));
        host.values.struct_size = sizeof(host);
        source.have_explicit_targets = 0;
        query.abi_version = 3; query.struct_size = sizeof(query);
        CHECK(!tpmshx_resolve_inlet_flow_2d_v3(&source, &options, &host.values, &query, &failure, error, sizeof(error)));
        CHECK(!checks.count && !query.have_capacities);
        tpmshx_preparation_flow_2d_release_v3(&query);
        query.abi_version = 3; query.struct_size = sizeof(query);
        CHECK(!tpmshx_prepare_inlet_mass_capacities_2d_v3(&source, &options, &host.values, &query, &failure, error, sizeof(error)));
        CHECK(checks.count == 1 && checks.stage[0] == 1 && checks.side[0] == 2);
        tpmshx_preparation_flow_2d_release_v3(&query);
        source.have_explicit_targets = 1;
    }
    CHECK(!check_cache_v3(&source));
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
    {
        host_checks checks = {0};
        tpmshx_preparation_case_callbacks_v2 host = {{2, sizeof(host), NULL, &checks}, check_host_input};
        CHECK(!tpmshx_prepare_flow_case_2d_v4(&source, &options, &host.values, &result, &failure, error, sizeof(error)));
        CHECK(checks.count == 5 && checks.stage[0] == 1 && checks.stage[1] == 0 && checks.stage[2] == 1);
        CHECK(checks.stage[3] == 2 && checks.side[3] == 0 && checks.stage[4] == 2 && checks.side[4] == 1);
    }
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


static int check_v5(void) {
    tpmshx_preparation_zoned_input_2d_v5 source = {0}, original;
    tpmshx_preparation_zone_region_v5 regions[2] = {{0}}, saved_regions[2];
    tpmshx_preparation_zoned_case_2d_v5 result = {0}, before;
    tpmshx_preparation_case_failure_v2 failure = {0}, failure_before;
    tpmshx_preparation_case_options_v1 options = {1, sizeof(options), 0, 1, 0.};
    tpmshx_preparation_case_callbacks_v1 callbacks = {1, sizeof(callbacks), cancel_event, NULL};
    const tpmshx_preparation_scalar_kind_v2 weak = {64, 0, 0};
    char first[] = "first", second[] = "second", error[4096];
    size_t side, j, calls = 0;
    source.abi_version = result.abi_version = 5;
    source.struct_size = sizeof(source); result.struct_size = sizeof(result);
    source.values.abi_version = failure.abi_version = 2;
    source.values.struct_size = sizeof(source.values); failure.struct_size = sizeof(failure);
    source.values.values = input(); source.values.values.geometry_mode = 2;
    source.values.values.requested_nx = 8; source.values.values.requested_ny = 6;
    source.values.kinds.cell_length = source.values.kinds.wall_thickness = source.values.kinds.solid_conductivity = weak;
    for (side = 0; side < 2; ++side) {
        source.values.kinds.sides[side].velocity = source.values.kinds.sides[side].temperature = source.values.kinds.sides[side].pressure = weak;
        regions[side].cell_kind = regions[side].wall_kind = weak;
        regions[side].cell_length_mm = side ? 6. : 7.; regions[side].wall_thickness_mm = side ? .5 : .4;
        for (j = 0; j < 4; ++j) {regions[side].bounds[j].precision = 64; regions[side].bounds[j].strong = 0;}
    }
    regions[0].name.data = first; regions[0].name.size = strlen(first);
    regions[1].name.data = second; regions[1].name.size = strlen(second);
    regions[0].bounds[0].value = 0.; regions[0].bounds[1].value = .4;
    regions[1].bounds[0].value = .4; regions[1].bounds[1].value = 1.;
    source.regions = regions; source.region_count = 2; source.axis = 1;
    original = source; memcpy(saved_regions, regions, sizeof(regions));
    CHECK(tpmshx_preparation_case_abi_version_v5() == 5);
    CHECK(!tpmshx_prepare_zoned_case_2d_v5(&source, &options, NULL, &result, &failure, error, sizeof(error)));
    CHECK(result.owner && !result.prepared.values.owner && !failure.kind && !error[0]);
    CHECK(!memcmp(&source, &original, sizeof(source)) && !memcmp(regions, saved_regions, sizeof(regions)));
    CHECK(result.region_count == 2 && result.cell_count == 48 && result.prepared.values.nx == 8 && result.prepared.values.ny == 6);
    CHECK(result.zone_id[0] == 0 && result.zone_id[5] == 1);
    CHECK(result.thermal_porosity.size == 48 && result.volumetric_transfer[1].size == 48);
    CHECK(result.prepared.values.sides[0].row_permeability.size == 8 && !result.prepared.values.sides[0].permeability.size);
    first[0] = 'X'; regions[0].cell_length_mm = -1.;
    CHECK(result.regions[0].region.name.data[0] == 'f' && result.regions[0].region.cell_length_mm == 7.);
    before = result;
    CHECK(tpmshx_prepare_zoned_case_2d_v5(&source, &options, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    tpmshx_preparation_zoned_case_2d_release_v5(&result);
    CHECK(!result.owner && !result.regions && !result.zone_id && !result.struct_size);
    tpmshx_preparation_zoned_case_2d_release_v5(&result); tpmshx_preparation_zoned_case_2d_release_v5(NULL);
    first[0] = 'f'; memcpy(regions, saved_regions, sizeof(regions));
    memset(&result, 0, sizeof(result)); result.abi_version = 5; result.struct_size = sizeof(result); before = result;
    callbacks.context = &calls;
    CHECK(tpmshx_prepare_zoned_case_2d_v5(&source, &options, &callbacks, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_RUNTIME);
    CHECK(calls == 1 && failure.kind == 3 && strstr(error, "callback failed") && !memcmp(&before, &result, sizeof(result)));
    source.values.values.sides[0].have_mass_flow = 1;
    CHECK(tpmshx_prepare_zoned_case_2d_v5(&source, &options, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(strstr(error, "prescribed inlet velocity") && failure.kind == 1 && !memcmp(&before, &result, sizeof(result)));
    source = original;
    CHECK(tpmshx_prepare_zoned_case_2d_v5(&source, &options, NULL, &result, &failure, (char*)&result, sizeof(result)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    failure_before = failure;
    source.regions = (const tpmshx_preparation_zone_region_v5*)&result; source.region_count = 1;
    CHECK(tpmshx_prepare_zoned_case_2d_v5(&source, &options, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)) && !memcmp(&failure_before, &failure, sizeof(failure)));
    source = original; regions[0].name.data = (const char*)&failure; regions[0].name.size = sizeof(failure);
    CHECK(tpmshx_prepare_zoned_case_2d_v5(&source, &options, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)) && !memcmp(&failure_before, &failure, sizeof(failure)));
    regions[0].name.data = error; regions[0].name.size = sizeof(error); memset(error, 'R', sizeof(error));
    CHECK(tpmshx_prepare_zoned_case_2d_v5(&source, &options, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(error[0] == 'R' && error[sizeof(error)-1] == 'R' && !memcmp(&failure_before, &failure, sizeof(failure)));
    regions[0].name.data = NULL; regions[0].name.size = 1;
    CHECK(tpmshx_prepare_zoned_case_2d_v5(&source, &options, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)) && !memcmp(&failure_before, &failure, sizeof(failure)));
    memcpy(regions, saved_regions, sizeof(regions)); source = original;
    callbacks.abi_version = 2;
    CHECK(tpmshx_prepare_zoned_case_2d_v5(&source, &options, &callbacks, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    return 0;
}

static int check_v6(void) {
    tpmshx_preparation_sigmoid_lut_v6 lut = {0}, lut_before;
    tpmshx_preparation_sigmoid_input_2d_v6 source = {0};
    tpmshx_preparation_sigmoid_case_2d_v6 result = {0}, before;
    tpmshx_preparation_zone_region_v5 region = {0};
    tpmshx_preparation_case_failure_v2 failure = {0}, failure_before;
    tpmshx_preparation_case_options_v1 options = {1, sizeof(options), 0, 1, 0.};
    const tpmshx_preparation_scalar_kind_v2 weak = {64, 0, 0};
    double decisions[36]; char error[4096]; size_t i;
    lut.abi_version = source.abi_version = result.abi_version = 6;
    lut.struct_size = sizeof(lut); source.struct_size = sizeof(source); result.struct_size = sizeof(result);
    source.values.abi_version = 5; source.values.struct_size = sizeof(source.values);
    source.values.values.abi_version = failure.abi_version = 2;
    source.values.values.struct_size = sizeof(source.values.values); failure.struct_size = sizeof(failure);
    source.values.values.values = input(); source.values.values.values.geometry_mode = 2;
    source.values.values.values.requested_nx = 8; source.values.values.values.requested_ny = 6;
    source.values.values.kinds.cell_length = source.values.values.kinds.wall_thickness = source.values.values.kinds.solid_conductivity = weak;
    for (i = 0; i < 2; ++i)
        source.values.values.kinds.sides[i].velocity = source.values.values.kinds.sides[i].temperature = source.values.values.kinds.sides[i].pressure = weak;
    for (i = 0; i < 4; ++i) {region.bounds[i].precision = 64; region.bounds[i].value = i % 2 ? 1. : 0.;}
    region.cell_length_mm = 7.; region.wall_thickness_mm = .4; region.cell_kind = region.wall_kind = weak;
    source.values.kind = source.values.axis = 1; source.values.regions = &region; source.values.region_count = 1;
    for (i = 0; i < 18; ++i) {decisions[2*i] = 7.; decisions[2*i+1] = .4;}
    source.controls.decision_mm.data = decisions; source.controls.decision_mm.size = 36;
    source.controls.inlet_transition.value = source.controls.outlet_transition.value = .2;
    source.controls.inlet_transition.precision = source.controls.outlet_transition.precision = 64;
    CHECK(tpmshx_preparation_case_abi_version_v6() == 6);
    CHECK(!tpmshx_preparation_sigmoid_lut_create_v6(1, 2, 2, 16, &lut, error, sizeof(error)));
    CHECK(lut.owner && lut.values.porosity.size == 4 && lut.values.porosity_fast == 1);
    lut_before = lut;
    CHECK(tpmshx_preparation_sigmoid_lut_create_v6(1, 2, 2, 16, &lut, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&lut, &lut_before, sizeof(lut)));
    source.lut = lut.values;
    CHECK(!tpmshx_prepare_sigmoid_case_2d_v6(&source, &options, NULL, &result, &failure, error, sizeof(error)));
    CHECK(result.owner && !result.values.owner && !result.values.prepared.values.owner);
    CHECK(result.values.kind == 2 && !result.values.region_count && result.values.cell_count == 48);
    CHECK(result.controls.decision_mm.size == 36 && result.values.thermal_porosity.size == 48);
    tpmshx_preparation_sigmoid_lut_release_v6(&lut);
    CHECK(!lut.owner && !lut.values.porosity.data);
    decisions[0] = -1.; CHECK(result.controls.decision_mm.data[0] == 7.);
    CHECK(isfinite(result.values.volumetric_transfer[0].data[0]));
    tpmshx_preparation_sigmoid_case_2d_release_v6(&result);
    CHECK(!result.owner && !result.values.zone_id && !result.controls.decision_mm.data);
    tpmshx_preparation_sigmoid_case_2d_release_v6(&result); tpmshx_preparation_sigmoid_case_2d_release_v6(NULL);
    tpmshx_preparation_sigmoid_lut_release_v6(&lut); tpmshx_preparation_sigmoid_lut_release_v6(NULL);
    result.abi_version = 6; result.struct_size = sizeof(result); before = result; failure_before = failure;
    source.lut.cell_mm.data = (const double*)&result; source.lut.cell_mm.size = 1;
    CHECK(tpmshx_prepare_sigmoid_case_2d_v6(&source, &options, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)) && !memcmp(&failure_before, &failure, sizeof(failure)));
    CHECK(tpmshx_preparation_sigmoid_lut_create_v6(1, 2, 2, 16, &lut, (char*)&lut, sizeof(lut)) == TPMSHX_PREPARATION_INVALID);
    return 0;
}

static int check_v7(void) {
    tpmshx_preparation_flow_input_2d_v3 source = {0}, original;
    tpmshx_preparation_flow_case_2d_v3 result = {0}, before;
    tpmshx_preparation_grid_kinds_2d_v7 grid = {0}, original_grid;
    tpmshx_preparation_case_failure_v2 failure = {0};
    tpmshx_preparation_case_options_v1 options = {1, sizeof(options), 0, 1, 0.};
    const tpmshx_preparation_scalar_kind_v2 weak = {64, 0, 0};
    const tpmshx_preparation_scalar_kind_v2 integer = {8, 2, 1}, half = {16, 1, 1};
    char error[4096]; size_t side, column;
    CHECK(tpmshx_preparation_case_abi_version_v7() == 7);
    source.abi_version = result.abi_version = 3;
    source.struct_size = sizeof(source); result.struct_size = sizeof(result);
    source.values.abi_version = failure.abi_version = 2;
    source.values.struct_size = sizeof(source.values); failure.struct_size = sizeof(failure);
    source.values.values = input();
    source.values.values.length_m = 1.; source.values.values.height_m = 2.;
    source.values.values.requested_nx = source.values.values.requested_ny = 12;
    source.values.kinds.cell_length = source.values.kinds.wall_thickness = source.values.kinds.solid_conductivity = weak;
    source.physical_depth_kind = source.target_kinds[0] = source.target_kinds[1] = weak;
    grid.abi_version = 7; grid.struct_size = sizeof(grid);
    for (side = 0; side < 2; ++side) {
        grid.lengths[side] = integer;
        source.values.kinds.sides[side].velocity = source.values.kinds.sides[side].temperature = source.values.kinds.sides[side].pressure = weak;
        for (column = 0; column < 4; ++column) grid.ports[side][column] = weak;
    }
    source.values.values.sides[0].port.inlet_center_m = source.values.values.sides[0].port.outlet_center_m = 1.;
    source.values.values.sides[0].port.inlet_width_m = source.values.values.sides[0].port.outlet_width_m = .199951171875;
    grid.ports[0][0] = grid.ports[0][2] = integer;
    grid.ports[0][1] = grid.ports[0][3] = half;
    original = source; original_grid = grid;
    CHECK(!tpmshx_prepare_flow_case_2d_v7(&source, &grid, &options, NULL, &result, &failure, error, sizeof(error)));
    CHECK(result.prepared.values.sides[0].inlet_bounds[0] == .89990234375);
    CHECK(result.prepared.values.sides[0].inlet_bounds[1] == 1.099609375);
    CHECK(!memcmp(&source, &original, sizeof(source)) && !memcmp(&grid, &original_grid, sizeof(grid)));
    CHECK(result.owner && !result.prepared.values.owner && !result.flow.owner);
    tpmshx_preparation_flow_case_2d_release_v3(&result);
    result.abi_version = 3; result.struct_size = sizeof(result); before = result;
    CHECK(tpmshx_prepare_flow_case_2d_v7(&source, &grid, &options, NULL, &result, &failure,
        (char*)&grid, sizeof(grid)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&grid, &original_grid, sizeof(grid)) && !memcmp(&result, &before, sizeof(result)));
    CHECK(tpmshx_prepare_flow_case_2d_v7(&source, NULL, &options, NULL, &result, &failure,
        error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&result, &before, sizeof(result)));
    return 0;
}

static int check_v8(void) {
    tpmshx_preparation_zoned_flow_input_2d_v8 source = {0};
    tpmshx_preparation_zoned_flow_2d_v8 result = {8, sizeof(result)}, before;
    tpmshx_preparation_sigmoid_flow_2d_v8 sigmoid = {8, sizeof(sigmoid)};
    tpmshx_preparation_grid_kinds_2d_v7 grid = {7, sizeof(grid)};
    tpmshx_preparation_case_failure_v2 failure = {2, sizeof(failure)};
    char error[4096];
    CHECK(tpmshx_preparation_case_abi_version_v8() == 8);
    before = result;
    source.abi_version = 99; source.struct_size = sizeof(source);
    CHECK(tpmshx_prepare_zoned_inlet_mass_capacities_2d_v8(&source, &grid, NULL, NULL,
        &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(strstr(error, "v8 ABI version") && !memcmp(&result, &before, sizeof(result)));
    tpmshx_preparation_zoned_flow_2d_release_v8(&result);
    tpmshx_preparation_sigmoid_flow_2d_release_v8(&sigmoid);
    CHECK(!result.struct_size && !sigmoid.struct_size);
    tpmshx_preparation_zoned_flow_2d_release_v8(NULL);
    tpmshx_preparation_zoned_flow_case_2d_release_v8(NULL);
    tpmshx_preparation_sigmoid_flow_2d_release_v8(NULL);
    tpmshx_preparation_sigmoid_flow_case_2d_release_v8(NULL);
    return 0;
}

static int check_v9(void) {
    tpmshx_preparation_zoned_flow_input_2d_v9 source = {0};
    tpmshx_preparation_zoned_flow_2d_v9 result = {9, sizeof(result)}, before;
    tpmshx_preparation_sigmoid_flow_2d_v9 sigmoid = {9, sizeof(sigmoid)};
    tpmshx_preparation_grid_kinds_2d_v7 grid = {7, sizeof(grid)};
    tpmshx_preparation_case_failure_v2 failure = {2, sizeof(failure)};
    char error[4096];
    CHECK(tpmshx_preparation_case_abi_version_v9() == 9);
    source.abi_version = 99; source.struct_size = sizeof(source); before = result;
    CHECK(tpmshx_prepare_zoned_inlet_mass_capacities_2d_v9(&source, &grid, NULL, NULL,
        &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(strstr(error, "v9 ABI version") && !memcmp(&result, &before, sizeof(result)));
    tpmshx_preparation_zoned_flow_2d_release_v9(&result);
    tpmshx_preparation_sigmoid_flow_2d_release_v9(&sigmoid);
    CHECK(!result.struct_size && !sigmoid.struct_size);
    tpmshx_preparation_zoned_flow_2d_release_v9(NULL);
    tpmshx_preparation_zoned_flow_case_2d_release_v9(NULL);
    tpmshx_preparation_sigmoid_flow_2d_release_v9(NULL);
    tpmshx_preparation_sigmoid_flow_case_2d_release_v9(NULL);
    return 0;
}

static int check_v10(void) {
    tpmshx_preparation_flow_input_2d_v3 source = {0}, original;
    tpmshx_preparation_flow_case_2d_v10 result = {10, sizeof(result)}, before;
    tpmshx_preparation_zoned_flow_input_2d_v9 zoned = {99, sizeof(zoned)};
    tpmshx_preparation_sigmoid_flow_input_2d_v9 sigmoid = {99, sizeof(sigmoid)};
    tpmshx_preparation_zoned_flow_case_2d_v10 zoned_case = {10, sizeof(zoned_case)}, zoned_before;
    tpmshx_preparation_sigmoid_flow_case_2d_v10 sigmoid_case = {10, sizeof(sigmoid_case)}, sigmoid_before;
    tpmshx_preparation_zoned_flow_2d_v9 zoned_flow = {9, sizeof(zoned_flow)}, zoned_flow_before;
    tpmshx_preparation_sigmoid_flow_2d_v9 sigmoid_flow = {9, sizeof(sigmoid_flow)}, sigmoid_flow_before;
    tpmshx_preparation_grid_kinds_2d_v7 grid = {7, sizeof(grid)};
    tpmshx_preparation_case_failure_v2 failure = {2, sizeof(failure)};
    tpmshx_preparation_case_options_v1 options = {1, sizeof(options), 0, 1, 0.};
    const tpmshx_preparation_scalar_kind_v2 weak = {64, 0, 0};
    char error[4096]; size_t side, column;
    CHECK(tpmshx_preparation_case_abi_version_v10() == 10);
    source.abi_version = 3; source.struct_size = sizeof(source);
    source.values.abi_version = 2; source.values.struct_size = sizeof(source.values);
    source.values.values = input(); source.values.values.delta_levelset = .1;
    source.values.values.requested_nx = 8; source.values.values.requested_ny = 6;
    source.values.kinds.cell_length = source.values.kinds.wall_thickness = source.values.kinds.solid_conductivity = weak;
    source.physical_depth_kind = source.target_kinds[0] = source.target_kinds[1] = weak;
    for (side = 0; side < 2; ++side) {
        grid.lengths[side] = weak;
        source.values.kinds.sides[side].velocity = source.values.kinds.sides[side].temperature = source.values.kinds.sides[side].pressure = weak;
        for (column = 0; column < 4; ++column) grid.ports[side][column] = weak;
    }
    original = source;
    CHECK(!tpmshx_prepare_flow_case_2d_v10(&source, &grid, &options, NULL, &result, &failure, error, sizeof(error)));
    CHECK(result.owner && !result.values.owner && !result.values.prepared.values.owner && !result.values.flow.owner);
    CHECK(result.thermal.have_side_geometry && result.values.prepared.values.input.delta_levelset == .1);
    CHECK(result.values.prepared.values.split_a > 0. && result.values.prepared.values.split_a < 1.);
    CHECK(!memcmp(&source, &original, sizeof(source)));
    for (side = 0; side < 2; ++side)
        for (column = 0; column < 4; ++column)
            CHECK(isfinite(result.thermal.side_geometry[side][column]) && result.thermal.side_geometry[side][column] > 0.);
    before = result;
    CHECK(tpmshx_prepare_flow_case_2d_v10(&source, &grid, &options, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&result, &before, sizeof(result)));
    tpmshx_preparation_flow_case_2d_release_v10(&result);
    CHECK(!result.owner && !result.struct_size && !result.values.prepared.values.dx.data && !result.thermal.have_side_geometry);
    tpmshx_preparation_flow_case_2d_release_v10(&result);
    tpmshx_preparation_flow_case_2d_release_v10(NULL);

    zoned_before = zoned_case; sigmoid_before = sigmoid_case;
    CHECK(tpmshx_prepare_zoned_flow_case_2d_v10(&zoned, &grid, NULL, NULL, &zoned_case, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&zoned_case, &zoned_before, sizeof(zoned_case)));
    CHECK(tpmshx_prepare_sigmoid_flow_case_2d_v10(&sigmoid, &grid, NULL, NULL, &sigmoid_case, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&sigmoid_case, &sigmoid_before, sizeof(sigmoid_case)));
    zoned_flow_before = zoned_flow; sigmoid_flow_before = sigmoid_flow;
    CHECK(tpmshx_prepare_zoned_inlet_mass_capacities_2d_v10(&zoned, &grid, NULL, NULL, &zoned_flow, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(tpmshx_resolve_zoned_inlet_flow_2d_v10(&zoned, &grid, NULL, NULL, &zoned_flow, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&zoned_flow, &zoned_flow_before, sizeof(zoned_flow)));
    CHECK(tpmshx_prepare_sigmoid_inlet_mass_capacities_2d_v10(&sigmoid, &grid, NULL, NULL, &sigmoid_flow, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(tpmshx_resolve_sigmoid_inlet_flow_2d_v10(&sigmoid, &grid, NULL, NULL, &sigmoid_flow, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&sigmoid_flow, &sigmoid_flow_before, sizeof(sigmoid_flow)));
    tpmshx_preparation_zoned_flow_case_2d_release_v10(&zoned_case);
    tpmshx_preparation_sigmoid_flow_case_2d_release_v10(&sigmoid_case);
    CHECK(!zoned_case.struct_size && !sigmoid_case.struct_size);
    tpmshx_preparation_zoned_flow_case_2d_release_v10(NULL);
    tpmshx_preparation_sigmoid_flow_case_2d_release_v10(NULL);
    tpmshx_preparation_zoned_flow_2d_release_v9(&zoned_flow);
    tpmshx_preparation_sigmoid_flow_2d_release_v9(&sigmoid_flow);
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
    CHECK(!check_v4());
    CHECK(!check_v5());
    CHECK(!check_v6());
    CHECK(!check_v7());
    CHECK(!check_v8());
    CHECK(!check_v9());
    return check_v10();
}
